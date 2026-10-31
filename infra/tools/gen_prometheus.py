#!/usr/bin/env python3
"""Generate the Prometheus scrape configuration from the service catalog (topology as code).

Usage: python3 infra/tools/gen_prometheus.py [catalog.yaml] [output.yml]
Every series gets the labels service=<catalog name> and env=sandbox (contracts/telemetry.md).
Services of kind cache/database are scraped through the probe sidecar (cd-probes), because the
scrape target must be something that can report the service as down.
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
catalog_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "infra" / "catalog" / "services.yaml"
out_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "infra" / "generated" / "prometheus.yml"

catalog = yaml.safe_load(catalog_path.read_text())
jobs = []
for svc in catalog["services"]:
    metrics = svc.get("metrics")
    if not metrics:
        continue
    host = "cd-probes" if svc["kind"] in ("cache", "database") else svc["container"]
    jobs.append({
        "job_name": f"sim-{svc['name']}",
        "metrics_path": metrics["path"],
        "static_configs": [{"targets": [f"{host}:{metrics['port']}"],
                            "labels": {"service": svc["name"], "env": catalog["environment"]}}],
    })

config = {
    "global": {"scrape_interval": "5s", "scrape_timeout": "3s", "evaluation_interval": "15s"},
    "scrape_configs": jobs,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
header = "# GENERATED from infra/catalog/services.yaml by infra/tools/gen_prometheus.py - do not edit.\n"
out_path.write_text(header + yaml.safe_dump(config, sort_keys=False))
print(f"wrote {out_path} with {len(jobs)} scrape jobs")
