"""Spec 0005 edge behavior on the running site (pytest -m integration).

Each test makes its own throwaway course and student (random prefix) and deletes them again, so
the real course is never touched. The student has a password so a test can log in as them.
"""

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest
from test_content_sync_integration import (  # noqa: F401  (site_is_up is an autouse fixture)
    COURSE_YAML,
    connect,
    site_is_up,
    sync,
)
from test_data_model_integration import REPO, _run_script, _site, _sql

from nile_tools import config, lms
from nile_tools.content import Course
from nile_tools.contentfile import load_course
from nile_tools.sync import run_sync

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).parent / "live_scripts"


@dataclass(frozen=True)
class Fixture:
    """One throwaway course: its file prefix, loaded course and the student's login."""

    prefix: str
    course: Course
    password: str


def _script(name: str, prefix: str, password: str = "") -> str:
    text = (SCRIPTS / f"content_sync_edges_{name}.pyscript").read_text()
    return text.replace("__P__", prefix).replace("__PW__", password)


@pytest.fixture
def fx(tmp_path: Path) -> Iterator[Fixture]:
    prefix = "ed" + uuid.uuid4().hex[:8]
    password = secrets.token_urlsafe(16)
    _run_script(_script("setup", prefix, password))
    try:
        (tmp_path / "labs").mkdir()
        (tmp_path / "labs" / "lab.md").write_text("# Lab\n\nDo the thing & report back.\n")
        (tmp_path / "course.yaml").write_text(COURSE_YAML.format(p=prefix))
        yield Fixture(prefix, load_course(tmp_path), password)
    finally:
        _run_script(_script("cleanup", prefix))
        assert _sql(f"select count(*) from `tabLMS Course` where nile_key like '{prefix}-%'") == [
            ["0"]
        ]
        assert _sql(f"select count(*) from tabUser where name like '{prefix}-%'") == [["0"]]


def test_check_on_an_empty_site_lists_everything_and_writes_nothing(fx: Fixture) -> None:
    """AC-6, AC-1: --check on a new course names all 11 records; a real run then makes them."""
    code, said = sync(fx.course, check=True)
    assert code == 1
    assert len([x for x in said if x.startswith("would create")]) == 11
    assert _sql(f"select count(*) from `tabLMS Course` where nile_key like '{fx.prefix}-%'") == [
        ["0"]
    ]

    code, said = sync(fx.course)
    assert code == 0, said
    assert said[-1].startswith("11 created"), said
    assert sync(fx.course, check=True) == (0, ["nothing to change"])


def test_quiz_defaults_then_limits_marks_and_lesson_order(fx: Fixture) -> None:
    """AC-1, AC-2, AC-4: named defaults on create; later edits and a lesson swap update in place."""
    prefix = fx.prefix
    assert sync(fx.course)[0] == 0
    limits = (
        f"select passing_percentage, max_attempts from `tabLMS Quiz` where nile_key = '{prefix}-q1'"
    )
    assert _sql(limits) == [["80", "3"]]
    marks = (
        "select qq.marks from `tabLMS Quiz Question` qq join `tabLMS Quiz` q on q.name = qq.parent "
        f"where q.nile_key = '{prefix}-q1'"
    )
    assert _sql(marks) == [["1"]]

    quiz, other = fx.course.quizzes
    question = replace(quiz.questions[0], marks=4)
    edited_quiz = replace(quiz, passing_percentage=70, max_attempts=5, questions=(question,))
    chapter = fx.course.chapters[0]
    swapped = replace(chapter, lessons=tuple(reversed(chapter.lessons)))
    edited = replace(
        fx.course, quizzes=(edited_quiz, other), chapters=(swapped, *fx.course.chapters[1:])
    )

    code, said = sync(edited)
    assert code == 0, said
    assert _sql(limits) == [["70", "5"]]
    assert _sql(marks) == [["4"]]
    order = _sql(
        "select l.nile_key from `tabLesson Reference` r "
        "join `tabCourse Chapter` c on c.name = r.parent "
        f"join `tabCourse Lesson` l on l.name = r.lesson where c.nile_key = '{prefix}-ch1' "
        "order by r.idx"
    )
    assert order == [[f"{prefix}-vq"], [f"{prefix}-video"]]
    assert sync(edited) == (0, ["nothing to change"])


def test_a_lesson_added_by_hand_is_reported_then_taken_out_of_the_outline(fx: Fixture) -> None:
    """AC-5, AC-6: an unmanaged lesson shows in --check; sync drops its row, keeps the record."""
    assert sync(fx.course)[0] == 0
    rogue = _run_script(_script("rogue", fx.prefix))["lesson"]

    code, said = sync(fx.course, check=True)
    assert code == 1
    assert any(x.startswith("unmanaged Course Lesson") and "no nile_key" in x for x in said), said

    code, said = sync(fx.course)
    assert code == 0, said
    assert any("removed unmanaged row" in x for x in said), said
    in_outline = _sql(f"select count(*) from `tabLesson Reference` where lesson = '{rogue}'")
    assert in_outline == [["0"]]
    assert _sql(f"select count(*) from `tabCourse Lesson` where name = '{rogue}'") == [["1"]]


def test_a_wrong_secret_fails_with_the_url_and_status_and_no_secret() -> None:
    """AC-7: the error names the request and HTTP 401, and never prints the secret."""
    values = config.load_env(REPO).values
    bad = "not-the-secret-" + uuid.uuid4().hex
    connection = lms.connect(values["LMS_HOSTNAME"], values["LMS_API_KEY"], bad)
    course = Course("x-course", "x", ())
    with pytest.raises(lms.LmsError) as raised:
        run_sync(connection, course, check=True, say=lambda _line: None)
    message = str(raised.value)
    assert f"https://{values['LMS_HOSTNAME']}/api/resource/" in message
    assert "HTTP 401" in message
    assert bad not in message and values["LMS_API_KEY"] not in message


def test_a_student_sees_the_published_course_in_file_order(fx: Fixture) -> None:
    """AC-1, AC-4: logged in as a student, the outline and lessons come out as the file says."""
    assert sync(fx.course)[0] == 0
    _run_script(_script("enroll", fx.prefix))
    name = _sql(f"select name from `tabLMS Course` where nile_key = '{fx.prefix}-course'")[0][0]

    with httpx.Client(base_url=f"https://{_site()}", timeout=30) as student:
        login = student.post(
            "/api/method/login",
            data={"usr": f"{fx.prefix}-student@example.com", "pwd": fx.password},
        )
        assert login.status_code == 200, login.text
        outline = student.get(
            "/api/method/lms.lms.utils.get_course_outline", params={"course": name}
        ).json()["message"]
        assert [c["title"] for c in outline] == ["Concepts", "Lab"]
        titles = [[x["title"] for x in c["lessons"]] for c in outline]
        assert titles == [["Video", "Video quiz"], ["Lab guide", "Lab quiz"]]

        video = student.get(
            "/api/method/lms.lms.utils.get_lesson",
            params={"course": name, "chapter": 1, "lesson": 1},
        ).json()["message"]
        assert video["youtube"] == "dQw4w9WgXcQ"
        lab = student.get(
            "/api/method/lms.lms.utils.get_lesson",
            params={"course": name, "chapter": 2, "lesson": 1},
        ).json()["message"]
        assert "Do the thing" in lab["body"]
