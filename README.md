# Document Intake Review — source-based composition

This local CLI converts Markdown and accepts DoclingDocument JSON. A reviewer examines the exact version and its content hash before JSONL export. Changed source bytes, pending or rejected versions, damaged decisions and legacy unsealed decisions block export.

The conversion and schema components are actual duplicated upstream package source. `components/docling-slim` is Docling v2.135.0 at `2b3a00c5bfcd8b218d32e7e9c33d509aeaa0cb56`. `components/docling-core` is Docling Core v2.101.1 at `f61fbf5cd4384a6307c63131a3f2f70d517b5f51`. Original build metadata, licenses and copyright notices are retained. No parser or schema implementation was rewritten.

## Repository map

| Start here | Purpose |
| --- | --- |
| [intake_review.py](intake_review.py) and [tools/demo.py](tools/demo.py) | Review/export adapter and runnable demonstration |
| [tests/](tests/) | Review/export and copied-source identity checks |
| [tools/install_source.py](tools/install_source.py) | Build and install the local copied packages |
| [docs/architecture.md](docs/architecture.md) and [docs/source-composition.md](docs/source-composition.md) | Data flow, reuse boundary and recorded comparison |
| [components/](components/) and [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) | Unchanged package source, licenses and exact identities |
| [REFERENCES.md](REFERENCES.md) | Research context and limits |

The component directories preserve upstream package snapshots. Some copied README example/contribution links refer to files outside those snapshots. For the complete upstream guides, use the pinned [Docling repository](https://github.com/docling-project/docling/tree/2b3a00c5bfcd8b218d32e7e9c33d509aeaa0cb56) and [Docling Core repository](https://github.com/docling-project/docling-core/tree/f61fbf5cd4384a6307c63131a3f2f70d517b5f51). Use this root README for the assembled product's commands and scope.

## Build and run

Use Python 3.12 from a short checkout path on Windows. Run the source installer from a fresh checkout. It creates a new environment, installs the pinned normal dependencies, builds both copied upstream packages and this adapter, and installs only those three local wheels with `--no-index --no-deps`. It records all commands, outputs and wheel hashes in `.source-build/<label>/install.json`. Package downloads for normal dependencies and isolated build tooling are required; document conversion needs no network access.

```sh
python tools/install_source.py
# Windows
.v/Scripts/python -m pytest -q
.v/Scripts/python tools/demo.py --workspace demo-workspace --receipt demo-receipt.json
# Linux
.v/bin/python -m pytest -q
.v/bin/python tools/demo.py --workspace demo-workspace --receipt demo-receipt.json
```

Do not replace the source installer with `pip install .`: that would permit dependency resolution from a package index. The application requires file-based wheel origin metadata with a nonempty archive hash and checks loaded Docling module bytes against `SOURCE_MANIFEST.json`; an ordinary registry distribution without that origin is refused. The runtime guard does not compare that archive hash with a built wheel. The build receipts perform that comparison separately. The identity checks detect packaging mistakes and source changes, and do not authenticate against an owner who can rewrite the manifest and checks.

The installed command is `intake-review`. Create a workspace with `intake-review --workspace demo-workspace init`, copy a Markdown file into `demo-workspace/sources/`, and run `intake`, `review`, `decide` and `export`. The existing demo shows the exact command arguments and records installed CLI output. PDF, OCR, model weights, hosted services and external indexes are outside this slice.

## Lineage and limits

`SOURCE_MANIFEST.json` records every copied Git blob, SHA-256, original path, commit, physical line count and zero modified source lines. The complete upstream Python packages retain their own dependency graph; optional code for other formats and models remains present as source, without corresponding model dependencies, weights, fixtures or execution. This avoids extracting one parser file and replacing its required modules. `dependencies-lock.txt` distinguishes normal transitive dependencies from the two local-source packages.

`comparison-snapshot/` preserves the repaired application and tests before integration. The application adds only the source-identity import/check. SQLite review decisions, their checksum repair, version gates and legacy fail-closed behavior remain inherited from that repaired application, not from Docling. Source-based composition does not establish inherited lineage for that review application itself.

The baseline uses the concrete upstream `tests/test_backend_markdown.py::test_convert_valid` construction sequence and Core schema/serialization contracts. Comparative receipts execute original pinned source, unchanged copied source and the installed composition against the same seven-item fixture. They include actual `__file__` paths and normalized source hashes. The focused inherited tests and CLI demo verify local review behavior. See `REFERENCES.md` and `docs/source-composition.md` for the inspected paths and evidence.

This is a local, owner-controlled review gate. Approval labels are not authenticated identities; integrity hashes are not signatures against an administrator. The recorded checks cover the local workflow; remote CI has not run.
