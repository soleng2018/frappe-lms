"""Unit tests for nile_tools.cli. No network, no real .env: everything runs in tmp_path."""

import base64
import logging
import stat
import sys

import httpx
import pytest

from nile_tools import cli, config

GENERATED = [k.name for k in config.KEYS if k.source == "generated"]
REQUIRED_OPERATOR = ["LMS_HOSTNAME", "AUTHENTIK_HOSTNAME", "AUTHENTIK_API_TOKEN"]


def values_of(path):
    return dict(config.parse_env(path.read_text(), [k.name for k in config.env_keys()]).values)


@pytest.fixture(autouse=True)
def restore_global_hooks():
    """main() installs a log record factory and an exception hook; undo them after each test."""
    factory, hook = logging.getLogRecordFactory(), sys.excepthook
    yield
    logging.setLogRecordFactory(factory)
    sys.excepthook = hook


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".env.sample").write_text(config.render_sample())
    return tmp_path


def test_init_creates_env_with_generated_secrets(root, capsys):
    assert cli.init(root) == 0
    values = values_of(root / ".env")
    for key in GENERATED:
        assert values[key], key
    assert values["LMS_SERVICE_USER"] == "nile-tools@example.com"
    assert capsys.readouterr().out.startswith(f"Created {root / '.env'}")


def test_init_encryption_key_is_32_bytes_base64(root):
    cli.init(root)
    key = values_of(root / ".env")["LMS_ENCRYPTION_KEY"]
    assert len(base64.urlsafe_b64decode(key)) == 32


def test_init_env_file_is_owner_only(root):
    cli.init(root)
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600


def test_init_leaves_no_temp_file(root):
    cli.init(root)
    assert not (root / ".env.tmp").exists()


def test_init_is_idempotent_and_keeps_existing_values(root, capsys):
    cli.init(root)
    first = (root / ".env").read_text()
    capsys.readouterr()
    assert cli.init(root) == 0
    assert (root / ".env").read_text() == first
    assert capsys.readouterr().out.startswith("Kept ")


def test_init_never_overwrites_a_value_the_user_set(root):
    (root / ".env").write_text("DB_ROOT_PASSWORD=mine\nLMS_API_KEY=\n")
    cli.init(root)
    values = values_of(root / ".env")
    assert values["DB_ROOT_PASSWORD"] == "mine"
    assert values["LMS_API_KEY"] != ""


def test_init_does_not_generate_keys_outside_the_generated_set(root):
    cli.init(root)
    assert values_of(root / ".env")["LMS_HOSTNAME"] == ""


def test_init_reports_hostname_still_blank(root, capsys):
    cli.init(root)
    assert "Still blank, fill these in: LMS_HOSTNAME" in capsys.readouterr().out


def test_init_does_not_nag_once_operator_keys_are_set(root, capsys):
    keys = "".join(f"{k}=x\n" for k in REQUIRED_OPERATOR)
    (root / ".env").write_text(keys)
    cli.init(root)
    assert "Still blank" not in capsys.readouterr().out


def test_init_never_prints_a_secret(root, capsys):
    cli.init(root)
    out = capsys.readouterr().out
    for key in GENERATED:
        assert values_of(root / ".env")[key] not in out


def test_init_without_sample_fails_when_no_env(tmp_path):
    with pytest.raises(FileNotFoundError):
        cli.init(tmp_path)


class FakeClock:
    """Replaces time.monotonic and time.sleep so retry loops run instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(cli.time, "monotonic", c.monotonic)
    monkeypatch.setattr(cli.time, "sleep", c.sleep)
    return c


@pytest.fixture
def env_root(tmp_path):
    (tmp_path / ".env").write_text(
        "LMS_HOSTNAME=lms.example.com\nLMS_API_KEY=key123\nLMS_API_SECRET=sec456\n"
    )
    return tmp_path


def _resp(status, body=None):
    return httpx.Response(status, json=body or {}, request=httpx.Request("GET", "https://x"))


def test_whoami_prints_service_user(env_root, monkeypatch, capsys, clock):
    # covers: AC-3
    seen: dict[str, object] = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return _resp(200, {"message": "nile-tools@example.com"})

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    assert cli.whoami(env_root) == 0
    assert capsys.readouterr().out.strip() == "nile-tools@example.com"
    assert seen["url"] == "https://lms.example.com/api/method/frappe.auth.get_logged_user"
    assert seen["headers"] == {"Authorization": "token key123:sec456"}


def test_whoami_retries_until_the_site_is_up(env_root, monkeypatch, capsys, clock):
    # covers: AC-3
    replies = iter([_resp(502), httpx.ConnectError("down"), _resp(200, {"message": "u"})])

    def fake_get(url, headers, timeout):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    assert cli.whoami(env_root) == 0
    assert clock.sleeps == [5, 5]
    assert capsys.readouterr().out.strip() == "u"


def test_whoami_gives_up_after_five_minutes_naming_url(env_root, monkeypatch, capsys, clock):
    monkeypatch.setattr(cli.httpx, "get", lambda url, headers, timeout: _resp(503))
    assert cli.whoami(env_root) == 1
    err = capsys.readouterr().err
    assert "https://lms.example.com/api/method/frappe.auth.get_logged_user" in err
    assert "HTTP 503" in err
    assert sum(clock.sleeps) >= 300


def test_whoami_failure_message_never_leaks_credentials(env_root, monkeypatch, capsys, clock):
    monkeypatch.setattr(cli.httpx, "get", lambda url, headers, timeout: _resp(401))
    cli.whoami(env_root)
    captured = capsys.readouterr()
    assert "sec456" not in captured.err + captured.out
    assert "key123" not in captured.err + captured.out


def test_whoami_reports_exception_type_on_network_error(env_root, monkeypatch, capsys, clock):
    def boom(url, headers, timeout):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(cli.httpx, "get", boom)
    assert cli.whoami(env_root) == 1
    assert "ConnectTimeout" in capsys.readouterr().err


def test_whoami_missing_hostname_key_raises(tmp_path):
    (tmp_path / ".env").write_text("LMS_API_KEY=a\nLMS_API_SECRET=b\n")
    with pytest.raises(config.ConfigError, match="LMS_HOSTNAME"):
        cli.whoami(tmp_path)


def test_main_dispatches_to_the_named_command(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(sys, "argv", ["tools", "init"])
    monkeypatch.chdir(tmp_path)

    def fake_init(root):
        called.append(root)
        return 0

    monkeypatch.setattr(cli, "init", fake_init)
    assert cli.main() == 0
    assert called == [tmp_path]


def test_main_rejects_unknown_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["tools", "nope"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_whoami_blank_hostname_fails_fast_naming_the_key(tmp_path):
    (tmp_path / ".env").write_text("LMS_HOSTNAME=\nLMS_API_KEY=a\nLMS_API_SECRET=b\n")
    with pytest.raises(config.ConfigError, match="LMS_HOSTNAME"):
        cli.whoami(tmp_path)


def test_main_prints_config_error_and_exits_one(monkeypatch, tmp_path, capsys):
    (tmp_path / ".env").write_text("LMS_HOSTNAME=\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["tools", "whoami"])
    assert cli.main() == 1
    assert "LMS_HOSTNAME" in capsys.readouterr().err


def test_init_reports_every_blank_operator_key(root, capsys):
    cli.init(root)
    out = capsys.readouterr().out
    for key in REQUIRED_OPERATOR:
        assert key in out


def test_init_replaces_a_leftover_wide_temp_file(root):
    (root / ".env.tmp").write_text("stale")
    (root / ".env.tmp").chmod(0o644)
    cli.init(root)
    assert not (root / ".env.tmp").exists()
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600


def test_init_tightens_a_wide_env_file_mode(root):
    (root / ".env").write_text("LMS_HOSTNAME=x\n")
    (root / ".env").chmod(0o644)
    cli.init(root)
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600


# --- init: errors, appends and the optional list (AC-3) ---


def test_init_refuses_a_file_with_a_syntax_error_and_leaves_it_untouched(root):
    bad = "LMS_HOSTNAME='x'\nDB_ROOT_PASSWORD=\n"
    (root / ".env").write_text(bad)
    with pytest.raises(config.ConfigError, match="line 1: LMS_HOSTNAME"):
        cli.init(root)
    assert (root / ".env").read_text() == bad


def test_main_init_with_a_syntax_error_exits_one_and_names_the_line(root, monkeypatch, capsys):
    (root / ".env").write_text("export LMS_HOSTNAME=a\n")
    monkeypatch.chdir(root)
    assert cli.main(["init"]) == 1
    assert "line 1: 'export' is not allowed" in capsys.readouterr().err


def test_init_appends_keys_added_since_and_says_updated(root, capsys):
    (root / ".env").write_text("LMS_HOSTNAME=mine.example.com\n")
    assert cli.init(root) == 0
    values = values_of(root / ".env")
    assert values["LMS_HOSTNAME"] == "mine.example.com"
    assert set(values) == {k.name for k in config.env_keys()}
    assert capsys.readouterr().out.startswith("Updated ")


def test_init_does_not_rewrite_the_file_when_nothing_changes(root):
    cli.init(root)
    before = (root / ".env").stat().st_mtime_ns
    cli.init(root)
    assert (root / ".env").stat().st_mtime_ns == before


def test_init_lists_optional_operator_keys_apart_from_required_ones(root, monkeypatch, capsys):
    optional = config.Key("SMTP_HOST", "SMTP", "Mail relay", "operator")
    monkeypatch.setattr(config, "KEYS", (*config.KEYS, optional))
    cli.init(root)
    out = capsys.readouterr().out
    assert "Optional, left blank: SMTP_HOST" in out
    assert "SMTP_HOST" not in out.split("Optional")[0]


def test_init_names_the_blank_required_keys_in_one_line(root, capsys):
    cli.init(root)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("Still blank"))
    assert line == "Still blank, fill these in: " + ", ".join(REQUIRED_OPERATOR)


# --- config check, show and main wiring (AC-4, AC-7) ---


def test_config_check_success_says_so_on_stdout_and_prints_the_frozen_reminder(
    monkeypatch, tmp_path, capsys
):
    from nile_tools import checks

    monkeypatch.setattr(checks, "check", lambda *a: checks.CheckResult((), ("a note",)))
    assert cli.config_check(tmp_path, "up") == 0
    out = capsys.readouterr()
    assert "a note" in out.out and "Config is fine for: up" in out.out
    assert out.err == ""


def test_config_check_failure_lists_each_problem_on_stderr_and_not_the_fine_line(
    monkeypatch, tmp_path, capsys
):
    from nile_tools import checks

    result = checks.CheckResult(("first", "second"), ())
    monkeypatch.setattr(checks, "check", lambda *a: result)
    assert cli.config_check(tmp_path, "tools-authentik") == 1
    out = capsys.readouterr()
    assert out.err.splitlines() == ["ERROR first", "ERROR second"]
    assert "Config is fine" not in out.out


def test_config_check_passes_the_chosen_scope_through(monkeypatch, tmp_path):
    from nile_tools import checks

    seen = []
    monkeypatch.chdir(tmp_path)

    def fake_check(root, scope, environ, git):
        seen.append(scope)
        return checks.CheckResult((), ())

    monkeypatch.setattr(checks, "check", fake_check)
    assert cli.main(["config", "check", "--for", "tools-authentik"]) == 0
    assert cli.main(["config", "check"]) == 0
    assert seen == ["tools-authentik", "up"]


@pytest.mark.parametrize("argv", [["config", "check", "--for", "nope"], ["config"], []])
def test_main_rejects_bad_arguments_with_exit_two(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_config_show_includes_the_committed_pins_unmasked(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("LMS_HOSTNAME=a.example.com\n")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "versions.env").write_text("BUILD_LMS_TAG=v2.3.4\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "BUILD_LMS_TAG=v2.3.4" in out
    assert "BUILD_FRAPPE_TAG=(blank)" in out


def test_config_show_marks_a_blank_secret_blank_and_never_prints_a_set_one(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / ".env").write_text(
        "LMS_API_KEY=0123456789abcdef0123456789abcdef\n"  # gitleaks:allow
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "LMS_API_KEY=*****" in out
    assert "LMS_API_SECRET=(blank)" in out
    assert "0123456789abcdef" not in out


def test_config_show_reports_a_bad_versions_file_without_a_traceback(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "versions.env").write_text("BUILD_LMS_TAG='x'\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "show"]) == 1
    assert "versions.env has problems" in capsys.readouterr().err


def test_main_masks_secrets_in_later_log_records(tmp_path, monkeypatch, capsys):
    secret = "Zk3-very-secret-value-9"
    (tmp_path / ".env").write_text(f"DB_ROOT_PASSWORD={secret}\n")
    monkeypatch.chdir(tmp_path)
    cli.main(["config", "sample"])
    record = logging.getLogger("t").makeRecord("t", 20, "f", 1, "pw %s", (secret,), None)
    assert record.getMessage() == "pw *****"


def test_main_still_runs_when_the_env_file_is_bad_so_the_error_can_be_shown(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / ".env").write_text("DB_ROOT_PASSWORD='hunter2hunter2'\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "sample"]) == 0
    assert capsys.readouterr().out == config.render_sample()


# --- a missing or unreadable .env is a message, not a traceback ---


@pytest.mark.parametrize("argv", [["config", "show"], ["whoami"]])
def test_commands_that_need_env_say_to_run_init_when_it_is_missing(
    argv, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert cli.main(argv) == 1
    assert (
        ".env cannot be read (No such file or directory): run make init" in capsys.readouterr().err
    )


def test_config_check_on_an_unreadable_env_exits_one_with_a_message(root, monkeypatch, capsys):
    (root / ".env").write_text("LMS_HOSTNAME=a.example.com\n")
    (root / ".env").chmod(0)
    monkeypatch.chdir(root)
    try:
        if (root / ".env").stat().st_uid == 0:
            pytest.skip("root can read any file")
        assert cli.main(["config", "check"]) == 1
    finally:
        (root / ".env").chmod(0o600)
    err = capsys.readouterr().err
    assert "ERROR .env cannot be read (Permission denied)" in err
    assert "Traceback" not in err
