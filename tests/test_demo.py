import hashlib
import json

import pytest

from tools.demo import render_result_html


def demo_result():
    record = {
        "item_ref": "#/texts/0",
        "item": {"label": "text", "text": "Reviewed <script>source</script>"},
        "page_refs": [],
    }
    export_jsonl = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    return {
        "input_markdown": "# Input\n\n<script>source</script>\n",
        "changed_markdown": "# Changed input\n",
        "intake_v1": {"version": 1, "decision": "pending", "content_sha256": "a" * 64},
        "review_v1": {"markdown": "# Input\n\n<script>source</script>\n"},
        "decision_v1": {"version": 1, "decision": "approve"},
        "repeated_intake": {"version": 1, "reused": True},
        "export_v1": {
            "items": 1,
            "filename": "approved-v1.jsonl",
            "sha256": hashlib.sha256(export_jsonl.encode("utf-8")).hexdigest(),
        },
        "export_jsonl": export_jsonl,
        "intake_v2": {"version": 2, "decision": "pending"},
        "latest_status": [{"decision": "pending", "integrity": "verified"}],
        "reviewer": "Demo reviewer",
        "gates": {
            "pending_v1_export": {
                "exit_code": 2,
                "stderr": "error: Selected latest version is pending or rejected.\n",
            },
            "changed_v1_export": {
                "exit_code": 2,
                "stderr": "error: Source bytes changed since intake.\n",
            },
            "stale_v1_approval": {
                "exit_code": 2,
                "stderr": "error: Stale version; review the latest intake version.\n",
            },
            "pending_v2_export": {
                "exit_code": 2,
                "stderr": "error: Selected latest version is pending or rejected.\n",
            },
        },
        "runtime": "Python 3.12.0\nBuild details",
        "model_weights": "not installed or executed",
        "external_ai_or_index_upload": False,
    }


def test_demo_html_shows_the_input_gates_and_observed_export_offline():
    result = demo_result()

    report = render_result_html(result)

    assert "Synthetic handbook input" in report
    assert "Blocked · exit 2" in report
    assert "Approved JSONL result" in report
    assert "0 page references" in report
    assert "Reviewed &lt;script&gt;source&lt;/script&gt;" in report
    assert "version 2" in report
    assert "integrity <strong>verified</strong>" in report
    assert "copies the checked-in fixture into a fresh workspace" in report
    assert "changes its workspace copy" in report
    assert 'role="region"' in report
    assert 'aria-label="Exported JSONL records"' in report
    assert 'tabindex="0"' in report
    assert "overflow-wrap: anywhere" in report
    assert "overflow-x: auto" in report
    assert "min-width: 46rem" in report
    assert ":focus-visible" in report
    assert "details:not([open]) > *:not(summary)" in report
    assert "display: block !important" in report
    assert "href=\"../fixtures/intake.md\"" not in report
    assert "<script>source</script>" not in report
    assert "<script" not in report.lower()
    assert "https://" not in report


def test_demo_html_refuses_export_content_that_does_not_match_its_receipt():
    result = demo_result()
    result["export_jsonl"] += "extra\n"

    with pytest.raises(ValueError, match="SHA-256"):
        render_result_html(result)
