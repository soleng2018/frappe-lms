"""The process healthcheck passes only when a bench process with every wanted argument runs."""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/scripts/healthcheck-process.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("healthcheck_process", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def add_proc(tmp_path: Path) -> Callable[[int, list[str]], None]:
    def add(pid: int, args: list[str]) -> None:
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / "cmdline").write_bytes(("\0".join(args) + "\0").encode())

    return add


BENCH = ["python", "-m", "frappe.utils.bench_helper", "frappe"]


def test_healthy_when_a_bench_process_has_every_wanted_argument(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(10, [*BENCH, "worker", "--queue", "short"])

    assert load().healthy(["worker", "short"], proc=str(tmp_path)) is True


def test_unhealthy_when_one_wanted_argument_is_missing(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(10, [*BENCH, "worker", "--queue", "short"])

    assert load().healthy(["worker", "long"], proc=str(tmp_path)) is False


def test_unhealthy_when_the_process_is_not_a_bench_process(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(10, ["sleep", "worker"])

    assert load().healthy(["worker"], proc=str(tmp_path)) is False


def test_unhealthy_when_no_process_is_running(tmp_path: Path) -> None:
    assert load().healthy(["worker"], proc=str(tmp_path)) is False


def test_arguments_must_match_whole_words_not_substrings(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(10, [*BENCH, "schedule"])

    assert load().healthy(["sched"], proc=str(tmp_path)) is False


def test_a_healthy_process_among_unrelated_ones_is_found(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(1, ["nginx"])
    add_proc(2, [*BENCH, "schedule"])
    add_proc(3, [*BENCH, "worker"])

    assert load().healthy(["worker"], proc=str(tmp_path)) is True


def test_a_process_that_vanishes_mid_scan_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "7").mkdir()  # a pid folder with no readable cmdline file

    assert load().healthy(["worker"], proc=str(tmp_path)) is False


def test_non_pid_folders_are_ignored(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    (tmp_path / "self").mkdir()
    (tmp_path / "self" / "cmdline").write_bytes(("\0".join([*BENCH, "worker"])).encode())

    assert load().healthy(["worker"], proc=str(tmp_path)) is False


def test_no_wanted_arguments_means_any_bench_process_will_do(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    add_proc(10, BENCH)

    assert load().healthy([], proc=str(tmp_path)) is True


def test_undecodable_bytes_in_a_cmdline_do_not_crash(
    tmp_path: Path, add_proc: Callable[[int, list[str]], None]
) -> None:
    folder = tmp_path / "9"
    folder.mkdir()
    (folder / "cmdline").write_bytes(b"\xff\xfe\0" + b"\0".join(a.encode() for a in BENCH))

    assert load().healthy([], proc=str(tmp_path)) is True
