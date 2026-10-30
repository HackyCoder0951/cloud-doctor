#!/usr/bin/env python3
"""Contract validation: the shared check every stream runs before pushing.

Checks
  1. every JSON Schema in contracts/schemas is itself valid (2020-12) and cross-references resolve;
  2. every contracts/examples/*.example.json validates against its schema;
  3. negative fixtures are REJECTED;
  4. infra/catalog/services.yaml validates, container names are unique, dependencies exist;
  5. contracts/openapi.yaml and contracts/actuator.openapi.yaml parse and every $ref target file exists.

Requires: pyyaml, jsonschema (>= 4.18, uses 'referencing').  Exit code 0 only if everything passes.
"""
import json
import pathlib
import sys

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
EXAMPLES = ROOT / "contracts" / "examples"

failures = []


def fail(msg):
    failures.append(msg)
    print("FAIL:", msg)


def ok(msg):
    print("ok  :", msg)


def load_registry():
    resources = []
    schemas = {}
    for path in sorted(SCHEMAS.glob("*.json")):
        doc = json.loads(path.read_text())
        schemas[path.stem] = doc
        resources.append((doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012)))
    return Registry().with_resources(resources), schemas


def validator_for(name, registry, schemas):
    return Draft202012Validator(schemas[name], registry=registry)


def main():
    registry, schemas = load_registry()

    for name, doc in schemas.items():
        try:
            Draft202012Validator.check_schema(doc)
        except Exception as err:  # noqa: BLE001
            fail(f"schema {name} invalid: {err}")
    ok(f"{len(schemas)} schemas are valid JSON Schema 2020-12")

    mapping = {
        "evidence": ("evidence", None),
        "diagnosis": ("diagnosis", None),
        "plan": ("plan", None),
        "decision": ("decision", None),
        "signed_plan": ("signed_plan", None),
        "execution": ("execution", None),
        "verification": ("verification", None),
        "incident": ("incident", None),
        "report": ("report", None),
        "audit_event": ("audit_event", None),
    }
    for stem, (schema_name, _) in mapping.items():
        data = json.loads((EXAMPLES / f"{stem}.example.json").read_text())
        errors = list(validator_for(schema_name, registry, schemas).iter_errors(data))
        if errors:
            fail(f"{stem}.example.json: {errors[0].message}")
        else:
            ok(f"{stem}.example.json validates")

    # timeline_event lives in incident.json#/$defs/timeline_event
    tl_schema = {"$ref": "https://cloud-doctor.local/schemas/incident.json#/$defs/timeline_event"}
    tl = json.loads((EXAMPLES / "timeline_event.example.json").read_text())
    errs = list(Draft202012Validator(tl_schema, registry=registry).iter_errors(tl))
    (fail if errs else ok)(f"timeline_event.example.json {'invalid: ' + errs[0].message if errs else 'validates'}")

    for item in json.loads((EXAMPLES / "evidence_list.example.json").read_text()):
        errs = list(validator_for("evidence", registry, schemas).iter_errors(item))
        if errs:
            fail(f"evidence_list item {item.get('evidence_id')}: {errs[0].message}")
    ok("evidence_list.example.json items validate")

    neg = json.loads((EXAMPLES / "negative_cases.json").read_text())
    for key, schema_name in [("plan_unknown_action", "plan"), ("plan_missing_service", "plan"),
                             ("plan_extra_param", "plan"), ("evidence_bad_id", "evidence")]:
        errs = list(validator_for(schema_name, registry, schemas).iter_errors(neg[key]))
        (ok if errs else fail)(f"negative case {key} is rejected" if errs else f"negative case {key} was ACCEPTED")

    catalog = yaml.safe_load((ROOT / "infra" / "catalog" / "services.yaml").read_text())
    errs = list(validator_for("service_catalog", registry, schemas).iter_errors(catalog))
    if errs:
        fail(f"services.yaml: {errs[0].message}")
    else:
        names = [s["name"] for s in catalog["services"]]
        containers = [s["container"] for s in catalog["services"]]
        if len(set(names)) != len(names) or len(set(containers)) != len(containers):
            fail("services.yaml: duplicate service or container names")
        missing = [d["service"] for s in catalog["services"] for d in s["depends_on"] if d["service"] not in names]
        (fail if missing else ok)(f"services.yaml dependencies {'missing: ' + str(missing) if missing else 'resolve'}")
        for s in catalog["services"]:
            if s["kind"] == "database" and any(a != "escalate" for a in s["allowed_actions"]):
                fail(f"services.yaml: database {s['name']} must only allow 'escalate'")
        ok("services.yaml validates")

    for api in ["openapi.yaml", "actuator.openapi.yaml"]:
        path = ROOT / "contracts" / api
        if not path.exists():
            fail(f"{api} missing")
            continue
        doc = yaml.safe_load(path.read_text())
        refs = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "$ref" and isinstance(v, str):
                        refs.append(v)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(doc)
        bad = [r for r in refs if not r.startswith("#") and not (path.parent / r.split("#")[0]).exists()]
        if bad:
            fail(f"{api}: unresolved $ref targets {sorted(set(bad))}")
        else:
            ok(f"{api} parses; {len(refs)} $refs resolve; {len(doc.get('paths', {}))} paths")

    print("\nRESULT:", "FAIL" if failures else "PASS", f"({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
