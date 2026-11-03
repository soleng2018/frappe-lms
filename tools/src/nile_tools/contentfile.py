"""Read `content/course.yaml` and the lab markdown files into the frozen content model."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from nile_tools.content import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PASSING_PERCENTAGE,
    Chapter,
    Course,
    LabLesson,
    Lesson,
    Option,
    Question,
    Quiz,
    QuizLesson,
    VideoLesson,
    check_course,
)

__all__ = ["CONTENT_FILE", "ContentError", "load_course"]

CONTENT_FILE = "course.yaml"


class ContentError(Exception):
    """The content file cannot be turned into a sound course; `problems` lists every reason."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


class _Reader:
    """Collects problems while reading, so every one is reported at once."""

    def __init__(self, content_dir: Path) -> None:
        self.dir = content_dir
        self.file = content_dir / CONTENT_FILE
        self.problems: list[str] = []

    def problem(self, where: str, message: str) -> None:
        self.problems.append(f"{self.file.name}: {where}: {message}")

    def mapping(self, node: object, where: str) -> Mapping[str, Any]:
        if isinstance(node, Mapping):
            return node
        self.problem(where, "must be a mapping")
        return {}

    def items(self, node: object, where: str) -> list[object]:
        if node is None:
            return []
        if isinstance(node, list):
            return node
        self.problem(where, "must be a list")
        return []

    def text(
        self, node: Mapping[str, Any], field: str, where: str, *, required: bool = True
    ) -> str:
        value = node.get(field)
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            # YAML reads `no` as false and 12345678901 as a number, so say what was found.
            self.problem(where, f"{field} must be text, found {type(value).__name__} {value!r}")
            return ""
        return value

    def number(self, node: Mapping[str, Any], field: str, default: int, where: str) -> int:
        value = node.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int):
            self.problem(where, f"{field} must be a whole number, found {value!r}")
            return default
        return value

    def body(self, node: Mapping[str, Any], where: str) -> str:
        name = self.text(node, "body_file", where)
        if not name:
            return ""
        root = self.dir.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            self.problem(where, f"body_file {name!r} points outside content/")
        elif not path.is_file():
            self.problem(where, f"body_file {name!r} does not exist")
        else:
            try:
                return path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                self.problem(where, f"body_file {name!r} cannot be read as UTF-8 text: {e}")
        return ""


def _option(r: _Reader, node: object, where: str) -> Option:
    node = r.mapping(node, where)
    correct = node.get("correct", False)
    if not isinstance(correct, bool):
        r.problem(where, f"correct must be true or false, found {correct!r}")
    return Option(r.text(node, "text", where), correct is True)


def _question(r: _Reader, node: object, where: str) -> Question:
    node = r.mapping(node, where)
    key = r.text(node, "key", where)
    here = f"{where} question {key!r}"
    options = tuple(
        _option(r, o, f"{here} option {i}")
        for i, o in enumerate(r.items(node.get("options"), here), 1)
    )
    return Question(
        key=key,
        text=r.text(node, "text", here),
        marks=r.number(node, "marks", 1, here),
        options=options,
    )


def _quiz(r: _Reader, node: object, lesson_of: Mapping[str, str]) -> Quiz:
    node = r.mapping(node, "quiz")
    key = r.text(node, "key", "quiz")
    here = f"quiz {key!r}"
    return Quiz(
        key=key,
        title=r.text(node, "title", here),
        lesson_key=lesson_of.get(key, ""),
        questions=tuple(
            _question(r, q, here) for q in r.items(node.get("questions"), f"{here} questions")
        ),
        passing_percentage=r.number(node, "passing_percentage", DEFAULT_PASSING_PERCENTAGE, here),
        max_attempts=r.number(node, "max_attempts", DEFAULT_MAX_ATTEMPTS, here),
    )


def _lesson(r: _Reader, node: object, where: str) -> Lesson:
    node = r.mapping(node, where)
    key = r.text(node, "key", where)
    here = f"{where} lesson {key!r}"
    title = r.text(node, "title", here)
    kind = node.get("type")
    if kind == "video":
        return VideoLesson(key, title, r.text(node, "youtube", here))
    if kind == "quiz":
        return QuizLesson(key, title, r.text(node, "quiz", here))
    if kind != "lab":
        r.problem(here, f"type must be video, lab or quiz, found {kind!r}")
    return LabLesson(key, title, r.body(node, here))


def _chapter(r: _Reader, node: object) -> Chapter:
    node = r.mapping(node, "chapter")
    key = r.text(node, "key", "chapter")
    here = f"chapter {key!r}"
    lessons = tuple(_lesson(r, x, here) for x in r.items(node.get("lessons"), f"{here} lessons"))
    return Chapter(key, r.text(node, "title", here), lessons)


def _build(r: _Reader, node: object) -> Course:
    node = r.mapping(node, "course")
    chapters = tuple(_chapter(r, c) for c in r.items(node.get("chapters"), "chapters"))
    lesson_of = {
        x.quiz_key: x.key for c in chapters for x in c.lessons if isinstance(x, QuizLesson)
    }
    quizzes = tuple(_quiz(r, q, lesson_of) for q in r.items(node.get("quizzes"), "quizzes"))
    return Course(
        key=r.text(node, "key", "course"),
        title=r.text(node, "title", "course"),
        chapters=chapters,
        quizzes=quizzes,
        short_introduction=r.text(node, "short_introduction", "course"),
        description=r.text(node, "description", "course"),
    )


def load_course(content_dir: Path) -> Course:
    """Read `course.yaml` in `content_dir` and return the checked course, or raise ContentError."""
    r = _Reader(content_dir)
    try:
        raw = yaml.safe_load(r.file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise ContentError((f"cannot read {r.file}: {getattr(e, 'strerror', None) or e}",)) from e
    except yaml.YAMLError as e:
        raise ContentError((f"{r.file.name} is not valid YAML: {e}",)) from e
    course = _build(r, raw)
    problems = (*r.problems, *(() if r.problems else check_course(course)))
    if problems:
        raise ContentError(problems)
    return course
