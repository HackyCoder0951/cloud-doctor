"""Optional YAML support. PyYAML is imported ONLY here and only if installed."""
from __future__ import annotations

try:  # optional dependency
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised when PyYAML is absent
    _yaml = None


def available() -> bool:
    return _yaml is not None


def load_yaml(text: str):
    if _yaml is None:
        raise RuntimeError("PyYAML is not installed; use a .json catalog or install the 'yaml' extra")
    return _yaml.safe_load(text)
