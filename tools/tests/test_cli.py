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
    seen = {}

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
    monkeypatch.setattr(cli, "init", lambda root: called.append(root) or 0)
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
