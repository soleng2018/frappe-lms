"""Spec 0004 on the running site: fields, roles, attempts, permissions (pytest -m integration)."""

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nile_tools import config

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    str(REPO),
    "-f",
    str(REPO / "deploy/compose.yaml"),
    "--env-file",
    str(REPO / "deploy/versions.env"),
    "--env-file",
    str(REPO / ".env"),
]

# Runs inside `bench console` and rolls everything back, so the site keeps nothing. Prints one
# RESULT line of JSON.
BEHAVIOUR_SCRIPT = """
import json
import frappe
from frappe.utils import random_string

out = {}
try:
    sfx = random_string(6)

    def make_user(roles, kind):
        user = frappe.get_doc({
            "doctype": "User", "email": f"nile-it-{kind}-{sfx}@example.com", "first_name": kind,
            "user_type": "System User" if kind == "admin" else "Website User",
            "send_welcome_email": 0,
        })
        for role in roles:
            user.append("roles", {"role": role})
        return user.insert(ignore_permissions=True).name

    student = make_user(["LMS Student"], "student")
    admin = make_user(["Moderator", "Course Creator"], "admin")
    quiz = frappe.get_doc({
        "doctype": "LMS Quiz", "title": "nile it quiz", "passing_percentage": 80,
        "max_attempts": 3, "total_marks": 10,
    }).insert(ignore_permissions=True)

    def attempt(score):
        return frappe.get_doc({
            "doctype": "LMS Quiz Submission", "quiz": quiz.name, "member": student,
            "score": score, "score_out_of": 10, "percentage": score * 10, "passing_percentage": 80,
        }).insert(ignore_permissions=True)

    subs = [attempt(7) for _ in range(3)]
    out["percentages"] = [s.percentage for s in subs]
    try:
        attempt(7)
        out["fourth"] = "allowed"
    except Exception as e:
        out["fourth"] = type(e).__name__
    check = frappe.has_permission
    out["moderator_delete"] = check("LMS Quiz Submission", "delete", doc=subs[0], user=admin)
    out["moderator_read"] = check("LMS Quiz Submission", "read", doc=subs[0], user=admin)
    out["student_delete"] = check("LMS Quiz Submission", "delete", doc=subs[0], user=student)
except Exception as e:
    out["error"] = repr(e)
finally:
    frappe.db.rollback()
print("RESULT:" + json.dumps(out, default=str))
"""


LIVE_SCRIPTS = Path(__file__).parent / "live_scripts"


def _run_script(source: str) -> dict[str, Any]:
    encoded = base64.b64encode(source.encode()).decode()
    stdin = f"exec(__import__('base64').b64decode('{encoded}').decode(), {{}})\n"
    done = _exec("bench", "--site", _site(), "console", stdin=stdin)
    lines = [x for x in done.stdout.splitlines() if "RESULT:" in x]
    assert lines, done.stdout[-500:] + done.stderr[-500:]
    result: dict[str, Any] = json.loads(lines[-1].split("RESULT:", 1)[1])
    assert "error" not in result, result["error"]
    return result


def _site() -> str:
    return config.load_env(REPO).values["LMS_HOSTNAME"]


def _exec(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMPOSE, "exec", "-T", "backend", *args],
        check=False,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=300,
    )


def _sql(query: str) -> list[list[str]]:
    done = _exec("bench", "--site", _site(), "mariadb", "-N", "-B", "-e", query)
    assert done.returncode == 0, done.stderr
    return [line.split("\t") for line in done.stdout.splitlines() if line]


@pytest.fixture(scope="module", autouse=True)
def site_is_up() -> None:
    if shutil.which("docker") is None or not (REPO / ".env").exists():
        pytest.skip("needs docker and a .env")
    ps = subprocess.run(
        [*COMPOSE, "ps", "--status", "running", "--services"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if "backend" not in ps.stdout.split():
        pytest.skip("the stack is not running (make up)")


def test_custom_fields_exist_with_unique_indexes() -> None:
    rows = _sql(
        "select table_name, column_name, non_unique from information_schema.statistics "
        "where table_schema = database() and column_name in ('nile_key', 'nile_group')"
    )
    found = {(r[0], r[1]): r[2] for r in rows}
    wanted = {
        (f"tab{dt}", "nile_key")
        for dt in ("LMS Course", "Course Chapter", "Course Lesson", "LMS Quiz", "LMS Question")
    } | {("tabLMS Batch", "nile_group")}
    assert set(found) == wanted
    assert set(found.values()) == {"0"}


def test_the_roles_named_in_the_spec_exist() -> None:
    names = {r[0] for r in _sql("select name from tabRole")}
    assert {
        "LMS Student",
        "Moderator",
        "Course Creator",
        "Batch Evaluator",
        "System Manager",
    } <= names


@pytest.mark.parametrize(
    ("doctype", "columns"),
    [
        ("Course Lesson", {"chapter", "title", "body", "youtube", "quiz_id", "course"}),
        ("LMS Quiz", {"title", "course", "lesson", "passing_percentage", "max_attempts"}),
        ("LMS Batch", {"title", "start_date", "end_date", "start_time", "end_time", "timezone"}),
    ],
)
def test_the_fields_the_spec_names_exist(doctype: str, columns: set[str]) -> None:
    have = {r[0] for r in _sql(f"show columns from `tab{doctype}`")}
    assert columns <= have


def test_quiz_submission_permissions_keep_the_lms_rows_and_add_moderator_delete() -> None:
    """One Custom DocPerm row makes Frappe drop the standard rows, so all five must be here."""
    rows = _sql(
        "select role, `read`, `write`, `delete`, if_owner from `tabCustom DocPerm` "
        "where parent = 'LMS Quiz Submission' and name like 'nile-%' order by role"
    )
    assert rows == [
        ["Batch Evaluator", "1", "0", "0", "0"],
        ["Course Creator", "1", "0", "0", "0"],
        ["LMS Student", "1", "0", "0", "1"],
        ["Moderator", "1", "0", "1", "0"],
        ["System Manager", "1", "1", "1", "0"],
    ]
    every_row = _sql(
        "select count(*) from `tabCustom DocPerm` where parent = 'LMS Quiz Submission'"
    )
    assert every_row == [["5"]]  # nothing else widens or narrows the access


def test_attempts_are_limited_and_only_a_moderator_may_reset_them() -> None:
    result = _run_script(BEHAVIOUR_SCRIPT)
    assert result["percentages"] == [70, 70, 70]  # 70 is under the pass mark of 80
    assert result["fourth"] == "MaximumAttemptsExceededError"
    assert result["moderator_read"] is True
    assert result["moderator_delete"] is True
    assert result["student_delete"] is False
    left = _sql("select count(*) from tabUser where name like 'nile-it-%'")
    assert left == [["0"]]  # the rollback left nothing behind


@pytest.fixture(scope="module")
def lms() -> dict[str, Any]:
    """One rolled back run of the student, quiz, certificate and batch flows."""
    result = _run_script((LIVE_SCRIPTS / "lms_behaviour.pyscript").read_text())
    assert _sql("select count(*) from tabUser where name like 'nile-it-%'") == [["0"]]
    return result


def test_a_quiz_lesson_with_only_quiz_id_can_be_skipped(lms: dict[str, Any]) -> None:
    """LMS reads the quiz from a macro in the body, so `quiz_id` alone does not gate the lesson.

    If this starts failing, LMS changed: re check the sync's quiz lesson body in spec 0004.
    """
    assert lms["A_quiz_lesson_completes_without_passing"] == 1
    assert lms["A_mark_lesson_progress_quiz_lesson"] == 1


def test_a_quiz_lesson_with_the_body_macro_needs_a_pass(lms: dict[str, Any]) -> None:
    assert lms["B_quiz_lesson_before_attempt"] == 0
    assert lms["B_failed_submit"]["pass"] is False
    assert lms["B_quiz_lesson_after_failed_attempt"] == 0
    assert lms["B_passing_submit"]["pass"] is True
    assert (
        lms["B_lesson_complete_right_after_submit"] == 1
    )  # LMS completes it on the passing submit


def test_video_and_lab_lessons_complete_when_marked(lms: dict[str, Any]) -> None:
    assert lms["B_video_completes_on_mark"] == 1
    assert lms["B_lab_completes_on_mark"] == 1


def test_certificate_needs_every_quiz_passed(lms: dict[str, Any]) -> None:
    assert "not completed the course" in lms["B_certificate_refused_at_zero"]
    assert lms["B_progress_before_pass"] < 100
    assert "not completed the course" in lms["B_certificate_refused_before_pass"]
    assert lms["B_progress_after_pass"] == 100
    assert lms["B_certificate_issued"] == {"template": "Certificate"}
    assert lms["B_certificate_row"]["published"] == 0


def test_a_student_sees_only_their_own_records(lms: dict[str, Any]) -> None:
    assert len(lms["AC7_s2_sees_enrollments_of"]) == 1
    assert lms["AC7_s2_sees_progress_of"] == []
    assert lms["AC7_s2_sees_certificates_of"] == []
    assert lms["AC7_s2_reads_s1_certificate"] is False
    assert lms["AC7_s1_reads_own_certificate"] is True
    assert lms["AC7_s2_reads_own_submission"] is True
    assert lms["AC7_s2_reads_s1_submission"] is False
    assert len(lms["AC7_s2_lists_submissions_of"]) == 1  # only their own member value


def test_batch_with_the_spec_values_enrolls_members_in_its_courses(lms: dict[str, Any]) -> None:
    assert lms["batch_created_with_spec_values"] is True
    assert lms["batch_enrollment_as_admin_user"] is True
    assert lms["batch_enrollment_creates_course_enrollment"] is True
    assert "UniqueValidationError" in lms["duplicate_nile_group_refused"]


def test_a_course_added_to_a_batch_later_does_not_enroll_existing_members(
    lms: dict[str, Any],
) -> None:
    assert lms["course_added_to_batch_enrolls_existing_members"] is False


def test_nile_key_is_unique_but_records_without_one_are_allowed(lms: dict[str, Any]) -> None:
    assert "UniqueValidationError" in lms["repeated_nile_key_refused"]
    assert lms["many_records_without_key_allowed"] == "ok"
