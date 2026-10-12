"""A loopback browser interface to the existing Store review gate."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from intake_review import MAX_BYTES, IntakeError, Store, sha

MAX_REQUEST_BYTES = MAX_BYTES + 64 * 1024
STYLE = """
:root{color-scheme:light;font:16px/1.55 system-ui,sans-serif;color:#172b3a;
background:#f4f7f8}body{margin:0}main{max-width:1020px;margin:auto;
padding:1.2rem clamp(1rem,4vw,3rem) 3rem}header,section{background:#fff;
border:1px solid #d9e2e7;border-radius:12px;padding:clamp(1rem,3vw,2rem);
margin:1rem 0}h1,h2{line-height:1.2}h1{font-size:clamp(1.8rem,5vw,2.5rem)}
h2{margin-top:0}a{color:#075c83}nav{display:flex;gap:1rem;flex-wrap:wrap}
label{display:block;font-weight:650;margin:.8rem 0 .25rem}
input,textarea,select,button{font:inherit;box-sizing:border-box;max-width:100%}
input:not([type=hidden]),textarea,select{padding:.5rem;border:1px solid #778d9b;
border-radius:4px;width:100%}input[type=file]{border:0;padding:.5rem 0}
textarea{min-height:5rem}button{padding:.6rem 1rem;margin:.7rem .5rem 0 0;
background:#075c83;color:white;border:2px solid #075c83;border-radius:4px;
cursor:pointer}.reject{background:white;color:#933b24;border-color:#933b24}
:focus-visible{outline:3px solid #ad6412;outline-offset:3px}
pre,code{overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f0f4f6;
padding:1rem;border-radius:6px}code{font-family:ui-monospace,monospace}
.markdown-preview{white-space:pre;overflow-x:auto;overflow-wrap:normal}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:40rem}
th,td{text-align:left;vertical-align:top;padding:.6rem;border-bottom:1px solid #d9e2e7}
th{background:#eef3f5}.note{color:#425563}.message{border-left:4px solid #16734a;
background:#f0faf4;padding:1rem}.error{border-color:#a44224;background:#fff8f4}
details{margin:1rem 0}summary{font-weight:650;cursor:pointer}.compact{display:inline}
.compact button{font-size:.9rem;margin:0}dt{font-weight:650}dd{margin:0 0 .6rem}
@media print{body{background:white}main{padding:0;max-width:none}nav,form{display:none}
section,header{border-color:#888}details:not([open])>*:not(summary){display:block!important}
details>summary{display:none}.scroll{overflow:visible}table{min-width:0}}
"""


def fields(data: str) -> dict[str, str]:
    values = parse_qs(data, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
    if any(len(value) != 1 for value in values.values()):
        raise IntakeError("Each form field must occur once.")
    return {key: value[0] for key, value in values.items()}


def source_filename(filename: str) -> str:
    if (
        not filename
        or len(filename) > 120
        or any(char in filename for char in '/\\:<>"|?*')
        or any(ord(char) < 32 for char in filename)
        or filename.startswith(".")
        or filename.endswith((" ", "."))
        or not filename.endswith((".md", ".json"))
        or filename.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise IntakeError("Use a plain .md or .json filename, up to 120 characters.")
    return filename


def export_filename(filename: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,121}\.jsonl", filename):
        raise IntakeError("Use a plain export filename such as approved-1.jsonl.")
    return filename


def upload(store: Store, filename: str, data: bytes) -> dict:
    """Save a new source exclusively; the Store performs conversion and all gates."""
    filename = source_filename(filename)
    if not data or len(data) > MAX_BYTES:
        raise IntakeError(f"Source size must be 1..{MAX_BYTES} bytes.")
    target = store.sources / filename
    try:
        with target.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise IntakeError(
            "Source already exists. Choose a new filename or re-intake it."
        ) from exc
    try:
        return store.intake(filename)
    except Exception:
        # Remove only our failed upload, never a source changed by another local process.
        if (
            not target.is_symlink()
            and target.is_file()
            and sha(target.read_bytes()) == sha(data)
        ):
            target.unlink()
        raise


class ReviewServer(HTTPServer):
    # minimalism: one request at a time; each request opens its own SQLite connection.
    def __init__(self, workspace: Path, port: int = 8765):
        if not 0 <= port <= 65535:
            raise IntakeError("Port must be in 0..65535.")
        with_store = Store(workspace)
        self.workspace = with_store.workspace
        with_store.close()
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ReviewHandler)
        self.authority = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.authority}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, _format, *_args):
        # Do not log document names, form values, or request query strings.
        pass

    def reply(
        self,
        body: str | bytes,
        status=200,
        content_type="text/html; charset=utf-8",
        location: str | None = None,
    ):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def redirect_review(self, result: dict, notice: str):
        query = urlencode(
            {"source": result["source_id"], "version": result["version"], "notice": notice}
        )
        self.reply(b"", 303, location="/review?" + query)

    def page(self, title: str, body: str, status=200):
        self.reply(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)} · Document Intake Review</title><style>{STYLE}</style>"
            '</head><body><main><header><nav aria-label="Main navigation">'
            '<a href="/">Documents</a></nav><h1>Document Intake Review</h1>'
            "<p>Check the exact converted version, record a decision, then export approved "
            'current content.</p><details><summary>Workspace: '
            f"{escape(self.server.workspace.name)}</summary><p>Local directory: "
            f"<code>{escape(str(self.server.workspace))}</code>.</p>"
            '<p class="note">Reviewer names are local labels, not authenticated identities.'
            f"</p></details></header>{body}</main></body></html>",
            status,
        )

    def hidden(self, **values: object) -> str:
        return "".join(
            f'<input type="hidden" name="{escape(key)}" value="{escape(str(value))}">'
            for key, value in {"csrf": self.server.csrf, **values}.items()
        )

    def error(self, message: str, status=400):
        self.page(
            "Action blocked",
            '<section class="message error" role="alert"><h2>Action blocked</h2>'
            f'<p>{escape(message)}</p><p><a href="/">Return to documents</a></p></section>',
            status,
        )

    def trusted_request(self, mutation=False) -> bool:
        hosts = self.headers.get_all("Host", [])
        if hosts != [self.server.authority]:
            self.error("Use the exact loopback URL printed by the server.", 403)
            return False
        if mutation:
            origin = self.headers.get("Origin")
            referer = urlsplit(self.headers.get("Referer", ""))
            referred_origin = f"{referer.scheme}://{referer.netloc}"
            if (
                origin != self.server.origin
                if origin is not None
                else referred_origin != self.server.origin
            ) or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
                self.error("Browser mutation must come from this server's origin.", 403)
                return False
        return True

    def do_GET(self):
        if not self.trusted_request():
            return
        store = None
        try:
            parsed = urlsplit(self.path)
            query = fields(parsed.query) if parsed.query else {}
            store = Store(self.server.workspace)
            if parsed.path == "/":
                self.documents(store)
            elif parsed.path == "/review":
                notices = {
                    "added": "Document added. Review it below.",
                    "intaken": "Intake completed. Check this exact version.",
                    "decided": "Decision recorded.",
                }
                self.review(
                    store,
                    query["source"],
                    int(query["version"]),
                    notices.get(query.get("notice", ""), ""),
                )
            elif parsed.path == "/export-result":
                self.saved_export(store, query["filename"])
            elif parsed.path == "/download":
                filename = export_filename(query["filename"])
                path = store.exports / filename
                if path.is_symlink() or not path.is_file():
                    raise IntakeError("Export file not found or is a symlink.")
                self.reply(path.read_bytes(), content_type="application/x-ndjson")
            else:
                self.error("Page not found.", 404)
        except (IntakeError, OSError, sqlite3.Error, ValueError, KeyError) as exc:
            self.error(str(exc))
        finally:
            if store:
                store.close()

    def saved_export(self, store: Store, name: str):
        filename = export_filename(name)
        path = store.exports / filename
        if path.is_symlink() or not path.is_file():
            raise IntakeError("Export file not found or is a symlink.")
        data = path.read_bytes()
        items = len(data.splitlines())
        link = "/download?" + urlencode({"filename": filename})
        self.page(
            "Export saved",
            '<section class="message" role="status"><h2>Export saved</h2>'
            f'<p>{items} items · <a href="{escape(link)}" download>'
            f"Download {escape(filename)}</a></p><p>SHA-256: "
            f"<code>{sha(data)}</code></p><p>Saved at "
            f"<code>{escape(str(path))}</code>.</p></section>",
        )

    def documents(self, store: Store, message: str = ""):
        notice = (
            f'<section class="message" role="status">{escape(message)}</section>'
            if message
            else ""
        )
        rows = []
        for item in store.status():
            source = item["source_id"]
            link = "/review?" + urlencode({"source": source, "version": item["version"]})
            rows.append(
                f'<tr><th scope="row"><a href="{escape(link)}">{escape(source)}</a></th>'
                f"<td>{item['version']}</td><td>{escape(item['decision'])}</td>"
                f'<td>{escape(item["integrity"])}</td><td><form class="compact" '
                f'action="/intake" method="post">{self.hidden(source=source)}'
                "<button>Re-intake source</button></form></td></tr>"
            )
        listing = (
            '<div class="scroll" role="region" aria-label="Document status" tabindex="0">'
            '<table><thead><tr><th scope="col">Document</th><th scope="col">Version</th>'
            '<th scope="col">Decision</th><th scope="col">Integrity</th>'
            '<th scope="col">Changed local file</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></div>"
            if rows
            else "<p>No documents yet. Upload a Markdown or Docling JSON file below.</p>"
        )
        exports = "".join(
            f'<li><a href="/download?{escape(urlencode({"filename": path.name}))}" '
            f"download>{escape(path.name)}</a></li>"
            for path in sorted(store.exports.glob("*.jsonl"))
            if path.is_file() and not path.is_symlink()
        )
        self.page(
            "Documents",
            notice + f'<section><h2>Documents</h2>{listing}<p class="note">Re-intake '
            "after editing a file in <code>sources/</code>. Changed content needs a new "
            "decision; unchanged content reuses its version.</p></section>"
            '<section><h2>Add a document</h2><form action="/upload" method="post" '
            f'enctype="multipart/form-data">{self.hidden()}'
            '<label for="document">UTF-8 Markdown or DoclingDocument JSON</label>'
            '<input id="document" type="file" name="document" accept=".md,.json" required>'
            '<label for="filename">Save as (optional)</label>'
            '<input id="filename" name="filename" maxlength="120" '
            'placeholder="handbook.md" aria-describedby="upload-help">'
            '<p id="upload-help" class="note">Up to 1 MiB. A plain filename is required. '
            "Existing source files are never overwritten. "
            "No file is sent to a cloud service.</p>"
            "<button>Upload and intake</button></form></section>"
            "<section><h2>Export approved current documents</h2>"
            f'<form action="/export" method="post">{self.hidden()}'
            '<label for="output">New JSONL filename</label><input id="output" '
            'name="output" placeholder="approved-1.jsonl" required maxlength="128">'
            '<p class="note">Only approved latest versions with unchanged source bytes '
            "can export. A new file is created under <code>exports/</code>.</p>"
            "<button>Export all approved documents</button></form>"
            + (f"<h3>Saved exports</h3><ul>{exports}</ul>" if exports else "")
            + "</section>",
        )

    def review(self, store: Store, source: str, version: int, message: str = ""):
        item = store.review(source, version)
        record = store.db.execute(
            "SELECT * FROM decisions WHERE source_id=? AND version=?", (source, version)
        ).fetchone()
        detail = ""
        if record:
            detail = (
                f"<p>Reviewer: {escape(record['reviewer'])} · "
                f"{escape(record['decided_at'])}</p><p>Reason: "
                f"{escape(record['reason']) or 'No reason recorded.'}</p>"
            )
        decision_form = (
            '<form action="/decide" method="post">'
            + self.hidden(source=source, version=version, sha256=item["content_sha256"])
            + '<label for="reviewer">Reviewer label</label><input id="reviewer" '
            'name="reviewer" required maxlength="80" autocomplete="name">'
            '<label for="reason">Reason (optional, up to 500 characters)</label>'
            '<textarea id="reason" name="reason" maxlength="500"></textarea>'
            '<p class="note">This records an immutable decision for the version and content '
            "SHA-256 shown above. Check the full preview before choosing.</p>"
            '<button name="decision" value="approve">Approve this version</button>'
            '<button class="reject" name="decision" value="reject">Reject this version</button>'
            "</form>"
            if item["latest"] and item["decision"] == "pending"
            else "<p>This version has a decision or is older than the latest intake. "
            "It cannot receive a different decision.</p>"
        )
        export_form = (
            f'<form action="/export" method="post">{self.hidden(source=source)}'
            '<label for="output">New JSONL filename</label><input id="output" '
            'name="output" required maxlength="128" placeholder="approved-1.jsonl">'
            "<button>Export this document</button></form>"
            if item["latest"] and item["decision"] == "approve"
            else ""
        )
        document_details = json.dumps(
            {"document": item["document"], "conversion": item["conversion"]},
            ensure_ascii=False,
            indent=2,
        )
        self.page(
            "Review " + source,
            (
                f'<section class="message" role="status">{escape(message)}</section>'
                if message
                else ""
            )
            + f"<section><h2>{escape(source)} · version {version}</h2><p>Decision: "
            f"<strong>{escape(item['decision'])}</strong> · "
            f"{'Latest version' if item['latest'] else 'Historical version'}</p>"
            "<dl><dt>Source SHA-256</dt><dd><code>"
            + item["source_sha256"]
            + "</code></dd><dt>Reviewed content SHA-256</dt><dd><code>"
            + item["content_sha256"]
            + f"</code></dd></dl>{detail}"
            '<h3>Exact normalized Markdown preview</h3>'
            '<p id="preview-help" class="note">Scroll horizontally to read wide tables.</p>'
            '<pre class="markdown-preview" tabindex="0" aria-describedby="preview-help" '
            f'aria-label="Exact normalized Markdown">{escape(item["markdown"])}</pre>'
            "<details><summary>Exact Docling document and conversion details</summary>"
            f"<pre>{escape(document_details)}</pre>"
            f"</details></section><section><h2>Record a decision</h2>{decision_form}</section>"
            + (
                f"<section><h2>Export this approved version</h2>{export_form}</section>"
                if export_form
                else ""
            ),
        )

    def form(self) -> tuple[dict[str, str], tuple[str, bytes] | None]:
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
            raise IntakeError(
                "A single Content-Length is required; chunked requests are unsupported."
            )
        length = int(lengths[0])
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise IntakeError("Request exceeds the upload limit or is empty.")
        body = self.rfile.read(length)
        if len(body) != length:
            raise IntakeError("Incomplete request body.")
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            return fields(body.decode("utf-8")), None
        if not content_type.startswith("multipart/form-data"):
            raise IntakeError("Use the document upload form.")
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        if not message.is_multipart() or message.defects:
            raise IntakeError("Invalid multipart upload.")
        values, uploaded = {}, None
        parts = list(message.iter_parts())
        if len(parts) > 4:
            raise IntakeError("Too many upload fields.")
        for part in parts:
            name = part.get_param("name", header="content-disposition")
            data = part.get_payload(decode=True)
            if part.get_content_disposition() != "form-data" or not name or data is None:
                raise IntakeError("Invalid upload field.")
            if part.get_filename() is not None:
                if name != "document" or uploaded is not None:
                    raise IntakeError("Upload exactly one document.")
                uploaded = (part.get_filename(), data)
            else:
                if name in values or len(data) > 1000:
                    raise IntakeError("Invalid or duplicate upload field.")
                values[name] = data.decode("utf-8")
        return values, uploaded

    def do_POST(self):
        if not self.trusted_request(mutation=True):
            return
        store = None
        try:
            values, uploaded = self.form()
            if not hmac.compare_digest(
                values.get("csrf", "").encode("utf-8"), self.server.csrf.encode("utf-8")
            ):
                self.error("Form expired or has an invalid CSRF token. Reload the page.", 403)
                return
            store = Store(self.server.workspace)
            if self.path == "/upload":
                if uploaded is None:
                    raise IntakeError("Choose a document file.")
                result = upload(store, values.get("filename", "") or uploaded[0], uploaded[1])
                self.redirect_review(result, "added")
            elif self.path == "/intake":
                result = store.intake(values["source"])
                self.redirect_review(result, "intaken")
            elif self.path == "/decide":
                result = store.decide(
                    values["source"],
                    int(values["version"]),
                    values["sha256"],
                    values["decision"],
                    values["reviewer"],
                    values.get("reason", ""),
                )
                self.redirect_review(result, "decided")
            elif self.path == "/export":
                filename = export_filename(values["output"])
                store.export(filename, values.get("source") or None)
                self.reply(
                    b"",
                    303,
                    location="/export-result?" + urlencode({"filename": filename}),
                )
            else:
                self.error("Action not found.", 404)
        except (IntakeError, OSError, sqlite3.Error, ValueError, KeyError) as exc:
            self.error(str(exc))
        finally:
            if store:
                store.close()


def serve(workspace: Path, port: int = 8765) -> None:
    with ReviewServer(workspace, port) as server:
        print(f"Document Intake Review: {server.origin}/", flush=True)
        print("Loopback only. Keep this terminal open; press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
