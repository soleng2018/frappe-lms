"""Unit tests for nile_auth.login and nile_auth.cleanup with a stubbed Frappe (specs 0006 and 0009).

No site, no network. A small fake `frappe` is put in sys.modules for the length of each test, so the
real module code runs against a fake database. Live behaviour is covered by integration tests.
"""

import importlib
import logging
import sys
import types
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

ADMIN_ROLES = ("Moderator", "Course Creator", "Desk User")


class FakeUser:
    """Just enough of a Frappe User document: roles, set, append, save, flags."""

    def __init__(self, name: str, roles: tuple[str, ...] = ()) -> None:
        self.name = name
        self.roles = [SimpleNamespace(role=r) for r in roles]
        self.nile_groups = ""
        self.user_type = ""
        self.saved = 0
        self.flags = SimpleNamespace()

    def set(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def append(self, key: str, row: dict) -> None:
        getattr(self, key).append(SimpleNamespace(**row))

    def save(self) -> None:
        self.saved += 1


class FakeFrappe:
    """The state behind the fake `frappe` module."""

    class QueryDeadlockError(Exception):
        pass

    def __init__(self) -> None:
        self.conf: dict[str, Any] = {}
        self.users: dict[str, FakeUser] = {}
        self.enrollments: list[dict] = []  # {"name", "member", "course"}
        self.has_role: set[tuple[str, str]] = set()
        self.social: dict[tuple[str, str], str] = {}  # (user, provider) -> userid
        self.batches: list[str] = []
        self.batch_courses: list[SimpleNamespace] = []
        self.deleted: list[tuple[str, str]] = []
        self.commits = 0
        self.rollbacks = 0
        self.session_users: list[str] = []
        self.logs: list[tuple[str, str]] = []
        self.created = 0

    def set_user(self, name: str) -> None:
        self.session_users.append(name)


def _build(state: FakeFrappe) -> dict[str, types.ModuleType]:
    frappe = types.ModuleType("frappe")
    frappe.conf = state.conf  # type: ignore[attr-defined]
    frappe.QueryDeadlockError = state.QueryDeadlockError  # type: ignore[attr-defined]
    frappe.whitelist = lambda **_kw: lambda fn: fn  # type: ignore[attr-defined]
    frappe.set_user = state.set_user  # type: ignore[attr-defined]
    frappe.local = SimpleNamespace(response={})  # type: ignore[attr-defined]

    def exists(doctype: str, name: Any = None) -> Any:
        if doctype == "User":
            return name if name in state.users else None
        return None

    def get_value(doctype: str, name: Any, field: Any = None) -> Any:
        if doctype == "User Social Login":
            return state.social.get((name["parent"], name["provider"]))
        if doctype == "Social Login Key":
            return None  # no user_id_property set, so the code falls back to "sub"
        return None

    def db_exists(doctype: str, name: Any = None) -> Any:
        if doctype == "Has Role" and isinstance(name, dict):
            return (name["parent"], name["role"]) in state.has_role or None
        return exists(doctype, name)

    def commit() -> None:
        state.commits += 1

    def rollback() -> None:
        state.rollbacks += 1

    frappe.db = SimpleNamespace(  # type: ignore[attr-defined]
        exists=db_exists, get_value=get_value, commit=commit, rollback=rollback
    )

    def get_all(doctype: str, filters: Any = None, fields: Any = None, pluck: Any = None) -> list:
        if doctype == "LMS Batch":
            return list(state.batches)
        if doctype == "Batch Course":
            return list(state.batch_courses)
        if doctype == "LMS Enrollment":
            allowed = filters["course"][1]
            return [
                SimpleNamespace(**row)
                for row in state.enrollments
                if row["member"] == filters["member"] and row["course"] in allowed
            ]
        if doctype == "LMS Course":
            return []
        raise AssertionError(f"unexpected get_all {doctype}")

    frappe.get_all = get_all  # type: ignore[attr-defined]

    def delete_doc(doctype: str, name: str, **_kw: Any) -> None:
        state.deleted.append((doctype, name))
        if doctype == "LMS Enrollment":
            state.enrollments[:] = [e for e in state.enrollments if e["name"] != name]

    frappe.delete_doc = delete_doc  # type: ignore[attr-defined]

    def get_doc(arg: Any, name: str | None = None) -> Any:
        if isinstance(arg, dict) and arg.get("doctype") == "LMS Enrollment":
            return SimpleNamespace(insert=lambda **_kw: _add_enrollment(state, arg))
        return state.users[name or ""]

    frappe.get_doc = get_doc  # type: ignore[attr-defined]

    def new_doc(doctype: str) -> Any:
        user = FakeUser("")
        user.update = lambda data: _create_user(state, user, data)  # type: ignore[attr-defined]
        user.insert = lambda **_kw: _insert_user(state, user)  # type: ignore[attr-defined]
        return user

    frappe.new_doc = new_doc  # type: ignore[attr-defined]
    frappe.generate_hash = lambda: "hash"  # type: ignore[attr-defined]

    class Logger:
        level = logging.WARNING

        def setLevel(self, level: int) -> None:
            self.level = level

        def info(self, line: str) -> None:
            state.logs.append(("info", line))

        def warning(self, line: str) -> None:
            state.logs.append(("warning", line))

        def error(self, line: str) -> None:
            state.logs.append(("error", line))

    logger = Logger()
    frappe.logger = lambda _name: logger  # type: ignore[attr-defined]

    integrations = types.ModuleType("frappe.integrations")
    oauth2 = types.ModuleType("frappe.integrations.oauth2_logins")
    oauth2.decoder_compat = object()  # type: ignore[attr-defined]
    utils = types.ModuleType("frappe.utils")
    utils.get_url = lambda path="": "https://lms.example.com" + path  # type: ignore[attr-defined]
    oauth = types.ModuleType("frappe.utils.oauth")
    oauth.OAUTH_LOGIN_FLOW_CACHE_PREFIX = "flow"  # type: ignore[attr-defined]
    oauth.get_email = lambda info: info.get("email")  # type: ignore[attr-defined]
    oauth.get_first_name = lambda info: info.get("given_name")  # type: ignore[attr-defined]
    oauth.get_last_name = lambda info: info.get("family_name")  # type: ignore[attr-defined]
    oauth.get_info_via_oauth = lambda *a, **k: {}  # type: ignore[attr-defined]
    oauth.login_oauth_user = lambda *a, **k: None  # type: ignore[attr-defined]
    lms = types.ModuleType("lms")
    lms_lms = types.ModuleType("lms.lms")
    lms_utils = types.ModuleType("lms.lms.utils")
    lms_utils.get_course_progress = lambda course, member: 0  # type: ignore[attr-defined]
    return {
        "frappe": frappe,
        "frappe.integrations": integrations,
        "frappe.integrations.oauth2_logins": oauth2,
        "frappe.utils": utils,
        "frappe.utils.oauth": oauth,
        "lms": lms,
        "lms.lms": lms_lms,
        "lms.lms.utils": lms_utils,
    }


def _create_user(state: FakeFrappe, user: FakeUser, data: dict) -> None:
    user.name = data["email"]
    user.user_type = data["user_type"]


def _insert_user(state: FakeFrappe, user: FakeUser) -> None:
    user.roles.append(SimpleNamespace(role="LMS Student"))  # LMS adds this on insert
    state.users[user.name] = user
    state.created += 1


def _add_enrollment(state: FakeFrappe, doc: dict) -> None:
    state.enrollments.append(
        {
            "name": f"enr-{len(state.enrollments) + 1}",
            "member": doc["member"],
            "course": doc["course"],
        }
    )


@pytest.fixture
def fake() -> FakeFrappe:
    return FakeFrappe()


@pytest.fixture
def load(fake: FakeFrappe, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], types.ModuleType]:
    """Import a nile_auth module against the fake frappe, then forget it again."""
    for name, module in _build(fake).items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in ("nile_auth.login", "nile_auth.cleanup"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    def _load(name: str) -> types.ModuleType:
        module = importlib.import_module(name)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    return _load


def _decision(**kw: Any) -> Any:
    from nile_auth.groups import Decision

    return Decision(**kw)


LIVE = {
    "kind": "live",
    "course": "nca",
    "course_group": "Nile Certified Associate",
    "matched_groups": ("Nile Certified Associate",),
    "desired_roles": ("LMS Student",),
}
INFO = {"email": "kim@example.com", "given_name": "Kim", "family_name": "Lee"}


# --- protected accounts and identity (spec 0009 AC-8) ---


@pytest.mark.parametrize("name", ["Administrator", "Guest"])
def test_the_built_in_accounts_are_protected(load: Any, fake: FakeFrappe, name: str) -> None:
    login = load("nile_auth.login")
    with pytest.raises(login.Refused) as caught:
        login._refuse_if_protected(name, INFO, "authentik")
    assert caught.value.outcome == "refused_protected"
    assert caught.value.page[2] == 403


def test_the_service_and_mcp_users_are_protected_in_any_case(load: Any, fake: FakeFrappe) -> None:
    fake.conf.update({"nile_service_user": "Svc@Example.com", "nile_mcp_user": "MCP@example.com"})
    login = load("nile_auth.login")
    for name in ("svc@example.com", "mcp@example.com"):
        with pytest.raises(login.Refused) as caught:
            login._refuse_if_protected(name, INFO, "authentik")
        assert caught.value.outcome == "refused_protected"


def test_an_unset_mcp_user_protects_nobody(load: Any, fake: FakeFrappe) -> None:
    fake.conf["nile_service_user"] = "svc@example.com"
    login = load("nile_auth.login")
    login._refuse_if_protected("kim@example.com", {"sub": "1"}, "authentik")


def test_a_system_manager_is_protected(load: Any, fake: FakeFrappe) -> None:
    fake.has_role.add(("boss@example.com", "System Manager"))
    login = load("nile_auth.login")
    with pytest.raises(login.Refused) as caught:
        login._refuse_if_protected("boss@example.com", INFO, "authentik")
    assert caught.value.outcome == "refused_protected"


def test_a_stored_social_id_that_differs_is_refused_and_one_that_matches_passes(
    load: Any, fake: FakeFrappe
) -> None:
    fake.social[("kim@example.com", "authentik")] = "sub-1"
    login = load("nile_auth.login")
    login._refuse_if_protected("kim@example.com", {"sub": "sub-1"}, "authentik")
    with pytest.raises(login.Refused) as caught:
        login._refuse_if_protected("kim@example.com", {"sub": "sub-2"}, "authentik")
    assert caught.value.outcome == "refused_identity"


def test_a_user_with_no_stored_social_id_passes(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login._refuse_if_protected("new@example.com", {"sub": "x"}, "authentik")


# --- roles (spec 0006 AC-2, AC-5) ---


def test_roles_follow_the_decision_and_nile_groups_is_written(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    user = FakeUser("a@example.com", ("Moderator", "Desk User", "LMS Student", "Sales User"))
    out = login.Outcome()
    login._reconcile_roles(user, _decision(**LIVE), out)
    assert {r.role for r in user.roles} == {"LMS Student", "Sales User"}
    assert out.roles_removed == ["Desk User", "Moderator"]
    assert out.roles_added == []
    assert user.nile_groups == "Nile Certified Associate"
    assert user.saved == 1


def test_an_admin_gets_all_three_admin_roles(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    user = FakeUser("a@example.com")
    out = login.Outcome()
    decision = _decision(
        kind="admin_only",
        matched_groups=("hol-admins",),
        is_admin=True,
        desired_roles=ADMIN_ROLES,
    )
    login._reconcile_roles(user, decision, out)
    assert {r.role for r in user.roles} == set(ADMIN_ROLES)
    assert out.roles_added == sorted(ADMIN_ROLES)


def test_drop_student_removes_the_role_lms_added(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    user = FakeUser("a@example.com", ("LMS Student",))
    out = login.Outcome()
    login._reconcile_roles(user, _decision(kind="admin_only", desired_roles=ADMIN_ROLES), out, True)
    assert "LMS Student" not in {r.role for r in user.roles}
    assert out.roles_removed == ["LMS Student"]


# --- one course only (spec 0009 AC-1, AC-2, AC-3, AC-9) ---


def test_a_new_live_learner_gets_one_enrollment_and_a_student_user(
    load: Any, fake: FakeFrappe
) -> None:
    login = load("nile_auth.login")
    out = login.provision(INFO, _decision(**LIVE), "Kim@Example.com", ["nca", "adv"])
    assert out.user == "kim@example.com"
    assert out.created and out.enrollments_created == 1
    assert [(e["member"], e["course"]) for e in fake.enrollments] == [("kim@example.com", "nca")]
    assert fake.users["kim@example.com"].user_type == "Website User"


def test_a_second_login_does_not_enroll_again(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login.provision(INFO, _decision(**LIVE), "kim@example.com", ["nca", "adv"])
    out = login.provision(INFO, _decision(**LIVE), "kim@example.com", ["nca", "adv"])
    assert out.enrollments_created == 0 and not out.created
    assert len(fake.enrollments) == 1


def test_moving_to_another_course_removes_the_old_enrollment(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login.provision(INFO, _decision(**LIVE), "kim@example.com", ["nca", "adv"])
    moved = {**LIVE, "course": "adv", "course_group": "Advanced Lab"}
    out = login.provision(INFO, _decision(**moved), "kim@example.com", ["nca", "adv"])
    assert out.enrollments_removed == ["nca"]
    assert [e["course"] for e in fake.enrollments] == ["adv"]


def test_results_mode_removes_every_managed_enrollment(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login.provision(INFO, _decision(**LIVE), "kim@example.com", ["nca"])
    out = login.provision(INFO, _decision(kind="results"), "kim@example.com", ["nca"])
    assert out.enrollments_removed == ["nca"] and out.enrollments_created == 0
    assert fake.enrollments == []


def test_an_enrollment_in_an_unmanaged_course_is_left_alone(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login.provision(INFO, _decision(**LIVE), "kim@example.com", ["nca"])
    fake.enrollments.append({"name": "hand", "member": "kim@example.com", "course": "by-hand"})
    login.provision(INFO, _decision(kind="results"), "kim@example.com", ["nca"])
    assert [e["name"] for e in fake.enrollments] == ["hand"]


def test_a_new_admin_with_no_course_group_is_not_a_student_and_not_enrolled(
    load: Any, fake: FakeFrappe
) -> None:
    login = load("nile_auth.login")
    decision = _decision(
        kind="admin_only", matched_groups=("hol-admins",), is_admin=True, desired_roles=ADMIN_ROLES
    )
    out = login.provision(INFO, decision, "kim@example.com", ["nca"])
    roles = {r.role for r in fake.users["kim@example.com"].roles}
    assert roles == set(ADMIN_ROLES)
    assert out.enrollments_created == 0 and fake.enrollments == []


# --- deadlock retry (spec 0009 AC-9) ---


def test_a_deadlock_victim_is_retried_and_the_session_goes_back_to_guest(
    load: Any, fake: FakeFrappe, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = load("nile_auth.login")
    monkeypatch.setattr(login.time, "sleep", lambda _s: None)
    calls = []

    def flaky(info: dict, decision: Any, email: str, managed: list) -> str:
        calls.append(1)
        if len(calls) < 3:
            raise fake.QueryDeadlockError
        return "done"

    monkeypatch.setattr(login, "provision", flaky)
    assert login._provision_retrying(INFO, _decision(**LIVE), "kim@example.com", []) == "done"
    assert len(calls) == 3 and fake.rollbacks == 2
    assert fake.session_users[-1] == "Guest"


def test_a_deadlock_that_never_clears_is_raised_after_four_tries(
    load: Any, fake: FakeFrappe, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = load("nile_auth.login")
    monkeypatch.setattr(login.time, "sleep", lambda _s: None)
    calls = []

    def always(*_a: Any) -> None:
        calls.append(1)
        raise fake.QueryDeadlockError

    monkeypatch.setattr(login, "provision", always)
    with pytest.raises(fake.QueryDeadlockError):
        login._provision_retrying(INFO, _decision(**LIVE), "kim@example.com", [])
    assert len(calls) == login.DEADLOCK_TRIES
    assert fake.session_users[-1] == "Guest"


# --- the log line (spec 0006 AC-12, spec 0009 AC-15) ---


def test_the_ok_line_is_info_and_names_email_outcome_mode_and_group(
    load: Any, fake: FakeFrappe
) -> None:
    login = load("nile_auth.login")
    seen = {"email": "kim@example.com", "mode": "live", "group": "Advanced Lab", "lock": ""}
    login._log("ok", seen)
    level, line = fake.logs[0]
    assert level == "info"
    assert line == (
        'login email="kim@example.com" outcome=ok mode=live course_group="Advanced Lab"'
    )


@pytest.mark.parametrize(
    ("outcome", "level"),
    [
        ("error", "error"),
        ("setup_fault_claim", "error"),
        ("setup_fault_settings", "error"),
        ("setup_fault_course", "error"),
        ("refused_no_group", "warning"),
        ("refused_protected", "warning"),
        ("disabled", "warning"),
    ],
)
def test_faults_log_as_errors_and_refusals_as_warnings(
    load: Any, fake: FakeFrappe, outcome: str, level: str
) -> None:
    login = load("nile_auth.login")
    login._log(outcome, {"email": "none", "mode": "none", "group": "", "lock": ""})
    assert fake.logs[0][0] == level


def test_an_email_with_a_quote_cannot_forge_a_second_field(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    login._log("ok", {"email": 'a" outcome=ok mode=admin', "mode": "none", "group": "", "lock": ""})
    assert '\\" outcome=ok' in fake.logs[0][1]


# --- the callback guard (spec 0006 AC-10) ---


def test_the_callback_does_nothing_for_an_unknown_provider(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    sys.modules["frappe"].request = SimpleNamespace(path="/api/method/x/y/z/ghost")  # type: ignore[attr-defined]
    assert login.custom("c", "s") is None
    assert fake.logs == []


def test_a_login_with_no_remembered_state_is_refused_before_any_code_exchange(
    load: Any, fake: FakeFrappe
) -> None:
    login = load("nile_auth.login")
    sys.modules["frappe"].cache = SimpleNamespace(get_value=lambda _k: None)  # type: ignore[attr-defined]
    with pytest.raises(login.Refused) as caught:
        login._login("authentik", "code", "bogus", {})
    assert caught.value.outcome == "bad_state"
    assert caught.value.page[2] == 417


def test_missing_site_settings_end_in_a_setup_fault(load: Any, fake: FakeFrappe) -> None:
    login = load("nile_auth.login")
    sys.modules["frappe"].cache = SimpleNamespace(get_value=lambda _k: "/lms")  # type: ignore[attr-defined]
    fake.conf["nile_admin_group"] = "hol-admins"  # the service user is missing
    with pytest.raises(login.Refused) as caught:
        login._login("authentik", "code", "state", {})
    assert caught.value.outcome == "setup_fault_settings"
    assert caught.value.page[2] == 500


# --- the one time cleanup (spec 0009 AC-10) ---


def test_cleanup_dry_run_lists_and_removes_nothing(
    load: Any, fake: FakeFrappe, capsys: pytest.CaptureFixture[str]
) -> None:
    cleanup = load("nile_auth.cleanup")
    fake.batches = ["b1"]
    fake.batch_courses = [SimpleNamespace(name="r1", parent="b1", course="nca")]
    rows = cleanup.clear_batch_courses()
    assert len(rows) == 1
    assert fake.deleted == [] and fake.commits == 0
    assert "would remove course nca from batch b1" in capsys.readouterr().out


def test_cleanup_removes_the_rows_and_commits_once(load: Any, fake: FakeFrappe) -> None:
    cleanup = load("nile_auth.cleanup")
    fake.batches = ["b1"]
    fake.batch_courses = [
        SimpleNamespace(name="r1", parent="b1", course="nca"),
        SimpleNamespace(name="r2", parent="b1", course="adv"),
    ]
    cleanup.clear_batch_courses(dry_run=False)
    assert fake.deleted == [("Batch Course", "r1"), ("Batch Course", "r2")]
    assert fake.commits == 1


def test_cleanup_with_no_batches_does_nothing(
    load: Any, fake: FakeFrappe, capsys: pytest.CaptureFixture[str]
) -> None:
    cleanup = load("nile_auth.cleanup")
    assert cleanup.clear_batch_courses(dry_run=False) == []
    assert fake.deleted == []
    assert "0 Batch Course row(s) in 0 batch(es)" in capsys.readouterr().out
