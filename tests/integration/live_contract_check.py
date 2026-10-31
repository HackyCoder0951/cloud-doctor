#!/usr/bin/env python3
"""Live conformance check of a RUNNING backend against contracts/openapi.yaml, and of the frontend client against both.

Usage: python3 tests/integration/live_contract_check.py --token-file FILE [--base http://127.0.0.1:8080/api/v1]

1. every path the frontend client (frontend/src/api/client.ts) calls exists in the contract with the same method;
2. the backend answers every contract operation that has no side effect (GET) with a documented status, and every JSON
   body validates against the contract schema (real wiring and real data, not fixtures);
3. a missing route is told apart from a missing object (FastAPI's default 404 body has no `error` key);
4. authentication and the Idempotency-Key rule are enforced.
Operations that need an incident, plan or other object are reported as NOT EXERCISED when none exists yet; they are never
counted as passed. Needs pyyaml and jsonschema (>= 4.18). Exit code 0 only if there is no FAIL.
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
FAILS, SKIPPED = [], []


def ok(msg):
    print("ok  :", msg)


def bad(msg):
    FAILS.append(msg)
    print("FAIL:", msg)


def skip(msg):
    SKIPPED.append(msg)
    print("skip:", msg, "(NOT EXERCISED)")


def registry():
    docs = {p.stem: json.loads(p.read_text()) for p in sorted(SCHEMAS.glob("*.json"))}
    reg = Registry().with_resources([(d["$id"], Resource.from_contents(d, default_specification=DRAFT202012)) for d in docs.values()])
    return reg, docs


def absolutize(node, docs, components):
    """Rewrite './schemas/x.json#/frag' refs of an inline OpenAPI schema into the schemas' own $id, and inline
    '#/components/schemas/X' refs from the OpenAPI document."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            return absolutize(components[ref.rsplit("/", 1)[1]], docs, components)
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("./schemas/"):
                name, _, frag = v[len("./schemas/"):].partition("#")
                out[k] = docs[name.removesuffix(".json")]["$id"] + (("#" + frag) if frag else "")
            else:
                out[k] = absolutize(v, docs, components)
        return out
    if isinstance(node, list):
        return [absolutize(v, docs, components) for v in node]
    return node


def norm(path):
    return re.sub(r"\{[^}]+\}", "{}", path)


def frontend_calls():
    src = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text()
    block = src[src.index("export const api = {"):]
    calls = set()
    for m in re.finditer(r"(getJson<[^>]*>|request\('(GET|POST)',)\s*\(?\s*([`'])(/[^`']*)\3", block):
        method = "GET" if m.group(1).startswith("getJson") else m.group(2)
        calls.add((method, norm(re.sub(r"\$\{[^}]*\}", "{}", m.group(4)))))
    for m in re.finditer(r"getJson<[^>]*>\(([`'])(/[^`']*)\1", block):
        calls.add(("GET", norm(re.sub(r"\$\{[^}]*\}", "{}", m.group(2)))))
    return calls


class Client:
    """Minimal HTTP client. The session cookie is `Secure`; a browser sends it to localhost over http, urllib's cookie jar does not,
    so it is carried by hand."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookie = None

    def call(self, method, path, query=None, body=None, headers=None, auth=True):
        url = self.base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        if auth and self.cookie:
            hdrs["Cookie"] = self.cookie
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if path == "/auth/login" and r.headers.get("Set-Cookie"):
                    self.cookie = r.headers["Set-Cookie"].split(";")[0]
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers.get("Content-Type", ""), err.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080/api/v1")
    ap.add_argument("--token-file", required=True)
    args = ap.parse_args()
    spec = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text())
    reg, docs = registry()
    ops = {(m.upper(), norm(p)): (p, o) for p, item in spec["paths"].items() for m, o in item.items() if m in ("get", "post")}

    # 1. frontend -> contract
    fc = frontend_calls()
    for method, path in sorted(fc):
        (ok if (method, path) in ops else bad)(f"frontend calls {method} {path}" + ("" if (method, path) in ops else ": not in contracts/openapi.yaml"))
    unused = sorted(k for k in ops if k not in fc and k[1] not in ("/stream",))
    for method, path in unused:
        print(f"note: contract operation {method} {path} is not called by the frontend client")

    # login
    cl = Client(args.base)
    token = pathlib.Path(args.token_file).read_text().strip()
    st, _, _ = cl.call("POST", "/auth/login", body={"token": token}, headers={"Idempotency-Key": "live-check-login"})
    (ok if st in (200, 204) else bad)(f"POST /auth/login with the session token -> {st}")
    st, _, _ = cl.call("GET", "/services", auth=False)
    (ok if st == 401 else bad)(f"GET /services without a session -> {st} (expected 401)")
    st, _, body = cl.call("POST", "/incidents/INC-0001/diagnose", headers={})
    (ok if st in (400, 422) else bad)(f"mutating call without Idempotency-Key -> {st} (expected 400 or 422)")

    # objects to substitute
    def get_json(path, query=None):
        s, ct, b = cl.call("GET", path, query)
        return s, (json.loads(b) if b and "json" in ct else None)

    _, services = get_json("/services")
    svc = (services or [{}])[0].get("service") or (services or [{}])[0].get("name")
    _, incidents = get_json("/incidents", {"limit": 5})
    inc = (incidents or [{}])[0].get("incident_id") if incidents else None
    plan = None
    if inc:
        _, rem = get_json(f"/incidents/{inc}/remediation")
        plans = (rem or {}).get("plans") or []
        plan = plans[0].get("plan_id") if plans else None

    # 2. every GET operation
    for (method, npath), (path, op) in sorted(ops.items()):
        if method != "GET" or path == "/stream":
            continue
        params = list(op.get("parameters", [])) + list(spec["paths"][path].get("parameters", []))
        params = [spec["components"]["parameters"][p["$ref"].split("/")[-1]] if "$ref" in p else p for p in params]
        url, query, needs = path, {}, None
        for p in params:
            sch = p.get("schema", {})
            if p["in"] == "path":
                if p["name"] == "service":
                    val = svc
                elif p["name"] == "incident":
                    val = inc
                elif p["name"] == "plan":
                    val = plan
                else:
                    val = None
                if val is None:
                    needs = p["name"]
                url = url.replace("{" + p["name"] + "}", urllib.parse.quote(str(val)) if val else "x")
            elif p.get("required"):
                query[p["name"]] = (sch.get("enum") or [sch.get("default", sch.get("minimum", 1))])[0]
        if needs:
            skip(f"GET {path}: no {needs} exists yet")
            continue
        st, ct, raw = cl.call("GET", url, query)
        documented = {int(k) for k in op["responses"] if k.isdigit()}
        if st not in documented:
            bad(f"GET {path} -> {st}, documented {sorted(documented)}")
            continue
        if st >= 400:
            try:
                err = json.loads(raw)
            except ValueError:
                err = {}
            (ok if "error" in err else bad)(f"GET {path} -> {st} documented, body {'is' if 'error' in err else 'is NOT'} the contract Error")
            continue
        content = op["responses"][str(st)].get("content", {})
        js = content.get("application/json", {}).get("schema")
        if js is None:
            ok(f"GET {path} -> {st}")
            continue
        errors = list(Draft202012Validator(absolutize(js, docs, spec.get("components", {}).get("schemas", {})), registry=reg).iter_errors(json.loads(raw)))
        if errors:
            bad(f"GET {path} -> {st}, body violates the contract: {errors[0].message[:160]} at /{'/'.join(map(str, errors[0].absolute_path))}")
        else:
            ok(f"GET {path} -> {st}, body validates against the contract")

    print(f"\n{len(FAILS)} failed, {len(SKIPPED)} not exercised")
    print("RESULT:", "PASS" if not FAILS else "FAIL")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
