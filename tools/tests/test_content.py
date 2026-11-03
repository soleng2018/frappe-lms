"""Unit tests for nile_tools.content: defaults, the check and lesson bodies (AC-1, 2, 8, 10)."""

from dataclasses import replace

import pytest

from nile_tools import content
from nile_tools.content import (
    Chapter,
    Course,
    LabLesson,
    Option,
    Question,
    Quiz,
    QuizLesson,
    VideoLesson,
    check_course,
    lesson_body,
)

VIDEO_ID = "dQw4w9WgXcQ"


def _q(key: str, *options: Option) -> Question:
    return Question(key, "?", options=options or (Option("yes", True), Option("no")))


def good_course() -> Course:
    return Course(
        key="c",
        title="Nile",
        chapters=(
            Chapter(
                "ch1",
                "Concepts",
                (VideoLesson("v1", "What is Nile", VIDEO_ID), QuizLesson("l1", "Quiz", "q1")),
            ),
            Chapter(
                "ch2",
                "Feature",
                (LabLesson("lab", "Lab", "# Do it"), QuizLesson("l2", "Lab quiz", "q2")),
            ),
        ),
        quizzes=(
            Quiz("q1", "Quiz", "l1", (_q("a"),)),
            Quiz("q2", "Lab quiz", "l2", (_q("b"),)),
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
    orphan = Quiz("q3", "Orphan", "nowhere", (_q("c"),))
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
    q2 = replace(course.quizzes[1], questions=(_q("a"), _q(" ")))
    problems = check_course(replace(course, quizzes=(course.quizzes[0], q2)))
    assert any("question nile_key is repeated: 'a'" in p for p in problems)
    assert any("question nile_key is empty" in p for p in problems)


def test_reports_every_problem_at_once() -> None:
    course = good_course()
    bad = replace(course.quizzes[0], passing_percentage=0, max_attempts=0, questions=())
    assert len(check_course(replace(course, quizzes=(bad, course.quizzes[1])))) == 3


def test_video_body_is_the_youtube_macro() -> None:
    assert lesson_body(VideoLesson("v", "t", "abc12345678")) == '{{ YouTubeVideo("abc12345678") }}'


def test_quiz_body_is_the_quiz_macro_with_the_lms_name() -> None:
    assert lesson_body(QuizLesson("l", "t", "q"), "QZ-0001") == '{{ Quiz("QZ-0001") }}'


def test_quiz_body_without_a_quiz_name_is_refused() -> None:
    with pytest.raises(ValueError, match="quiz lesson 'l' needs the quiz name"):
        lesson_body(QuizLesson("l", "t", "q"))


def test_lab_body_is_the_markdown_and_ignores_a_quiz_name() -> None:
    assert lesson_body(LabLesson("l", "t", "# Do it"), "QZ-1") == "# Do it"


@pytest.mark.parametrize("bad", ["abc", "https://youtu.be/dQw4w9WgXcQ", "", "dQw4w9WgXcQ "])
def test_video_value_that_is_not_an_id(bad: str) -> None:
    course = good_course()
    chapter = replace(course.chapters[0], lessons=(VideoLesson("v1", "x", bad),))
    problems = check_course(replace(course, chapters=(chapter, course.chapters[1])))
    assert any("video lesson 'v1' youtube" in p for p in problems)


def _with_video(youtube: str) -> tuple[str, ...]:
    course = good_course()
    chapter = replace(
        course.chapters[0], lessons=(VideoLesson("v1", "x", youtube), course.chapters[0].lessons[1])
    )
    return check_course(replace(course, chapters=(chapter, course.chapters[1])))


@pytest.mark.parametrize("bad", ["abcdefghij", "abcdefghijkl", "abcdefghi!k", "abcdefghi k"])
def test_video_id_must_be_exactly_11_allowed_characters(bad: str) -> None:
    assert any("video lesson 'v1'" in p for p in _with_video(bad))


@pytest.mark.parametrize("ok", ["a-b_c1D2E3F", "-----------", "___________"])
def test_video_id_with_dashes_and_underscores_is_allowed(ok: str) -> None:
    assert _with_video(ok) == ()


def test_every_bad_video_is_named() -> None:
    course = good_course()
    lessons = (VideoLesson("v1", "x", "short"), VideoLesson("v2", "y", "also bad"))
    chapter = replace(course.chapters[0], lessons=lessons)
    problems = check_course(
        replace(course, chapters=(chapter, course.chapters[1]), quizzes=course.quizzes[1:])
    )
    assert [("'v1'" in p, "'v2'" in p) for p in problems] == [(True, False), (False, True)]


def test_blank_course_chapter_and_lesson_keys_are_named() -> None:
    course = good_course()
    chapter = replace(course.chapters[1], key="  ", lessons=(LabLesson("", "Lab", "x"),))
    problems = check_course(replace(course, key=" ", chapters=(course.chapters[0], chapter)))
    assert any("course nile_key is empty" in p for p in problems)
    assert any("chapter nile_key is empty" in p for p in problems)
    assert any("lesson nile_key is empty" in p for p in problems)


def test_quiz_body_with_an_empty_quiz_name_is_refused() -> None:
    with pytest.raises(ValueError, match="needs the quiz name"):
        lesson_body(QuizLesson("l", "t", "q"), "")


def test_user_input_question_is_gradable() -> None:
    course = good_course()
    ok = replace(course.quizzes[0], questions=(Question("a", "?", type="User Input"),))
    assert check_course(replace(course, quizzes=(ok, course.quizzes[1]))) == ()


def _choice(*options: Option) -> tuple[str, ...]:
    course = good_course()
    bad = replace(course.quizzes[0], questions=(_q("a", *options),))
    return check_course(replace(course, quizzes=(bad, course.quizzes[1])))


def test_a_choice_question_with_two_to_four_options_is_sound() -> None:
    assert _choice(Option("a", True), Option("b")) == ()
    assert _choice(*(Option(x, x == "a") for x in "abcd")) == ()


def test_a_choice_question_with_one_or_five_options_is_named() -> None:
    assert "has 1 options, must be 2 to 4" in "".join(_choice(Option("a", True)))
    five = tuple(Option(x, x == "a") for x in "abcde")
    assert "has 5 options, must be 2 to 4" in "".join(_choice(*five))


def test_a_choice_question_needs_a_correct_option() -> None:
    assert "has no correct option" in "".join(_choice(Option("a"), Option("b")))


def test_empty_and_repeated_options_are_named() -> None:
    joined = "".join(_choice(Option("a", True), Option(" ")))
    assert "has an empty option" in joined
    assert "repeats the option 'a'" in "".join(_choice(Option("a", True), Option("a ")))


def test_a_choice_question_without_text_is_named() -> None:
    course = good_course()
    blank = Question("a", " ", options=(Option("x", True), Option("y")))
    bad = replace(course.quizzes[0], questions=(blank,))
    assert "has no text" in "".join(check_course(replace(course, quizzes=(bad, course.quizzes[1]))))
