"""Unit tests for the `content` commands (AC-5, AC-9): offline, no .env, exit codes."""

from pathlib import Path

import pytest

from nile_tools import cli


def test_check_prints_ok_per_course_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "content").mkdir()
    assert cli.content_new(tmp_path, "demo", None) == 0
    assert cli.content_check(tmp_path) == 0
    assert capsys.readouterr().out.endswith("ok demo\n")


def test_check_prints_every_problem_on_stderr_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "content").mkdir()
    cli.content_new(tmp_path, "demo", None)
    guide = tmp_path / "content" / "demo" / "guides" / "welcome.md"
    guide.write_text("{{ x }}\n![](missing.png)\n")
    capsys.readouterr()
    assert cli.content_check(tmp_path) == 1
    captured = capsys.readouterr()
    assert "ERROR demo/guides/welcome.md: line 1:" in captured.err
    assert "ERROR demo/guides/welcome.md: line 2: the image has no alt text" in captured.err
    assert "ok demo" not in captured.out


def test_check_one_course_and_an_unknown_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "content").mkdir()
    cli.content_new(tmp_path, "demo", None)
    assert cli.content_check(tmp_path, "demo") == 0
    assert cli.content_check(tmp_path, "nope") == 1
    assert "unknown course 'nope'; known courses: demo" in capsys.readouterr().err


def test_new_refuses_twice_with_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "content").mkdir()
    assert cli.content_new(tmp_path, "demo", "My Demo") == 0
    assert cli.content_new(tmp_path, "demo", None) == 1
    assert "already exists" in capsys.readouterr().err


def test_a_usage_error_exits_2() -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["content", "new"])
    assert e.value.code == 2
