"""Run a CLI demonstration with only the self-authored fixture; preserve the receipt."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from html import escape
from pathlib import Path

DEMO_REVIEWER = "Demo reviewer"


def render_result_html(result: dict) -> str:
    """Render an offline, readable summary from the captured CLI results."""
    export = result["export_v1"]
    export_jsonl = result["export_jsonl"]
    if hashlib.sha256(export_jsonl.encode("utf-8")).hexdigest() != export["sha256"]:
        raise ValueError("Export preview does not match the recorded SHA-256.")
    records = [json.loads(line) for line in export_jsonl.splitlines()]
    if len(records) != export["items"]:
        raise ValueError("Export preview does not match the recorded item count.")

    item_types = Counter(record["item"].get("label", "unknown") for record in records)
    page_ref_count = sum(len(record.get("page_refs", [])) for record in records)
    page_ref_word = "reference" if page_ref_count == 1 else "references"
    type_summary = ", ".join(
        f"{count} {label}" for label, count in sorted(item_types.items())
    )
    item_rows = []
    for record in records:
        item = record["item"]
        label = item.get("label", "unknown")
        if label == "table":
            data = item.get("data", {})
            description = (
                f"{data.get('num_rows', '?')} rows × "
                f"{data.get('num_cols', '?')} columns"
            )
        else:
            description = item.get("text") or label
        pages = ", ".join(map(str, record.get("page_refs", []))) or "None"
        item_rows.append(
            "<tr>"
            f"<td><code>{escape(str(record.get('item_ref', '')))}</code></td>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(description))}</td>"
            f"<td>{escape(pages)}</td>"
            "</tr>"
        )

    def blocked_gate(key: str, title: str) -> str:
        observation = result["gates"][key]
        message = observation["stderr"].strip()
        if message.lower().startswith("error:"):
            message = message[6:].strip()
        return (
            '<article class="gate">'
            f"<h3>{escape(title)}</h3>"
            f"<p><strong>Blocked · exit {observation['exit_code']}</strong></p>"
            f"<p>{escape(message)}</p>"
            "</article>"
        )

    intake_v1 = result["intake_v1"]
    decision_v1 = result["decision_v1"]
    intake_v2 = result["intake_v2"]
    status = result["latest_status"][0]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Document Intake Review — demo result</title>
  <style>
    :root {{
      color-scheme: light;
      font: 16px/1.55 system-ui, sans-serif;
      color: #172b3a;
      background: #f4f7f8;
    }}
    body {{ margin: 0; }}
    main {{
      max-width: 920px;
      margin: auto;
      padding: 2rem clamp(1rem, 4vw, 3rem) 4rem;
    }}
    header, section {{
      background: #fff;
      border: 1px solid #d9e2e7;
      border-radius: 12px;
      padding: clamp(1rem, 3vw, 2rem);
      margin: 1rem 0;
    }}
    h1, h2, h3 {{ line-height: 1.2; }}
    h1 {{
      font-size: clamp(2rem, 5vw, 3rem);
      max-width: 18ch;
      margin: .3rem 0 1rem;
    }}
    h2 {{ margin-top: 0; }}
    .eyebrow {{
      color: #47687b;
      font-size: .8rem;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    nav ul {{ display: flex; flex-wrap: wrap; gap: .6rem 1.2rem; padding-left: 1.2rem; }}
    a {{ color: #075c83; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      overflow-wrap: anywhere;
    }}
    pre {{
      overflow-wrap: anywhere;
      white-space: pre-wrap;
      background: #f0f4f6;
      border-radius: 8px;
      padding: 1rem;
    }}
    .table-scroll {{ max-width: 100%; overflow-x: auto; }}
    .table-scroll:focus-visible {{ outline: 3px solid #075c83; outline-offset: 3px; }}
    table {{ width: 100%; min-width: 46rem; border-collapse: collapse; }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: .65rem;
      border-bottom: 1px solid #d9e2e7;
    }}
    th {{ background: #eef3f5; }}
    .gate {{
      border-left: 4px solid #a44224;
      padding: .3rem 1rem;
      margin: 1rem 0;
      background: #fff8f4;
    }}
    .result {{
      border-left: 4px solid #16734a;
      padding: .5rem 1rem;
      background: #f0faf4;
    }}
    .note {{ color: #425563; }}
    details {{ margin-top: 1rem; }}
    summary {{ cursor: pointer; font-weight: 650; }}
    @media print {{
      body {{ background: #fff; }}
      main {{ max-width: none; padding: 0; }}
      header, section {{ break-inside: avoid; border-color: #888; }}
      nav {{ display: none; }}
      details:not([open]) > *:not(summary) {{ display: block !important; }}
      details > summary {{ display: none; }}
      .table-scroll {{ overflow: visible; }}
      table {{ min-width: 0; table-layout: fixed; }}
      th, td {{ overflow-wrap: anywhere; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Offline demonstration · synthetic input</p>
    <h1>Review the exact version before export</h1>
    <p>A local Markdown intake creates a pending version. The demo shows the
      content-hash approval gate, the approved JSONL output, and what happens
      when the source changes.</p>
    <p class="note">This demo label is not an authenticated reviewer identity.
      No document is sent to an AI service or external index.</p>
  </header>
  <nav aria-label="Demo sections">
    <ul>
      <li><a href="#input">Input</a></li>
      <li><a href="#review">Review and approval</a></li>
      <li><a href="#export">Export</a></li>
      <li><a href="#changed">Changed source</a></li>
      <li><a href="#flow">Data flow</a></li>
    </ul>
  </nav>
  <section id="input">
    <h2>1. Synthetic handbook input</h2>
    <p>The demo copies the checked-in fixture into a fresh workspace. It
      contains response targets for Operations and the service desk, with no
      customer data.</p>
    <pre><code>{escape(result['input_markdown'])}</code></pre>
  </section>
  <section id="review">
    <h2>2. Review and approval</h2>
    <p>Intake created version {intake_v1['version']} with decision
      <strong>{escape(intake_v1['decision'])}</strong>. The reviewer view is bound
      to content SHA-256 <code>{escape(intake_v1['content_sha256'])}</code>.</p>
    <details>
      <summary>View the normalized content reviewed for version 1</summary>
      <pre><code>{escape(result['review_v1']['markdown'])}</code></pre>
    </details>
    {blocked_gate('pending_v1_export', 'Export before approval')}
    <div class="result">
      <h3>Digest-bound demonstration decision</h3>
      <p>Version {decision_v1['version']} is
        <strong>{escape(decision_v1['decision'])}</strong> for the reviewed
        content hash. Reviewer label: <strong>{escape(result['reviewer'])}</strong>.</p>
      <p>Re-intaking unchanged bytes reused version
        {result['repeated_intake']['version']}: <strong>
        {str(result['repeated_intake']['reused']).lower()}</strong>.</p>
    </div>
  </section>
  <section id="export">
    <h2>3. Approved JSONL result</h2>
    <p class="result"><strong>{export['items']} records</strong> in
      <code>exports/{escape(export['filename'])}</code>. File SHA-256:
      <code>{escape(export['sha256'])}</code>.</p>
    <p>Record types: {escape(type_summary)}. The conversion returned
      {page_ref_count} page {page_ref_word}; this table shows each record's
      values from the JSONL export.</p>
    <div class="table-scroll" role="region"
         aria-label="Exported JSONL records" tabindex="0">
      <table>
        <thead><tr>
          <th scope="col">Item reference</th>
          <th scope="col">Type</th>
          <th scope="col">Content</th>
          <th scope="col">Page refs</th>
        </tr></thead>
        <tbody>{''.join(item_rows)}</tbody>
      </table>
    </div>
    <details>
      <summary>Inspect the exact exported JSONL</summary>
      <pre><code>{escape(result['export_jsonl'])}</code></pre>
    </details>
  </section>
  <section id="changed">
    <h2>4. Changed source requires a new review</h2>
    <p>After the approved export, the demo changes its workspace copy of the
      synthetic input and attempts the old export again. The changed bytes block
      version 1.</p>
    {blocked_gate('changed_v1_export', 'Export after the source changed')}
    <p>Intake then creates version {intake_v2['version']} with decision
      <strong>{escape(intake_v2['decision'])}</strong>. A decision for the older
      version is rejected, and the new pending version cannot be exported.</p>
    {blocked_gate('stale_v1_approval', 'Approval against the stale version')}
    {blocked_gate('pending_v2_export', 'Export of the new pending version')}
    <p>Final status: latest decision <strong>{escape(status['decision'])}</strong>;
      integrity <strong>{escape(status['integrity'])}</strong>.</p>
    <details>
      <summary>View the changed synthetic input</summary>
      <pre><code>{escape(result['changed_markdown'])}</code></pre>
    </details>
  </section>
  <section id="flow">
    <h2>Entry point and data flow</h2>
    <ol>
      <li><code>tools/demo.py</code> copies the fixture into a new local
        workspace and drives the installed CLI.</li>
      <li><code>intake_review.py</code> dispatches each command.
        <code>Store.intake</code> converts the Markdown and saves a version;
        <code>Store.review</code> reads that exact version;
        <code>Store.decide</code> binds the decision to its content hash.</li>
      <li><code>Store.export</code> checks current source bytes, version and
        decision integrity, then writes JSONL under the workspace's
        <code>exports/</code> directory.</li>
    </ol>
    <p class="note">Runtime: Python {escape(result['runtime'].splitlines()[0])}.
      Model weights: {escape(result['model_weights'])}. External AI or index
      upload: {str(result['external_ai_or_index_upload']).lower()}.</p>
  </section>
</main>
</body>
</html>
"""


def demo(workspace: Path, receipt: Path, html_path: Path | None = None) -> dict:
    if workspace.exists() or receipt.exists() or (html_path and html_path.exists()):
        raise ValueError(
            "Demo workspace, receipt and HTML output must not exist; choose new paths."
        )
    if html_path and html_path.resolve() in {workspace.resolve(), receipt.resolve()}:
        raise ValueError("Demo workspace, receipt and HTML output must use distinct paths.")
    commands = []
    executable = Path(sys.executable).parent / (
        "intake-review.exe" if os.name == "nt" else "intake-review"
    )
    if not executable.is_file():
        raise ValueError(
            "Install the project into this Python environment before running the demo."
        )

    def run(*args, expected=0):
        command = [str(executable), "--workspace", str(workspace), *args]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=os.environ | {"PYTHONUTF8": "1"},
        )
        commands.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != expected:
            raise RuntimeError(f"Expected {expected}, got {result.returncode}: {result.stderr}")
        return json.loads(result.stdout) if expected == 0 else None

    run("init")
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "intake.md"
    source = workspace / "sources" / "handbook.md"
    input_bytes = fixture.read_bytes()
    shutil.copyfile(fixture, source)
    first = run("intake", "handbook.md")
    review = run("review", "handbook.md", "--version", "1")
    run("export", "--source", "handbook.md", "--output", "pending.jsonl", expected=2)
    pending_v1_export = commands[-1]
    decision = run(
        "decide",
        "handbook.md",
        "--version",
        "1",
        "--sha256",
        first["content_sha256"],
        "--decision",
        "approve",
        "--reviewer",
        DEMO_REVIEWER,
    )
    exported = run("export", "--source", "handbook.md", "--output", "approved-v1.jsonl")
    repeated = run("intake", "handbook.md")
    assert repeated["version"] == 1 and repeated["reused"]
    changed_bytes = input_bytes.replace(
        b"| High | Operations | 4 |", b"| High | Operations | 6 |"
    )
    if changed_bytes == input_bytes:
        raise RuntimeError("Demo fixture no longer contains the expected response target.")
    source.write_bytes(changed_bytes)
    run("export", "--source", "handbook.md", "--output", "source-changed.jsonl", expected=2)
    changed_v1_export = commands[-1]
    second = run("intake", "handbook.md")
    assert second["version"] == 2 and second["decision"] == "pending"
    run(
        "decide",
        "handbook.md",
        "--version",
        "1",
        "--sha256",
        first["content_sha256"],
        "--decision",
        "approve",
        "--reviewer",
        DEMO_REVIEWER,
        expected=2,
    )
    stale_v1_approval = commands[-1]
    run("export", "--source", "handbook.md", "--output", "version2-pending.jsonl", expected=2)
    pending_v2_export = commands[-1]
    status = run("status")

    export_path = Path(exported["output"])
    export_bytes = export_path.read_bytes()
    if hashlib.sha256(export_bytes).hexdigest() != exported["sha256"]:
        raise RuntimeError("Export bytes do not match the CLI-reported SHA-256.")
    export_jsonl = export_bytes.decode("utf-8")
    result = {
        "runtime": sys.version,
        "commands": commands,
        "input_markdown": input_bytes.decode("utf-8"),
        "changed_markdown": changed_bytes.decode("utf-8"),
        "intake_v1": first,
        "review_v1": {"markdown": review["markdown"]},
        "decision_v1": decision,
        "repeated_intake": repeated,
        "export_v1": {**exported, "filename": export_path.name},
        "export_jsonl": export_jsonl,
        "intake_v2": second,
        "latest_status": status,
        "reviewer": DEMO_REVIEWER,
        "gates": {
            "pending_v1_export": pending_v1_export,
            "changed_v1_export": changed_v1_export,
            "stale_v1_approval": stale_v1_approval,
            "pending_v2_export": pending_v2_export,
        },
        "model_weights": "not installed or executed",
        "external_ai_or_index_upload": False,
    }
    if html_path:
        html_bytes = render_result_html(result).encode("utf-8")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        with html_path.open("xb") as output:
            output.write(html_bytes)
            output.flush()
            os.fsync(output.fileno())
        result["html_artifact"] = {
            "path": str(html_path),
            "sha256": hashlib.sha256(html_bytes).hexdigest(),
            "bytes": len(html_bytes),
        }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--html", type=Path, help="Write a standalone HTML summary of the observed run."
    )
    arguments = parser.parse_args()
    outcome = demo(arguments.workspace, arguments.receipt, arguments.html)
    print(
        json.dumps(
            {
                "receipt": str(arguments.receipt),
                "html": str(arguments.html) if arguments.html else None,
                "html_sha256": outcome.get("html_artifact", {}).get("sha256"),
                "commands": len(outcome["commands"]),
                "exported_items": outcome["export_v1"]["items"],
                "export_sha256": outcome["export_v1"]["sha256"],
            },
            indent=2,
        )
    )
