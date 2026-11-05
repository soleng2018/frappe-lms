"""The course content model and the check that runs before anything is written to the LMS."""

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from nile_tools.markdown import local_image_paths, rewrite_images

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_PASSING_PERCENTAGE",
    "MAX_OPTIONS",
    "MIN_PASSING_PERCENTAGE",
    "Block",
    "Chapter",
    "Course",
    "Image",
    "Lesson",
    "Option",
    "Problem",
    "Question",
    "QuestionType",
    "Quiz",
    "QuizBlock",
    "TextBlock",
    "VideoBlock",
    "lesson_body",
    "lesson_image_paths",
    "lesson_quiz_key",
    "lesson_video",
]

DEFAULT_PASSING_PERCENTAGE = 80
DEFAULT_MAX_ATTEMPTS = 3
MIN_PASSING_PERCENTAGE = 80  # a certificate means 80% or more on every quiz (spec 0010)
MAX_OPTIONS = 4  # an LMS Question has option_1 to option_4

# The question types LMS knows. Only Open Ended is never graded automatically.
QuestionType = Literal["Choices", "User Input", "Open Ended"]


@dataclass(frozen=True)
class Option:
    """One answer to a multiple choice question."""

    text: str
    correct: bool = False


@dataclass(frozen=True)
class Question:
    """One LMS Question. Only `Choices` questions carry options."""

    key: str
    text: str
    type: QuestionType = "Choices"
    marks: int = 1
    options: tuple[Option, ...] = ()


@dataclass(frozen=True)
class Quiz:
    """One LMS Quiz, linked to exactly one lesson by `lesson_key` (the lesson with its block)."""

    key: str
    title: str
    lesson_key: str
    questions: tuple[Question, ...]
    passing_percentage: int = DEFAULT_PASSING_PERCENTAGE
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    file: str = ""  # the quiz file, relative to the course folder, for messages


@dataclass(frozen=True)
class TextBlock:
    """A markdown file in the course folder, shown as it is."""

    path: str
    markdown: str


@dataclass(frozen=True)
class VideoBlock:
    """A YouTube video, by its 11 character id."""

    youtube: str


@dataclass(frozen=True)
class QuizBlock:
    """A quiz, named by its key."""

    quiz_key: str


Block = TextBlock | VideoBlock | QuizBlock


@dataclass(frozen=True)
class Lesson:
    """One lesson: blocks in reading order."""

    key: str
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Chapter:
    """One chapter. Lesson order is the order of the tuple."""

    key: str
    title: str
    lessons: tuple[Lesson, ...]


@dataclass(frozen=True)
class Image:
    """A local image file, read at load. `path` is relative to the course folder."""

    path: str
    data: bytes
    alt: str = ""


@dataclass(frozen=True)
class Course:
    """One course: chapter order is the order of the tuple, quizzes sit beside the chapters."""

    key: str
    title: str
    chapters: tuple[Chapter, ...]
    quizzes: tuple[Quiz, ...] = ()
    short_introduction: str = ""
    description: str = ""
    image: str = ""  # the cover, a path relative to the course folder, or empty
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class Problem:
    """One thing wrong (or, with `warning`, worth a look) in a course's files."""

    course: str
    file: str
    where: str
    message: str
    warning: bool = False

    def line(self) -> str:
        """Return the one line `ERROR <course>/<file>: <where>: <message>` (or `WARN ...`)."""
        path = f"{self.course}/{self.file}" if self.course else self.file
        return f"{'WARN' if self.warning else 'ERROR'} {path}: {self.where}: {self.message}"

    def sort_key(self) -> tuple[str, str, str, str]:
        """Order by course, file, then where."""
        return (self.course, self.file, self.where, self.message)


def lesson_video(lesson: Lesson) -> str:
    """Return the video id of the lesson's video block, or an empty string."""
    return next((b.youtube for b in lesson.blocks if isinstance(b, VideoBlock)), "")


def lesson_quiz_key(lesson: Lesson) -> str | None:
    """Return the quiz key of the lesson's quiz block, or None."""
    return next((b.quiz_key for b in lesson.blocks if isinstance(b, QuizBlock)), None)


def lesson_image_paths(lesson: Lesson) -> list[str]:
    """List the resolved path of every local image in the lesson's text blocks."""
    return [
        p
        for b in lesson.blocks
        if isinstance(b, TextBlock)
        for p in local_image_paths(b.markdown, posixpath.dirname(b.path))
    ]


def lesson_body(
    lesson: Lesson, quiz_name: str | None = None, urls: Mapping[str, str] | None = None
) -> str:
    """Return the `body` the LMS needs: each block rendered, stripped, joined by a blank line.

    `quiz_name` is the name LMS gave the quiz, so it is only known after the quiz is created.
    `urls` maps a resolved image path to its LMS URL.
    """
    parts: list[str] = []
    for block in lesson.blocks:
        match block:
            case TextBlock(path=path, markdown=text):
                parts.append(rewrite_images(text, posixpath.dirname(path), urls or {}).strip())
            case VideoBlock(youtube=video_id):
                parts.append(f'{{{{ YouTubeVideo("{video_id}") }}}}')
            case QuizBlock():
                if not quiz_name:
                    raise ValueError(f"lesson {lesson.key!r} needs the quiz name to build its body")
                parts.append(f'{{{{ Quiz("{quiz_name}") }}}}')
    return "\n\n".join(p for p in parts if p)
