"""The course content model and the check that runs before anything is written to the LMS."""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_PASSING_PERCENTAGE",
    "MAX_OPTIONS",
    "MIN_PASSING_PERCENTAGE",
    "Chapter",
    "Course",
    "LabLesson",
    "Lesson",
    "Option",
    "Question",
    "QuestionType",
    "Quiz",
    "QuizLesson",
    "VideoLesson",
    "check_course",
    "lesson_body",
]

DEFAULT_PASSING_PERCENTAGE = 80
DEFAULT_MAX_ATTEMPTS = 3
MIN_PASSING_PERCENTAGE = 80  # a certificate means 80% or more on every quiz (spec 0010)
MAX_OPTIONS = 4  # an LMS Question has option_1 to option_4

# A YouTube video id: 11 letters, digits, dashes or underscores. A URL is not an id.
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")

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
    """One LMS Quiz, linked to exactly one quiz lesson by `lesson_key`."""

    key: str
    title: str
    lesson_key: str
    questions: tuple[Question, ...]
    passing_percentage: int = DEFAULT_PASSING_PERCENTAGE
    max_attempts: int = DEFAULT_MAX_ATTEMPTS


@dataclass(frozen=True)
class VideoLesson:
    """A lesson that shows a YouTube video."""

    key: str
    title: str
    youtube: str


@dataclass(frozen=True)
class LabLesson:
    """A lab guide lesson. The body is markdown from git."""

    key: str
    title: str
    body: str


@dataclass(frozen=True)
class QuizLesson:
    """A lesson that holds a quiz, named by `quiz_key`."""

    key: str
    title: str
    quiz_key: str


Lesson = VideoLesson | LabLesson | QuizLesson


@dataclass(frozen=True)
class Chapter:
    """One chapter. Lesson order is the order of the tuple."""

    key: str
    title: str
    lessons: tuple[Lesson, ...]


@dataclass(frozen=True)
class Course:
    """The one course: chapter order is the order of the tuple, quizzes sit beside the chapters."""

    key: str
    title: str
    chapters: tuple[Chapter, ...]
    quizzes: tuple[Quiz, ...] = ()
    short_introduction: str = ""
    description: str = ""


def lesson_body(lesson: Lesson, quiz_name: str | None = None) -> str:
    """Return the `body` the LMS needs: a video or quiz macro, or the lab markdown.

    `quiz_name` is the name LMS gave the quiz, so it is only known after the quiz is created.
    """
    match lesson:
        case VideoLesson(youtube=video_id):
            return f'{{{{ YouTubeVideo("{video_id}") }}}}'
        case QuizLesson(key=key):
            if not quiz_name:
                raise ValueError(f"quiz lesson {key!r} needs the quiz name to build its body")
            return f'{{{{ Quiz("{quiz_name}") }}}}'
        case LabLesson(body=body):
            return body


def _repeats(keys: Iterable[str]) -> list[str]:
    return sorted(k for k, n in Counter(keys).items() if n > 1)


def _key_problems(course: Course) -> list[str]:
    lessons = [lesson for chapter in course.chapters for lesson in chapter.lessons]
    kinds = {
        "chapter": [c.key for c in course.chapters],
        "lesson": [lesson.key for lesson in lessons],
        "quiz": [q.key for q in course.quizzes],
        "question": [q.key for quiz in course.quizzes for q in quiz.questions],
    }
    problems = [f"course nile_key is empty: {course.title!r}"] if not course.key.strip() else []
    for kind, keys in kinds.items():
        problems += [f"{kind} nile_key is empty" for k in keys if not k.strip()]
        problems += [
            f"{kind} nile_key is repeated: {k!r}" for k in _repeats(k for k in keys if k.strip())
        ]
    return problems


def _link_problems(course: Course) -> list[str]:
    lessons = [lesson for chapter in course.chapters for lesson in chapter.lessons]
    quiz_lessons = {x.key: x for x in lessons if isinstance(x, QuizLesson)}
    quizzes = {q.key: q for q in course.quizzes}
    problems = []
    for quiz in course.quizzes:
        lesson = quiz_lessons.get(quiz.lesson_key)
        if lesson is None:
            problems.append(
                f"quiz {quiz.key!r} has no quiz lesson (lesson_key {quiz.lesson_key!r})"
            )
        elif lesson.quiz_key != quiz.key:
            problems.append(
                f"quiz {quiz.key!r} names lesson {lesson.key!r}, "
                f"which holds quiz {lesson.quiz_key!r}"
            )
    for lesson in quiz_lessons.values():
        if lesson.quiz_key not in quizzes:
            problems.append(
                f"quiz lesson {lesson.key!r} has no quiz (quiz_key {lesson.quiz_key!r})"
            )
    shared = _repeats(x.quiz_key for x in quiz_lessons.values())
    problems += [f"quiz {k!r} is used by more than one lesson" for k in shared]
    return problems


def _video_problems(course: Course) -> list[str]:
    videos = (x for c in course.chapters for x in c.lessons if isinstance(x, VideoLesson))
    return [
        f"video lesson {v.key!r} youtube is {v.youtube!r}, must be the 11 character video id"
        for v in videos
        if not _VIDEO_ID.fullmatch(v.youtube)
    ]


def _choice_problems(quiz_name: str, question: Question) -> list[str]:
    if question.type != "Choices":
        return []
    name = f"{quiz_name} question {question.key!r}"
    options = question.options
    problems = []
    if not question.text.strip():
        problems.append(f"{name} has no text")
    if not 2 <= len(options) <= MAX_OPTIONS:
        problems.append(f"{name} has {len(options)} options, must be 2 to {MAX_OPTIONS}")
    if not any(o.correct for o in options):
        problems.append(f"{name} has no correct option")
    if any(not o.text.strip() for o in options):
        problems.append(f"{name} has an empty option")
    texts = [o.text.strip() for o in options if o.text.strip()]
    problems += [f"{name} repeats the option {t!r}" for t in _repeats(texts)]
    return problems


def _quiz_problems(quiz: Quiz) -> list[str]:
    name = f"quiz {quiz.key!r}"
    problems = []
    if not MIN_PASSING_PERCENTAGE <= quiz.passing_percentage <= 100:
        problems.append(
            f"{name} passing_percentage is {quiz.passing_percentage}, "
            f"must be {MIN_PASSING_PERCENTAGE} to 100"
        )
    if quiz.max_attempts < 1:
        problems.append(f"{name} max_attempts is {quiz.max_attempts}, must be at least 1")
    if not quiz.questions:
        # LMS would force the pass mark of a quiz with no questions to 100.
        problems.append(f"{name} has no questions")
    for q in quiz.questions:
        problems += _choice_problems(name, q)
    problems += [
        f"{name} question {q.key!r} is open ended, so it is never graded "
        "and the lesson could never complete"
        for q in quiz.questions
        if q.type == "Open Ended"
    ]
    return problems


def check_course(course: Course) -> tuple[str, ...]:
    """Return every problem in the course at once, or an empty tuple when it is sound."""
    problems = _key_problems(course) + _link_problems(course) + _video_problems(course)
    problems += [f"chapter {c.key!r} has no lessons" for c in course.chapters if not c.lessons]
    for quiz in course.quizzes:
        problems += _quiz_problems(quiz)
    return tuple(problems)
