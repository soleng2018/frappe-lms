"""Unit tests for nile_auth.setup with a stubbed Frappe: the guards that stop before any change.

`setup.py` uses Python 3.14 syntax (the Frappe image), so these run only on 3.14 and skip on the
tools Python 3.12. Run them with:
PYTHONPATH=../apps/nile_auth uv run --no-project --python 3.14 --with pytest \
    pytest -c /dev/null --rootdir . tests/test_nile_auth_setup.py
"""

import importlib
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

if sys.version_info < (3, 14):
    pytest.skip("nile_auth.setup needs Python 3.14 syntax", allow_module_level=True)


class FakeDb:
    def __init__(self, timezone: str = "Asia/Kolkata") -> None:
        self.timezone = timezone
        self.users: dict[str, Any] = {}
        self.commits = 0
        self.writes: list[str] = []

    def get_single_value(self, _doctype: str, _field: str) -> str:
        return self.timezone

    def set_single_value(self, _doctype: str, _field: str, value: str) -> None:
        self.writes.append(value)
        self.timezone = value

    def commit(self) -> None:
        self.commits += 1

    def exists(self, doctype: str, name: str) -> Any:
        return name if doctype == "User" and name in self.users else None


@pytest.fixture
def setup_mod(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, FakeDb]:
    db = FakeDb()
    frappe = types.ModuleType("frappe")
    frappe.db = db
    frappe.get_doc = lambda _arg, name=None: db.users[name]
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.delitem(sys.modules, "nile_auth.setup", raising=False)
    module = importlib.import_module("nile_auth.setup")
    monkeypatch.setitem(sys.modules, "nile_auth.setup", module)
    return module, db


def _mcp_env(monkeypatch: pytest.MonkeyPatch, user: str = "mcp@example.com") -> None:
    monkeypatch.setenv("LMS_MCP_USER", user)
    monkeypatch.setenv("LMS_MCP_API_KEY", "k")
    monkeypatch.setenv("LMS_MCP_API_SECRET", "s")
    monkeypatch.setenv("LMS_SERVICE_USER", "svc@example.com")


def test_a_bad_timezone_stops_with_a_message_and_changes_nothing(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, db = setup_mod
    monkeypatch.setenv("LMS_TIMEZONE", "Mars/Olympus")
    with pytest.raises(SystemExit) as caught:
        module.ensure_timezone()
    assert "Mars/Olympus" in str(caught.value)
    assert db.writes == [] and db.commits == 0


def test_the_timezone_is_set_once_and_a_rerun_changes_nothing(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, db = setup_mod
    monkeypatch.setenv("LMS_TIMEZONE", "Europe/Paris")
    module.ensure_timezone()
    module.ensure_timezone()
    assert db.writes == ["Europe/Paris"] and db.commits == 1


def test_a_service_user_with_a_different_key_stops_and_is_not_changed(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, db = setup_mod
    db.users["svc@example.com"] = SimpleNamespace(api_key="old", get_password=lambda _f: "old")
    monkeypatch.setenv("LMS_SERVICE_USER", "svc@example.com")
    monkeypatch.setenv("LMS_API_KEY", "new")
    monkeypatch.setenv("LMS_API_SECRET", "new-secret")
    with pytest.raises(SystemExit) as caught:
        module.ensure_service_user()
    assert "different API key" in str(caught.value)
    assert db.commits == 0


def test_a_matching_service_user_is_left_alone(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, db = setup_mod
    db.users["svc@example.com"] = SimpleNamespace(api_key="k", get_password=lambda _f: "s")
    monkeypatch.setenv("LMS_SERVICE_USER", "svc@example.com")
    monkeypatch.setenv("LMS_API_KEY", "k")
    monkeypatch.setenv("LMS_API_SECRET", "s")
    module.ensure_service_user()
    assert "already set up" in capsys.readouterr().out
    assert db.commits == 0


def test_the_mcp_user_may_not_be_the_service_user_in_any_case(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, db = setup_mod
    _mcp_env(monkeypatch, "Svc@Example.com")
    with pytest.raises(SystemExit) as caught:
        module.ensure_mcp_user()
    assert "must differ" in str(caught.value)
    assert db.commits == 0


def test_an_mcp_user_holding_system_manager_stops(
    setup_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, db = setup_mod
    db.users["mcp@example.com"] = SimpleNamespace(
        user_type="System User",
        roles=[SimpleNamespace(role="Desk User"), SimpleNamespace(role="System Manager")],
    )
    monkeypatch.setattr(module, "_mcp_problems", lambda t, r: module.mcp_user_problems(t, r, []))
    _mcp_env(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        module.ensure_mcp_user()
    assert "System Manager" in str(caught.value)
    assert db.commits == 0
