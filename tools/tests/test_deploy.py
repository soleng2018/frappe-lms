"""Unit tests for deploy glue: version pins agree, process healthcheck logic."""

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = ["python", "-m", "frappe.utils.bench_helper", "frappe"]


def _load_healthcheck():
    spec = importlib.util.spec_from_file_location(
        "healthcheck_process", REPO / "deploy/scripts/healthcheck-process.py"
    )
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
