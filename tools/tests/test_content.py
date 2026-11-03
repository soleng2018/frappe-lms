"""Unit tests for nile_tools.content: defaults and the content check (AC-1, AC-2, AC-8)."""

from dataclasses import replace

import pytest

from nile_tools import content
from nile_tools.content import (
    Chapter,
    Course,
    LabLesson,
    Question,
    Quiz,
    QuizLesson,
    VideoLesson,
    check_course,
)


def good_course() -> Course:
    return Course(
        key="c",
        title="Nile",
        chapters=(
            Chapter(
                "ch1",
                "Concepts",
                (VideoLesson("v1", "What is Nile", "abc"), QuizLesson("l1", "Quiz", "q1")),
            ),
            Chapter(
                "ch2",
                "Feature",
                (LabLesson("lab", "Lab", "# Do it"), QuizLesson("l2", "Lab quiz", "q2")),
            ),
        ),
        quizzes=(
            Quiz("q1", "Quiz", "l1", (Question("a", "?"),)),
            Quiz("q2", "Lab quiz", "l2", (Question("b", "?"),)),
        ),
    )


def test_defaults_are_80_and_3() -> None:
    quiz = Quiz("q", "t", "l", ())
    assert (quiz.passing_percentage, quiz.max_attempts) == (80, 3)
    assert (content.DEFAULT_PASSING_PERCENTAGE, content.DEFAULT_MAX_ATTEMPTS) == (80, 3)


def test_sound_course_has_no_problems() -> None:
    assert check_course(good_course()) == ()


def test_a_lab_without_a_video_is_fine() -> None:
    course = good_course()
    assert (
        check_course(replace(course, chapters=course.chapters[1:], quizzes=course.quizzes[1:]))
        == ()
    )


def test_quiz_with_no_lesson_and_repeated_key_are_both_named() -> None:
    course = good_course()
    orphan = Quiz("q3", "Orphan", "nowhere", (Question("c", "?"),))
    dup = replace(course.chapters[1], key="ch1")
    problems = check_course(
        replace(course, chapters=(course.chapters[0], dup), quizzes=(*course.quizzes, orphan))
    )
    assert any("quiz 'q3' has no quiz lesson" in p for p in problems)
    assert any("chapter nile_key is repeated: 'ch1'" in p for p in problems)


def test_quiz_lesson_with_no_quiz() -> None:
    course = good_course()
    problems = check_course(replace(course, quizzes=course.quizzes[:1]))
    assert any("quiz lesson 'l2' has no quiz" in p for p in problems)


def test_quiz_naming_a_lesson_that_holds_another_quiz() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], lesson_key="l2")
    problems = check_course(replace(course, quizzes=(bad, course.quizzes[1])))
    assert any("holds quiz 'q2'" in p for p in problems)


def test_quiz_shared_between_lessons() -> None:
    course = good_course()
    shared = Chapter("ch3", "More", (QuizLesson("l3", "Again", "q1"),))
    problems = check_course(replace(course, chapters=(*course.chapters, shared)))
    assert any("quiz 'q1' is used by more than one lesson" in p for p in problems)


def test_empty_chapter() -> None:
    course = good_course()
    problems = check_course(
        replace(course, chapters=(*course.chapters, Chapter("ch3", "Empty", ())))
    )
    assert problems == ("chapter 'ch3' has no lessons",)


@pytest.mark.parametrize("mark", [0, 101, -5])
def test_pass_mark_outside_1_to_100(mark: int) -> None:
    course = good_course()
    bad = replace(course.quizzes[0], passing_percentage=mark)
    problems = check_course(replace(course, quizzes=(bad, course.quizzes[1])))
    assert any("passing_percentage" in p for p in problems)


@pytest.mark.parametrize("mark", [1, 100])
def test_pass_mark_edges_are_allowed(mark: int) -> None:
    course = good_course()
    ok = replace(course.quizzes[0], passing_percentage=mark)
    assert check_course(replace(course, quizzes=(ok, course.quizzes[1]))) == ()


def test_attempt_limit_under_1() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], max_attempts=0)
    assert any(
        "max_attempts" in p for p in check_course(replace(course, quizzes=(bad, course.quizzes[1])))
    )


def test_quiz_with_no_questions() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], questions=())
    assert any(
        "has no questions" in p
        for p in check_course(replace(course, quizzes=(bad, course.quizzes[1])))
    )


def test_open_ended_question() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], questions=(Question("a", "?", type="Open Ended"),))
    assert any(
        "open ended" in p for p in check_course(replace(course, quizzes=(bad, course.quizzes[1])))
    )


def test_repeated_question_key_across_quizzes_and_blank_key() -> None:
    course = good_course()
    q2 = replace(course.quizzes[1], questions=(Question("a", "?"), Question(" ", "?")))
    problems = check_course(replace(course, quizzes=(course.quizzes[0], q2)))
    assert any("question nile_key is repeated: 'a'" in p for p in problems)
    assert any("question nile_key is empty" in p for p in problems)


def test_reports_every_problem_at_once() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], passing_percentage=0, max_attempts=0, questions=())
    assert len(check_course(replace(course, quizzes=(bad, course.quizzes[1])))) == 3
