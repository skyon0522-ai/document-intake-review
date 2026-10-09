# Source references and notices

The source for this composition was inspected before copying. It was taken from the saved, pinned local Git objects, not from installed package files.

- Docling project, `https://github.com/docling-project/docling`, tag v2.135.0, commit `2b3a00c5bfcd8b218d32e7e9c33d509aeaa0cb56`. Source: `components/docling-slim/docling/`. Original MIT license: `components/docling-slim/LICENSE`, copyright The Docling Contributors. Original package/build identity: root `pyproject.toml`, hatchling, `docling-slim` 2.135.0, complete `docling` package. Its slim-package README is a required build input and was read from the same Git commit.
- Docling Core, `https://github.com/docling-project/docling-core`, tag v2.101.1, commit `f61fbf5cd4384a6307c63131a3f2f70d517b5f51`. Source: `components/docling-core/docling_core/`. Original MIT license: `components/docling-core/LICENSE`, copyright 2024 International Business Machines. Original metadata has no explicit build-system section; pip uses its default setuptools backend. The original package search and JSON schema package-data settings were preserved.

## Inspected execution and development paths

Docling `docling/backend/md_backend.py` implements the actual Markdown backend. It uses Marko GFM, constructs DoclingDocument items and delegates embedded HTML to `docling/backend/html_backend.py`. Its original imports include `backend/abstract_backend.py`, `backend/utils/image_resource_loader.py`, `datamodel/backend_options.py`, `datamodel/base_models.py`, `datamodel/document.py`, `utils/code_language.py` and `utils/text_decoding.py`. These are copied with the existing package, not replaced with adapters. `InputDocument` records the source origin and loads the concrete backend. Resource fetching is disabled through original MarkdownBackendOptions fields.

Core `docling_core/types/doc/document.py` provides DoclingDocument validation, item traversal, structured export and Markdown export. It uses the existing split types under `types/doc/common/` and `types/doc/items/` and original transforms/serializers. The original JSON package-data rules are preserved; the pinned Git package tree contains no committed JSON resources. The exercised schema is the existing Python/Pydantic implementation. Pydantic, Marko, Beautiful Soup, pandas and other normal transitive dependencies are listed separately in `dependencies-lock.txt`.

The inspected upstream baseline is Docling `tests/test_backend_markdown.py::test_convert_valid`: construct InputDocument, construct the concrete backend, verify it, call convert and export Markdown. `tools/compare_component.py` adapts only the shared fixture stream, filename and disabled resource options, then uses the unchanged backend/schema. Core `tests/test_serialization.py` supplied the document/schema/Markdown comparison contract. The complete upstream test suites were not run: they import converters, many formats and optional models beyond this Markdown/JSON slice. The direct component baseline and inherited intake tests execute the actual selected components without those extras.

The upstream Docling Makefile uses `make setup`, `make test`, and `make validate` for its full development environment. That environment includes all extras and mutating hooks and was not applied to these unchanged copies. This composition performs scoped lint, real conversion comparisons, dependency checks, package builds, installed CLI scenarios and the inherited contract tests instead. No claim of full upstream validation is made.

## Adaptation boundary

All 401 upstream source/build files were copied as Git blobs with zero modifications. `SOURCE_MANIFEST.json` gives per-file exact hashes, Git blob IDs, line counts, original and copied paths. The copied package modules provide the running components. Preserved original build metadata may contain optional format/model extras, but those extras and weights are not installed or executed.

The repaired review application, tests and CLI demo are local preexisting work, copied into `comparison-snapshot/`. Their provenance is not relabeled as upstream Docling application source. Composition changes add the source-origin/hash check, package that identity manifest and provide the source build/comparison commands. `Store.decision_integrity`, `Store.verify_decision`, legacy refusal, version selection and atomic JSONL publication remain from the repaired app.

See `docs/verification.json` for the recorded local checks and their limits.

## Research background

Auer et al., [Docling Technical Report](https://arxiv.org/abs/2408.09869), 2024; also available on [alphaXiv](https://www.alphaxiv.org/abs/2408.09869). The report describes upstream PDF conversion with layout and table models. It is background for the converter's architecture; this repository checks Markdown and document JSON, not the paper's PDF or model results.
