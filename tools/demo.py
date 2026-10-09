"""Run a CLI demonstration with only the self-authored fixture; preserve the receipt."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def demo(workspace: Path, receipt: Path) -> dict:
    if workspace.exists() or receipt.exists():
        raise ValueError("Demo workspace and receipt must not exist; choose new paths.")
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
    shutil.copyfile(fixture, source)
    first = run("intake", "handbook.md")
    run("review", "handbook.md", "--version", "1")
    run("export", "--source", "handbook.md", "--output", "pending.jsonl", expected=2)
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
        "Demo reviewer",
    )
    exported = run("export", "--source", "handbook.md", "--output", "approved-v1.jsonl")
    repeated = run("intake", "handbook.md")
    assert repeated["version"] == 1 and repeated["reused"]
    source.write_bytes(
        source.read_bytes().replace(b"| High | Operations | 4 |", b"| High | Operations | 6 |")
    )
    run("export", "--source", "handbook.md", "--output", "source-changed.jsonl", expected=2)
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
        "Demo reviewer",
        expected=2,
    )
    run("export", "--source", "handbook.md", "--output", "version2-pending.jsonl", expected=2)
    status = run("status")
    result = {
        "runtime": sys.version,
        "commands": commands,
        "export_v1": exported,
        "latest_status": status,
        "model_weights": "not installed or executed",
        "external_ai_or_index_upload": False,
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    outcome = demo(arguments.workspace, arguments.receipt)
    print(
        json.dumps(
            {
                "receipt": str(arguments.receipt),
                "commands": len(outcome["commands"]),
                "exported_items": outcome["export_v1"]["items"],
            },
            indent=2,
        )
    )
