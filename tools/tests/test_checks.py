"""Unit tests for nile_tools.checks. Git runs on a throwaway repo in tmp_path, never the network."""

import os
import shutil
import subprocess

import pytest

from nile_tools import checks, cli, config

SECRET = "S3cretValue-abcdefghij0123"


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A repo with a complete, valid .env and a matching sample and versions file."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env.sample").write_text(config.render_sample())
    (tmp_path / "deploy").mkdir()
    lines = "".join(f"{k.name}=v1\n" for k in config.committed_keys())
    (tmp_path / "deploy" / "versions.env").write_text(lines)
    (tmp_path / ".env.tmp").unlink(missing_ok=True)
    config.write_private(
        tmp_path / ".env",
        config.fill_generated(config.render_sample())
        .replace("LMS_HOSTNAME=\n", "LMS_HOSTNAME=lms.example.com\n")
        .replace("AUTHENTIK_HOSTNAME=\n", "AUTHENTIK_HOSTNAME=idp.example.com\n"),
    )
    git(tmp_path, "add", ".")
    return tmp_path


def run(root, scope="up", environ=None):
    return checks.check(root, scope, environ or {}, checks.run_git(root))


def test_a_complete_file_passes_and_reminds_about_frozen_keys(repo):
    result = run(repo)
    assert result.problems == ()
    assert any("LMS_ENCRYPTION_KEY" in n for n in result.notes)


def test_missing_env_file_tells_the_operator_to_run_init(tmp_path):
    result = run(tmp_path)
    assert result.problems == (".env does not exist: run make init",)


def test_wide_mode_fails(repo):
    (repo / ".env").chmod(0o644)
    assert any("mode is 0o644" in p for p in run(repo).problems)


def test_a_tracked_env_file_fails(repo):
    git(repo, "add", "-f", ".env")
    problems = run(repo).problems
    assert any(".env is tracked by git" in p for p in problems)


def test_a_secret_pasted_into_a_tracked_file_fails_with_file_and_line_only(repo):
    values = config.load_env(repo, {}).values
    leak = values["DB_ROOT_PASSWORD"]
    (repo / "notes.txt").write_text(f"line one\npassword is {leak}\n")
    git(repo, "add", "notes.txt")
    problems = run(repo).problems
    assert "a current secret value from .env is in tracked file notes.txt:2" in problems
    assert leak not in " ".join(problems)


def test_a_secret_in_the_working_tree_but_not_staged_still_fails(repo):
    leak = config.load_env(repo, {}).values["LMS_ADMIN_PASSWORD"]
    (repo / "notes.txt").write_text("x\n")
    git(repo, "add", "notes.txt")
    (repo / "notes.txt").write_text(f"{leak}\n")
    assert any("notes.txt:1" in p for p in run(repo).problems)


def test_short_secret_values_are_not_scanned(repo):
    text = (repo / ".env").read_text().replace("AUTHENTIK_API_TOKEN=", "AUTHENTIK_API_TOKEN=short")
    config.write_private(repo / ".env", text)
    (repo / "notes.txt").write_text("short short short\n")
    git(repo, "add", "notes.txt")
    assert run(repo).problems == ()


def test_git_that_cannot_run_skips_the_git_checks_with_a_message(repo):
    def broken(args, stdin):
        return 127, "", "FileNotFoundError"

    result = checks.check(repo, "up", {}, broken)
    assert result.problems == ()
    assert any("git checks skipped" in n for n in result.notes)


def test_a_failing_git_grep_is_a_note_not_a_crash(repo):
    def flaky(args, stdin):
        return (2, "", "bad") if args[0] == "grep" else (0, "", "")

    result = checks.check(repo, "up", {}, flaky)
    assert any("secret scan skipped" in n for n in result.notes)


def test_every_problem_is_listed_at_once_and_none_holds_a_value(repo):
    text = (repo / ".env").read_text()
    text = text.replace("LMS_HOSTNAME=lms.example.com", "LMS_HOSTNAME=a_b")
    text = text.replace("AUTHENTIK_HOSTNAME=idp.example.com", "AUTHENTIK_HOSTNAME=")
    config.write_private(repo / ".env", text)
    problems = run(repo).problems
    assert any("LMS_HOSTNAME" in p for p in problems)
    assert any("AUTHENTIK_HOSTNAME is missing" in p for p in problems)


def test_a_syntax_error_still_lists_the_missing_keys_without_repeating_itself(repo):
    config.write_private(repo / ".env", "LMS_HOSTNAME='x'\n")
    problems = run(repo).problems
    assert any(p.startswith("line 1: LMS_HOSTNAME") for p in problems)
    assert any("AUTHENTIK_HOSTNAME is missing" in p for p in problems)
    assert not any("LMS_HOSTNAME is missing" in p for p in problems)


def test_a_sample_that_differs_from_the_key_list_fails(repo):
    (repo / ".env.sample").write_text("LMS_HOSTNAME=\n")
    assert any(".env.sample differs" in p for p in run(repo).problems)


def test_versions_file_with_a_missing_pin_fails(repo):
    (repo / "deploy" / "versions.env").write_text("DB_IMAGE=x\n")
    assert any("missing BUILD_FRAPPE_TAG" in p for p in run(repo).problems)


def test_process_environment_can_supply_a_missing_key(repo):
    text = (
        (repo / ".env")
        .read_text()
        .replace("AUTHENTIK_HOSTNAME=idp.example.com", "AUTHENTIK_HOSTNAME=")
    )
    config.write_private(repo / ".env", text)
    assert run(repo, environ={"AUTHENTIK_HOSTNAME": "idp.example.com"}).problems == ()


def test_authentik_scope_needs_the_token(repo):
    assert run(repo, "tools-authentik").problems != ()
    assert run(repo, "up").problems == ()


def test_config_check_exit_code_and_stderr(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert cli.main(["config", "check"]) == 0
    (repo / ".env").chmod(0o666)
    assert cli.main(["config", "check", "--for", "up"]) == 1
    assert "ERROR .env mode is" in capsys.readouterr().err
    assert os.getuid() == (repo / ".env").stat().st_uid
