"""The checks on a loaded course, and across courses. Pure: they only read the model."""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from nile_tools.content import (
    MAX_OPTIONS,
    MIN_PASSING_PERCENTAGE,
    Chapter,
    Course,
    Lesson,
    Problem,
    Question,
    Quiz,
    QuizBlock,
    VideoBlock,
)

__all__ = ["COURSE_FILE", "check_across", "check_course"]

COURSE_FILE = "course.yaml"
# A YouTube video id: 11 letters, digits, dashes or underscores. A URL is not an id.
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def _repeats(keys: Iterable[str]) -> list[str]:
    return sorted(k for k, n in Counter(keys).items() if n > 1)


def _at(chapter: Chapter, lesson: Lesson | None = None) -> str:
    here = f"chapters[{chapter.key or '?'}]"
    return here if lesson is None else f"{here}.lessons[{lesson.key or '?'}]"


def _lesson_problems(
    folder: str, chapter: Chapter, lesson: Lesson, quiz_keys: set[str]
) -> list[Problem]:
    where = _at(chapter, lesson)
    out: list[Problem] = []

    def add(message: str, at: str = where) -> None:
        out.append(Problem(folder, COURSE_FILE, at, message))

    if not lesson.blocks:
        add("a lesson needs at least one block")
    videos = [b for b in lesson.blocks if isinstance(b, VideoBlock)]
    quizzes = [b for b in lesson.blocks if isinstance(b, QuizBlock)]
    if len(videos) > 1:
        add("a lesson may hold at most one video block")
    if len(quizzes) > 1:
        add("a lesson may hold at most one quiz block")
    for i, block in enumerate(lesson.blocks):
        at = f"{where}.blocks[{i}]"
        if isinstance(block, VideoBlock) and not _VIDEO_ID.fullmatch(block.youtube):
            add(f"video {block.youtube!r} must be the 11 character video id, not a link", at)
        if isinstance(block, QuizBlock) and block.quiz_key not in quiz_keys:
            add(f"quiz {block.quiz_key!r} has no file in quizzes/", at)
    return out


def _choice_problems(question: Question) -> list[str]:
    if question.type != "Choices":
        return []
    options = question.options
    problems = []
    if not question.text.strip():
        problems.append("the question has no text")
    if not 2 <= len(options) <= MAX_OPTIONS:
        problems.append(f"{len(options)} options, must be 2 to {MAX_OPTIONS}")
    if not any(o.correct for o in options):
        problems.append("no correct option")
    if any(not o.text.strip() for o in options):
        problems.append("an empty option")
    texts = [o.text.strip() for o in options if o.text.strip()]
    problems += [f"repeats the option {t!r}" for t in _repeats(texts)]
    return problems


def _quiz_problems(folder: str, quiz: Quiz) -> list[Problem]:
    file = quiz.file or COURSE_FILE
    out: list[Problem] = []

    def add(where: str, message: str) -> None:
        out.append(Problem(folder, file, where, message))

    if not MIN_PASSING_PERCENTAGE <= quiz.passing_percentage <= 100:
        add(
            "passing_percentage",
            f"{quiz.passing_percentage}, must be {MIN_PASSING_PERCENTAGE} to 100",
        )
    if quiz.max_attempts < 1:
        add("max_attempts", f"{quiz.max_attempts}, must be at least 1")
    if not quiz.questions:
        add("questions", "a quiz has no questions")  # LMS would force the pass mark to 100
    for q in quiz.questions:
        where = f"questions[{q.key or '?'}]"
        for message in _choice_problems(q):
            add(where, message)
        if q.type == "Open Ended":
            add(where, "open ended, so it is never graded and the lesson could never complete")
    return out


def check_course(course: Course, folder: str) -> tuple[Problem, ...]:
    """Return every problem in the course model at once, or an empty tuple when it is sound."""
    out: list[Problem] = []
    lessons = [(c, x) for c in course.chapters for x in c.lessons]
    quiz_keys = {q.key for q in course.quizzes}
    kinds = {
        "chapter": [(c.key, _at(c)) for c in course.chapters],
        "lesson": [(x.key, _at(c, x)) for c, x in lessons],
        "quiz": [(q.key, "key") for q in course.quizzes],
        "question": [(q.key, f"questions[{q.key}]") for z in course.quizzes for q in z.questions],
    }
    for kind, items in kinds.items():
        for key, where in items:
            if not key.strip():
                out.append(Problem(folder, COURSE_FILE, where, f"a {kind} key is empty"))
        for dup in _repeats(k for k, _ in items if k.strip()):
            if kind in ("quiz", "question"):
                file = next(
                    (
                        z.file
                        for z in course.quizzes
                        if dup in (z.key, *(q.key for q in z.questions))
                    ),
                    COURSE_FILE,
                )
            else:
                file = COURSE_FILE
            where = next(w for k, w in items if k == dup)
            out.append(
                Problem(
                    folder, file or COURSE_FILE, where, f"{kind} key {dup!r} is used more than once"
                )
            )
    for chapter in course.chapters:
        if not chapter.lessons:
            out.append(
                Problem(folder, COURSE_FILE, _at(chapter), "a chapter needs at least one lesson")
            )
    for chapter, lesson in lessons:
        out += _lesson_problems(folder, chapter, lesson, quiz_keys)
    used = Counter(b.quiz_key for _, x in lessons for b in x.blocks if isinstance(b, QuizBlock))
    for quiz in course.quizzes:
        n = used.get(quiz.key, 0)
        if n == 0:
            out.append(
                Problem(
                    folder,
                    quiz.file or COURSE_FILE,
                    "key",
                    f"quiz {quiz.key!r} is not used by any quiz block",
                )
            )
        elif n > 1:
            out.append(
                Problem(
                    folder,
                    quiz.file or COURSE_FILE,
                    "key",
                    f"quiz {quiz.key!r} is used by {n} quiz blocks, it must be used once",
                )
            )
        out += _quiz_problems(folder, quiz)
    return tuple(out)


def check_across(courses: Mapping[str, Course]) -> tuple[Problem, ...]:
    """Find clashes between courses: equal titles, and keys that two courses both use.

    `courses` maps the folder name to the course. One problem is returned per course involved.
    """
    out: list[Problem] = []
    titles: dict[str, list[str]] = defaultdict(list)
    for folder, course in courses.items():
        if course.title.strip():
            titles[course.title.strip().casefold()].append(folder)
    for folders in titles.values():
        for folder in folders:
            others = ", ".join(f for f in folders if f != folder)
            if others:
                out.append(
                    Problem(
                        folder,
                        COURSE_FILE,
                        "title",
                        f"the title is also used by {others} (case ignored)",
                    )
                )
    owners: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for folder, course in courses.items():
        for c in course.chapters:
            owners[("chapter", c.key)].append((folder, COURSE_FILE, _at(c)))
            for x in c.lessons:
                owners[("lesson", x.key)].append((folder, COURSE_FILE, _at(c, x)))
        for q in course.quizzes:
            owners[("quiz", q.key)].append((folder, q.file or COURSE_FILE, "key"))
            for question in q.questions:
                owners[("question", question.key)].append(
                    (folder, q.file or COURSE_FILE, f"questions[{question.key}]")
                )
    for (kind, key), places in owners.items():
        involved = sorted({f for f, _, _ in places})
        if not key.strip() or len(involved) < 2:
            continue
        for folder, file, where in places:
            others = ", ".join(f for f in involved if f != folder)
            if others:
                out.append(
                    Problem(
                        folder,
                        file,
                        where,
                        f"{kind} key {key!r} is also used by {others}; keys must be unique",
                    )
                )
    return tuple(sorted(set(out), key=Problem.sort_key))
