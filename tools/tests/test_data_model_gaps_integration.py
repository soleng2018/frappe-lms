"""Spec 0004 checks that need the sync and the login on the live site (pytest -m integration).

Each test uses the throwaway course of `fx` (random prefix, removed afterwards).
"""

from dataclasses import replace

import pytest
from test_content_sync_edges_integration import Fixture, fx  # noqa: F401  (fx is a fixture)
from test_content_sync_integration import site_is_up, sync  # noqa: F401  (autouse fixture)
from test_data_model_integration import _run_script, _sql

pytestmark = pytest.mark.integration

PASS_MARK_SCRIPT = """
import json, frappe
out = {}
try:
    quiz = frappe.db.get_value("LMS Quiz", {"nile_key": "__P__-q1"}, "name")
    sub = frappe.get_doc({"doctype": "LMS Quiz Submission", "quiz": quiz,
        "member": "__P__-student@example.com", "score": 7, "score_out_of": 10,
        "percentage": 70, "passing_percentage": 80}).insert(ignore_permissions=True)
    frappe.db.set_value("LMS Quiz Submission", sub.name, "percentage", 70)
    frappe.db.set_value("LMS Quiz", quiz, "passing_percentage", 60)
    row = frappe.db.get_value("LMS Quiz Submission", sub.name,
        ["percentage", "passing_percentage"], as_dict=True)
    out["old_attempt"] = [row.percentage, row.passing_percentage]
    out["quiz_now"] = frappe.db.get_value("LMS Quiz", quiz, "passing_percentage")
except Exception as e:
    out["error"] = type(e).__name__ + ": " + str(e)[:300]
finally:
    frappe.db.rollback()
print("RESULT:" + json.dumps(out))
"""

TIMEZONE_SCRIPT = """
import json, frappe
from nile_auth import login
out = {}
try:
    course = frappe.get_all("LMS Course", {"published": 1}, pluck="name", limit=1)[0]
    original = frappe.db.get_single_value("System Settings", "time_zone")
    out["original"] = original
    for i, tz in enumerate(["Asia/Tokyo", "America/New_York"]):
        frappe.db.set_single_value("System Settings", "time_zone", tz)
        frappe.local.system_settings = frappe.get_doc("System Settings")
        batch = login._new_batch("NileWorkshop9" + str(i) + "Admin", [course])
        out[tz] = [batch.timezone, str(batch.start_time), str(batch.end_time),
            batch.published, batch.allow_self_enrollment]
except Exception as e:
    out["error"] = type(e).__name__ + ": " + str(e)[:300]
finally:
    frappe.db.rollback()
print("RESULT:" + json.dumps(out))
"""


def _records(prefix: str) -> list[list[str]]:
    return _sql(
        "select 'c', name, nile_key from `tabLMS Course` "
        f"where nile_key like '{prefix}-%' union all "
        "select 'q', name, nile_key from `tabLMS Quiz` "
        f"where nile_key like '{prefix}-%' union all "
        "select 'l', name, nile_key from `tabCourse Lesson` "
        f"where nile_key like '{prefix}-%' order by 1, 3"
    )


def test_changing_titles_keeps_every_key_and_record_name(fx: Fixture) -> None:  # noqa: F811
    """AC-3: a new title on a course, a quiz and a lesson updates the same records."""
    assert sync(fx.course)[0] == 0
    before = _records(fx.prefix)
    chapter = fx.course.chapters[0]
    lesson = replace(chapter.lessons[0], title="Video renamed")
    quiz = replace(fx.course.quizzes[0], title="Quiz renamed")
    renamed = replace(
        fx.course,
        title="Course renamed",
        quizzes=(quiz, *fx.course.quizzes[1:]),
        chapters=(
            replace(chapter, lessons=(lesson, *chapter.lessons[1:])),
            *fx.course.chapters[1:],
        ),
    )
    code, said = sync(renamed)
    assert code == 0, said
    assert _records(fx.prefix) == before
    titles = _sql(
        f"select (select title from `tabLMS Course` where nile_key = '{fx.prefix}-course'), "
        f"(select title from `tabLMS Quiz` where nile_key = '{fx.prefix}-q1'), "
        f"(select title from `tabCourse Lesson` where nile_key = '{fx.prefix}-video')"
    )
    assert titles == [["Course renamed", "Quiz renamed", "Video renamed"]]


def test_a_quiz_made_again_under_a_new_name_gets_its_lesson_body_rebuilt(
    fx: Fixture,  # noqa: F811
) -> None:
    """AC-10: the macro in the lesson body names the new quiz in the same run."""
    assert sync(fx.course)[0] == 0
    key = f"{fx.prefix}-q1"
    old = _sql(f"select name from `tabLMS Quiz` where nile_key = '{key}'")[0][0]
    # Take the key off the quiz, as if it had been deleted and the sync must make it again.
    _sql(f"update `tabLMS Quiz` set nile_key = NULL, lesson = NULL where name = '{old}'")
    try:
        code, said = sync(fx.course)
        assert code == 0, said
        new = _sql(f"select name from `tabLMS Quiz` where nile_key = '{key}'")[0][0]
        assert new != old
        body = _sql(f"select body from `tabCourse Lesson` where nile_key = '{fx.prefix}-vq'")[0][0]
        assert body == f'{{{{ Quiz("{new}") }}}}'
        again = sync(fx.course)
        assert again[0] == 0 and again[1][-1] == "nothing to change"
        assert any(old in line and "unmanaged" in line for line in again[1])  # the old one is named
    finally:
        _sql(f"delete from `tabLMS Quiz Question` where parent = '{old}'")
        _sql(f"delete from `tabLMS Quiz` where name = '{old}'")


def test_an_old_attempt_keeps_its_own_pass_mark(fx: Fixture) -> None:  # noqa: F811
    """AC-6: pass or fail reads the attempt's own numbers, so a later quiz change cannot flip it."""
    assert sync(fx.course)[0] == 0
    result = _run_script(PASS_MARK_SCRIPT.replace("__P__", fx.prefix))
    assert result["old_attempt"] == [70, 80]
    assert result["quiz_now"] == 60


def test_a_new_batch_has_the_spec_values_and_follows_the_site_timezone() -> None:
    """AC-4: the values of spec 0004, with the timezone read from the site each time."""
    result = _run_script(TIMEZONE_SCRIPT)
    print("site time_zone setting:", result["original"])
    assert result["Asia/Tokyo"] == ["Asia/Tokyo", "00:00:00", "23:59:59", 1, 0]
    assert result["America/New_York"] == ["America/New_York", "00:00:00", "23:59:59", 1, 0]
    now = _sql(
        "select value from tabSingles where doctype = 'System Settings' and field = 'time_zone'"
    )[0][0]
    # The rollback put the site setting back (unset is NULL in the table, empty to Frappe).
    assert (now in ("NULL", "")) == (not result["original"])
