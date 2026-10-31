"""Run metadata: git commit, image digests, versions, host. Commands go through the injectable CommandRunner."""
from __future__ import annotations

import os
import platform
import sys
import urllib.parse
from importlib import metadata as importlib_metadata

from harness import __version__
from harness.catalog import Catalog
from harness.command import CommandRunner

LIBS = ("pyyaml", "jsonschema", "pytest")


def _lib_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for lib in LIBS:
        try:
            out[lib] = importlib_metadata.version(lib)
        except importlib_metadata.PackageNotFoundError:
            out[lib] = None
    return out


def sanitize_url(url: str | None) -> str | None:
    """scheme://host:port only: drops userinfo, path, query."""
    if not url:
        return None
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.hostname}" + (f":{p.port}" if p.port else "") if p.hostname else None


class MetadataCollector:
    def __init__(self, runner: CommandRunner, catalog: Catalog, api_url: str | None = None, timeout: float = 15.0) -> None:
        self._runner, self._catalog, self._api_url, self._timeout = runner, catalog, api_url, timeout

    def collect(self) -> dict:
        commit = None
        res = self._runner.run(["git", "rev-parse", "HEAD"], timeout=self._timeout)
        if res.returncode == 0 and len(res.stdout.strip()) == 40:
            commit = res.stdout.strip()
        digests: dict[str, str | None] = {}
        for svc in self._catalog.services.values():
            r = self._runner.run(["docker", "inspect", "--format", "{{.Image}}", svc.container], timeout=self._timeout)
            out = r.stdout.strip()
            digests[svc.container] = out if r.returncode == 0 and out.startswith("sha256:") else None
        return {
            "git_commit": commit,
            "image_digests": digests,
            "python": sys.version.split()[0],
            "libraries": _lib_versions(),
            "harness_version": __version__,
            "host": {"platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count()},
            "api_endpoint": sanitize_url(self._api_url),
            # AI is out of scope: the LLM flag is recorded as a variant only.
            "model": {"model_id": None, "parameters": None, "prompts_hash": None},
        }
