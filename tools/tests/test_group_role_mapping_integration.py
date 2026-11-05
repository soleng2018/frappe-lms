"""Spec 0009 on the running site: login, roles, course enrollments (pytest -m integration).

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


def test_a_first_login_makes_a_student_in_one_course_with_no_batch(run: dict[str, Any]) -> None:
    """AC-1, AC-11."""
    assert run["first"]["signed_in"]
    s = run["student"]
    assert s["user_type"] == "Website User"
    assert s["state"]["roles"] == ["LMS Student"]
    assert s["state"]["enrolled"] == [run["names"][0]]
    assert s["state"]["groups"].startswith("Nile IT A ")
    assert s["from_batch"] in (None, "")
    assert run["first"]["location"].endswith(f"/lms/courses/{run['names'][0]}")
    assert run["own_lesson"]


def test_a_second_login_changes_nothing(run: dict[str, Any]) -> None:
    """AC-9."""
    assert run["repeat_same"]


def test_a_move_removes_the_old_enrollment_and_keeps_progress(run: dict[str, Any]) -> None:
    """AC-1, AC-3."""
    assert run["moved_state"]["enrolled"] == [run["names"][1]]
    assert run["progress_kept"] == 1


def test_a_learner_in_one_course_cannot_reach_the_other(run: dict[str, Any]) -> None:
    """AC-13: course, lesson, chapter, catalog, quiz and Program reads, and self enrollment."""
    assert run["isolation"] == {
        "own_access": True,
        "other_access": False,
        "other_lesson": False,
        "other_chapter": False,
    }
    assert run["self_enroll"] != "allowed"
    # The catalog, the course row, a quiz of A, and a Program that holds A (read through LMS code
    # with the throwaway learner as the session user).
    assert run["catalog"]["list_sees_a"] is False
    assert run["catalog"]["api"] == {"sees_a": False, "sees_b": False}
    assert run["catalog"]["row_a"] is False
    assert run["quiz_a"] == {"listed": False, "read": False}
    assert run["program"]["course_access"] is False
    assert run["program"]["lesson_access"] is False
    assert run["program"]["self_enroll"] != "allowed"


def test_results_mode_closes_lessons_and_keeps_everything_else(run: dict[str, Any]) -> None:
    """AC-3, AC-11."""
    assert run["results_state"] == {
        "roles": ["LMS Student"],
        "enrolled": [],
        "groups": "",
        "enabled": 1,
    }
    assert run["results_progress_kept"] == 1
    assert run["results"]["location"].endswith("/lms/user/nile_test")


def test_a_returning_learner_is_enrolled_again_at_the_rebuilt_progress(
    run: dict[str, Any],
) -> None:
    """AC-1, AC-3."""
    assert run["back_live_progress"] == 100


def test_deep_links_win_and_default_targets_count_as_absent(run: dict[str, Any]) -> None:
    """AC-11."""
    assert run["deep"].endswith("/lms/courses/other/learn/1.1")
    assert all(x.endswith(f"/lms/courses/{run['names'][0]}") for x in run["default_targets"])


def test_admins(run: dict[str, Any]) -> None:
    """AC-2, AC-11."""
    admin_roles = ["Course Creator", "Desk User", "Moderator"]
    assert run["admin"]["state"]["roles"] == admin_roles
    assert run["admin"]["state"]["enrolled"] == []
    assert run["admin"]["type"] == "System User"
    assert run["admin"]["student_role"] is False
    assert run["admin_live"]["roles"] == sorted([*admin_roles, "LMS Student"])
    assert run["admin_live"]["enrolled"] == [run["names"][0]]
    assert run["admin_live"]["groups"].endswith("\nhol-admins")
    assert run["admin_demoted"]["state"]["roles"] == ["LMS Student"]
    assert run["admin_demoted"]["type"] == "Website User"
    assert run["admin_results_state"]["enrolled"] == []
    for name in ("admin_live_location", "admin_results_location"):
        assert run[name].endswith("/lms")


def test_no_course_group_from_a_stranger_is_refused(run: dict[str, Any]) -> None:
    """AC-4, AC-5."""
    for name in ("nogroup_new", "empty_list_new", "nonlearner"):
        assert run[name] == {"status": 403, "signed_in": False, "location": None}
    assert run["nogroup_new_user"] is False
    assert run["nonlearner_state"] == {"roles": [], "enrolled": [], "groups": "", "enabled": 1}
    assert run["near_miss"] == [403, 403, 403]
    assert run["near_miss_user"] is False


def test_two_course_groups_are_refused_for_everyone_and_change_nothing(
    run: dict[str, Any],
) -> None:
    """AC-6."""
    assert [r["status"] for r in run["two"]] == [403, 403, 403]
    assert not any(r["signed_in"] for r in run["two"])
    assert run["two_unchanged"]
    assert (run["two_new"], run["two_new_user"]) == (403, False)


def test_faults_change_nothing(run: dict[str, Any]) -> None:
    """AC-7."""
    for name in ("no_claim", "bad_claim", "empty_admin_setting", "duplicate_title"):
        assert run[name] == 500, name
    assert run["faults_unchanged"]


def test_protected_accounts_and_identity_changes_are_refused(run: dict[str, Any]) -> None:
    """AC-8."""
    for name in ("administrator", "service", "mcp", "system_manager", "identity", "no_email"):
        assert run[name] == 403, name
    assert run["sm_unchanged"]
    assert run["same_sub_ok"]
    assert run["disabled_same"]


def test_a_bad_state_or_a_fault_leaves_nothing_behind(run: dict[str, Any]) -> None:
    """AC-9."""
    assert (run["bad_state"], run["bad_state_user"]) == (417, False)
    assert run["fault"] == {"status": 500, "signed_in": False, "location": None}
    assert run["fault_user"] is False


def test_no_batch_mail_or_job_is_made(run: dict[str, Any]) -> None:
    """AC-10."""
    assert run["batches_same"]
    assert run["mail_queued"] == 0
    assert run["jobs_queued"] == 0


def test_every_login_writes_one_line_without_a_secret(run: dict[str, Any]) -> None:
    """AC-15."""
    text = "\n".join(run["log_tail"])
    assert "outcome=ok mode=live" in text
    assert "outcome=ok mode=results" in text
    assert "outcome=refused_two_courses" in text
    assert "outcome=setup_fault_course" in text
    assert "CODE-SECRET" not in text
    assert "STATE-" not in text


def _race(emails: list[str], premade: bool, tag: str, action: str) -> dict[str, Any]:
    return _run_script(
        _script(
            "race", ACTION=action, TAG=tag, EMAILS=",".join(emails), PREMADE="1" if premade else "0"
        )
    )


@pytest.mark.parametrize("premade", [True, False])
def test_two_logins_of_one_person_at_once(key: None, premade: bool) -> None:
    """AC-9: two real processes, real commits. An existing person ends in one state with no
    error. Two first logins may collide on the User insert, and then nothing is left half done."""
    tag = uuid.uuid4().hex[:6]
    email = f"nile-race-{tag}@example.com"
    _race([email], premade, tag, "make")
    start = str(time.time() + 25)
    jobs = [_script("concurrent", EMAIL=email, TITLE=f"Nile Race {tag}", START=start)] * 2
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(_run_script, jobs))
        left = _race([email], premade, tag, "check")
        assert left["enrollments"][email] == 1
        assert left["roles"][email] == 1
        signed = [r.get("signed_in") for r in results]
        if premade:
            assert signed == [True, True], results
        else:
            assert any(signed), results
    finally:
        assert _race([email], premade, tag, "drop")["left"] == 0


def test_two_first_logins_of_different_people_at_once(key: None) -> None:
    """AC-9: two new learners whose emails sort side by side must both get in. A locking read of
    a missing User row takes a gap lock, and the two User inserts then deadlock."""
    tag = uuid.uuid4().hex[:6]
    emails = [f"nile-race-{tag}-a@example.com", f"nile-race-{tag}-b@example.com"]
    _race(emails, False, tag, "make")
    start = str(time.time() + 25)
    jobs = [_script("concurrent", EMAIL=e, TITLE=f"Nile Race {tag}", START=start) for e in emails]
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(_run_script, jobs))
        left = _race(emails, False, tag, "check")
        assert [r.get("signed_in") for r in results] == [True, True], results
        assert [left["enrollments"][e] for e in emails] == [1, 1]
        assert [left["roles"][e] for e in emails] == [1, 1]
    finally:
        assert _race(emails, False, tag, "drop")["left"] == 0
