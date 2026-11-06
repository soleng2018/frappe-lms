"""Spec 0014 on the running site: Monthly Report against real LMS records (-m integration).

One live script builds throwaway learners dated in 2026-09 and 2026-10 inside a transaction, runs
the report, exports it as a Moderator, and rolls the transaction back, so the site keeps nothing.
See live_scripts/monthly_report.pyscript.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from test_content_sync_integration import site_is_up  # noqa: F401  (autouse)
from test_data_model_integration import _run_script

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).parent / "live_scripts" / "monthly_report.pyscript"


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    prefix = "mr" + uuid.uuid4().hex[:8]
    return _run_script(SCRIPT.read_text().replace("__P__", prefix))


def test_a_failed_locked_quiz_is_done_but_not_passed(result: dict[str, Any]) -> None:
    row = result["oct"]["failed"]
    assert (row["result"], row["outcome"]) == ("Done", "Not passed")
    assert row["done_date"] == "2026-10-07"  # the third failed attempt
    assert row["completed_this_month"] == "Yes"
    assert row["locked_quizzes"] == "1"
    assert row["lessons_left"] == "2"  # the two quiz lessons never complete


def test_month_activity_counts_only_october(result: dict[str, Any]) -> None:
    row = result["oct"]["failed"]
    assert (row["lessons_completed"], row["quizzes_first_passed"], row["attempts"]) == (
        "2",
        "1",
        "4",
    )
    assert (row["avg_attempt_score"], row["attempt_score_sum"]) == ("66", "265")  # 265 / 4 = 66.25


def test_the_same_learner_is_behind_in_the_month_before(result: dict[str, Any]) -> None:
    assert result["sep"] == {"failed": ["Behind", "None"]}  # others have no record before October


def test_a_certificate_makes_a_learner_done_and_passed(result: dict[str, Any]) -> None:
    row = result["oct"]["certed"]
    assert (row["result"], row["outcome"], row["done_date"]) == ("Done", "Passed", "2026-10-20")
    assert row["certificate_issued"] == "Yes"
    assert result["oct"]["behind"]["result"] == "Behind"


def test_five_totals_are_offered(result: dict[str, Any]) -> None:
    assert result["summary_labels"] == [
        "Done",
        "Behind",
        "Certified this month",
        "Attempts this month",
        "Average attempt score",
    ]


def test_the_current_month_matches_learner_progress(result: dict[str, Any]) -> None:
    assert result["same_rows"] is True
    assert all(all(flags) for flags in result["match"].values())


def test_bad_filters_raise_a_validation_error(result: dict[str, Any]) -> None:
    assert [result[k] for k in ("bad_month", "future", "bad_result")] == ["ValidationError"] * 3


def test_a_student_is_refused_and_a_moderator_gets_rows(result: dict[str, Any]) -> None:
    assert result["student"] == "PermissionError"
    assert result["mod_is_sysmgr"] is False
    assert result["moderator"] == "ran:4"


def test_the_moderator_can_export_csv_and_formulas_are_escaped(result: dict[str, Any]) -> None:
    assert "csv_error" not in result
    assert (
        "Course ID" not in result["csv_header"] and "Attempt score sum" not in result["csv_header"]
    )
    assert result["csv_cells_with_formula_start"] == []
    assert result["csv_has_evil"] == ["'=1+1"]


def test_nothing_is_left_behind(result: dict[str, Any]) -> None:
    assert result["leftover"] == 0
