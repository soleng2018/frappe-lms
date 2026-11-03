"""Unit tests for nile_tools.contentfile: the loader and its file errors (AC-1, AC-3)."""

from pathlib import Path

import pytest

from nile_tools.content import LabLesson, QuizLesson, VideoLesson
from nile_tools.contentfile import ContentError, load_course

GOOD = """\
key: c
title: Course
short_introduction: short
description: long
chapters:
  - key: ch
    title: Chapter
    lessons:
      - {key: v, type: video, title: Video, youtube: dQw4w9WgXcQ}
      - {key: lab, type: lab, title: Lab, body_file: labs/a.md}
      - {key: ql, type: quiz, title: Quiz lesson, quiz: q}
quizzes:
  - key: q
    title: Quiz
    questions:
      - key: q1
        text: Which?
        options: [{text: A, correct: true}, {text: B}]
"""


def write(tmp_path: Path, text: str = GOOD) -> Path:
    (tmp_path / "labs").mkdir(exist_ok=True)
    (tmp_path / "labs" / "a.md").write_text("# Lab\n")
    (tmp_path / "course.yaml").write_text(text)
    return tmp_path


def problems(tmp_path: Path, text: str) -> str:
    with pytest.raises(ContentError) as e:
        load_course(write(tmp_path, text))
    return "\n".join(e.value.problems)


def test_a_good_file_loads_into_the_model(tmp_path: Path) -> None:
    course = load_course(write(tmp_path))
    video, lab, quiz_lesson = course.chapters[0].lessons
    assert video == VideoLesson("v", "Video", "dQw4w9WgXcQ")
    assert lab == LabLesson("lab", "Lab", "# Lab\n")
    assert quiz_lesson == QuizLesson("ql", "Quiz lesson", "q")
    quiz = course.quizzes[0]
    assert (quiz.lesson_key, quiz.passing_percentage, quiz.max_attempts) == ("ql", 80, 3)
    assert [(o.text, o.correct) for o in quiz.questions[0].options] == [("A", True), ("B", False)]
    assert (course.short_introduction, course.description) == ("short", "long")


def test_the_sample_course_in_the_repo_is_sound() -> None:
    root = Path(__file__).resolve().parents[2] / "content"
    course = load_course(root)
    assert course.key == "nile-workshop"
    assert len(course.quizzes) == 2


def test_a_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match=r"cannot read .*course\.yaml"):
        load_course(tmp_path)


def test_invalid_yaml_is_named(tmp_path: Path) -> None:
    assert "not valid YAML" in problems(tmp_path, "key: [unclosed")


def test_yaml_no_as_a_key_is_refused_and_named(tmp_path: Path) -> None:
    text = GOOD.replace("key: ch\n", "key: no\n")
    out = problems(tmp_path, text)
    assert "course.yaml: chapter" in out
    assert "key must be text, found bool False" in out


def test_a_number_for_a_video_id_is_refused(tmp_path: Path) -> None:
    out = problems(tmp_path, GOOD.replace("dQw4w9WgXcQ", "12345678901"))
    assert "lesson 'v'" in out
    assert "youtube must be text, found int" in out


def test_a_number_for_question_or_option_text_is_refused(tmp_path: Path) -> None:
    out = problems(
        tmp_path, GOOD.replace("text: Which?", "text: 5").replace("{text: B}", "{text: 7}")
    )
    assert "question 'q1': text must be text" in out
    assert "option 2: text must be text" in out


@pytest.mark.parametrize("path", ["../secret.md", "/etc/passwd", "labs/../../x.md"])
def test_a_body_file_outside_content_is_refused(tmp_path: Path, path: str) -> None:
    out = problems(tmp_path, GOOD.replace("labs/a.md", path))
    assert "points outside content/" in out


def test_a_missing_body_file_is_named(tmp_path: Path) -> None:
    out = problems(tmp_path, GOOD.replace("labs/a.md", "labs/none.md"))
    assert "lesson 'lab'" in out
    assert "'labs/none.md' does not exist" in out


def test_an_unknown_lesson_type_is_named(tmp_path: Path) -> None:
    assert "type must be video, lab or quiz, found 'slides'" in problems(
        tmp_path, GOOD.replace("type: lab", "type: slides")
    )


def test_correct_must_be_true_or_false(tmp_path: Path) -> None:
    assert "correct must be true or false" in problems(
        tmp_path, GOOD.replace("correct: true", "correct: yes please")
    )


def test_every_loader_problem_is_reported_at_once(tmp_path: Path) -> None:
    text = GOOD.replace("dQw4w9WgXcQ", "12345678901").replace("labs/a.md", "../x.md")
    out = problems(tmp_path, text)
    assert "youtube must be text" in out
    assert "outside content/" in out


def test_content_check_problems_come_back_too(tmp_path: Path) -> None:
    assert "has no correct option" in problems(
        tmp_path, GOOD.replace("correct: true", "correct: false")
    )


def test_a_top_level_list_is_refused(tmp_path: Path) -> None:
    assert "course: must be a mapping" in problems(tmp_path, "- a\n- b\n")


def test_a_non_utf8_body_file_is_not_a_traceback(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / "labs" / "a.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ContentError):
        load_course(tmp_path)
