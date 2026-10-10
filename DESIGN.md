# Design record: document intake demo

## Reader and use

The reader is an engineer deciding whether the local conversion and approval
flow is understandable and runnable. The README should help them assess the
purpose, try a synthetic input, see the observed result, and find the relevant
code. The voice is concise, direct technical English; describe observed gates
and outputs without implying authenticated review or production use.

## References and adopted structure

- The read-only reference was the existing `Ops Daily Report` README. Its order
  moves from purpose to a synthetic example, a runnable command, actual result
  counts, navigation, and scope. This README uses the same information order
  for document intake.
- The installed `answer-me-with-html` renderer was inspected. Its default sheet
  layout organizes sections as a multi-column panel grid. That grid would weaken
  the ordered input → review → decision → export → changed-source sequence here,
  so the demo result uses one semantic document flow with a contents list,
  tables, and expandable detail.

## Design choices

- The README starts with the review gate, then links to the generated result and
  architecture. The actual CLI commands and results appear before implementation
  and reuse notes.
- `docs/demo-result.html` is generated from the captured CLI receipt. It shows
  the fixture copied into the workspace, normalized review text, decision
  gates, exported JSONL records, hashes, and changed-copy outcome. The fixture
  is embedded, so the HTML has no path-dependent link. It contains no
  JavaScript, remote assets, or external links.
- Semantic headings, navigation, table headers, visible gate text, native
  disclosure controls, a 16px base font, wrapping code, and a labelled,
  keyboard-focusable horizontal table region support different reading
  conditions. Print styles expand details. There is no animation.
- The demo and fixture remain the editable inputs. Regenerate the result from a
  fresh workspace and keep the matching receipt with its HTML hash; approval
  timestamps make export hashes run-specific.

## Observed checks and limits

The Windows baseline run produced 37 passing tests, one symlink test skipped
because the host could not create symlinks, passing Ruff checks, and a
12-command CLI demo that exported seven JSONL records. The refinement run
passed both renderer tests and Ruff. A fresh 12-command demo exported seven
records; the committed HTML hash matches its private receipt. The README's
fixture link resolves to `fixtures/intake.md`.

The CI workflow is configured to run the demo after source installation and
verification. This task did not run that workflow.

After the worker checks, the generated HTML was rendered in headless Chrome
at 1440, 390 and 320 pixels. All three layouts had seven export rows and four
blocked gates, no page overflow, broken section anchors, external requests or
script errors, and a keyboard-focusable table region. The README image is an
actual capture of the exported-record section. The desktop image was inspected.
