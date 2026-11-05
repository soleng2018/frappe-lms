"""Spec 0013 on the running site: both reports against real LMS records (-m integration).

One live script builds throwaway learners inside a transaction, runs both reports, and rolls the
transaction back, so the site keeps nothing. See live_scripts/progress_reports.pyscript.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from test_content_sync_integration import site_is_up  # noqa: F401  (autouse)
from test_data_model_integration import _run_script

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).parent / "live_scripts" / "progress_reports.pyscript"


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    prefix = "pg" + uuid.uuid4().hex[:8]
    return _run_script(SCRIPT.read_text().replace("__P__", prefix))


def test_the_site_has_a_managed_course_with_two_quizzes(result: dict[str, Any]) -> None:
    assert result["lessons"] >= 1
    assert result["quizzes"] >= 2


def test_status_enrolled_and_exclusions(result: dict[str, Any]) -> None:
    lp = result["lp"]
    assert set(lp) == {"ready", "ended", "fresh", "off"}  # the service user is excluded
    assert lp["ready"]["status"] == "Ready for certificate"
    assert lp["ready"]["progress"] == "100"
    assert lp["ended"]["status"] == "Certified"
    assert lp["ended"]["enrolled"] == "No"
    assert lp["fresh"]["status"] == "Not started"
    assert lp["fresh"]["enrolled"] == "Yes"
    assert lp["off"]["enabled"] == "No"


def test_outline_ignores_a_lesson_that_is_not_in_it(result: dict[str, Any]) -> None:
    assert result["lp"]["ended"]["lessons_done"] == "1"


def test_newest_certificate_is_shown(result: dict[str, Any]) -> None:
    ended = result["lp"]["ended"]
    assert ended["issue_date"] == "2026-03-01"
    assert ended["published"] == "Yes"
    assert ended["certificate"] != "None"


def test_quiz_states_passed_and_locked(result: dict[str, Any]) -> None:
    assert result["qs_ready"] == [[True, "Passed", 1, "85"], [False, "Locked", 3, "60"]]
    assert result["locked_filter"] == [True]


def test_enrolled_only_hides_the_ended_slot(result: dict[str, Any]) -> None:
    assert result["enrolled_only"] == ["fresh", "ready"]


def test_pass_mark_is_read_from_the_quiz_now(result: dict[str, Any]) -> None:
    assert result["raised_mark"] == ["In progress"]
    assert result["raised_quizzes_passed"] == [0]


def test_a_student_gets_permission_error_from_both(result: dict[str, Any]) -> None:
    assert result["student Learner Progress"] == "PermissionError"
    assert result["student Quiz Scores"] == "PermissionError"


def test_nothing_is_left_behind(result: dict[str, Any]) -> None:
    assert result["leftover"] == 0
