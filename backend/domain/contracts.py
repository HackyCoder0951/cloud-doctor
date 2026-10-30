"""Contract validation helper: jsonschema 2020-12 + `referencing` registry over contracts/schemas."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[2]
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class ContractViolation(ValueError):
    def __init__(self, schema: str, errors: list[str]) -> None:
        super().__init__(f"{schema}: " + "; ".join(errors[:5]))
        self.schema = schema
        self.errors = errors


def schemas_dir() -> Path:
    return Path(os.environ.get("CD_CONTRACTS_DIR", REPO_ROOT / "contracts")) / "schemas"


@lru_cache(maxsize=1)
def _registry() -> tuple[Registry, dict[str, dict]]:
    docs: dict[str, dict] = {}
    resources = []
    for path in sorted(schemas_dir().glob("*.json")):
        doc = json.loads(path.read_text())
        docs[path.stem] = doc
        resources.append((doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012)))
    return Registry().with_resources(resources), docs


def _format_checker() -> FormatChecker:
    fc = FormatChecker()

    @fc.checks("date-time")
    def _dt(value: Any) -> bool:  # jsonschema skips date-time unless an extra package is installed
        return not isinstance(value, str) or bool(_RFC3339.match(value))

    return fc


_FC = _format_checker()


def validate_against_contract(obj: Any, schema: str, fragment: str | None = None) -> None:
    """Validate ``obj`` against contracts/schemas/<schema>.json (optionally a ``#/$defs/x`` fragment).

    Raises ContractViolation listing the first errors. Used in tests for every emitted object and at
    API boundaries for objects that cross a process boundary.
    """
    registry, docs = _registry()
    if schema not in docs:
        raise KeyError(f"unknown contract schema {schema!r}")
    target: dict = docs[schema]
    if fragment:
        target = {"$ref": f"{docs[schema]['$id']}{fragment}"}
    validator = Draft202012Validator(target, registry=registry, format_checker=_FC)
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        raise ContractViolation(schema, [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:160]}" for e in errors])
