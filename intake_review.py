"""A local review gate around upstream Docling conversion and document exports."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath

from docling.backend.md_backend import MarkdownDocumentBackend
from docling.datamodel.backend_options import MarkdownBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import InputDocument
from docling_core.types.doc import DoclingDocument

from source_identity import verify_source_components

verify_source_components()

MAX_BYTES = 1024 * 1024
MAX_ITEMS = 10_000
MAX_REVIEW_BYTES = 8 * 1024 * 1024
MAX_VERSIONS = 1_000


class IntakeError(Exception):
    """An actionable input, approval, or integrity failure."""


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reviewed(doc: DoclingDocument) -> tuple[str, str, str]:
    document = canonical(doc.export_to_dict())
    markdown = doc.export_to_markdown().replace("\r\n", "\n").replace("\r", "\n")
    markdown = markdown.rstrip("\n") + "\n"
    return (
        document,
        markdown,
        sha(canonical({"document": json.loads(document), "markdown": markdown})),
    )


def convert(data: bytes, filename: str, fmt: str) -> tuple[DoclingDocument, dict]:
    metadata = {
        "docling_slim": importlib.metadata.version("docling-slim"),
        "docling_core": importlib.metadata.version("docling-core"),
        "format": fmt,
        "layout_score": None,
        "ocr_score": None,
        "table_score": None,
        "confidence_note": "Unavailable for this declarative conversion/import route.",
    }
    try:
        if fmt == "docling-json":
            doc = DoclingDocument.model_validate_json(data)
            metadata["backend"] = "docling_core.types.doc.DoclingDocument.model_validate_json"
        elif fmt == "markdown":
            # minimalism: direct official declarative backend, no recognition pipeline/models.
            data.decode("utf-8")
            stream = BytesIO(data)
            options = MarkdownBackendOptions(
                encoding="utf-8",
                fetch_images=False,
                enable_remote_fetch=False,
                enable_local_fetch=False,
            )
            in_doc = InputDocument(
                path_or_stream=stream,
                filename=filename,
                format=InputFormat.MD,
                backend=MarkdownDocumentBackend,
                backend_options=options,
            )
            backend = MarkdownDocumentBackend(in_doc, stream, options)
            try:
                if not in_doc.valid or not backend.is_valid():
                    raise IntakeError("Docling rejected the Markdown input.")
                doc = backend.convert()
            finally:
                backend.unload()
                in_doc._backend.unload()
            metadata["backend"] = "docling.backend.md_backend.MarkdownDocumentBackend.convert"
            metadata["resource_fetch"] = "disabled (local, remote and image fetch)"
        else:
            raise IntakeError("Supported formats: UTF-8 Markdown and DoclingDocument JSON.")
        items = list(doc.iterate_items())
        if not items or len(items) > MAX_ITEMS:
            raise IntakeError(f"Document must contain 1..{MAX_ITEMS} items.")
        # Validate the actual upstream export, including references and provenance.
        doc = DoclingDocument.model_validate(doc.export_to_dict())
        metadata["items"] = len(items)
        metadata["pages"] = len(doc.pages)
        return doc, metadata
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError(f"Docling conversion/schema validation failed: {exc}") from exc


class Store:
    def __init__(self, workspace: Path):
        if workspace.is_symlink():
            raise IntakeError("Workspace must not be a symlink.")
        workspace.mkdir(parents=True, exist_ok=True)
        self.workspace = workspace.resolve()
        self.sources = self.workspace / "sources"
        self.exports = self.workspace / "exports"
        for directory in (self.sources, self.exports):
            if directory.is_symlink():
                raise IntakeError("Workspace directories must not be symlinks.")
            directory.mkdir(exist_ok=True)
        database = self.workspace / "intake.sqlite3"
        if database.is_symlink():
            raise IntakeError("Database must not be a symlink.")
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                source_id TEXT NOT NULL, version INTEGER NOT NULL,
                source_bytes BLOB NOT NULL, source_sha TEXT NOT NULL,
                document_json TEXT NOT NULL, markdown TEXT NOT NULL,
                content_sha TEXT NOT NULL, metadata_json TEXT NOT NULL,
                integrity_sha TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(source_id, version)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                source_id TEXT NOT NULL, version INTEGER NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approve','reject')),
                integrity_sha TEXT NOT NULL, reviewer TEXT NOT NULL,
                reason TEXT NOT NULL, decided_at TEXT NOT NULL,
                PRIMARY KEY(source_id, version),
                FOREIGN KEY(source_id,version) REFERENCES versions(source_id,version)
            );
        """)
        self.db.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.db.close()

    def source_path(self, identity: str) -> Path:
        parts = PurePosixPath(identity)
        if (
            not identity
            or len(identity) > 240
            or "\\" in identity
            or ":" in identity
            or parts.is_absolute()
            or any(p in ("", ".", "..") for p in identity.split("/"))
        ):
            raise IntakeError("Source must be a bounded relative POSIX path under sources/.")
        path = self.sources
        for part in parts.parts:
            path /= part
            if path.is_symlink():
                raise IntakeError("Source symlinks are not supported.")
        if not path.resolve().is_relative_to(self.sources):
            raise IntakeError("Source path escapes sources/.")
        if not path.is_file():
            raise IntakeError(f"Source file does not exist: {identity}")
        return path

    def read_source(self, identity: str) -> bytes:
        path = self.source_path(identity)
        with path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise IntakeError(f"Source size must be 1..{MAX_BYTES} bytes.")
        return data

    @staticmethod
    def integrity(row: dict | sqlite3.Row) -> str:
        return sha(
            canonical(
                {
                    "source_id": row["source_id"],
                    "version": row["version"],
                    "source_sha": row["source_sha"],
                    "content_sha": row["content_sha"],
                    "document_json": row["document_json"],
                    "markdown": row["markdown"],
                    "metadata_json": row["metadata_json"],
                }
            )
        )

    @staticmethod
    def decision_integrity(decision: dict | sqlite3.Row, version: dict | sqlite3.Row) -> str:
        payload = {
            key: decision[key]
            for key in ("source_id", "version", "decision", "reviewer", "reason", "decided_at")
        }
        payload["version_integrity_sha"] = version["integrity_sha"]
        return sha(canonical(payload))

    def verify_decision(self, decision: sqlite3.Row, version: dict | sqlite3.Row) -> None:
        try:
            valid = decision["integrity_sha"] == self.decision_integrity(decision, version)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise IntakeError(
                "Stored decision integrity mismatch; "
                "legacy decisions require separate re-review."
            )

    def intake(self, identity: str, fmt: str | None = None) -> dict:
        data = self.read_source(identity)
        if fmt is None:
            fmt = (
                "markdown"
                if identity.endswith(".md")
                else "docling-json"
                if identity.endswith(".json")
                else "unsupported"
            )
        doc, metadata = convert(data, PurePosixPath(identity).name, fmt)
        document, markdown, content_hash = reviewed(doc)
        if len(document.encode("utf-8")) + len(markdown.encode("utf-8")) > MAX_REVIEW_BYTES:
            raise IntakeError(f"Normalized review content exceeds {MAX_REVIEW_BYTES} bytes.")
        if sha(self.read_source(identity)) != sha(data):
            raise IntakeError("Source changed during conversion; retry on a stable source.")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute(
                "SELECT * FROM versions WHERE source_id=? ORDER BY version DESC LIMIT 1",
                (identity,),
            ).fetchone()
            payload = {
                "source_id": identity,
                "source_bytes": data,
                "source_sha": sha(data),
                "document_json": document,
                "markdown": markdown,
                "content_sha": content_hash,
                "metadata_json": canonical(metadata),
            }
            if previous:
                self.verify(previous, live=False)
                if all(previous[key] == payload[key] for key in payload):
                    self.db.commit()
                    return self.summary(previous, reused=True)
            version = previous["version"] + 1 if previous else 1
            if version > MAX_VERSIONS:
                raise IntakeError(f"Source reached the {MAX_VERSIONS}-version limit.")
            payload.update(version=version, created_at=now())
            payload["integrity_sha"] = self.integrity(payload)
            self.db.execute(
                "INSERT INTO versions VALUES (:source_id,:version,:source_bytes,:source_sha,"
                ":document_json,:markdown,:content_sha,:metadata_json,:integrity_sha,:created_at)",
                payload,
            )
            self.db.commit()
            return self.summary(payload, reused=False)
        except Exception:
            self.db.rollback()
            raise

    def get(self, identity: str, version: int | None = None) -> sqlite3.Row:
        if version is not None and version < 1:
            raise IntakeError("Version must be positive.")
        row = self.db.execute(
            "SELECT * FROM versions WHERE source_id=? "
            + ("AND version=?" if version is not None else "ORDER BY version DESC LIMIT 1"),
            (identity, version) if version is not None else (identity,),
        ).fetchone()
        if row is None:
            raise IntakeError("Intake version not found.")
        return row

    def verify(self, row: dict | sqlite3.Row, *, live: bool = True) -> DoclingDocument:
        try:
            doc = DoclingDocument.model_validate_json(row["document_json"])
            document, markdown, content_hash = reviewed(doc)
            valid = (
                sha(row["source_bytes"]) == row["source_sha"]
                and document == row["document_json"]
                and markdown == row["markdown"]
                and content_hash == row["content_sha"]
                and self.integrity(row) == row["integrity_sha"]
                and canonical(json.loads(row["metadata_json"])) == row["metadata_json"]
            )
        except Exception as exc:
            raise IntakeError("Stored version failed schema/integrity validation.") from exc
        if not valid:
            raise IntakeError("Stored version integrity mismatch.")
        if live and sha(self.read_source(row["source_id"])) != row["source_sha"]:
            raise IntakeError(
                "Source bytes changed since intake; intake and review a new version."
            )
        return doc

    def summary(self, row: dict | sqlite3.Row, **extra: object) -> dict:
        decision = self.db.execute(
            "SELECT * FROM decisions WHERE source_id=? AND version=?",
            (row["source_id"], row["version"]),
        ).fetchone()
        if decision:
            self.verify_decision(decision, row)
        try:
            conversion = json.loads(row["metadata_json"])
        except (TypeError, ValueError):
            conversion = {"unavailable": "Stored conversion metadata is invalid."}
        return {
            "source_id": row["source_id"],
            "version": row["version"],
            "source_sha256": row["source_sha"],
            "content_sha256": row["content_sha"],
            "decision": decision["decision"] if decision else "pending",
            "conversion": conversion,
            **extra,
        }

    def review(self, identity: str, version: int) -> dict:
        row = self.get(identity, version)
        self.verify(row)
        return {
            **self.summary(row),
            "latest": self.get(identity)["version"] == version,
            "markdown": row["markdown"],
            "document": json.loads(row["document_json"]),
        }

    def decide(
        self,
        identity: str,
        version: int,
        expected_sha: str,
        decision: str,
        reviewer: str,
        reason: str = "",
    ) -> dict:
        if (
            decision not in ("approve", "reject")
            or not reviewer.strip()
            or len(reviewer) > 80
            or len(reason) > 500
        ):
            raise IntakeError(
                "Decision/reviewer invalid; reviewer 1..80, reason <=500 characters."
            )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.get(identity, version)
            if self.get(identity)["version"] != version:
                raise IntakeError("Stale version; review the latest intake version.")
            self.verify(row)
            if row["content_sha"] != expected_sha:
                raise IntakeError("Content SHA-256 does not match the exact reviewed version.")
            existing = self.db.execute(
                "SELECT * FROM decisions WHERE source_id=? AND version=?",
                (identity, version),
            ).fetchone()
            values = (decision, reviewer.strip(), reason)
            if existing:
                self.verify_decision(existing, row)
                if tuple(existing[key] for key in ("decision", "reviewer", "reason")) != values:
                    raise IntakeError("Version already has a different immutable decision.")
            else:
                record = {
                    "source_id": identity,
                    "version": version,
                    "decision": decision,
                    "reviewer": reviewer.strip(),
                    "reason": reason,
                    "decided_at": now(),
                }
                record["integrity_sha"] = self.decision_integrity(record, row)
                self.db.execute(
                    "INSERT INTO decisions VALUES (:source_id,:version,:decision,"
                    ":integrity_sha,:reviewer,:reason,:decided_at)",
                    record,
                )
            self.db.commit()
            return self.summary(row)
        except Exception:
            self.db.rollback()
            raise

    def status(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT v.* FROM versions v JOIN
            (SELECT source_id,MAX(version) version FROM versions GROUP BY source_id) latest
            USING(source_id,version) ORDER BY source_id
        """).fetchall()
        result = []
        for row in rows:
            try:
                self.verify(row)
                integrity = "verified"
            except IntakeError as exc:
                integrity = str(exc)
            result.append(self.summary(row, integrity=integrity))
        return result

    def export(self, filename: str, identity: str | None = None) -> dict:
        if (
            not filename.endswith(".jsonl")
            or len(filename) > 128
            or any(c in filename for c in "/\\:")
            or filename.startswith(".")
        ):
            raise IntakeError("Export must be a plain .jsonl filename under exports/.")
        target = self.exports / filename
        if target.exists() or target.is_symlink():
            raise IntakeError("Export already exists; choose a new filename.")
        self.db.execute("BEGIN IMMEDIATE")
        temporary = None
        try:
            identities = (
                [identity]
                if identity
                else [
                    row[0]
                    for row in self.db.execute(
                        "SELECT DISTINCT source_id FROM versions ORDER BY source_id"
                    )
                ]
            )
            records = []
            for source_id in identities:
                row = self.get(source_id)
                decision = self.db.execute(
                    "SELECT * FROM decisions WHERE source_id=? AND version=?",
                    (source_id, row["version"]),
                ).fetchone()
                if decision:
                    self.verify_decision(decision, row)
                if not decision or decision["decision"] != "approve":
                    if identity:
                        raise IntakeError("Selected latest version is pending or rejected.")
                    continue
                doc = self.verify(row)
                for item, _ in doc.iterate_items():
                    records.append(
                        {
                            "source_id": source_id,
                            "source_sha256": row["source_sha"],
                            "version": row["version"],
                            "content_sha256": row["content_sha"],
                            "item_ref": item.self_ref,
                            "page_refs": sorted({p.page_no for p in getattr(item, "prov", [])}),
                            "item": item.model_dump(mode="json", exclude_none=True),
                            "approval": {
                                "reviewer": decision["reviewer"],
                                "decided_at": decision["decided_at"],
                            },
                            "conversion": json.loads(row["metadata_json"]),
                        }
                    )
            if not records:
                raise IntakeError("No approved current documents to export.")
            # minimalism: exclusive hard-link publication avoids a check/replace overwrite race.
            descriptor, temporary = tempfile.mkstemp(prefix=".intake-", dir=self.exports)
            with os.fdopen(descriptor, "wb") as output:
                output.write(
                    "".join(canonical(record) + "\n" for record in records).encode("utf-8")
                )
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, target)
            self.db.commit()
            return {
                "output": str(target),
                "items": len(records),
                "sha256": sha(target.read_bytes()),
            }
        except Exception:
            self.db.rollback()
            raise
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    intake = commands.add_parser("intake")
    intake.add_argument("source")
    intake.add_argument("--format", choices=("markdown", "docling-json"))
    commands.add_parser("status")
    review = commands.add_parser("review")
    review.add_argument("source")
    review.add_argument("--version", required=True, type=int)
    decide = commands.add_parser("decide")
    decide.add_argument("source")
    decide.add_argument("--version", required=True, type=int)
    decide.add_argument("--sha256", required=True)
    decide.add_argument("--decision", required=True, choices=("approve", "reject"))
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--reason", default="")
    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    export.add_argument("--source")
    args = parser.parse_args(argv)
    store = None
    try:
        store = Store(args.workspace)
        if args.command == "init":
            result = {"workspace": str(store.workspace), "max_source_bytes": MAX_BYTES}
        elif args.command == "intake":
            result = store.intake(args.source, args.format)
        elif args.command == "review":
            result = store.review(args.source, args.version)
        elif args.command == "decide":
            result = store.decide(
                args.source,
                args.version,
                args.sha256,
                args.decision,
                args.reviewer,
                args.reason,
            )
        elif args.command == "status":
            result = store.status()
        else:
            result = store.export(args.output, args.source)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (IntakeError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
