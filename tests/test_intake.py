import json
import os
import shutil
import socket
from pathlib import Path

import pytest
from docling_core.types.doc import DoclingDocument

from intake_review import MAX_BYTES, IntakeError, Store, canonical, convert, main, reviewed, sha

FIXTURE = Path(__file__).parents[1] / "fixtures" / "intake.md"


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "workspace")
    shutil.copyfile(FIXTURE, result.sources / "handbook.md")
    yield result
    result.close()


def approve(store, intake):
    return store.decide(
        intake["source_id"],
        intake["version"],
        intake["content_sha256"],
        "approve",
        "Test reviewer",
    )


def test_real_markdown_backend_table_and_core_roundtrip(monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("Conversion must not access the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    document, metadata = convert(FIXTURE.read_bytes(), "intake.md", "markdown")
    assert metadata["backend"].endswith("MarkdownDocumentBackend.convert")
    assert metadata["docling_slim"] == "2.135.0"
    assert metadata["table_score"] is None
    assert document.pages == {}  # Markdown does not invent physical pages.
    table = document.tables[0]
    assert (table.data.num_rows, table.data.num_cols) == (3, 3)
    assert [cell.text for cell in table.data.table_cells] == [
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
    output = DoclingDocument.model_validate(document.export_to_dict())
    assert reviewed(document) == reviewed(output)
    assert "| High" in output.export_to_markdown()
    assert "Service desk" in output.export_to_html()


def test_approval_gate_and_actual_item_refs(store):
    intake = store.intake("handbook.md")
    assert intake["decision"] == "pending"
    with pytest.raises(IntakeError, match="pending or rejected"):
        store.export("pending.jsonl", "handbook.md")
    assert not (store.exports / "pending.jsonl").exists()
    review = store.review("handbook.md", 1)
    assert review["content_sha256"] == intake["content_sha256"]
    assert review["document"]["tables"][0]["data"]["table_cells"][5]["text"] == "4"
    with pytest.raises(IntakeError, match="SHA-256"):
        store.decide("handbook.md", 1, "0" * 64, "approve", "Reviewer")
    approve(store, intake)
    assert approve(store, intake)["decision"] == "approve"
    result = store.export("approved.jsonl")
    records = [json.loads(line) for line in Path(result["output"]).read_text().splitlines()]
    doc = DoclingDocument.model_validate(review["document"])
    assert [row["item_ref"] for row in records] == [
        item.self_ref for item, _ in doc.iterate_items()
    ]
    assert all(row["source_sha256"] == sha(FIXTURE.read_bytes()) for row in records)
    assert all(row["content_sha256"] == intake["content_sha256"] for row in records)
    assert all(row["page_refs"] == [] for row in records)
    table = next(row for row in records if row["item"]["label"] == "table")
    assert table["item"]["data"]["num_rows"] == 3
    assert result["sha256"] == sha(Path(result["output"]).read_bytes())


def test_json_export_import_retains_real_page_provenance(store):
    from docling_core.types.doc import BoundingBox, DocItemLabel, ProvenanceItem, Size

    # An actual, self-authored DoclingDocument export; this is not OCR/conversion evidence.
    document = DoclingDocument(name="schema-export-fixture")
    document.add_page(page_no=7, size=Size(width=100, height=100))
    document.add_text(
        label=DocItemLabel.TEXT,
        text="Self-authored schema provenance fixture.",
        prov=ProvenanceItem(
            page_no=7, bbox=BoundingBox(l=1, t=1, r=90, b=20), charspan=(0, 40)
        ),
    )
    raw = canonical(document.export_to_dict()).encode()
    (store.sources / "schema-export.json").write_bytes(raw)
    intake = store.intake("schema-export.json")
    approve(store, intake)
    result = store.export("schema.jsonl", "schema-export.json")
    record = json.loads(Path(result["output"]).read_text())
    assert record["page_refs"] == [7]
    assert record["item_ref"] == "#/texts/0"
    assert record["item"]["prov"][0]["page_no"] == 7
    assert store.review("schema-export.json", 1)["document"] == document.export_to_dict()


def test_reimport_is_idempotent_but_changed_bytes_require_new_approval(store):
    first = store.intake("handbook.md")
    approve(store, first)
    repeated = store.intake("handbook.md")
    assert repeated["version"] == 1 and repeated["reused"] and repeated["decision"] == "approve"
    (store.sources / "handbook.md").write_bytes(FIXTURE.read_bytes() + b"\n")
    with pytest.raises(IntakeError, match="Source bytes changed"):
        store.export("changed.jsonl")
    with pytest.raises(IntakeError, match="Source bytes changed"):
        approve(store, first)
    second = store.intake("handbook.md")
    assert second["version"] == 2 and second["decision"] == "pending"
    assert second["content_sha256"] != first["content_sha256"]
    assert store.get("handbook.md", 2)["markdown"] == store.get("handbook.md", 1)["markdown"]
    with pytest.raises(IntakeError, match="Stale version"):
        approve(store, first)
    with pytest.raises(IntakeError, match="pending or rejected"):
        store.export("new-pending.jsonl", "handbook.md")
    (store.sources / "handbook.md").write_bytes(FIXTURE.read_bytes())
    third = store.intake("handbook.md")
    assert third["version"] == 3 and third["decision"] == "pending"


def test_reject_and_decision_immutability(store):
    intake = store.intake("handbook.md")
    store.decide(
        "handbook.md", 1, intake["content_sha256"], "reject", "Reviewer", "Incorrect owner"
    )
    with pytest.raises(IntakeError, match="pending or rejected"):
        store.export("rejected.jsonl", "handbook.md")
    with pytest.raises(IntakeError, match="different immutable decision"):
        approve(store, intake)
    with pytest.raises(IntakeError, match="No approved"):
        store.export("empty.jsonl")


@pytest.mark.parametrize("identity", ["handbook.md", None])
@pytest.mark.parametrize(
    "column,value",
    [
        ("decision", "approve"),
        ("reviewer", "Changed reviewer"),
        ("reason", "Changed reason"),
        ("decided_at", "2000-01-01T00:00:00+00:00"),
    ],
)
def test_rejected_decision_tamper_refused_without_output(store, identity, column, value):
    intake = store.intake("handbook.md")
    store.decide(
        "handbook.md", 1, intake["content_sha256"], "reject", "Reviewer", "Incorrect owner"
    )
    version = dict(store.get("handbook.md"))
    store.db.execute(f"UPDATE decisions SET {column}=?", (value,))
    store.db.commit()
    with pytest.raises(IntakeError, match="decision integrity"):
        store.export("decision-tampered.jsonl", identity)
    with pytest.raises(IntakeError, match="decision integrity"):
        store.review("handbook.md", 1)
    with pytest.raises(IntakeError, match="decision integrity"):
        approve(store, intake)
    assert not (store.exports / "decision-tampered.jsonl").exists()
    assert list(store.exports.iterdir()) == []
    assert dict(store.get("handbook.md")) == version
    assert (store.sources / "handbook.md").read_bytes() == FIXTURE.read_bytes()


def test_approved_only_export_skips_other_pending_sources(store):
    approved = store.intake("handbook.md")
    approve(store, approved)
    (store.sources / "other.md").write_text("# Pending\n", encoding="utf-8")
    store.intake("other.md")
    result = store.export("approved-only.jsonl")
    assert {
        json.loads(line)["source_id"]
        for line in Path(result["output"]).read_text().splitlines()
    } == {"handbook.md"}


@pytest.mark.parametrize(
    "column,value",
    [
        ("source_bytes", b"tampered"),
        ("markdown", "tampered"),
        ("document_json", "{}"),
        ("metadata_json", "{}"),
        ("content_sha", "0" * 64),
        ("source_sha", "0" * 64),
    ],
)
def test_stored_version_tamper_rejected_without_output(store, column, value):
    intake = store.intake("handbook.md")
    approve(store, intake)
    store.db.execute(f"UPDATE versions SET {column}=?", (value,))
    store.db.commit()
    with pytest.raises(IntakeError, match="integrity|schema"):
        store.export("tampered.jsonl")
    assert not (store.exports / "tampered.jsonl").exists()


def test_stale_approval_binding_rejected(store):
    intake = store.intake("handbook.md")
    approve(store, intake)
    store.db.execute("UPDATE decisions SET integrity_sha=?", ("0" * 64,))
    store.db.commit()
    with pytest.raises(IntakeError, match="decision integrity"):
        store.export("stale.jsonl")


def test_legacy_decision_preserved_but_not_trusted(store):
    intake = store.intake("handbook.md")
    approve(store, intake)
    version = dict(store.get("handbook.md"))
    store.db.execute("UPDATE decisions SET integrity_sha=?", (version["integrity_sha"],))
    store.db.commit()
    decision = dict(store.db.execute("SELECT * FROM decisions").fetchone())
    store.close()
    reopened = Store(store.workspace)
    try:
        with pytest.raises(IntakeError, match="legacy decisions"):
            reopened.export("legacy.jsonl")
        with pytest.raises(IntakeError, match="legacy decisions"):
            approve(reopened, intake)
        assert not (reopened.exports / "legacy.jsonl").exists()
        assert dict(reopened.get("handbook.md")) == version
        assert dict(reopened.db.execute("SELECT * FROM decisions").fetchone()) == decision
    finally:
        reopened.close()


def test_status_reports_corrupt_metadata_without_traceback(store):
    store.intake("handbook.md")
    store.db.execute("UPDATE versions SET metadata_json=?", ("not-json",))
    store.db.commit()
    result = store.status()[0]
    assert "integrity" in result["integrity"]
    assert "unavailable" in result["conversion"]


def test_atomic_export_no_overwrite_even_target_race(store, monkeypatch):
    approve(store, store.intake("handbook.md"))
    target = store.exports / "race.jsonl"
    original_link = os.link

    def race(source, destination):
        target.write_bytes(b"existing output")
        return original_link(source, destination)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        store.export("race.jsonl")
    assert target.read_bytes() == b"existing output"
    assert list(store.exports.glob(".intake-*")) == []
    with pytest.raises(IntakeError, match="already exists"):
        store.export("race.jsonl")


@pytest.mark.parametrize(
    "identity",
    ["../outside.md", "/outside.md", "C:/outside.md", "x\\y.md", "./handbook.md", "a//b.md"],
)
def test_source_path_bounds(store, identity):
    with pytest.raises(IntakeError, match="relative POSIX"):
        store.intake(identity)


def test_size_utf8_format_and_schema_bounds(store):
    for filename, data, error in [
        ("large.md", b"x" * (MAX_BYTES + 1), "Source size"),
        ("empty.md", b"", "Source size"),
        ("bad.md", b"\xff", "conversion/schema"),
        ("bad.json", b"{}", "conversion/schema"),
        ("unsupported.pdf", b"%PDF", "Supported formats"),
    ]:
        (store.sources / filename).write_bytes(data)
        with pytest.raises(IntakeError, match=error):
            store.intake(filename)


def test_symlink_escape_rejected(store, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    try:
        (store.sources / "link.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks unavailable on this host")
    with pytest.raises(IntakeError, match="symlinks"):
        store.intake("link.md")


def test_cli_errors_are_clear_and_status_records_source_mismatch(store, capsys):
    store.intake("handbook.md")
    (store.sources / "handbook.md").write_text("# Changed\n", encoding="utf-8")
    assert "Source bytes changed" in store.status()[0]["integrity"]
    assert (
        main(["--workspace", str(store.workspace), "export", "--output", "../bad.jsonl"]) == 2
    )
    assert "plain .jsonl" in capsys.readouterr().err


def test_inline_html_delegates_to_real_official_backend_without_fetch():
    document, metadata = convert(
        b"# Heading\n\n<table><tr><td>value</td></tr></table>\n", "inline.md", "markdown"
    )
    assert metadata["resource_fetch"].startswith("disabled")
    assert document.tables[0].data.table_cells[0].text == "value"
