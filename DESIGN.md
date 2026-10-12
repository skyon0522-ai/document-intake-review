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

## Local browser review, 2026-10-13

References inspected before implementation:

- Existing `docs/demo-result.html`: preserve its one-column reading order,
  exact normalized preview, separate hashes, visible gate states, native details,
  16px type, focus styles, wrapping text and print behavior.
- [Datasette](https://github.com/simonw/datasette): adopt a short purpose/demo/install
  flow and an explicit local `serve` command that prints the browser URL.
- [linear-tui](https://github.com/k1-c/linear-tui): put the useful operation first,
  then installation and first-run commands, and preserve workspace continuity.
  Its terminal layout and account connection are not part of this local tool.

The reader is the local document owner checking a document before exporting it.
The UI uses native file inputs, named labels, semantic tables, readable preview
text, explicit approval/rejection buttons and visible error/success messages.
The document list supports the add → review → decision → export path. Detailed
Docling structure is available in-place without hiding version or hash information.
The exact Markdown preview preserves whitespace and scrolls horizontally, with
a visible scroll cue, so narrow screens retain Markdown table column alignment.
The surrounding page and expandable JSON details continue to wrap normally.
Workspace details remain discoverable in a native disclosure while the opening
header focuses on the task. There is no JavaScript, remote asset, animation or
additional design system. The editable sources are `intake_web.py` and the
packaged sample in `intake_sample.py`.

Actual HTTP regression requests check the installed wheel's behavior. Desktop
and mobile browser observations and screenshots are separate evidence; checking
HTML strings alone does not establish visual acceptance.
