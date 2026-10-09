"""Reject fallback distributions; check loaded components against copied source."""

import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
EXPECTED = {
    item["upstream_path"]: item["sha256"]
    for item in MANIFEST["files"]
    if item["upstream_path"].startswith(("docling/", "docling_core/"))
}


def loaded_modules():
    results = []
    for name, module in sorted(sys.modules.items()):
        if name.split(".", 1)[0] not in ("docling", "docling_core"):
            continue
        filename = getattr(module, "__file__", None)
        if filename is None:  # Upstream namespace packages have no file.
            continue
        path = Path(filename).resolve()
        if path.suffix != ".py":
            continue
        parts = path.parts
        package = name.split(".", 1)[0]
        relative = "/".join(parts[parts.index(package) :])
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if EXPECTED.get(relative) != digest:
            raise RuntimeError(f"Loaded component differs from copied source: {name} ({path})")
        results.append(
            {
                "module": name,
                "file": str(path),
                "upstream_path": relative,
                "normalized_lf_sha256": digest,
            }
        )
    return results


def verify_source_components():
    distributions = []
    for component in MANIFEST["components"]:
        distribution = importlib.metadata.distribution(component["distribution"])
        direct_text = distribution.read_text("direct_url.json")
        direct = json.loads(direct_text) if direct_text else {}
        origin = urlparse(direct.get("url", ""))
        if (
            distribution.version != component["version"]
            or origin.scheme != "file"
            or not origin.path.endswith(".whl")
            or not direct.get("archive_info", {}).get("hash")
        ):
            raise RuntimeError(
                f"Copied-source wheel required for {component['distribution']}; "
                "run tools/install_source.py"
            )
        distributions.append(
            {
                "distribution": component["distribution"],
                "version": distribution.version,
                "direct_url": direct,
            }
        )
    return {"distributions": distributions, "loaded_modules": loaded_modules()}
