# Architecture and decision boundary

[Open the offline demo result](demo-result.html) for the checked-in synthetic Markdown input, the observed approval gates, and the exported JSONL records.

The owner-controlled workspace contains `sources/`, `intake.sqlite3`, and `exports/`. No database or document is sent elsewhere. The CLI is a single module; SQLite transactions and standard filesystem primitives provide the local gate.

## Entry points

| Path | Responsibility |
| --- | --- |
| [`tools/demo.py`](../tools/demo.py) | Copies the synthetic fixture into a fresh workspace, runs the CLI sequence, and saves a receipt plus an optional standalone HTML result. |
| [`intake_review.py`](../intake_review.py) `main()` | Parses `init`, `intake`, `review`, `decide`, `status`, and `export` commands and dispatches them to `Store`. |
| [`intake_review.py`](../intake_review.py) `convert()` | Uses Docling's Markdown backend or validates DoclingDocument JSON; local, remote, and image fetching are disabled. |
| [`intake_review.py`](../intake_review.py) `Store` | Saves versions, verifies the reviewed content hash, records the immutable decision, and validates current bytes before export. |
| [`source_identity/__init__.py`](../source_identity/__init__.py) | Refuses registry-origin distributions and checks loaded component files against the local manifest. |

The demo is not a second implementation of the gate. It invokes the installed `intake-review` command so the walkthrough exercises the same parser and `Store` methods used by a normal CLI user.

```text
sources/handbook.md bytes
  -> bounded read and SHA-256
  -> official InputDocument + MarkdownDocumentBackend.convert()
     local/remote/image fetching disabled
  -> real DoclingDocument schema validation
  -> canonical document JSON + normalized Markdown
  -> SQLite pending version
  -> human review of exact version and content hash
  -> immutable approve/reject decision bound to version integrity
  -> latest-version + schema + hash + current-source checks
  -> temporary JSONL, fsync, exclusive hard link to exports/
```

An actual DoclingDocument JSON export enters through `DoclingDocument.model_validate_json` instead of Markdown conversion. Both routes then use the same schema, review hash, and approval gate. The upstream `tests/test_backend_markdown.py::test_convert_valid` supplied the direct-backend pattern. The upstream simple pipeline confirms declarative backends return DoclingDocument directly. Core serialization tests supplied the schema round-trip and explicit provenance test pattern.

`versions` stores a composite `(source_id, version)` key, raw source bytes/hash, canonical document JSON, normalized Markdown, content hash, canonical conversion metadata, integrity hash, and intake timestamp. `decisions` has that same key, decision, version integrity hash, reviewer label, reason, and decision timestamp. Decisions are application-enforced immutable; there is no destructive reset command.

The content hash binds the document structure as well as its text view. The integrity hash additionally binds source identity, version, source hash, and conversion metadata. Source bytes are retained and checked against their hash. A conversion result or imported structure is not accepted as an approval.

Import, decision, and export use `BEGIN IMMEDIATE` to serialize local writers. Export selects latest approved versions within one database transaction, validates every selected record, prepares all rows, and publishes one output file. A refused record leaves no partial target. The filesystem may change outside SQLite; the supported use is an owner-controlled stable tree, not an adversarial concurrent writer.

Default export omits latest pending/rejected versions. Explicit source export refuses either state. A source mismatch or a stale/damaged selected approval fails the whole operation. The old stored bytes remain available for diagnosis, but only a latest version matching the current source can receive or use approval.

This gate ends at approved JSONL. An external index uploader, authenticated reviewer system, production retention policy, PDF/OCR pipeline, server, or dashboard needs a separate implementation. None is implemented here.
