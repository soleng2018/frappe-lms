"""Work out what the LMS needs so it matches the course in git. Pure: no network, no files."""

import html
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nile_tools import drift
from nile_tools.content import (
    MAX_OPTIONS,
    Course,
    Lesson,
    Question,
    Quiz,
    lesson_body,
    lesson_image_paths,
    lesson_quiz_key,
    lesson_video,
)

__all__ = [
    "CHAPTER",
    "COURSE",
    "LESSON",
    "QUESTION",
    "QUIZ",
    "Action",
    "Change",
    "Create",
    "Detach",
    "Found",
    "Ref",
    "Unmanaged",
    "Update",
    "course_progress",
    "held_elsewhere",
    "outline_changed",
    "plan_creates",
    "plan_sync",
]

COURSE = "LMS Course"
CHAPTER = "Course Chapter"
LESSON = "Course Lesson"
QUIZ = "LMS Quiz"
QUESTION = "LMS Question"

Doc = Mapping[str, Any]

# Rich text fields: Frappe escapes them on save, so both sides go through `_normalise`.
_RICH = frozenset({"description", "question", "body"})
# The fields that hold an ordered list of linked names (an outline table).
_TABLES = frozenset({"chapters", "lessons", "questions"})


@dataclass(frozen=True)
class Ref:
    """A record not yet in the LMS, named by its nile_key. Replaced by its name once created."""

    doctype: str
    key: str


@dataclass(frozen=True)
class Create:
    """A record git has and the LMS lacks, with only the fields it needs to exist."""

    doctype: str
    key: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class Change:
    """One field to overwrite: `found` is what the LMS shows, `wanted` is what git would write."""

    field: str
    found: object
    wanted: object


@dataclass(frozen=True)
class Update:
    """Overwrite these fields of an existing record. `notes` name outline rows that get dropped."""

    doctype: str
    key: str
    name: str
    changes: tuple[Change, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Detach:
    """A record the LMS has and git no longer does. It is kept; the writes happen on its parent."""

    doctype: str
    key: str
    name: str


@dataclass(frozen=True)
class Unmanaged:
    """An LMS record in the course that has no nile_key, so the sync does not manage it."""

    doctype: str
    name: str


Action = Update | Detach | Unmanaged


@dataclass(frozen=True)
class Found:
    """What the LMS holds for this course, as the API returned it (child tables included)."""

    course: Doc | None = None
    chapters: tuple[Doc, ...] = ()
    lessons: tuple[Doc, ...] = ()
    quizzes: tuple[Doc, ...] = ()
    questions: tuple[Doc, ...] = ()
    courses: tuple[Doc, ...] = ()  # every LMS Course: name, title, nile_key


def _normalise(field: str, value: object) -> object:
    if field.startswith("is_correct"):
        return int(bool(value))
    if field in _RICH and isinstance(value, str):
        return html.unescape(value).strip()
    return value


def _by_key(docs: Iterable[Doc]) -> dict[str, Doc]:
    return {d["nile_key"]: d for d in docs if d.get("nile_key")}


def _lessons(course: Course) -> list[Lesson]:
    return [lesson for chapter in course.chapters for lesson in chapter.lessons]


def _option_fields(question: Question) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for i in range(1, MAX_OPTIONS + 1):
        option = question.options[i - 1] if i <= len(question.options) else None
        fields[f"option_{i}"] = option.text if option else ""
        fields[f"is_correct_{i}"] = 1 if option and option.correct else 0
    return fields


def _question_fields(question: Question) -> dict[str, Any]:
    return {"question": question.text, "type": question.type, **_option_fields(question)}


def _course_fields(course: Course, urls: Mapping[str, str] | None = None) -> dict[str, Any]:
    known = urls or {}
    cover = {"image": known[course.image]} if course.image in known else {}
    return {
        **cover,
        "title": course.title,
        "short_introduction": course.short_introduction,
        "description": course.description,
        "published": 0,  # a learner reaches a course only through an enrollment (spec 0009)
        "status": "Approved",
        "enable_certification": 1,
        "enforce_lesson_completion": 0,
    }


def _lesson_fields(
    lesson: Lesson, quiz_name: str | None, urls: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """The fields git decides for a lesson. A part that is not known yet is left out.

    The body waits for the quiz name (a quiz block) and for the URL of every local image.
    """
    urls = urls or {}
    fields: dict[str, Any] = {"youtube": lesson_video(lesson)}
    has_quiz = lesson_quiz_key(lesson) is not None
    fields["quiz_id"] = (quiz_name or "") if has_quiz else ""
    if has_quiz and not quiz_name:
        del fields["quiz_id"]
    elif all(p in urls for p in lesson_image_paths(lesson)):
        fields["body"] = lesson_body(lesson, quiz_name, urls)
    return fields


def plan_creates(
    course: Course, found: Found, urls: Mapping[str, str] | None = None
) -> tuple[Create, ...]:
    """List the records git has that the LMS lacks, in an order that works.

    Each carries only what it needs to exist. Order: course, chapters, questions, quizzes
    (their question rows link to questions), then lessons. Links to records that are not
    created yet are `Ref`s, resolved to the LMS name when the earlier create returns.
    """
    have = {
        COURSE: _by_key([found.course] if found.course else []),
        CHAPTER: _by_key(found.chapters),
        QUESTION: _by_key(found.questions),
        QUIZ: _by_key(found.quizzes),
        LESSON: _by_key(found.lessons),
    }
    course_ref = Ref(COURSE, course.key)
    wanted: list[Create] = [Create(COURSE, course.key, _course_fields(course, urls))]
    wanted += [
        Create(CHAPTER, c.key, {"title": c.title, "course": course_ref}) for c in course.chapters
    ]
    for quiz in course.quizzes:
        wanted += [Create(QUESTION, q.key, _question_fields(q)) for q in quiz.questions]
    for quiz in course.quizzes:
        rows = [{"question": Ref(QUESTION, q.key), "marks": q.marks} for q in quiz.questions]
        quiz_fields: dict[str, Any] = {
            "title": quiz.title,
            "passing_percentage": quiz.passing_percentage,
            "max_attempts": quiz.max_attempts,
            "questions": rows,
        }
        wanted.append(Create(QUIZ, quiz.key, quiz_fields))
    for chapter in course.chapters:
        for lesson in chapter.lessons:
            fields = {"title": lesson.title, "chapter": Ref(CHAPTER, chapter.key)}
            made = {k: v for k, v in _lesson_fields(lesson, None, urls).items() if v != ""}
            wanted.append(Create(LESSON, lesson.key, fields | made))
    return tuple(c for c in wanted if c.key not in have[c.doctype])


def _names(docs: Iterable[Doc]) -> dict[str, str]:
    return {key: doc["name"] for key, doc in _by_key(docs).items()}


def _tuple_of(keys: Iterable[str], names: Mapping[str, str]) -> tuple[str, ...] | None:
    """Return the LMS names for these keys in order, or None if any is not in the LMS yet."""
    keys = tuple(keys)
    return tuple(names[k] for k in keys) if all(k in names for k in keys) else None


def _view(doctype: str, doc: Doc) -> dict[str, Any]:
    """Turn a record the LMS returned into plain comparable values (tables become tuples)."""
    view = dict(doc)
    if doctype == COURSE:
        view["chapters"] = tuple(r["chapter"] for r in doc.get("chapters") or ())
    elif doctype == CHAPTER:
        view["lessons"] = tuple(r["lesson"] for r in doc.get("lessons") or ())
    elif doctype == QUIZ:
        view["questions"] = tuple((r["question"], r["marks"]) for r in doc.get("questions") or ())
    return view


def payload(field: str, value: object) -> object:
    """Return the value in the shape the API takes: outline tuples become child table rows."""
    if field not in _TABLES or not isinstance(value, tuple):
        return value
    if field == "chapters":
        return [{"chapter": n} for n in value]
    if field == "lessons":
        return [{"lesson": n} for n in value]
    return [{"question": n, "marks": marks} for n, marks in value]


def _diff(
    doctype: str, key: str, wanted: Mapping[str, Any], doc: Doc, notes: tuple[str, ...] = ()
) -> Update | None:
    seen = _view(doctype, doc)
    want = {f: _normalise(f, v) for f, v in wanted.items()}
    have = {f: _normalise(f, seen.get(f)) for f in wanted}
    result = drift.compare(
        [drift.Record(doctype, key, want)], [drift.Record(doctype, key, have, doc["name"])]
    )
    changes = tuple(Change(d.field, d.found, wanted[d.field]) for d in result.differences)
    if not changes:
        return None
    return Update(doctype, key, doc["name"], changes, notes)


def _dropped_rows(
    found_rows: Iterable[str], wanted_rows: Iterable[str], skip: set[str]
) -> tuple[str, ...]:
    wanted = set(wanted_rows)
    return tuple(
        f"removed unmanaged row {name}"
        for name in found_rows
        if name not in wanted and name not in skip
    )


def _question_plan(
    quiz: Quiz, doc: Doc, questions: Mapping[str, str], keyed: Mapping[str, Doc], git_keys: set[str]
) -> tuple[dict[str, Any], tuple[str, ...], list[Detach]]:
    """Return the quiz's wanted `questions`, notes for unkeyed rows, and the questions detached."""
    wanted = _tuple_of((q.key for q in quiz.questions), questions)
    by_name = {d["name"]: d for d in keyed.values()}
    detached, notes = [], []
    for row in doc.get("questions") or ():
        other = by_name.get(row["question"])
        if other and other["nile_key"] not in git_keys:
            detached.append(Detach(QUESTION, other["nile_key"], other["name"]))
        elif other is None:
            notes.append(f"removed unmanaged row {row['question']}")
    if wanted is None:
        return {}, tuple(notes), detached
    marks = {q.key: q.marks for q in quiz.questions}
    rows = tuple((questions[k], marks[k]) for k in marks)
    return {"questions": rows}, tuple(notes), detached


def plan_sync(
    course: Course, found: Found, urls: Mapping[str, str] | None = None
) -> tuple[Action, ...]:
    """Compare git with the LMS and list every update, detach and unmanaged record.

    Records the LMS does not have yet are left to `plan_creates`. A field that links to such a
    record is left out until the record exists, so the plan is complete once creates are done.
    """
    if found.course is None:
        return ()
    cname = found.course["name"]
    chapters, lessons = _names(found.chapters), _names(found.lessons)
    quizzes, questions = _names(found.quizzes), _names(found.questions)
    git = {
        CHAPTER: {c.key for c in course.chapters},
        LESSON: {x.key for x in _lessons(course)},
        QUIZ: {q.key for q in course.quizzes},
        QUESTION: {q.key for quiz in course.quizzes for q in quiz.questions},
    }
    keyed_questions = _by_key(found.questions)
    detached = _detached(found, git)
    detached_names = {d.name for d in detached}  # reported as detached, not as unmanaged rows
    actions: list[Action] = []

    def add(update: Update | None) -> None:
        if update:
            actions.append(update)

    for quiz in course.quizzes:
        for q in quiz.questions:
            if doc := keyed_questions.get(q.key):
                add(_diff(QUESTION, q.key, _question_fields(q), doc))

    quiz_of = {x.key: k for x in _lessons(course) if (k := lesson_quiz_key(x))}
    for chapter in course.chapters:
        for lesson in chapter.lessons:
            doc = _by_key(found.lessons).get(lesson.key)
            if doc is None or chapter.key not in chapters:
                continue
            quiz_name = quizzes.get(quiz_of.get(lesson.key, ""))
            fields = {"title": lesson.title, "chapter": chapters[chapter.key]}
            fields |= _lesson_fields(lesson, quiz_name, urls)
            add(_diff(LESSON, lesson.key, fields, doc))

    for chapter in course.chapters:
        doc = _by_key(found.chapters).get(chapter.key)
        if doc is None:
            continue
        chapter_fields: dict[str, Any] = {"title": chapter.title, "course": cname}
        rows = _tuple_of((x.key for x in chapter.lessons), lessons)
        if rows is not None:
            chapter_fields["lessons"] = rows
        found_rows = tuple(r["lesson"] for r in doc.get("lessons") or ())
        moved = detached_names | set(
            lessons.values()
        )  # a lesson wanted elsewhere moved, not unmanaged
        notes = _dropped_rows(found_rows, rows, moved) if rows is not None else ()
        add(_diff(CHAPTER, chapter.key, chapter_fields, doc, notes))

    course_fields = _course_fields(course, urls)
    chapter_rows = _tuple_of((c.key for c in course.chapters), chapters)
    found_chapters = tuple(r["chapter"] for r in found.course.get("chapters") or ())
    if chapter_rows is not None:
        course_fields["chapters"] = chapter_rows
    notes = (
        _dropped_rows(found_chapters, chapter_rows, detached_names)
        if chapter_rows is not None
        else ()
    )
    if found.course.get("title") and found.course["title"] != course.title:
        notes = (_retitle_note(found.course["title"], course.title), *notes)
    add(_diff(COURSE, course.key, course_fields, found.course, notes))

    detached_questions: list[Detach] = []
    for quiz in course.quizzes:
        doc = _by_key(found.quizzes).get(quiz.key)
        if doc is None:
            continue
        quiz_fields: dict[str, Any] = {
            "title": quiz.title,
            "passing_percentage": quiz.passing_percentage,
            "max_attempts": quiz.max_attempts,
            "course": cname,
        }
        lesson_key = quiz.lesson_key
        if lesson_key in lessons:
            quiz_fields["lesson"] = lessons[lesson_key]
        table, notes, lost = _question_plan(quiz, doc, questions, keyed_questions, git[QUESTION])
        detached_questions += lost
        add(_diff(QUIZ, quiz.key, quiz_fields | table, doc, notes))

    for gone in detached:
        if gone.doctype == QUIZ:
            doc = _by_key(found.quizzes)[gone.key]
            if doc.get("lesson"):
                add(_diff(QUIZ, gone.key, {"lesson": ""}, doc))

    actions += [*detached, *detached_questions]
    actions += _unmanaged(found)
    return tuple(actions)


def _retitle_note(old: str, new: str) -> str:
    return (
        f"title changes from {old!r} to {new!r}: the Authentik group name must change too, "
        "or learners lose the course"
    )


def title_clash(course: Course, found: Found, admin_group: str) -> str | None:
    """Name the clash when creating or retitling would hit another course or the admin group.

    Titles are compared here with the case kept, because the REST filter ignores case.
    """
    here = found.course["name"] if found.course else None
    if found.course is not None and found.course.get("title") == course.title:
        return None
    if admin_group and course.title == admin_group:
        return f"course title {course.title!r} equals the admin group name (AUTHENTIK_ADMIN_GROUP)"
    for other in found.courses:
        if other.get("name") != here and other.get("title") == course.title:
            return (
                f"another LMS Course ({other.get('name')}) already has the title {course.title!r}"
            )
    return None


def held_elsewhere(course: Course, found: Found) -> str | None:
    """Name a chapter, lesson or quiz of this course that the LMS holds under another course."""
    here = found.course["name"] if found.course else None
    titles = {c.get("name"): f"{c.get('title')!r} ({c.get('name')})" for c in found.courses}
    wanted = {
        CHAPTER: {c.key for c in course.chapters},
        LESSON: {x.key for x in _lessons(course)},
        QUIZ: {q.key for q in course.quizzes},
    }
    kinds = ((CHAPTER, found.chapters), (LESSON, found.lessons), (QUIZ, found.quizzes))
    for doctype, docs in kinds:
        for doc in docs:
            owner = doc.get("course")
            if doc.get("nile_key") in wanted[doctype] and owner and owner != here:
                return (
                    f"{doctype} {doc['nile_key']} is held by LMS course "
                    f"{titles.get(owner, owner)}, not by this course"
                )
    return None


def _detached(found: Found, git: Mapping[str, set[str]]) -> list[Detach]:
    """List records git dropped that are still attached: in an outline, or holding their lesson."""
    in_chapters = {r["chapter"] for r in (found.course or {}).get("chapters") or ()}
    in_lessons = {
        r["lesson"]
        for d in found.chapters
        if d["name"] in in_chapters
        for r in d.get("lessons") or ()
    }
    attached = {
        CHAPTER: lambda d: d["name"] in in_chapters,
        LESSON: lambda d: d["name"] in in_lessons,
        QUIZ: lambda d: bool(d.get("lesson")),
    }
    kinds = ((CHAPTER, found.chapters), (LESSON, found.lessons), (QUIZ, found.quizzes))
    return [
        Detach(doctype, doc["nile_key"], doc["name"])
        for doctype, docs in kinds
        for doc in docs
        if doc.get("nile_key") and doc["nile_key"] not in git[doctype] and attached[doctype](doc)
    ]


def _unmanaged(found: Found) -> list[Action]:
    kinds = ((CHAPTER, found.chapters), (LESSON, found.lessons), (QUIZ, found.quizzes))
    return [
        Unmanaged(doctype, doc["name"])
        for doctype, docs in kinds
        for doc in docs
        if not doc.get("nile_key")
    ]


def outline_changed(creates: Sequence[Create], actions: Sequence[Action]) -> bool:
    """True when lessons were added to, moved in, or dropped from the course outline."""
    if any(c.doctype == LESSON for c in creates):
        return True
    for a in actions:
        if isinstance(a, Detach) and a.doctype in (LESSON, CHAPTER):
            return True
        if isinstance(a, Update) and any(c.field in ("lessons", "chapters") for c in a.changes):
            return True
    return False


def course_progress(completed: Iterable[str], outline: Sequence[str]) -> float:
    """Return progress as LMS does: completed lessons still in the outline over the outline."""
    if not outline:
        return 0.0
    done = len(set(completed) & set(outline))
    return round(min(done / len(outline) * 100, 100), 3)
