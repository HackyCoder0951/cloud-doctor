"""Static and runtime guards: no shell strings anywhere, and the harness stays isolated from other streams."""
import ast
import re
from pathlib import Path

import pytest

from harness.catalog import Catalog
from harness.faults import FaultSpec
from harness.injector import CPU_HOG_SCRIPT, MEMORY_HOG_SCRIPT, DockerInjector, InjectorConfig
from harness.paths import catalog_path
from tests.harness.fakes import FakeRunner

HARNESS = Path(__file__).resolve().parents[2] / "harness"
SOURCES = sorted(p for p in HARNESS.glob("*.py"))
FORBIDDEN_CALLS = {"system", "popen", "getoutput", "getstatusoutput", "check_output", "check_call", "call", "Popen",
                   "create_subprocess_shell", "spawnl", "execl", "execv"}
FORBIDDEN_STRINGS = {"sh", "bash", "/bin/sh", "/bin/bash", "cmd", "cmd.exe", "powershell"}
FORBIDDEN_IMPORTS = ("backend", "invariants", "actuator", "ai", "requests")


def tree(p):
    return ast.parse(p.read_text(encoding="utf-8"), filename=str(p))


def test_sources_exist():
    assert len(SOURCES) >= 12


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_shell_constructs(path):
    t = tree(path)
    for node in ast.walk(t):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert name not in FORBIDDEN_CALLS, f"{path.name}:{node.lineno} calls {name}"
            for kw in node.keywords:
                if kw.arg == "shell":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value is False, f"{path.name}:{node.lineno} shell not False"
            if name == "run" and node.args:
                first = node.args[0]
                assert not isinstance(first, (ast.JoinedStr, ast.BinOp, ast.Constant)), \
                    f"{path.name}:{node.lineno} run() argument is a string expression, not an argv list"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in FORBIDDEN_STRINGS, f"{path.name}:{node.lineno} shell program string {node.value!r}"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                assert m.split(".")[0] not in FORBIDDEN_IMPORTS, f"{path.name} imports {m}"
                assert m.split(".")[0] != "shlex", f"{path.name} imports shlex"
                if m.split(".")[0] == "subprocess":
                    assert path.name == "command.py", f"{path.name} imports subprocess; only command.py may"


def test_subprocess_run_only_in_command_module_with_shell_false():
    hits = []
    for p in SOURCES:
        for node in ast.walk(tree(p)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                hits.append(p.name)
                assert any(k.arg == "shell" and k.value.value is False for k in node.keywords)
                assert any(k.arg == "timeout" for k in node.keywords)
    assert hits == ["command.py"]


def test_every_runtime_argv_is_a_clean_list(tmp_path):
    catalog = Catalog.load(catalog_path({}))
    runner = FakeRunner()
    class H:
        def request(self, *a, **k):
            return 200, b"{}"
    inj = DockerInjector(catalog, runner, InjectorConfig(compose_file="/opt/c.yaml", compose_project="cdsandbox"), H())
    faults = [FaultSpec("container_stop", "redis"), FaultSpec("container_kill", "worker"),
              FaultSpec("cpu_hog", "api", {"duration_seconds": 30}),
              FaultSpec("memory_hog", "api", {"mb_per_second": 4, "max_mb": 64, "duration_seconds": 30}),
              FaultSpec("bad_deployment", "api", {"service": "api", "new_tag": "v2", "previous_tag": "v1"})]
    for f in faults:
        inj.apply(f)
        inj.revert(f)
        inj.container_running(f.target)
    assert runner.calls
    scripts = {CPU_HOG_SCRIPT, MEMORY_HOG_SCRIPT}
    for argv in runner.argvs:
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        for a in argv:
            if a in scripts or a.startswith("{{"):
                continue
            assert not re.search(r"[\s;|&$`<>(){}\\\"']", a), f"suspicious argv item {a!r} in {argv}"


def test_scripts_take_parameters_from_argv_not_interpolation():
    for s in (CPU_HOG_SCRIPT, MEMORY_HOG_SCRIPT):
        assert "sys.argv" in s and "{" not in s and "%" not in s
        compile(s, "<script>", "exec")


def test_harness_has_no_backend_imports_and_backend_has_none_of_harness():
    root = HARNESS.parent
    for d in ("backend", "invariants", "actuator", "ai"):
        for p in (root / d).rglob("*.py") if (root / d).exists() else []:
            assert "import harness" not in p.read_text(errors="ignore") and "from harness" not in p.read_text(errors="ignore"), p
