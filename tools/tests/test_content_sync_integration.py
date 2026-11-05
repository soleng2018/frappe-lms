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
from throwaway import question, write_course

from nile_tools import config, lms
from nile_tools.content import Course
from nile_tools.contentfile import load_catalog, load_course
from nile_tools.sync import run_sync, sync_all

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).parent / "live_scripts"


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
    p = prefix
    folder = write_course(
        tmp_path,
        p,
        title=f"Nile IT {p}",
        quiz_titles=(f"Nile IT quiz {p}", f"Nile IT quiz {p}"),
        q1_questions=question(f"{p}-q1a", "First & foremost?", "Yes", "No"),
        q2_questions=question(f"{p}-q2a", "Second?", "A", "B", "C"),
    )
    course = load_course(folder)

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


PNG = b"\x89PNG\r\n\x1a\n" + b"live" * 8


def test_two_courses_sync_with_a_mixed_lesson_and_an_image_then_change_nothing(
    prefix: str, tmp_path: Path
) -> None:
    """Spec 0011 AC-2, AC-4, AC-7 live: two courses, one lesson mixing blocks, run twice."""
    p = prefix
    write_course(
        tmp_path,
        p,
        title=f"Nile IT {p}",
        quiz_titles=(f"Nile IT quiz {p}", f"Nile IT quiz {p}"),
        q1_questions=question(f"{p}-q1a", "First?", "Yes", "No"),
        q2_questions=question(f"{p}-q2a", "Second?", "A", "B"),
    )
    two = tmp_path / f"{p}-two"
    (two / "guides").mkdir(parents=True)
    (two / "quizzes").mkdir()
    (two / "images").mkdir()
    (two / "images" / "shot.png").write_bytes(PNG)
    (two / "guides" / "intro.md").write_text("# Intro\n\n![a screen](../images/shot.png)\n")
    (two / "quizzes" / "q.yaml").write_text(
        f"key: {p}-two-q\ntitle: Two quiz {p}\nquestions:\n"
        + question(f"{p}-two-q1", "Seen it?", "Yes", "No")
        + "\n"
    )
    (two / "course.yaml").write_text(
        f"""format: 1
key: {p}-two
title: Nile IT two {p}
short_introduction: s
description: d
chapters:
  - key: {p}-two-ch
    title: Only chapter
    lessons:
      - key: {p}-two-l
        title: Mixed
        blocks:
          - video: dQw4w9WgXcQ
          - text: guides/intro.md
          - quiz: {p}-two-q
"""
    )
    catalog = load_catalog(tmp_path)
    assert not catalog.problems
    out: list[str] = []
    try:
        kwargs = {"only": None, "check": False, "say": out.append, "err": out.append}
        assert sync_all(connect(), catalog, **kwargs) == 0, out  # type: ignore[arg-type]
        body = _sql(f"select body from `tabCourse Lesson` where nile_key = '{p}-two-l'")[0][
            0
        ].replace("\\n", "\n")
        quiz = _sql(f"select name from `tabLMS Quiz` where nile_key = '{p}-two-q'")[0][0]
        url = _sql(f"select file_url from tabFile where file_name like '{p}-two-%-shot.png'")[0][0]
        assert body == (
            f'{{{{ YouTubeVideo("dQw4w9WgXcQ") }}}}\n\n# Intro\n\n![a screen]({url})\n\n'
            f'{{{{ Quiz("{quiz}") }}}}'
        )
        out.clear()
        assert sync_all(connect(), catalog, **kwargs) == 0, out  # type: ignore[arg-type]
        assert f"[{p}-two] nothing to change" in out and f"[{p}-course] nothing to change" in out
        files = _sql(f"select count(*) from tabFile where file_name like '{p}-two-%'")
        assert files == [["1"]]
    finally:
        for (name,) in _sql(f"select name from tabFile where file_name like '{p}-two-%'"):
            _sql(f"delete from tabFile where name = '{name}'")
