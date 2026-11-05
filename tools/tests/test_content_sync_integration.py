"""Spec 0005 on the running site: sync, rename, remove, batches, progress (pytest -m integration).

Uses a throwaway course whose nile_keys start with a random prefix, and deletes everything it
made afterwards, so the real course is never touched.
"""

import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from test_data_model_integration import COMPOSE, REPO, _run_script, _sql

from nile_tools import config, lms
from nile_tools.content import Course
from nile_tools.contentfile import load_course
from nile_tools.sync import run_sync

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).parent / "live_scripts"

COURSE_YAML = """\
key: {p}-course
title: Nile IT {p}
short_introduction: Throwaway course for the content sync test.
description: Made by the integration test & removed again.
chapters:
  - key: {p}-ch1
    title: Concepts
    lessons:
      - {{key: {p}-video, type: video, title: Video, youtube: dQw4w9WgXcQ}}
      - {{key: {p}-vq, type: quiz, title: Video quiz, quiz: {p}-q1}}
  - key: {p}-ch2
    title: Lab
    lessons:
      - {{key: {p}-lab, type: lab, title: Lab guide, body_file: labs/lab.md}}
      - {{key: {p}-lq, type: quiz, title: Lab quiz, quiz: {p}-q2}}
quizzes:
  - key: {p}-q1
    title: Nile IT quiz {p}
    questions:
      - key: {p}-q1a
        text: First & foremost?
        options: [{{text: "Yes", correct: true}}, {{text: "No"}}]
  - key: {p}-q2
    title: Nile IT quiz {p}
    questions:
      - key: {p}-q2a
        text: Second?
        options: [{{text: A, correct: true}}, {{text: B}}, {{text: C}}]
"""


def _script(name: str, prefix: str) -> str:
    text = (SCRIPTS / f"content_sync_{name}.pyscript").read_text()
    return text.replace("__P__", prefix)


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


@pytest.fixture(scope="module")
def prefix() -> Iterator[str]:
    p = "it" + uuid.uuid4().hex[:8]
    _run_script(_script("setup", p))
    try:
        yield p
    finally:
        _run_script(_script("cleanup", p))
        assert _sql(f"select count(*) from `tabLMS Course` where nile_key like '{p}-%'") == [["0"]]


def connect() -> lms.Lms:
    values = config.load_env(REPO).values
    return lms.connect(values["LMS_HOSTNAME"], values["LMS_API_KEY"], values["LMS_API_SECRET"])


def sync(course: Course, *, check: bool = False) -> tuple[int, list[str]]:
    said: list[str] = []
    return run_sync(connect(), course, check=check, say=said.append), said


def test_sync_on_the_live_site_end_to_end(prefix: str, tmp_path: Path) -> None:
    (tmp_path / "labs").mkdir()
    (tmp_path / "labs" / "lab.md").write_text("# Lab\n\nDo the thing & report back.\n")
    (tmp_path / "course.yaml").write_text(COURSE_YAML.format(p=prefix))
    course = load_course(tmp_path)

    # AC-1, AC-4: the whole course, every record keyed, bodies as spec 0004 says.
    code, said = sync(course)
    assert code == 0, said
    rows = _sql(f"select count(*) from `tabCourse Lesson` where nile_key like '{prefix}-%'")
    assert rows == [["4"]]
    quizzes = dict(
        _sql(f"select nile_key, name from `tabLMS Quiz` where nile_key like '{prefix}-%'")
    )
    assert len(set(quizzes.values())) == 2  # same title, so LMS suffixed one
    body = _sql(f"select body from `tabCourse Lesson` where nile_key = '{prefix}-vq'")[0][0]
    assert body == f'{{{{ Quiz("{quizzes[f"{prefix}-q1"]}") }}}}'
    link = _sql(f"select lesson, course from `tabLMS Quiz` where nile_key = '{prefix}-q2'")[0]
    assert all(link)
    course_row = _sql(
        f"select published, enable_certification, enforce_lesson_completion from `tabLMS Course` "
        f"where nile_key = '{prefix}-course'"
    )
    assert course_row == [["0", "1", "0"]]

    # Spec 0009 AC-12: sync adds the course to no batch.
    batch_rows = _sql(
        "select count(*) from `tabBatch Course` bc join `tabLMS Course` c on c.name = bc.course "
        f"where c.nile_key = '{prefix}-course'"
    )
    assert batch_rows == [["0"]]

    # AC-2: the second run writes nothing, check agrees.
    assert sync(course) == (0, ["nothing to change"])
    assert sync(course, check=True) == (0, ["nothing to change"])

    # AC-2: a renamed title updates the same record.
    chapter_name = _sql(f"select name from `tabCourse Chapter` where nile_key = '{prefix}-ch1'")
    c = course.chapters[0]
    renamed = replace(course, chapters=(replace(c, title="Concepts renamed"), course.chapters[1]))
    code, said = sync(renamed)
    assert code == 0
    after = _sql(f"select name, title from `tabCourse Chapter` where nile_key = '{prefix}-ch1'")
    assert after == [[chapter_name[0][0], "Concepts renamed"]]

    # AC-6: an edit in the LMS is found by --check and overwritten by a real run.
    _sql(f"update `tabCourse Lesson` set body = 'edited' where nile_key = '{prefix}-lab'")
    code, said = sync(renamed, check=True)
    assert code == 1 and any("Course Lesson" in line and "body" in line for line in said)
    code, said = sync(renamed)
    assert code == 0 and any("LMS has 'edited'" in line for line in said)

    # AC-5: remove the lab quiz lesson; a student who finished the rest reaches 100.
    _run_script(_script("student_progress", prefix))
    slim_lab = replace(renamed.chapters[1], lessons=renamed.chapters[1].lessons[:1])
    slim = replace(renamed, chapters=(renamed.chapters[0], slim_lab), quizzes=renamed.quizzes[:1])
    code, said = sync(slim)
    assert code == 0, said
    assert any(line.startswith(f"detached Course Lesson {prefix}-lq") for line in said)
    assert any(line.startswith(f"detached LMS Quiz {prefix}-q2") for line in said)
    kept = _sql(f"select count(*) from `tabCourse Lesson` where nile_key = '{prefix}-lq'")
    assert kept == [["1"]]
    progress = _sql(
        f"select progress from `tabLMS Enrollment` where member = '{prefix}-student@example.com'"
    )
    assert float(progress[0][0]) == 100.0
    quiz_course = _sql(f"select lesson, course from `tabLMS Quiz` where nile_key = '{prefix}-q2'")
    assert quiz_course[0][0] in ("", "None", "NULL") and quiz_course[0][1] not in (
        "",
        "None",
        "NULL",
    )
    assert sync(slim) == (0, ["nothing to change"])
