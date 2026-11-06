"""Spec 0013 AC-7, AC-9: run the real report scripts in Node, `frappe` stubbed (no browser)."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPORTS = Path(__file__).resolve().parents[2] / "apps/nile_auth/nile_auth/nile_auth/report"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = """
const fs = require("fs"), vm = require("vm");
const [file, name, probe] = process.argv.slice(1);
const frappe = {
  query_reports: {},
  utils: { escape_html: (s) => String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;") },
};
vm.runInNewContext(fs.readFileSync(file, "utf8"), { frappe, __: (s) => s });
const report = frappe.query_reports[name];
const out = { filters: report.filters.map((f) => (
  { fieldname: f.fieldname, query: f.get_query ? f.get_query() : null })) };
if (report.formatter) {
  const cases = JSON.parse(probe);
  out.cells = cases.map(([column, data]) =>
    report.formatter("v", {}, { fieldname: column }, data, (v) => String(v)));
}
console.log(JSON.stringify(out));
"""


def _run(script: str, name: str, probe: list[Any]) -> dict[str, Any]:
    path = REPORTS / script.removesuffix(".js") / script
    done = subprocess.run(
        ["node", "-e", HARNESS, str(path), name, json.dumps(probe)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


@pytest.mark.parametrize(
    ("script", "name"),
    [("quiz_scores.js", "Quiz Scores"), ("learner_progress.js", "Learner Progress")],
)
def test_course_dropdown_lists_only_managed_courses(script: str, name: str) -> None:
    """AC-7: the Course filter is restricted to courses with a nile_key."""
    out = _run(script, name, [])
    course = next(f for f in out["filters"] if f["fieldname"] == "course")
    assert course["query"] == {"filters": {"nile_key": ["is", "set"]}}


def test_locked_row_links_to_the_learners_submissions_for_that_quiz() -> None:
    """AC-9: a Locked state links to the filtered submission list, both values URL encoded."""
    data = {"learner": "a+b@x.com", "quiz": "Q 1/&", "state": "Locked", "quiz_title": "T"}
    out = _run("quiz_scores.js", "Quiz Scores", [["state", data]])
    url = "/app/lms-quiz-submission?member=a%2Bb%40x.com&quiz=Q%201%2F%26"
    assert out["cells"] == [f'<a href="{url}">v</a>']


def test_other_states_are_not_linked_and_quiz_title_is_escaped() -> None:
    """AC-9: only Locked links; the quiz cell escapes its title."""
    passed = {"learner": "a@x.com", "quiz": "q1", "state": "Passed"}
    evil = {"learner": "a@x.com", "quiz": "q 1", "state": "Passed", "quiz_title": "<b>&"}
    out = _run("quiz_scores.js", "Quiz Scores", [["state", passed], ["quiz", evil]])
    assert out["cells"] == ["v", '<a href="/app/lms-quiz/q%201">&lt;b&gt;&amp;</a>']


@pytest.mark.parametrize(
    ("script", "name"),
    [("quiz_scores.js", "Quiz Scores"), ("learner_progress.js", "Learner Progress")],
)
def test_learner_cell_shows_the_escaped_email_and_links_to_the_user(script: str, name: str) -> None:
    """AC-9: the learner cell shows the email (not the full name) as a link to the User."""
    data = {"learner": "a+b<x>@x.com", "full_name": "Ann"}
    out = _run(script, name, [["learner", data], ["full_name", data]])
    assert out["cells"] == ['<a href="/app/user/a%2Bb%3Cx%3E%40x.com">a+b&lt;x&gt;@x.com</a>', "v"]
