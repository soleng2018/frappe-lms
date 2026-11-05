"""The `idp` commands on the command line: wiring, exit codes and error messages (no network)."""

import signal
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from nile_tools import authentik, cli, idp, lms
from nile_tools.idp_selftest import SelftestError

ENV = (
    "AUTHENTIK_HOSTNAME=auth.example.com\nAUTHENTIK_API_TOKEN=tok-abcdefgh\n"
    "LMS_HOSTNAME=lms.example.com\nLMS_API_KEY=key123\nLMS_API_SECRET=sec456\n"
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(ENV)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def keep_sigterm() -> Iterator[None]:
    """`idp selftest` installs a SIGTERM handler; put the old one back after each test."""
    before = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, before)


def stub_selftest(monkeypatch, behaviour: Callable[..., int]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(ak, connection, browser, values, say, **kwargs):
        calls.append({"ak": ak, "lms": connection, "browser": browser, "values": values})
        return behaviour()

    monkeypatch.setattr(cli.idp_selftest_run, "selftest", fake)
    return calls


@pytest.mark.parametrize("result", [0, 1])
def test_selftest_exits_with_what_the_run_returns(root, monkeypatch, result):
    """AC-3: the exit code is 1 on any FAIL."""
    stub_selftest(monkeypatch, lambda: result)
    assert cli.main(["idp", "selftest"]) == result


def test_selftest_connects_with_the_hosts_in_the_config_file(root, monkeypatch):
    calls = stub_selftest(monkeypatch, lambda: 0)
    cli.main(["idp", "selftest"])
    call = calls[0]
    assert str(call["ak"].http.base_url) == "https://auth.example.com/api/v3/"
    assert str(call["lms"].http.base_url) == "https://lms.example.com"
    assert call["values"]["LMS_HOSTNAME"] == "lms.example.com"


def test_selftest_gives_every_login_a_fresh_browser(root, monkeypatch):
    """AC-3: the student and the stranger must not share cookies."""
    calls = stub_selftest(monkeypatch, lambda: 0)
    cli.main(["idp", "selftest"])
    make = calls[0]["browser"]
    first, second = make(), make()
    assert isinstance(first, httpx.Client) and first is not second
    assert first.cookies is not second.cookies


@pytest.mark.parametrize(
    "error",
    [
        idp.Refused("Authentik user 'x' exists without the ownership marker"),
        authentik.AuthentikError("GET https://auth.example.com/api/v3/x failed: ConnectError"),
        lms.LmsError("list User: GET https://lms.example.com/x failed: ConnectError"),
        idp.ConfigProblem("Config key LMS_HOSTNAME is missing or blank in .env"),
        SelftestError("https://lms.example.com/login shows no Authentik button"),
    ],
)
def test_selftest_names_every_expected_failure_on_stderr_and_exits_one(
    root, monkeypatch, capsys, error
):
    """AC-9, AC-11: one clear message, no traceback."""

    def boom() -> int:
        raise error

    stub_selftest(monkeypatch, boom)
    assert cli.main(["idp", "selftest"]) == 1
    captured = capsys.readouterr()
    assert captured.err == f"ERROR {error}\n" and captured.out == ""


def test_selftest_turns_ctrl_c_into_a_clean_exit_one(root, monkeypatch, capsys):
    """AC-11: the cleanup already ran in `finally`; the command only reports it."""

    def interrupted() -> int:
        raise KeyboardInterrupt

    stub_selftest(monkeypatch, interrupted)
    assert cli.main(["idp", "selftest"]) == 1
    assert "interrupted" in capsys.readouterr().err


def test_selftest_turns_sigterm_into_the_same_interrupt(root, monkeypatch):
    """AC-11: `docker stop` sends SIGTERM, which must also run the cleanup."""
    seen: list[object] = []

    def during_run() -> int:
        handler = signal.getsignal(signal.SIGTERM)
        seen.append(handler)
        assert callable(handler)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
        return 0

    stub_selftest(monkeypatch, during_run)
    assert cli.main(["idp", "selftest"]) == 0
    assert seen


def test_selftest_without_the_authentik_token_names_the_key(root, monkeypatch, capsys):
    (root / ".env").write_text(
        "LMS_HOSTNAME=lms.example.com\nAUTHENTIK_HOSTNAME=auth.example.com\n"
    )
    stub_selftest(monkeypatch, lambda: 0)
    assert cli.main(["idp", "selftest"]) == 1
    assert "AUTHENTIK_API_TOKEN" in capsys.readouterr().err


def test_selftest_never_prints_the_master_token(root, monkeypatch, capsys):
    def boom() -> int:
        raise authentik.AuthentikError("GET https://auth.example.com/api/v3/x -> HTTP 403")

    stub_selftest(monkeypatch, boom)
    cli.main(["idp", "selftest"])
    captured = capsys.readouterr()
    assert "tok-abcdefgh" not in captured.out + captured.err


def test_the_idp_group_lists_selftest(capsys):
    with pytest.raises(SystemExit):
        cli.main(["idp", "--help"])
    assert "selftest" in capsys.readouterr().out


# --- the other idp commands: wiring, flags and error mapping ---


def stub(
    monkeypatch, name: str, result: object = 0
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake(*args: Any, **kwargs: Any) -> int:
        calls.append((args, kwargs))
        if isinstance(result, Exception):
            raise result
        return int(result)  # type: ignore[call-overload]

    monkeypatch.setattr(cli.idp_run, name, fake)
    return calls


@pytest.mark.parametrize("flag", [False, True])
def test_setup_passes_the_resync_flag_through(root, monkeypatch, flag):
    """AC-2: `--resync-secret` reaches the command body."""
    calls = stub(monkeypatch, "setup")
    assert cli.main(["idp", "setup", *(["--resync-secret"] if flag else [])]) == 0
    assert calls[0][1] == {"resync_secret": flag}


def test_check_passes_the_user_and_returns_the_exit_code(root, monkeypatch):
    """AC-4, AC-7: `--user` names the real user for the groups test; exit 1 on a FAIL."""
    calls = stub(monkeypatch, "check", 1)
    assert cli.main(["idp", "check", "--user", "akadmin"]) == 1
    assert calls[0][1] == {"user": "akadmin"}


def test_remove_runs_the_command_body(root, monkeypatch):
    calls = stub(monkeypatch, "remove")
    assert cli.main(["idp", "remove"]) == 0 and len(calls) == 1


@pytest.mark.parametrize("state", ["on", "off"])
def test_password_login_passes_the_state_word(root, monkeypatch, state):
    """AC-5."""
    calls = stub(monkeypatch, "password_login")
    assert cli.main(["idp", "password-login", state]) == 0
    assert calls[0][0][1] == state


def test_password_login_rejects_any_other_word(root, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["idp", "password-login", "maybe"])
    assert e.value.code == 2


AK_ERROR = authentik.AuthentikError("GET https://auth.example.com/api/v3/x failed: ConnectError")
LMS_ERROR = lms.LmsError("Social Login Key authentik: GET https://lms.example.com/x failed")


@pytest.mark.parametrize(
    ("argv", "body", "error"),
    [
        (["idp", "setup"], "setup", AK_ERROR),
        (["idp", "setup"], "setup", LMS_ERROR),
        (["idp", "check"], "check", AK_ERROR),
        (["idp", "check"], "check", LMS_ERROR),
        (["idp", "remove"], "remove", AK_ERROR),
        (["idp", "remove"], "remove", LMS_ERROR),
        (["idp", "password-login", "off"], "password_login", LMS_ERROR),  # only the LMS is used
    ],
)
def test_each_command_names_a_failed_url_on_stderr_and_exits_one(
    root, monkeypatch, capsys, argv, body, error
):
    """AC-9: one message naming the URL, no traceback."""
    stub(monkeypatch, body, error)
    assert cli.main(argv) == 1
    assert capsys.readouterr().err == f"ERROR {error}\n"


def test_password_login_off_prints_the_refusal_and_exits_one(root, monkeypatch, capsys):
    """AC-5: `off` with no enabled Authentik key must say why."""
    stub(monkeypatch, "password_login", idp.Refused("No enabled Social Login Key; run `idp setup`"))
    assert cli.main(["idp", "password-login", "off"]) == 1
    assert "run `idp setup`" in capsys.readouterr().err


def test_setup_reports_a_missing_config_problem(root, monkeypatch, capsys):
    stub(monkeypatch, "setup", idp.ConfigProblem("Config key AUTHENTIK_APP_SLUG is missing"))
    assert cli.main(["idp", "setup"]) == 1
    assert "AUTHENTIK_APP_SLUG" in capsys.readouterr().err
