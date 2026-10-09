"""Build copied upstream packages, then install only their local wheels."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env", type=Path, default=ROOT / ".v")
parser.add_argument("--label", default="windows" if os.name == "nt" else "linux")
parser.add_argument("--resume", action="store_true")
parser.add_argument("--app-only", action="store_true")
args = parser.parse_args()
build = ROOT / ".source-build" / args.label
build.mkdir(parents=True, exist_ok=True)
receipt_path = build / "install.json"
if not args.resume and (receipt_path.exists() or args.env.exists()):
    raise SystemExit(
        "Use a fresh environment and receipt label; existing evidence is retained."
    )
receipt = (
    json.loads(receipt_path.read_text(encoding="utf-8"))
    if args.resume
    else {"platform": sys.platform, "host_python": sys.version, "steps": []}
)


def run(command, **kwargs):
    start = time.monotonic()
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **kwargs,
    )
    receipt["steps"].append(
        {
            "command": [str(c) for c in command],
            "exit_code": result.returncode,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"exit {result.returncode}: {' '.join(str(c) for c in command)}", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if not args.resume:
    run([sys.executable, "-m", "venv", str(args.env)])
python = args.env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not args.resume:
    run([str(python), "-m", "pip", "install", "-r", "dependencies-lock.txt"])
wheels = build / "wheels"
wheels.mkdir(exist_ok=True)
constraints = ROOT / "build-constraints.txt"
build_env = os.environ | {"PIP_CONSTRAINT": str(constraints), "PYTHONUTF8": "1"}
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
suffix = "w" if os.name == "nt" else "l"
stages = []
for name, prefix in [("docling-core", "c"), ("docling-slim", "d")]:
    stage = ROOT / ".b" / (prefix + suffix)
    for item in manifest["files"]:
        if item["component"] != name:
            continue
        source = ROOT / item["copied_path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
        target = stage / item["upstream_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    stages.append(stage)
stage = ROOT / ".b" / ("a" + suffix)
for path in [
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "intake_review.py",
    "source_identity/__init__.py",
    "source_identity/manifest.json",
]:
    target = stage / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / path, target)
stages.append(stage)
receipt["build_staging"] = [str(stage) for stage in stages]
for component in stages:
    if args.app_only and component != stages[-1]:
        continue
    run(
        [str(python), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), component],
        env=build_env,
    )
artifacts = sorted(wheels.glob("*.whl"))
assert len(artifacts) == 3
receipt["wheels"] = [
    {"path": str(wheel), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
    for wheel in artifacts
]
receipt.setdefault("wheel_sets", []).append(receipt["wheels"])
run(
    [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--force-reinstall",
        *map(str, artifacts),
    ]
)
run([str(python), "-m", "pip", "check"])
receipt["result"] = "copied-source wheels installed; dependency metadata consistent"
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
