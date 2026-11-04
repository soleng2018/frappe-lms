"""Spec 0006 on the running site: login, roles, batches, enrollments (pytest -m integration).

The IDP call and Frappe's last login step are replaced inside `bench console`; everything else is
the real code, and the scenario run rolls back. The throwaway Social Login Key is made and deleted
here. The concurrent test commits on purpose and cleans up after itself.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_data_model_integration import _exec, _run_script, _site, site_is_up  # noqa: F401

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).parent / "live_scripts"
ROUTE = "/api/method/frappe.integrations.oauth2_logins.custom/nileprobe"


def _script(name: str, **values: str) -> str:
    text = (SCRIPTS / f"group_role_{name}.pyscript").read_text()
    for key, value in values.items():
        text = text.replace(f"__{key}__", value)
    return text


@pytest.fixture(scope="module")
def key() -> Iterator[None]:
    assert _run_script(_script("key", ACTION="make"))["exists"]
    try:
        yield
    finally:
        assert not _run_script(_script("key", ACTION="drop"))["exists"]


@pytest.fixture(scope="module")
def run(key: None) -> dict[str, Any]:
    return _run_script(_script("scenarios"))


def test_the_route_is_ours_and_checks_state_before_anything_else(key: None) -> None:
    """AC-10: a bad state gets 417 before any code exchange (the IDP is unreachable here)."""
    url = f"http://127.0.0.1:8000{ROUTE}?code=abc&state=bogus"
    done = _exec(
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-H", f"Host: {_site()}", url
    )
    assert done.stdout == "417", done.stdout + done.stderr


def test_a_first_login_makes_a_student_with_batch_and_enrollments(run: dict[str, Any]) -> None:
    """AC-1."""
    assert run["first"]["signed_in"]
    s = run["student"]
    assert s["user_type"] == "Website User"
    assert s["managed"] == ["LMS Student"]
    assert s["groups"] == "NileWorkshop9103Admin"
    assert (s["batch"], s["batch_enrol"]) == (1, 1)
    assert s["enrolments"] == run["published"]
    assert s["batch_courses"] == 1
    assert s["from_batch"] == "nileworkshop9103admin"
    assert s["mail_flag"] == 1


def test_no_confirmation_mail_is_queued(run: dict[str, Any]) -> None:
    """AC-1: the batch enrollment sends nothing and the batch notification is switched off."""
    assert run["emails_queued"] == run["emails_after"] == 0
    assert not run["lms_notify_setting"]


def test_frappes_own_step_keeps_the_roles_and_links_the_subject(run: dict[str, Any]) -> None:
    after = run["after_frappe_student"]
    assert after["managed"] == ["LMS Student"]
    assert after["type"] == "Website User"
    assert after["sub"].startswith("sub-")


def test_a_second_login_changes_nothing(run: dict[str, Any]) -> None:
    """AC-6."""
    assert run["repeat_same"]


def test_a_move_between_groups_keeps_old_records(run: dict[str, Any]) -> None:
    """AC-5: nile_groups follows the groups (sorted by number), old batch enrollments stay."""
    moved = run["moved"]
    assert moved["groups"] == "NileWorkshop9101Admin\nNileWorkshop9102Admin"
    assert moved["batch_enrol"] == 3
    assert moved["managed"] == ["LMS Student"]


def test_a_course_published_later_arrives_at_the_next_login(run: dict[str, Any]) -> None:
    """AC-11."""
    assert run["late"]["enrolled"] == 1
    assert run["late"]["batch_rows"] == 2  # the student's two current batches


def test_admins(run: dict[str, Any]) -> None:
    """AC-2, AC-5: admin roles, System User by derivation, no enrollments without a group."""
    assert run["admin"] == {
        "user_type": "System User",
        "managed": ["Course Creator", "Desk User", "Moderator"],
        "groups": "hol-admins",
        "batch_enrol": 0,
        "enrolments": 0,
    }
    both = run["admin_both"]
    assert both["managed"] == ["Course Creator", "Desk User", "LMS Student", "Moderator"]
    assert both["groups"] == "NileWorkshop9101Admin\nhol-admins"
    assert both["batch_enrol"] == 1
    assert run["admin_demoted"] == {"managed": ["LMS Student"], "user_type": "Website User"}


def test_a_user_in_no_workshop_group_is_refused_and_loses_only_the_managed_roles(
    run: dict[str, Any],
) -> None:
    """AC-3."""
    for name in ("nogroup_new", "nogroup_existing", "empty_list"):
        assert run[name] == {"status": 403, "signed_in": False}
    assert run["nogroup_new_user"] is False
    after = run["after_strip"]
    assert after["managed"] == []
    assert after["enabled"] == 1
    assert after["enrolments_kept"]
    assert after["batch_enrol_kept"] == 3


def test_a_missing_or_bad_groups_value_changes_nothing(run: dict[str, Any]) -> None:
    """AC-7."""
    for name in ("no_claim", "bad_claim"):
        assert run[name] == {"status": 500, "signed_in": False}
    assert run["admin_unchanged"]


def test_protected_accounts_and_identity_changes_are_refused(run: dict[str, Any]) -> None:
    """AC-8, AC-12 (no email)."""
    for name in (
        "administrator",
        "service",
        "mcp",
        "mcp_upper",
        "system_manager",
        "system_manager_user",
        "identity",
        "no_email",
    ):
        assert run[name] == {"status": 403, "signed_in": False}, name
    assert run["sm_unchanged"]
    assert run["mcp_unchanged"]
    assert run["mcp_blank_setting"]["signed_in"]
    assert run["admin_user_ok"]
    assert run["same_sub_ok"]


def test_a_disabled_user_stays_disabled_and_gets_nothing(run: dict[str, Any]) -> None:
    """AC-9."""
    assert run["disabled"] == {"enabled": 0, "managed": [], "batch_enrol": 1}


def test_a_bad_state_or_a_fault_leaves_nothing_behind(run: dict[str, Any]) -> None:
    """AC-10."""
    assert run["bad_state"] == {"status": 417, "signed_in": False}
    assert run["bad_state_user"] is False
    assert run["fault"] == {"status": 500, "signed_in": False}
    assert run["fault_user"] is False
    assert run["fault_batch_enrol"] == 0


def test_two_first_logins_at_once_leave_one_batch(key: None) -> None:
    """AC-6: the locking read and savepoint, with two real processes and real commits."""
    number = str(9500 + uuid.uuid4().int % 400)
    tag = uuid.uuid4().hex[:6]
    a, b = f"nile-race-a-{tag}@example.com", f"nile-race-b-{tag}@example.com"
    start = str(time.time() + 25)
    jobs = [_script("concurrent", N=number, EMAIL=e, START=start) for e in (a, b)]
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(_run_script, jobs))
        assert sum(r["batches_created"] for r in results) == 1
    finally:
        left = _run_script(_script("cleanup", N=number, A=a, B=b))
        assert left["left"] == 0
