"""Spec 0004 on the running site: fields, roles, attempts, permissions (pytest -m integration)."""

import base64
import json
import shutil
import subprocess
from pathlib import Path

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


def test_moderator_delete_permission_is_one_row() -> None:
    rows = _sql(
        "select role, `delete` from `tabCustom DocPerm` where parent = 'LMS Quiz Submission' "
        "and name like 'nile-%'"
    )
    assert rows == [["Moderator", "1"]]


def test_attempts_are_limited_and_only_a_moderator_may_reset_them() -> None:
    encoded = base64.b64encode(BEHAVIOUR_SCRIPT.encode()).decode()
    stdin = f"exec(__import__('base64').b64decode('{encoded}').decode(), {{}})\n"
    done = _exec("bench", "--site", _site(), "console", stdin=stdin)
    lines = [x for x in done.stdout.splitlines() if "RESULT:" in x]
    assert lines, done.stdout[-500:] + done.stderr[-500:]
    result = json.loads(lines[-1].split("RESULT:", 1)[1])
    assert "error" not in result, result
    assert result["percentages"] == [70, 70, 70]  # 70 is under the pass mark of 80
    assert result["fourth"] == "MaximumAttemptsExceededError"
    assert result["moderator_read"] is True
    assert result["moderator_delete"] is True
    assert result["student_delete"] is False
    left = _sql("select count(*) from tabUser where name like 'nile-it-%'")
    assert left == [["0"]]  # the rollback left nothing behind
