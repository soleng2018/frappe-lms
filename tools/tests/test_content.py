"""Unit tests for content and coursecheck: bodies from blocks and course rules (AC-2, 3, 5)."""

from dataclasses import replace

import pytest
from courses import LabLesson, QuizLesson, VideoLesson

from nile_tools.content import (
    Chapter,
    Course,
    Lesson,
    Option,
    Question,
    Quiz,
    QuizBlock,
    TextBlock,
    VideoBlock,
    lesson_body,
)
from nile_tools.coursecheck import check_across, check_course

OPTIONS = (Option("yes", True), Option("no"))


def course() -> Course:
    return Course(
        key="c",
        title="Course",
        chapters=(
            Chapter(
                "ch", "One", (VideoLesson("v", "Video", "dQw4w9WgXcQ"), QuizLesson("ql", "Q", "q"))
            ),
        ),
        quizzes=(
            Quiz(
                "q", "Quiz", "ql", (Question("q1", "One?", options=OPTIONS),), file="quizzes/q.yaml"
            ),
        ),
    )


def messages(c: Course) -> list[str]:
    return [f"{p.file} {p.where} {p.message}" for p in check_course(c, "c")]


def with_lessons(*lessons: Lesson) -> Course:
    c = course()
    return replace(c, chapters=(Chapter("ch", "One", tuple(lessons)),))


def test_a_sound_course_has_no_problems() -> None:
    assert check_course(course(), "c") == ()


def test_one_block_gives_the_same_body_as_before() -> None:
    assert lesson_body(VideoLesson("v", "V", "dQw4w9WgXcQ")) == '{{ YouTubeVideo("dQw4w9WgXcQ") }}'
    assert lesson_body(QuizLesson("l", "Q", "q"), "quiz-name") == '{{ Quiz("quiz-name") }}'
    assert lesson_body(LabLesson("l", "L", "# Lab\n\n")) == "# Lab"


def test_blocks_are_joined_in_order_by_a_blank_line() -> None:
    lesson = Lesson(
        "l",
        "L",
        (VideoBlock("dQw4w9WgXcQ"), TextBlock("guides/a.md", "\nText\n"), QuizBlock("q")),
    )
    assert lesson_body(lesson, "the-quiz") == (
        '{{ YouTubeVideo("dQw4w9WgXcQ") }}\n\nText\n\n{{ Quiz("the-quiz") }}'
    )


def test_a_quiz_block_needs_the_lms_quiz_name() -> None:
    with pytest.raises(ValueError, match="quiz name"):
        lesson_body(QuizLesson("l", "Q", "q"))


def test_an_empty_text_block_adds_nothing() -> None:
    lesson = Lesson("l", "L", (TextBlock("guides/a.md", "  \n"), VideoBlock("dQw4w9WgXcQ")))
    assert lesson_body(lesson) == '{{ YouTubeVideo("dQw4w9WgXcQ") }}'


def test_image_links_are_replaced_by_their_url() -> None:
    lesson = Lesson("l", "L", (TextBlock("guides/a.md", "![x](../images/a.png)"),))
    assert lesson_body(lesson, urls={"images/a.png": "/files/a.png"}) == "![x](/files/a.png)"


def test_a_lesson_needs_a_block_and_allows_one_video_and_one_quiz() -> None:
    bad = with_lessons(
        Lesson("none", "N", ()),
        Lesson("two", "T", (VideoBlock("dQw4w9WgXcQ"), VideoBlock("dQw4w9WgXcQ"))),
        Lesson("ql", "Q", (QuizBlock("q"), QuizBlock("q"))),
    )
    text = "\n".join(messages(bad))
    assert "lessons[none] a lesson needs at least one block" in text
    assert "lessons[two] a lesson may hold at most one video block" in text
    assert "lessons[ql] a lesson may hold at most one quiz block" in text


def test_a_quiz_block_with_no_file_and_a_file_nobody_uses() -> None:
    c = with_lessons(QuizLesson("ql", "Q", "missing"))
    text = "\n".join(messages(c))
    assert "blocks[0] quiz 'missing' has no file in quizzes/" in text
    assert "quizzes/q.yaml key quiz 'q' is not used by any quiz block" in text


def test_a_quiz_used_twice_is_named() -> None:
    c = with_lessons(QuizLesson("a", "A", "q"), QuizLesson("b", "B", "q"))
    assert "used by 2 quiz blocks" in "\n".join(messages(c))


@pytest.mark.parametrize("bad", ["", "short", "https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXc!"])
def test_a_video_must_be_an_11_character_id(bad: str) -> None:
    assert "11 character video id" in "\n".join(
        messages(with_lessons(VideoLesson("v", "V", bad), QuizLesson("ql", "Q", "q")))
    )


@pytest.mark.parametrize("mark", [0, 79, 101])
def test_pass_mark_outside_80_to_100(mark: int) -> None:
    c = course()
    c = replace(c, quizzes=(replace(c.quizzes[0], passing_percentage=mark),))
    assert "must be 80 to 100" in "\n".join(messages(c))


def test_attempts_and_empty_quiz() -> None:
    c = course()
    c = replace(c, quizzes=(replace(c.quizzes[0], max_attempts=0, questions=()),))
    text = "\n".join(messages(c))
    assert "max_attempts" in text and "no questions" in text


def test_choice_rules() -> None:
    q = Question("q1", "?", options=(Option("a"), Option("a"), Option("")))
    c = course()
    c = replace(c, quizzes=(replace(c.quizzes[0], questions=(q,)),))
    text = "\n".join(messages(c))
    assert (
        "no correct option" in text
        and "an empty option" in text
        and "repeats the option 'a'" in text
    )


def test_open_ended_is_refused() -> None:
    q = Question("q1", "?", type="Open Ended")
    c = course()
    c = replace(c, quizzes=(replace(c.quizzes[0], questions=(q,)),))
    assert "never graded" in "\n".join(messages(c))


def test_empty_and_repeated_keys_and_empty_chapter() -> None:
    c = with_lessons(
        VideoLesson("v", "V", "dQw4w9WgXcQ"),
        VideoLesson("v", "V", "dQw4w9WgXcQ"),
        QuizLesson("", "Q", "q"),
    )
    c = replace(c, chapters=(*c.chapters, Chapter("empty", "E", ())))
    text = "\n".join(messages(c))
    assert "lesson key 'v' is used more than once" in text
    assert "a lesson key is empty" in text
    assert "chapters[empty] a chapter needs at least one lesson" in text


def test_across_courses_titles_and_keys_clash_one_line_per_course() -> None:
    a = course()
    b = replace(course(), key="d", title="COURSE")
    found = check_across({"c": a, "d": b})
    lines = [p.line() for p in found]
    assert "ERROR c/course.yaml: title: the title is also used by d (case ignored)" in lines
    assert "ERROR d/course.yaml: title: the title is also used by c (case ignored)" in lines
    assert any(p.course == "c" and "lesson key 'v' is also used by d" in p.message for p in found)
    assert any(p.course == "d" and "quiz key 'q' is also used by c" in p.message for p in found)
