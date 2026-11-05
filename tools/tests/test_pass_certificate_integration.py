"""Spec 0010 on the running site: pass mark, attempts, certificate, link, reset (-m integration).

One throwaway course, three throwaway users (a student, a second student, a Moderator) and a random
prefix, all removed afterwards. The tests run in order and share that state, like a real day.
The users call the LMS over HTTPS with API keys, so the real permission checks apply.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_content_sync_integration import site_is_up, sync  # noqa: F401  (site_is_up is autouse)
from test_data_model_integration import _run_script, _site, _sql

from nile_tools.contentfile import load_course

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).parent / "live_scripts"
QUIZ_API = "/api/method/lms.lms.doctype.lms_quiz.lms_quiz.submit_quiz"
CERT_API = "/api/method/lms.lms.doctype.lms_certificate.lms_certificate.create_certificate"
PROGRESS_API = "/api/method/lms.lms.doctype.course_lesson.course_lesson.save_progress"

COURSE_YAML = """\
key: {p}-course
title: Nile pass rules {p}
short_introduction: Throwaway course for the pass rules test.
description: Made by the integration test and removed again.
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
    title: Pass rules video quiz {p}
    questions:
{q1_questions}
  - key: {p}-q2
    title: Pass rules lab quiz {p}
    questions:
      - key: {p}-q2a
        text: Lab question?
        options: [{{text: "Yes", correct: true}}, {{text: "No"}}]
"""
Q1_QUESTION = """\
      - key: {p}-q1{n}
        text: Video question {n}?
        options: [{{text: "Yes", correct: true}}, {{text: "No"}}]"""


@dataclass(frozen=True)
class World:
    """The throwaway course, its records and the three users' API tokens."""

    prefix: str
    course: str
    quizzes: dict[str, str]  # quiz key suffix -> LMS Quiz name
    lessons: dict[str, str]  # lesson key suffix -> Course Lesson name
    questions: dict[str, list[str]]  # quiz key suffix -> LMS Question names
    users: dict[str, dict[str, str]]  # student, other, admin -> {email, token}


def _script(name: str, prefix: str, **extra: str) -> str:
    text = (SCRIPTS / f"{name}.pyscript").read_text().replace("__P__", prefix)
    for key, value in extra.items():
        text = text.replace(f"__{key.upper()}__", value)
    return text


def _enroll(world: World, who: str, action: str) -> None:
    _run_script(_script("pass_rules_enroll", world.prefix, who=who, action=action))


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    prefix = "pr" + uuid.uuid4().hex[:8]
    users = _run_script(_script("pass_rules_setup", prefix))
    try:
        folder = tmp_path_factory.mktemp("course")
        (folder / "labs").mkdir()
        (folder / "labs" / "lab.md").write_text("# Lab\n\nDo the thing.\n")
        q1 = "\n".join(Q1_QUESTION.format(p=prefix, n=n) for n in range(1, 6))
        (folder / "course.yaml").write_text(COURSE_YAML.format(p=prefix, q1_questions=q1))
        code, said = sync(load_course(folder))
        assert code == 0, said

        def names(table: str, like: str) -> dict[str, str]:
            rows = _sql(f"select nile_key, name from `tab{table}` where nile_key like '{like}'")
            return {key.removeprefix(prefix + "-"): name for key, name in rows}

        questions = names("LMS Question", f"{prefix}-q%")
        built = World(
            prefix=prefix,
            course=names("LMS Course", f"{prefix}-course")["course"],
            quizzes=names("LMS Quiz", f"{prefix}-q%"),
            lessons=names("Course Lesson", f"{prefix}-%"),
            questions={
                "q1": [questions[f"q1{n}"] for n in range(1, 6)],
                "q2": [questions["q2a"]],
            },
            users={k: users[k] for k in ("student", "other", "admin")},
        )
        _enroll(built, "student", "add")
        _enroll(built, "other", "add")
        yield built
    finally:
        _run_script(_script("pass_rules_cleanup", prefix))
        _run_script(_script("content_sync_edges_cleanup", prefix))
        assert _sql(f"select count(*) from `tabLMS Course` where nile_key like '{prefix}-%'") == [
            ["0"]
        ]
        assert _sql(f"select count(*) from tabUser where name like '{prefix}-%'") == [["0"]]


def client(world: World, who: str | None, *, follow: bool = False) -> httpx.Client:
    """An HTTPS client for one user, or a guest when `who` is None."""
    headers = {"Authorization": f"token {world.users[who]['token']}"} if who else {}
    return httpx.Client(
        base_url=f"https://{_site()}", headers=headers, timeout=60, follow_redirects=follow
    )


def attempt(world: World, who: str, quiz: str, correct: int) -> httpx.Response:
    """Submit one attempt with the first `correct` answers right and the rest wrong."""
    answers = [
        {"question_name": q, "answer": ["Yes" if i < correct else "No"]}
        for i, q in enumerate(world.questions[quiz])
    ]
    with client(world, who) as c:
        return c.post(QUIZ_API, data={"quiz": world.quizzes[quiz], "results": json.dumps(answers)})


def complete(world: World, who: str, lesson: str) -> None:
    """Mark a non quiz lesson complete through the call the LMS lesson page makes."""
    with client(world, who) as c:
        done = c.post(PROGRESS_API, data={"lesson": world.lessons[lesson], "course": world.course})
        assert done.status_code == 200, done.text


def done_lessons(world: World, who: str) -> set[str]:
    rows = _sql(
        "select lesson from `tabLMS Course Progress` where status = 'Complete' "
        f"and course = '{world.course}' and member = '{world.users[who]['email']}'"
    )
    by_name = {name: key for key, name in world.lessons.items()}
    return {by_name[r[0]] for r in rows}


def progress(world: World, who: str) -> float:
    rows = _sql(
        f"select progress from `tabLMS Enrollment` where course = '{world.course}' "
        f"and member = '{world.users[who]['email']}'"
    )
    return float(rows[0][0])


def request_certificate(world: World, who: str) -> httpx.Response:
    with client(world, who) as c:
        return c.post(CERT_API, data={"course": world.course})


def certificate_count(world: World) -> list[list[str]]:
    return _sql(f"select count(*) from `tabLMS Certificate` where course = '{world.course}'")


def certificate_name(world: World, who: str) -> str:
    rows = _sql(
        f"select name from `tabLMS Certificate` where course = '{world.course}' "
        f"and member = '{world.users[who]['email']}'"
    )
    assert len(rows) == 1
    return rows[0][0]


def set_published(world: World, who: str, name: str, value: int) -> httpx.Response:
    with client(world, who) as c:
        return c.put(f"/api/resource/LMS Certificate/{name}", json={"published": value})


def set_published_member(world: World, who: str, name: str, member: str) -> httpx.Response:
    with client(world, who) as c:
        return c.put(f"/api/resource/LMS Certificate/{name}", json={"member": member})


def open_link(world: World, who: str | None, name: str) -> httpx.Response:
    with client(world, who, follow=True) as c:
        # LMS routes /courses/<course>/<certificate id> to its certificate page.
        return c.get(f"/courses/{world.course}/{name}")


def test_the_synced_quizzes_pass_at_80_with_3_attempts(world: World) -> None:
    """AC-1: the course file says nothing, so the named defaults land on every quiz."""
    ids = ", ".join(f"'{n}'" for n in world.quizzes.values())
    rows = _sql(f"select passing_percentage, max_attempts from `tabLMS Quiz` where name in ({ids})")
    assert rows == [["80", "3"], ["80", "3"]]


def test_a_score_below_the_pass_mark_does_not_complete_the_lesson(world: World) -> None:
    """AC-2: 3 of 5 is 60%, the attempt is stored, the lesson stays open."""
    reply = attempt(world, "student", "q1", correct=3)
    assert reply.status_code == 200, reply.text
    result = reply.json()["message"]
    assert (result["percentage"], result["pass"]) == (60, False)
    assert "vq" not in done_lessons(world, "student")


def test_a_score_of_exactly_80_completes_the_lesson(world: World) -> None:
    """AC-2: 4 of 5 is 80%, the boundary passes."""
    result = attempt(world, "student", "q1", correct=4).json()["message"]
    assert (result["percentage"], result["pass"]) == (80, True)
    assert "vq" in done_lessons(world, "student")


def test_the_fourth_attempt_is_refused_and_the_lesson_stays_open(world: World) -> None:
    """AC-2: three misses lock the quiz. A fourth, even a perfect one, is refused and not stored."""
    assert attempt(world, "other", "q2", correct=0).status_code == 200  # another student's row
    for _ in range(3):
        result = attempt(world, "student", "q2", correct=0).json()["message"]
        assert result["pass"] is False
    fourth = attempt(world, "student", "q2", correct=1)
    assert fourth.status_code >= 400
    assert "MaximumAttemptsExceededError" in fourth.text
    quiz = world.quizzes["q2"]
    student = world.users["student"]["email"]
    count = _sql(
        "select count(*) from `tabLMS Quiz Submission` "
        f"where quiz = '{quiz}' and member = '{student}'"
    )
    assert count == [["3"]]
    assert "lq" not in done_lessons(world, "student")


def test_a_certificate_is_refused_while_a_lesson_is_incomplete(world: World) -> None:
    """AC-3: video and lab done, the lab quiz not: the LMS refuses and nothing is issued."""
    complete(world, "student", "video")
    complete(world, "student", "lab")
    assert progress(world, "student") < 100
    reply = request_certificate(world, "student")
    assert reply.status_code >= 400
    assert "You have not completed the course yet." in reply.text
    assert certificate_count(world) == [["0"]]


def test_a_moderator_resets_one_student_and_nothing_else(world: World) -> None:
    """AC-6: list, filter and delete one student's lab quiz attempts. Others and progress stay."""
    quiz = world.quizzes["q2"]
    student = world.users["student"]["email"]
    other = world.users["other"]["email"]
    with client(world, "admin") as c:
        listed = c.get(
            "/api/resource/LMS Quiz Submission",
            params={
                "filters": json.dumps([["quiz", "=", quiz], ["member", "=", student]]),
                "fields": json.dumps(["name", "member", "percentage"]),
            },
        )
        assert listed.status_code == 200, listed.text
        rows = listed.json()["data"]
        assert len(rows) == 3 and {r["member"] for r in rows} == {student}
        for row in rows:
            gone = c.delete(f"/api/resource/LMS Quiz Submission/{row['name']}")
            assert gone.status_code in (200, 202), gone.text
    left = _sql(
        f"select member, count(*) from `tabLMS Quiz Submission` where quiz = '{quiz}' group by 1"
    )
    assert left == [[other, "1"]]
    assert "vq" in done_lessons(world, "student")  # the passed video quiz is untouched
    # A student cannot delete attempts.
    mine = _sql(f"select name from `tabLMS Quiz Submission` where member = '{other}' limit 1")[0][0]
    with client(world, "other") as c:
        assert c.delete(f"/api/resource/LMS Quiz Submission/{mine}").status_code == 403


def test_the_reset_student_passes_and_requests_the_certificate(world: World) -> None:
    """AC-2, AC-3: after the reset a pass completes the last lesson, and the button issues it."""
    result = attempt(world, "student", "q2", correct=1).json()["message"]
    assert result["pass"] is True
    assert done_lessons(world, "student") == {"video", "vq", "lab", "lq"}
    assert progress(world, "student") == 100
    reply = request_certificate(world, "student")
    assert reply.status_code == 200, reply.text
    name = certificate_name(world, "student")
    assert reply.json()["message"]["name"] == name
    with client(world, "admin") as c:
        doc = c.get(f"/api/resource/LMS Certificate/{name}").json()["data"]
    assert doc["member"] == world.users["student"]["email"]
    assert doc["member_name"] and doc["course"] == world.course
    assert doc["course_title"] == f"Nile pass rules {world.prefix}"
    assert doc["issue_date"] == date.today().isoformat()
    assert doc["template"] and doc["published"] == 0


def test_the_owner_opens_the_pdf_and_a_second_request_returns_the_same_certificate(
    world: World,
) -> None:
    """AC-4: the link is the PDF. AC-3: asking again gives the same certificate."""
    name = certificate_name(world, "student")
    link = open_link(world, "student", name)
    assert link.status_code == 200, link.text[:300]
    assert link.content.startswith(b"%PDF")
    assert request_certificate(world, "student").json()["message"]["name"] == name
    assert certificate_count(world) == [["1"]]


def test_a_private_certificate_is_closed_to_a_guest_until_a_moderator_publishes(
    world: World,
) -> None:
    """AC-5: private by default, a student cannot publish, a Moderator tick opens and closes it."""
    name = certificate_name(world, "student")
    assert open_link(world, None, name).status_code == 403
    assert set_published(world, "student", name, 1).status_code == 403
    assert open_link(world, None, name).status_code == 403

    assert set_published(world, "admin", name, 1).status_code == 200
    guest = open_link(world, None, name)
    assert guest.status_code == 200, guest.text[:300]
    assert guest.content.startswith(b"%PDF")

    assert set_published(world, "admin", name, 0).status_code == 200
    assert open_link(world, None, name).status_code == 403


def test_a_removed_learner_keeps_the_certificate_and_a_learner_without_one_is_refused(
    world: World,
) -> None:
    """AC-7: no enrollment keeps the old certificate, and a learner with none is refused."""
    name = certificate_name(world, "student")
    assert set_published(world, "admin", name, 1).status_code == 200
    _enroll(world, "student", "remove")
    _enroll(world, "other", "remove")

    link = open_link(world, "student", name)
    assert link.status_code == 200 and link.content.startswith(b"%PDF")
    guest = open_link(world, None, name)
    assert guest.status_code == 200 and guest.content.startswith(b"%PDF")
    assert request_certificate(world, "student").json()["message"]["name"] == name

    refused = request_certificate(world, "other")
    assert refused.status_code >= 400
    assert "You are not enrolled in this course." in refused.text
    assert certificate_count(world) == [["1"]]

    # AC-10: the nile_auth override lets a Moderator publish and unpublish after removal.
    assert set_published(world, "admin", name, 0).status_code == 200
    assert open_link(world, None, name).status_code == 403
    assert set_published(world, "admin", name, 1).status_code == 200
    guest_again = open_link(world, None, name)
    assert guest_again.status_code == 200 and guest_again.content.startswith(b"%PDF")

    # A certificate cannot be moved to a learner who is not enrolled, and no new one is issued.
    moved = set_published_member(world, "admin", name, world.users["other"]["email"])
    assert moved.status_code >= 400
    assert certificate_name(world, "student") == name
    assert certificate_count(world) == [["1"]]
