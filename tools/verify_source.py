"""Record one comparable source baseline sequence and installed-app checks."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--label", required=True)
parser.add_argument("--reference-dir", type=Path, required=True)
parser.add_argument("--installed-only", action="store_true")
args = parser.parse_args()
evidence = ROOT / ".verification" / args.label
evidence.mkdir(parents=True, exist_ok=False)
receipt = {"python": sys.executable, "runtime": sys.version, "commands": []}
receipt_path = evidence / "verification.json"


def run(command, expected=0):
    start = time.monotonic()
    result = subprocess.run(
        command,
        cwd=evidence,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=os.environ | {"PYTHONPATH": "", "PYTHONUTF8": "1"},
    )
    receipt["commands"].append(
        {
            "command": [str(item) for item in command],
            "exit_code": result.returncode,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"exit {result.returncode}: {' '.join(str(item) for item in command)}", flush=True)
    if result.returncode != expected:
        raise SystemExit(result.returncode or 1)


compare = ROOT / "tools/compare_component.py"
originals = {}
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
for component in [] if args.installed_only else manifest["components"]:
    saved = "upstream-docling" if component["package"] == "docling" else "upstream-core"
    prefix = "w" if os.name == "nt" else "l"
    package_code = "d" if component["package"] == "docling" else "c"
    run_code = hashlib.sha256(args.label.encode()).hexdigest()[:4]
    original = ROOT / ".o" / (prefix + run_code + package_code)
    paths = [
        item["upstream_path"]
        for item in manifest["files"]
        if item["component"] == component["distribution"]
    ]
    command = [
        "git",
        "-c",
        "core.autocrlf=false",
        "-C",
        str(args.reference_dir / saved),
        "archive",
        "--format=tar",
        component["commit"],
        "--",
        component["package"],
        "pyproject.toml",
        "LICENSE",
        "README.md",
    ]
    if saved == "upstream-docling":
        command.append("packages/docling-slim/README.md")
    extraction = {"command": command, "path": str(original), "result": "started"}
    receipt.setdefault("materialized_original", []).append(extraction)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    try:
        archive = subprocess.check_output(command)
        extraction["archive_sha256"] = hashlib.sha256(archive).hexdigest()
        with tarfile.open(fileobj=BytesIO(archive)) as source:
            source.extractall(original, filter="data")
        for item in manifest["files"]:
            if item["component"] == component["distribution"]:
                digest = hashlib.sha256(
                    (original / item["upstream_path"]).read_bytes()
                ).hexdigest()
                assert digest == item["sha256"], item["upstream_path"]
        extraction.update(
            result="all original blobs verified", source_files_verified=len(paths)
        )
    except Exception as exc:
        extraction.update(result="failed", error=f"{type(exc).__name__}: {exc}")
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        raise
    originals[saved] = original
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
for stage in ["composed"] if args.installed_only else ["original", "duplicate", "composed"]:
    command = [
        sys.executable,
        "-B",
        str(compare),
        "--stage",
        stage,
        "--receipt",
        str(evidence / f"{stage}.json"),
    ]
    if stage == "original":
        command += [
            "--docling-source",
            str(originals["upstream-docling"]),
            "--core-source",
            str(originals["upstream-core"]),
        ]
    elif stage == "duplicate":
        command += [
            "--docling-source",
            str(ROOT / "components/docling-slim"),
            "--core-source",
            str(ROOT / "components/docling-core"),
        ]
    else:
        command += ["--workspace", str(evidence / "composed-workspace")]
    run(command)
if not args.installed_only:
    stages = [
        json.loads((evidence / f"{stage}.json").read_text())
        for stage in ["original", "duplicate", "composed"]
    ]
    for field in [
        "fixture_sha256",
        "document",
        "markdown",
        "item_refs",
        "content_sha256",
        "table_shape",
    ]:
        assert stages[0][field] == stages[1][field] == stages[2][field], field
    receipt["comparison"] = {
        "result": "exact equality",
        "content_sha256": stages[0]["content_sha256"],
        "items": len(stages[0]["item_refs"]),
        "schema_and_table": "equal",
    }
else:
    receipt["comparison"] = {
        "result": "installed composition only; original/duplicate comparison unverified",
        "reason": "Original/duplicate source comparison was not requested for this run.",
    }
run([sys.executable, "-m", "pytest", "-q", "--import-mode=importlib", str(ROOT / "tests")])
run(
    [
        sys.executable,
        str(ROOT / "tools/demo.py"),
        "--workspace",
        str(evidence / "cli-demo"),
        "--receipt",
        str(evidence / "cli-demo.json"),
    ]
)
run(
    [
        sys.executable,
        "-m",
        "ruff",
        "check",
        str(ROOT / "intake_review.py"),
        str(ROOT / "intake_web.py"),
        str(ROOT / "intake_sample.py"),
        str(ROOT / "source_identity"),
        str(ROOT / "tests"),
        str(ROOT / "tools"),
    ]
)
receipt["result"] = "selected source checks, inherited contract tests and installed CLI passed"
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt["comparison"], indent=2))
