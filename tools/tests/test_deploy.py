"""Unit tests for deploy glue: version pins agree, process healthcheck logic."""

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from nile_tools import config

REPO = Path(__file__).resolve().parents[2]
BENCH = ["python", "-m", "frappe.utils.bench_helper", "frappe"]


def _load_healthcheck():
    spec = importlib.util.spec_from_file_location(
        "healthcheck_process", REPO / "deploy/scripts/healthcheck-process.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_proc(root: Path, pid: str, args: list[str]) -> None:
    (root / pid).mkdir()
    (root / pid / "cmdline").write_bytes(("\0".join(args) + "\0").encode())


def test_nile_auth_version_agrees_in_all_three_places():
    versions = (REPO / "deploy/versions.env").read_text()
    pin = re.search(r"^BUILD_NILE_AUTH_VERSION=(.+)$", versions, re.MULTILINE)
    pyproject = re.search(
        r'^version = "(.+)"$', (REPO / "apps/nile_auth/pyproject.toml").read_text(), re.MULTILINE
    )
    init = re.search(
        r'__version__ = "(.+)"', (REPO / "apps/nile_auth/nile_auth/__init__.py").read_text()
    )
    assert pin and pyproject and init
    assert pin.group(1) == pyproject.group(1) == init.group(1)


def test_every_build_arg_in_compose_has_a_pin():
    pins = (REPO / "deploy/versions.env").read_text()
    compose = (REPO / "deploy/compose.yaml").read_text()
    for key in set(re.findall(r"\$\{(BUILD_[A-Z_]+)\}", compose)):
        assert re.search(rf"^{key}=.+$", pins, re.MULTILINE), key


def test_healthcheck_matches_process_with_all_arguments(tmp_path):
    hc = _load_healthcheck()
    _fake_proc(tmp_path, "10", [*BENCH, "worker", "--queue", "long"])
    assert hc.healthy(["worker", "long"], proc=str(tmp_path))


def test_healthcheck_fails_when_an_argument_is_missing(tmp_path):
    hc = _load_healthcheck()
    _fake_proc(tmp_path, "10", [*BENCH, "worker", "--queue", "short"])
    assert not hc.healthy(["worker", "long"], proc=str(tmp_path))


def test_healthcheck_ignores_processes_that_are_not_bench_helper(tmp_path):
    hc = _load_healthcheck()
    _fake_proc(tmp_path, "10", ["sleep", "worker", "long"])
    assert not hc.healthy(["worker", "long"], proc=str(tmp_path))


def test_healthcheck_survives_a_process_that_vanished(tmp_path):
    hc = _load_healthcheck()
    (tmp_path / "10").mkdir()  # no cmdline file: read raises OSError
    assert not hc.healthy(["worker"], proc=str(tmp_path))


# --- config wiring: key list vs compose vs Makefile (AC-1, AC-6, AC-8) ---


# Passed to compose by the Makefile on the command line, not settings.
MAKEFILE_VARS = {"APPS_HASH", "REPO_DIR"}


def _compose_text() -> str:
    return (REPO / "deploy/compose.yaml").read_text()


def _compose_vars(text: str) -> set[str]:
    """Names in ${NAME}, ${NAME:-x}, ${NAME:?x}; an escaped $${NAME} is not a Compose variable."""
    return set(re.findall(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)[^}]*\}", text))


def test_every_compose_variable_is_in_the_key_list():
    known = {k.name for k in config.KEYS} | MAKEFILE_VARS
    assert _compose_vars(_compose_text()) - known == set()


def test_the_compose_variable_finder_handles_defaults_and_escapes():
    text = "a: ${A} b: ${B:-x} c: ${C:?m} d: $${D} e: $$E"
    assert _compose_vars(text) == {"A", "B", "C"}


def _services() -> dict:
    return yaml.safe_load(_compose_text())["services"]


def _delivered(service: dict) -> dict[str, str]:
    """Environment entries that take a whole value from one config key: {VAR: KEY}."""
    env = service.get("environment") or {}
    found = {}
    for var, value in env.items():
        match = re.fullmatch(r"\$\{([A-Z][A-Z0-9_]*)\}", str(value))
        if match:
            found[var] = match.group(1)
    return found


def test_each_service_receives_exactly_the_keys_in_the_delivery_table():
    table = config.delivery()
    for name, service in _services().items():
        assert _delivered(service) == dict(table.get(name, {})), name
    assert set(table) <= set(_services())


def test_a_config_key_appears_in_compose_only_where_the_key_list_allows():
    """Secrets only in a delivered environment entry; no env_file; hostnames may be in labels."""
    services = _services()
    allowed = {
        k.name: {(s, v) for s, v in k.services} for k in config.KEYS if k.services or k.secret
    }
    for name, service in services.items():
        assert "env_file" not in service, name
        env = service.get("environment") or {}
        rest = yaml.safe_dump({k: v for k, v in service.items() if k != "environment"})
        for key in (k for k in config.KEYS if k.secret):
            assert f"${{{key.name}" not in rest, f"{key.name} outside environment of {name}"
            for var, value in env.items():
                if f"${{{key.name}" in str(value):
                    assert (name, var) in allowed[key.name], (name, var)


def test_tools_service_holds_no_environment_and_mounts_the_repo():
    tools = _services()["tools"]
    assert not tools.get("environment")
    assert tools["volumes"] == ["${REPO_DIR}:${REPO_DIR}"]


def test_build_arguments_come_only_from_the_committed_pins():
    for name, service in _services().items():
        args = (service.get("build") or {}).get("args") or {}
        for arg, value in args.items():
            used = _compose_vars(str(value))
            assert used, (name, arg)
            assert all(v.startswith(("BUILD_", "TOOLS_")) or v == "APPS_HASH" for v in used), arg
            committed = {k.name for k in config.committed_keys()}
            assert (used - {"APPS_HASH"}) <= committed, (name, arg)


def test_dockerignore_files_keep_env_out_of_every_build_context():
    root = (REPO / ".dockerignore").read_text().splitlines()
    assert ".env" in root and ".env.tmp" in root
    assert not any(line.startswith("!") and "env" in line for line in root)
    tools = (REPO / "tools/.dockerignore").read_text().splitlines()
    assert ".env" in tools and ".env.*" in tools


def test_gitignore_ignores_env_and_its_temp_file_but_not_the_sample():
    lines = (REPO / ".gitignore").read_text().splitlines()
    assert ".env" in lines and ".env.tmp" in lines
    assert "!.env.sample" in lines and "!deploy/versions.env" in lines


@pytest.mark.skipif(not shutil.which("make"), reason="make is not installed")
def test_the_makefile_refuses_to_run_when_a_config_key_is_exported():
    clean = {k: v for k, v in os.environ.items() if k not in {c.name for c in config.KEYS}}
    ok = subprocess.run(
        ["make", "guard"], cwd=REPO, env=clean, capture_output=True, text=True, check=False
    )
    assert ok.returncode == 0, ok.stderr
    bad = subprocess.run(
        ["make", "guard"],
        cwd=REPO,
        env={**clean, "LMS_HOSTNAME": "x", "TOOLS_PYTHON_IMAGE": "y"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "LMS_HOSTNAME" in bad.stderr and "TOOLS_PYTHON_IMAGE" in bad.stderr


def test_make_up_runs_the_config_check_before_any_build_or_start():
    makefile = (REPO / "Makefile").read_text()
    assert re.search(r"^up: build$", makefile, re.MULTILINE)
    assert re.search(r"^build: check$", makefile, re.MULTILINE)
    assert "config check --for up" in makefile
