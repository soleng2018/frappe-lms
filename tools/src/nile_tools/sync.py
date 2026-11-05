"""Push the course from git to the LMS: read, plan, then apply (or only report with `--check`)."""

import posixpath
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from nile_tools import images, plan
from nile_tools.content import Course
from nile_tools.contentfile import Catalog
from nile_tools.lms import (
    Lms,
    LmsError,
    create_record,
    get_record,
    list_records,
    update_record,
    upload_file,
)
from nile_tools.plan import (
    Action,
    Create,
    Detach,
    Found,
    Ref,
    Unmanaged,
    Update,
)

__all__ = ["read_state", "run_sync", "sync_all"]

ENROLLMENT = "LMS Enrollment"
PROGRESS = "LMS Course Progress"
_SHORT = 60

Say = Callable[[str], None]
Names = dict[tuple[str, str], str]


def _short(value: object) -> str:
    """Show a value on one line, long text cut."""
    text = " ".join(str(value).split()) if not isinstance(value, tuple) else repr(list(value))
    return repr(text if len(text) <= _SHORT else text[:_SHORT] + "...")


def _merge(*groups: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: dict[str, Mapping[str, Any]] = {}
    for group in groups:
        for doc in group:
            seen.setdefault(doc["name"], doc)
    return list(seen.values())


def _in(keys: Sequence[str]) -> list[list[object]]:
    return [["nile_key", "in", list(keys)]]


def _lms_courses(lms: Lms) -> tuple[Mapping[str, Any], ...]:
    return tuple(list_records(lms, plan.COURSE, fields=["name", "title", "nile_key"]))


def read_state(
    lms: Lms, course: Course, courses: tuple[Mapping[str, Any], ...] | None = None
) -> Found:
    """Read what the LMS holds for this course: by `nile_key`, and by `course` for strays."""
    courses = _lms_courses(lms) if courses is None else courses
    found = list_records(lms, plan.COURSE, filters=[["nile_key", "=", course.key]])
    doc = get_record(lms, plan.COURSE, found[0]["name"]) if found else None
    here = [["course", "=", doc["name"]]] if doc else None
    lesson_keys = [x.key for c in course.chapters for x in c.lessons]
    chapters = _merge(
        list_records(lms, plan.CHAPTER, filters=here) if here else (),
        list_records(lms, plan.CHAPTER, filters=_in([c.key for c in course.chapters])),
    )
    lessons = _merge(
        list_records(lms, plan.LESSON, filters=here) if here else (),
        list_records(lms, plan.LESSON, filters=_in(lesson_keys)),
    )
    quizzes = _merge(
        list_records(lms, plan.QUIZ, filters=here) if here else (),
        list_records(lms, plan.QUIZ, filters=_in([q.key for q in course.quizzes])),
    )
    quizzes = [get_record(lms, plan.QUIZ, q["name"]) for q in quizzes]
    chapters = [get_record(lms, plan.CHAPTER, c["name"]) for c in chapters]
    question_keys = [q.key for quiz in course.quizzes for q in quiz.questions]
    in_quizzes = sorted({r["question"] for q in quizzes for r in q.get("questions") or ()})
    questions = _merge(
        list_records(lms, plan.QUESTION, filters=[["name", "in", in_quizzes]])
        if in_quizzes
        else (),
        list_records(lms, plan.QUESTION, filters=_in(question_keys)) if question_keys else (),
    )
    return Found(doc, tuple(chapters), tuple(lessons), tuple(quizzes), tuple(questions), courses)


def _names(found: Found) -> Names:
    kinds = (
        (plan.COURSE, [found.course] if found.course else []),
        (plan.CHAPTER, found.chapters),
        (plan.LESSON, found.lessons),
        (plan.QUIZ, found.quizzes),
        (plan.QUESTION, found.questions),
    )
    return {(t, d["nile_key"]): d["name"] for t, docs in kinds for d in docs if d.get("nile_key")}


def _resolve(value: object, names: Names) -> object:
    if isinstance(value, Ref):
        return names[(value.doctype, value.key)]
    if isinstance(value, Mapping):
        return {k: _resolve(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, names) for v in value]
    return value


def _create_all(lms: Lms, creates: Sequence[Create], names: Names, say: Say) -> None:
    for c in creates:
        data = {k: _resolve(v, names) for k, v in c.fields.items()} | {"nile_key": c.key}
        made = create_record(lms, c.doctype, data, label=f"{c.doctype} {c.key}")
        names[(c.doctype, c.key)] = made["name"]
        say(f"created {c.doctype} {c.key}")


def _is_empty(value: object) -> bool:
    return value is None or value == "" or value == ()


def _overwrites(update: Update) -> list[str]:
    return [
        f"{update.doctype} {update.key} {c.field}: LMS has {_short(c.found)}, "
        f"git has {_short(c.wanted)}"
        for c in update.changes
        if not _is_empty(c.found)
    ]


def _apply(lms: Lms, action: Action, say: Say) -> None:
    match action:
        case Update(doctype=doctype, key=key, name=name, changes=changes, notes=notes):
            for note in notes:
                say(f"{doctype} {key}: {note}")
            for line in _overwrites(action):
                say(line)
            body = {c.field: plan.payload(c.field, c.wanted) for c in changes}
            update_record(lms, doctype, name, body, label=f"{doctype} {key}")
            say(f"updated {doctype} {key}: {', '.join(c.field for c in changes)}")
        case Detach(doctype=doctype, key=key):
            say(f"detached {doctype} {key} (kept in the LMS, out of the course)")
        case Unmanaged(doctype=doctype, name=name):
            say(f"unmanaged {doctype} {name}: has no nile_key, left alone")


def _report(creates: Sequence[Create], actions: Sequence[Action]) -> list[str]:
    """Lines for `--check`: everything a real run would create, change, detach or leave alone."""
    lines = [f"would create {c.doctype} {c.key}" for c in creates]
    for a in actions:
        match a:
            case Update():
                lines += [f"differs: {line}" for line in _overwrites(a)]
                lines += [f"{a.doctype} {a.key}: {n}" for n in a.notes]
                lines += [
                    f"differs: {a.doctype} {a.key} {c.field}: LMS has nothing, "
                    f"git has {_short(c.wanted)}"
                    for c in a.changes
                    if _is_empty(c.found)
                ]
            case Detach():
                lines.append(f"would detach {a.doctype} {a.key}")
            case Unmanaged():
                lines.append(f"unmanaged {a.doctype} {a.name}: has no nile_key")
    return lines


def _recompute_progress(lms: Lms, course_name: str, outline: Sequence[str], say: Say) -> int:
    """Set stored progress from the lessons still in the outline, as LMS itself computes it."""
    enrolled = list_records(
        lms,
        ENROLLMENT,
        filters=[["course", "=", course_name]],
        fields=["name", "member", "progress"],
    )
    if not enrolled:
        return 0
    rows = list_records(
        lms,
        PROGRESS,
        filters=[["course", "=", course_name], ["status", "=", "Complete"]],
        fields=["member", "lesson"],
    )
    done: dict[str, set[str]] = {}
    for r in rows:
        done.setdefault(r["member"], set()).add(r["lesson"])
    fixed = 0
    for e in enrolled:
        right = plan.course_progress(done.get(e["member"], ()), outline)
        if abs(float(e.get("progress") or 0) - right) > 1e-6:
            update_record(
                lms, ENROLLMENT, e["name"], {"progress": right}, label=f"enrollment {e['name']}"
            )
            fixed += 1
    if fixed:
        say(f"updated progress of {fixed} enrollment(s)")
    return fixed


def _outline(course: Course, names: Names) -> list[str]:
    lessons = (x.key for c in course.chapters for x in c.lessons)
    return [names[(plan.LESSON, k)] for k in lessons if (plan.LESSON, k) in names]


def _counts(creates: int, updates: int, detached: int) -> str:
    return f"{creates} created, {updates} updated, {detached} detached"


def _image_urls(
    lms: Lms, course: Course, *, check: bool, say: Say
) -> tuple[dict[str, str], int, int]:
    """Phase 0: give every image its LMS URL. Return the URLs, the uploads, and the differences.

    With `check` nothing is uploaded: a missing file is reported and has no URL.
    """
    urls: dict[str, str] = {}
    uploaded = missing = 0
    for image in course.images:
        name = images.stored_name(course.key, image.data, posixpath.basename(image.path))
        found = list_records(
            lms,
            "File",
            filters=[["file_name", "=", name], ["is_private", "=", 0]],
            fields=["name", "file_url"],
        )
        if found and found[0].get("file_url"):
            urls[image.path] = found[0]["file_url"]
        elif check:
            say(f"would upload image {image.path}")
            missing += 1
        else:
            urls[image.path] = upload_file(lms, name, image.data)
            uploaded += 1
            say(f"uploaded image {image.path}")
    return urls, uploaded, missing


def run_sync(
    lms: Lms,
    course: Course,
    *,
    check: bool,
    say: Say,
    admin_group: str = "",
    courses: tuple[Mapping[str, Any], ...] | None = None,
) -> int:
    """Make the LMS match git (or, with `check`, only say what differs). Return the exit code."""
    found = read_state(lms, course, courses)
    if clash := plan.title_clash(course, found, admin_group):
        raise LmsError(f"refusing to sync: {clash}")
    if other := plan.held_elsewhere(course, found):
        raise LmsError(f"refusing to sync: {other}")
    urls, uploaded, missing = _image_urls(lms, course, check=check, say=say)
    creates = plan.plan_creates(course, found, urls)
    if check:
        lines = _report(creates, plan.plan_sync(course, found, urls))
        for line in lines:
            say(line)
        total = len(lines) + missing
        say(f"{total} difference(s) found" if total else "nothing to change")
        return 1 if total else 0
    names = _names(found)
    _create_all(lms, creates, names, say)
    if creates:
        found = read_state(lms, course, found.courses)
        names = _names(found)
    actions = plan.plan_sync(course, found, urls)
    for a in actions:
        _apply(lms, a, say)
    if found.course and plan.outline_changed(creates, actions):
        _recompute_progress(lms, found.course["name"], _outline(course, names), say)
    updates = sum(isinstance(a, Update) for a in actions)
    detached = sum(isinstance(a, Detach) for a in actions)
    changed = len(creates) + updates + detached + uploaded
    counts = _counts(len(creates), updates, detached) + f", {uploaded} images uploaded"
    say(counts if changed else "nothing to change")
    return 0


def _prefixed(say: Say, key: str) -> Say:
    return lambda line: say(f"[{key}] {line}")


def _reason(problems: Sequence[Any]) -> str:
    first = problems[0]
    more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
    return f"{first.file}: {first.where}: {first.message}{more}"


def sync_all(
    lms: Lms,
    catalog: Catalog,
    *,
    only: str | None,
    check: bool,
    say: Say,
    err: Say,
    admin_group: str = "",
) -> int:
    """Sync every ready course (or just `only`); a course that fails never stops the others."""
    if only is not None and only not in catalog.courses:
        err(f"ERROR unknown course {only!r}; known courses: {', '.join(sorted(catalog.courses))}")
        return 1
    shown = [p for p in catalog.problems if only is None or p.course == only]
    for p in shown:
        err(p.line())
    blocked = {k: _reason(v) for k, v in catalog.blocked().items() if only is None or k == only}
    targets = [only] if only else list(catalog.courses)
    lms_courses = _lms_courses(lms)
    differs = False
    for key in targets:
        course = catalog.courses[key]
        if key in blocked or course is None:
            continue
        try:
            code = run_sync(
                lms,
                course,
                check=check,
                say=_prefixed(say, key),
                admin_group=admin_group,
                courses=lms_courses,
            )
        except LmsError as e:
            blocked[key] = str(e)
            continue
        differs = differs or code != 0
    if only is None:
        for c in lms_courses:
            if c.get("nile_key") and c["nile_key"] not in catalog.courses:
                say(f"course {c['name']} ({c['nile_key']}) has no folder in content/, left alone")
                differs = differs or check
    for key in sorted(blocked):
        say(f"[{key}] blocked: {blocked[key]}")
    stray = only is None and any(not p.warning and p.course not in catalog.courses for p in shown)
    return 1 if blocked or stray or (check and differs) else 0
