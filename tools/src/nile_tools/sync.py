"""Push the course from git to the LMS: read, plan, then apply (or only report with `--check`)."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from nile_tools import plan
from nile_tools.content import Course
from nile_tools.lms import (
    Lms,
    create_record,
    get_record,
    list_records,
    update_record,
)
from nile_tools.plan import (
    Action,
    AddToBatch,
    Create,
    Detach,
    Found,
    Ref,
    Unmanaged,
    Update,
)

__all__ = ["read_state", "run_sync"]

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


def read_state(lms: Lms, course: Course) -> Found:
    """Read what the LMS holds for this course: by `nile_key`, and by `course` for strays."""
    batches = tuple(
        get_record(lms, plan.BATCH, b["name"])
        for b in list_records(lms, plan.BATCH, fields=["name"])
    )
    found = list_records(lms, plan.COURSE, filters=[["nile_key", "=", course.key]])
    if not found:
        return Found(batches=batches)
    doc = get_record(lms, plan.COURSE, found[0]["name"])
    here = [["course", "=", doc["name"]]]
    lesson_keys = [x.key for c in course.chapters for x in c.lessons]
    chapters = _merge(
        list_records(lms, plan.CHAPTER, filters=here),
        list_records(lms, plan.CHAPTER, filters=_in([c.key for c in course.chapters])),
    )
    lessons = _merge(
        list_records(lms, plan.LESSON, filters=here),
        list_records(lms, plan.LESSON, filters=_in(lesson_keys)),
    )
    quizzes = _merge(
        list_records(lms, plan.QUIZ, filters=here),
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
    return Found(doc, tuple(chapters), tuple(lessons), tuple(quizzes), tuple(questions), batches)


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
            for line in _overwrites(action):
                say(line)
            body = {c.field: plan.payload(c.field, c.wanted) for c in changes}
            update_record(lms, doctype, name, body, label=f"{doctype} {key}")
            for note in notes:
                say(f"{doctype} {key}: {note}")
            say(f"updated {doctype} {key}: {', '.join(c.field for c in changes)}")
        case Detach(doctype=doctype, key=key):
            say(f"detached {doctype} {key} (kept in the LMS, out of the course)")
        case AddToBatch(batch=batch, course=course_name):
            doc = get_record(lms, plan.BATCH, batch)
            rows = [*(doc.get("courses") or ()), {"course": course_name}]
            update_record(lms, plan.BATCH, batch, {"courses": rows}, label=f"LMS Batch {batch}")
            say(f"added the course to LMS Batch {batch}")
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
            case AddToBatch():
                lines.append(f"would add the course to LMS Batch {a.batch}")
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


def run_sync(lms: Lms, course: Course, *, check: bool, say: Say) -> int:
    """Make the LMS match git (or, with `check`, only say what differs). Return the exit code."""
    found = read_state(lms, course)
    creates = plan.plan_creates(course, found)
    if check:
        lines = _report(creates, plan.plan_sync(course, found))
        for line in lines:
            say(line)
        say(f"{len(lines)} difference(s) found" if lines else "nothing to change")
        return 1 if lines else 0
    names = _names(found)
    _create_all(lms, creates, names, say)
    if creates:
        found = read_state(lms, course)
        names = _names(found)
    actions = plan.plan_sync(course, found)
    for a in actions:
        _apply(lms, a, say)
    if found.course and plan.outline_changed(creates, actions):
        _recompute_progress(lms, found.course["name"], _outline(course, names), say)
    updates = sum(isinstance(a, Update) for a in actions)
    detached = sum(isinstance(a, Detach) for a in actions)
    changed = len(creates) + updates + detached + sum(isinstance(a, AddToBatch) for a in actions)
    say(_counts(len(creates), updates, detached) if changed else "nothing to change")
    return 0
