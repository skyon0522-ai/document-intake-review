"""Exercise actual HTTP requests and the same installed Store rules as the CLI."""

import hashlib
import http.client
import json
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest
from docling_core.types.doc import DocItemLabel, DoclingDocument

import intake_sample
from intake_review import MAX_BYTES, IntakeError, Store, main
from intake_web import ReviewServer

FIXTURE = Path(__file__).parents[1] / "fixtures" / "intake.md"


class Browser:
    def __init__(self, workspace):
        self.server = ReviewServer(workspace, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, method, path, body=None, headers=None, follow=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        if result[0] == 303 and follow:
            self.location = result[1]["Location"]
            return self.request("GET", self.location)
        return result

    def post(self, path, values, **headers):
        return self.request(
            "POST",
            path,
            urlencode({"csrf": self.server.csrf, **values}),
            {
                "Origin": self.server.origin,
                "Content-Type": "application/x-www-form-urlencoded",
                **headers,
            },
        )

    def upload(self, filename="handbook.md", data=None, saved_name=""):
        boundary = "intake-test-boundary"
        parts = []
        for name, value in {"csrf": self.server.csrf, "filename": saved_name}.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n{value}\r\n".encode()
            )
        parts.extend(
            [
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                    f'filename="{filename}"\r\n'
                    "Content-Type: application/octet-stream\r\n\r\n"
                ).encode(),
                FIXTURE.read_bytes() if data is None else data,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        return self.request(
            "POST",
            "/upload",
            b"".join(parts),
            {
                "Origin": self.server.origin,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )


@pytest.fixture
def browser(tmp_path):
    result = Browser(tmp_path / "workspace")
    yield result
    result.close()


def current(browser, source="handbook.md"):
    store = Store(browser.server.workspace)
    try:
        row = store.get(source)
        return dict(row)
    finally:
        store.close()


def decision(browser, **overrides):
    row = current(browser)
    return browser.post(
        "/decide",
        {
            "source": "handbook.md",
            "version": row["version"],
            "sha256": row["content_sha"],
            "decision": "approve",
            "reviewer": "Local reviewer",
            "reason": "Checked the table.",
            **overrides,
        },
    )


def test_browser_upload_exact_review_approval_export_and_restart(browser):
    assert browser.server.server_address[0] == "127.0.0.1"
    status, headers, page = browser.request("GET", "/")
    assert status == 200
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert b'type="file"' in page and b'name="csrf"' in page
    status, _, page = browser.upload()
    assert status == 200
    assert b"Exact normalized Markdown preview" in page
    row = current(browser)
    assert row["content_sha"].encode() in page
    assert b'value="1"' in page and b"pending" in page
    status, _, page = browser.post(
        "/export", {"output": "pending.jsonl", "source": "handbook.md"}
    )
    assert status == 400 and b"pending or rejected" in page
    status, _, page = decision(browser)
    assert status == 200 and b"Decision recorded." in page and b"Checked the table." in page
    status, _, page = browser.post(
        "/export", {"output": "approved-1.jsonl", "source": "handbook.md"}
    )
    assert status == 200 and b"7 items" in page
    status, _, data = browser.request("GET", "/download?filename=approved-1.jsonl")
    assert status == 200
    assert hashlib.sha256(data).hexdigest().encode() in page
    records = [json.loads(line) for line in data.splitlines()]
    assert all(record["source_id"] == "handbook.md" for record in records)
    assert all(record["approval"]["reviewer"] == "Local reviewer" for record in records)
    status, _, page = browser.post("/export", {"output": "approved-1.jsonl"})
    assert status == 400 and b"already exists" in page
    restarted = Browser(browser.server.workspace)
    try:
        status, _, page = restarted.request("GET", "/review?source=handbook.md&version=1")
        assert status == 200 and b"approve" in page and b"Checked the table." in page
        status, _, restored_data = restarted.request(
            "GET", "/download?filename=approved-1.jsonl"
        )
        assert status == 200 and restored_data == data
        # Tokens are tied to a running server, not reused after a restart.
        status, _, _ = restarted.post(
            "/intake", {"source": "handbook.md", "csrf": browser.server.csrf}
        )
        assert status == 403
    finally:
        restarted.close()


def test_rejection_and_changed_source_cannot_export_or_reuse_stale_approval(browser):
    assert browser.upload()[0] == 200
    original = current(browser)
    assert (
        decision(browser, decision="reject", reason="Response target needs correction.")[0]
        == 200
    )
    status, _, page = browser.post(
        "/export", {"output": "rejected.jsonl", "source": "handbook.md"}
    )
    assert status == 400 and b"rejected" in page
    assert decision(browser)[0] == 400  # Immutable decision.
    path = browser.server.workspace / "sources" / "handbook.md"
    path.write_bytes(FIXTURE.read_bytes().replace(b"| Operations | 4 |", b"| Operations | 6 |"))
    assert browser.request("GET", "/review?source=handbook.md&version=1")[0] == 400
    assert browser.post("/intake", {"source": "handbook.md"})[0] == 200
    status, _, page = decision(browser, version=1, sha256=original["content_sha"])
    assert status == 400 and b"Stale version" in page
    status, _, page = decision(browser, sha256=original["content_sha"])
    assert status == 400 and b"does not match" in page
    assert current(browser)["version"] == 2
    assert decision(browser)[0] == 200
    assert browser.post("/export", {"output": "v2.jsonl", "source": "handbook.md"})[0] == 200
    path.write_text("# Changed again", encoding="utf-8")
    status, _, page = browser.post(
        "/export", {"output": "changed.jsonl", "source": "handbook.md"}
    )
    assert status == 400 and b"Source bytes changed" in page


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://other.example"},
        {"Origin": "null"},
        {"Host": "other.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cross_origin_or_rebound_host_cannot_mutate(browser, headers):
    status, _, page = browser.post("/export", {"output": "blocked.jsonl"}, **headers)
    assert status == 403 and b"Action blocked" in page
    assert not list((browser.server.workspace / "exports").iterdir())


def test_missing_origin_and_invalid_tokens_block_mutation(browser):
    assert browser.request("GET", "/", headers={"Host": "localhost"})[0] == 403
    values = urlencode({"csrf": browser.server.csrf, "output": "blocked.jsonl"})
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    assert browser.request("POST", "/export", values, headers)[0] == 403
    assert browser.post("/export", {"output": "blocked.jsonl", "csrf": "wrong"})[0] == 403
    assert browser.post("/export", {"output": "blocked.jsonl", "csrf": "☃"})[0] == 403


@pytest.mark.parametrize(
    "filename", ["../escape.md", "C:\\fake.md", "CON.md", ".hidden.md", "input.pdf"]
)
def test_unsafe_upload_filenames_and_unsupported_formats_refused(browser, filename):
    status, _, page = browser.upload(saved_name=filename)
    assert status == 400 and b"plain .md or .json filename" in page
    assert not list((browser.server.workspace / "sources").iterdir())


def test_upload_bounds_validation_and_no_overwrite(browser):
    assert browser.upload(data=b"x" * (MAX_BYTES + 1))[0] == 400
    assert browser.upload(data=b"")[0] == 400
    assert browser.upload(filename="broken.json", data=b"{}")[0] == 400
    assert browser.upload(data=b"\xff")[0] == 400
    assert not list((browser.server.workspace / "sources").iterdir())
    assert browser.upload()[0] == 200
    original = (browser.server.workspace / "sources" / "handbook.md").read_bytes()
    status, _, page = browser.upload(data=b"# Replacement")
    assert status == 400 and b"Source already exists" in page
    assert (browser.server.workspace / "sources" / "handbook.md").read_bytes() == original
    assert browser.post("/export", {"output": "../escape.jsonl"})[0] == 400
    assert browser.request("GET", "/download?filename=../intake.sqlite3")[0] == 400


def test_docling_json_and_untrusted_document_strings_render_as_text(browser):
    document = DoclingDocument(name="Untrusted example")
    document.add_text(label=DocItemLabel.TEXT, text='<script>alert("unsafe")</script>')
    data = document.model_dump_json().encode()
    status, _, page = browser.upload(filename="document.json", data=data)
    assert status == 200
    assert b"&lt;script&gt;" in page and b"<script>" not in page
    assert b"docling_core.types.doc.DoclingDocument.model_validate_json" in page
    status, _, page = browser.post(
        "/decide",
        {
            "source": "document.json",
            "version": 1,
            "sha256": current(browser, "document.json")["content_sha"],
            "decision": "reject",
            "reviewer": "<img src=x>",
            "reason": "<svg onload=x>",
        },
    )
    assert status == 200
    assert b"&lt;img src=x&gt;" in page and b"<img src=x>" not in page
    assert b"&lt;svg onload=x&gt;" in page and b"<svg onload=x>" not in page


def test_packaged_demo_seeds_pending_fixture_without_overwriting(tmp_path):
    workspace = tmp_path / "demo"
    assert main(["demo", "--workspace", str(workspace)]) == 0
    assert (workspace / "sources" / "handbook.md").read_text() == FIXTURE.read_text()
    store = Store(workspace)
    try:
        assert store.status()[0]["decision"] == "pending"
    finally:
        store.close()
    with pytest.raises(IntakeError, match="new workspace"):
        intake_sample.seed(workspace)


def test_invalid_port_refused_before_workspace_creation(tmp_path):
    workspace = tmp_path / "unused"
    with pytest.raises(IntakeError, match="Port"):
        ReviewServer(workspace, 65536)
    assert not workspace.exists()


def test_success_redirects_are_read_only_and_refresh_does_not_repeat_writes(browser):
    assert browser.upload()[0] == 200
    assert browser.location.startswith("/review?")
    assert browser.request("GET", browser.location)[0] == 200
    assert current(browser)["version"] == 1
    assert decision(browser)[0] == 200
    assert browser.request("GET", browser.location)[0] == 200
    before = (browser.server.workspace / "intake.sqlite3").read_bytes()
    assert (
        browser.post("/export", {"output": "refresh.jsonl", "source": "handbook.md"})[0] == 200
    )
    assert browser.location == "/export-result?filename=refresh.jsonl"
    path = browser.server.workspace / "exports" / "refresh.jsonl"
    exported = path.read_bytes()
    assert browser.request("GET", browser.location)[0] == 200
    assert path.read_bytes() == exported
    assert (browser.server.workspace / "intake.sqlite3").read_bytes() == before
    assert len(list((browser.server.workspace / "exports").glob("*.jsonl"))) == 1
