"""Execute original, unchanged duplicate, or composed source-based intake."""

import argparse
import hashlib
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--stage", choices=["original", "duplicate", "composed"], required=True)
parser.add_argument("--receipt", type=Path, required=True)
parser.add_argument("--docling-source", type=Path)
parser.add_argument("--core-source", type=Path)
parser.add_argument("--workspace", type=Path)
args = parser.parse_args()
if args.receipt.exists():
    raise SystemExit("Receipt already exists.")
if args.stage in ("original", "duplicate"):
    if not args.docling_source or not args.core_source:
        raise SystemExit("Both source paths are required for a source baseline.")
    sys.path[:0] = [str(args.docling_source), str(args.core_source)]
    # Identity utility is shared measurement code, not a parser/schema substitute.
    sys.path.append(str(ROOT))


def deny_network(*_args, **_kwargs):
    raise AssertionError("This local conversion comparison must not access the network")


socket.socket.connect = deny_network
fixture = (ROOT / "fixtures/intake.md").read_bytes()
refusals = {}
if args.stage == "composed":
    import intake_review
    from intake_review import IntakeError, Store

    if args.workspace is None or args.workspace.exists():
        raise SystemExit("Composed stage requires a new workspace.")
    store = Store(args.workspace)
    (store.sources / "handbook.md").write_bytes(fixture)
    first = store.intake("handbook.md")
    review = store.review("handbook.md", 1)

    def refuse(label, operation):
        try:
            operation()
        except IntakeError as exc:
            refusals[label] = str(exc)
        else:
            raise AssertionError(f"Expected refusal: {label}")

    refuse("pending_export", lambda: store.export("pending.jsonl", "handbook.md"))
    store.decide("handbook.md", 1, first["content_sha256"], "approve", "Comparison reviewer")
    exported = store.export("approved.jsonl", "handbook.md")
    assert exported["items"] == 7
    (store.sources / "rejected.md").write_bytes(fixture)
    rejected = store.intake("rejected.md")
    store.decide("rejected.md", 1, rejected["content_sha256"], "reject", "Comparison reviewer")
    refuse("rejected_export", lambda: store.export("rejected.jsonl", "rejected.md"))
    (store.sources / "handbook.md").write_bytes(fixture + b"\n")
    refuse("changed_source_export", lambda: store.export("changed.jsonl", "handbook.md"))
    second = store.intake("handbook.md")
    assert second["version"] == 2 and second["decision"] == "pending"
    refuse(
        "stale_decision",
        lambda: store.decide(
            "handbook.md", 1, first["content_sha256"], "approve", "Comparison reviewer"
        ),
    )
    refuse(
        "new_version_pending_export", lambda: store.export("new-pending.jsonl", "handbook.md")
    )
    assert sorted(path.name for path in store.exports.iterdir()) == ["approved.jsonl"]
    document_json = review["document"]
    markdown = review["markdown"]
    from docling_core.types.doc import DoclingDocument

    document = DoclingDocument.model_validate(document_json)
    store.close()
else:
    from io import BytesIO

    from docling.backend.md_backend import MarkdownDocumentBackend
    from docling.datamodel.backend_options import MarkdownBackendOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import InputDocument
    from docling_core.types.doc import DoclingDocument

    # Upstream test_convert_valid constructs InputDocument, backend and convert().
    # Only stream/resource options adapt that source contract to the shared fixture.
    stream = BytesIO(fixture)
    options = MarkdownBackendOptions(
        encoding="utf-8",
        fetch_images=False,
        enable_remote_fetch=False,
        enable_local_fetch=False,
    )
    in_doc = InputDocument(
        path_or_stream=stream,
        filename="handbook.md",
        format=InputFormat.MD,
        backend=MarkdownDocumentBackend,
        backend_options=options,
    )
    backend = MarkdownDocumentBackend(in_doc, stream, options)
    try:
        assert in_doc.valid and backend.is_valid()
        document = backend.convert()
        document = DoclingDocument.model_validate(document.export_to_dict())
        document_json = document.export_to_dict()
        markdown = (
            document.export_to_markdown().replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
            + "\n"
        )
    finally:
        backend.unload()
        in_doc._backend.unload()

from source_identity import loaded_modules, verify_source_components  # noqa: E402

modules = loaded_modules()
if args.stage != "composed":
    for item in modules:
        source = (
            args.docling_source
            if item["module"].split(".", 1)[0] == "docling"
            else args.core_source
        )
        assert Path(item["file"]).is_relative_to(source.resolve()), item
else:
    identity = verify_source_components()
    assert Path(intake_review.__file__).resolve() != ROOT / "intake_review.py"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


content = canonical({"document": document_json, "markdown": markdown})
table = document.tables[0].data
assert (table.num_rows, table.num_cols) == (3, 3)
assert [cell.text for cell in table.table_cells] == [
    "Priority",
    "Owner",
    "Hours",
    "High",
    "Operations",
    "4",
    "Normal",
    "Service desk",
    "24",
]
refs = [item.self_ref for item, _ in document.iterate_items()]
assert len(refs) == 7
receipt = {
    "stage": args.stage,
    "runtime": sys.version,
    "fixture_sha256": hashlib.sha256(fixture).hexdigest(),
    "document": document_json,
    "markdown": markdown,
    "item_refs": refs,
    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
    "table_shape": [table.num_rows, table.num_cols],
    "loaded_modules": modules,
    "network": "socket connect refused during entire conversion run",
    "refusals": refusals,
}
if args.stage == "composed":
    receipt.update(
        identity=identity,
        export=exported,
        installed_application={
            "file": str(Path(intake_review.__file__).resolve()),
            "sha256": hashlib.sha256(Path(intake_review.__file__).read_bytes()).hexdigest(),
        },
    )
args.receipt.parent.mkdir(parents=True, exist_ok=True)
args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "stage": args.stage,
            "content_sha256": receipt["content_sha256"],
            "items": len(refs),
            "modules_checked": len(modules),
            "refusals": refusals,
        },
        indent=2,
    )
)
