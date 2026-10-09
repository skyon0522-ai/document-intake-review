"""Source-composition packaging must refuse registry fallback and changed modules."""

import importlib.metadata
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from source_identity import loaded_modules, verify_source_components


def test_registry_distribution_without_local_wheel_origin_refused(monkeypatch):
    original = importlib.metadata.distribution

    def registry_distribution(name):
        distribution = original(name)
        if name == "docling-core":
            return SimpleNamespace(version=distribution.version, read_text=lambda _name: None)
        return distribution

    monkeypatch.setattr(importlib.metadata, "distribution", registry_distribution)
    with pytest.raises(RuntimeError, match="Copied-source wheel required for docling-core"):
        verify_source_components()


def test_changed_loaded_component_refused_without_modifying_installed_source(
    tmp_path, monkeypatch
):
    module = sys.modules["docling.backend.md_backend"]
    original = Path(module.__file__)
    changed = tmp_path / "docling/backend/md_backend.py"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(original.read_bytes() + b"\n# changed component\n")
    monkeypatch.setitem(
        sys.modules, "docling.backend.md_backend", SimpleNamespace(__file__=changed)
    )
    with pytest.raises(RuntimeError, match="Loaded component differs from copied source"):
        loaded_modules()
