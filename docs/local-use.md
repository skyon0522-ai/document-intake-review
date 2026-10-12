# Local operation

## Workspace and restart

`intake-review serve --workspace PATH` creates `PATH` if needed and opens it
as the local workspace. It listens only on `127.0.0.1`; no remote-bind option
is available. Open the exact URL printed by the server. The default port is
8765; `--port 8766` selects another loopback port.

Keep the terminal running. Ctrl+C stops the server. Starting it again with
the same workspace restores document versions, decisions and saved exports.
An old browser form will have an expired token after restart; reload it.
The browser requires no account and does not authenticate reviewer labels.

| Workspace path | Contents |
| --- | --- |
| `sources/` | Original local document files. |
| `intake.sqlite3` | Source snapshots, normalized documents, versions and decisions. |
| `exports/` | Approved JSONL files created with no-overwrite publication. |

Back up this entire directory while the server and CLI are stopped. This
tool does not provide encryption, retention rules or a managed backup service.

## Add, review and change a document

Use the file input for UTF-8 Markdown (`.md`) or a JSON export that validates
as a DoclingDocument (`.json`). The source must contain 1..1,048,576 bytes and
1..10,000 document items. Normalized review content is limited to 8 MiB.
The source can have at most 1,000 intake versions.

Uploads use a plain filename and create a new file exclusively. The optional
**Save as** field lets you choose another name if the original name is already
present. Absolute paths, path separators, reserved Windows names, hidden
names, and other formats are refused. Failed validation removes the new upload
if its bytes have not changed; it never removes another process's changed file.

The review page shows the source name, exact version, source SHA-256, reviewed
content SHA-256, normalized Markdown, and expandable Docling JSON/conversion
details. The content hash includes the document structure and Markdown view.
Untrusted document text is escaped, including embedded HTML. It does not execute
as browser content. Markdown local, remote and image fetching are disabled.
Conversion confidence scores are unavailable on this declarative route.

Read the preview before making a decision. Enter a reviewer label with 1..80
characters and an optional reason with at most 500 characters. Approval and
rejection are explicit buttons. Upload and intake do not approve anything.
The decision must match the latest intake version and its reviewed content
hash. A recorded decision cannot be replaced by a different decision.

To correct a document, edit its file under `sources/` in your usual editor,
then choose **Re-intake source** on the Documents page. Changed input creates
a new pending version. Repeated intake of identical content reuses its version.
Files are expected to be stable during operations; concurrent adversarial
filesystem writers are outside the supported trust boundary.

## Export and download

An approved current document can export if its stored schema/integrity checks
pass and the live source bytes still match the intake. Exporting an explicit
pending or rejected document is blocked. **Export all approved documents**
omits latest pending/rejected documents; an integrity or source mismatch in a
selected approved document blocks the whole operation.

Choose a new plain `.jsonl` filename such as `approved-1.jsonl`. Each record
retains source identity, source/content SHA-256, version, item/page references,
reviewer label, decision timestamp and conversion metadata. The saved result
shows the actual item count, path and SHA-256. Download links read saved files
only from `exports/`. An existing export cannot be overwritten.

Exported files can contain your documents' sensitive text and identifying
reviewer labels. Review them before sharing or sending them to another system.
No external upload or index integration is performed by this tool.

## Browser trust boundary

The server requires its exact loopback Host header, rejects foreign browser
origins for mutations, and checks a random token on every mutation form.
The token is replaced each time the server starts. Page responses prohibit
scripts, embedding in frames, external assets and browser caching. Uploads and
request bodies are bounded. The server processes one request at a time.

These controls reduce cross-site browser request and document-script risks.
They do not protect against other software running as your user, malicious
browser extensions, or another user with access to your workspace. This is
a local single-user tool, not a remote multi-user service or security-certified
production system. Use an owner-controlled directory with suitable OS access
permissions. Workspace/source/database symlinks are rejected by the Store.

Successful form submissions redirect to read-only review or export-result
pages. Reloading those pages does not repeat the upload, decision or export.

## CLI compatibility

Existing commands retain their JSON output and gates. Both workspace positions
are supported, for example:

```sh
intake-review --workspace ./workspace status
intake-review status --workspace ./workspace
intake-review --workspace ./workspace review handbook.md --version 1
```

`intake-review demo --workspace NEW_PATH` creates the packaged synthetic
handbook in pending status and refuses an existing workspace. The separate
`tools/demo.py` command records the CLI gate walkthrough for developers.
