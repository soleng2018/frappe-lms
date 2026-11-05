"""Unit tests for nile_auth.progress (spec 0013 AC-2 to AC-8, AC-10, AC-11). No Frappe needed."""

from datetime import datetime
from typing import Any

import pytest
from nile_auth.progress import (
    DATASETS,
    assemble,
    filter_progress_rows,
    filter_quiz_rows,
    progress_percent,
    quiz_state,
    round_half_up,
    status_for,
)

T1, T2, T3 = datetime(2026, 1, 1), datetime(2026, 2, 1), datetime(2026, 3, 1)


def users(*names: str) -> list[dict[str, Any]]:
    return [{"name": n, "full_name": n.split("@")[0].title(), "enabled": 1} for n in names]


def world(**over: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base: dict[str, list[dict[str, Any]]] = {
        "courses": [{"name": "c1", "title": "Course One", "nile_key": "one"}],
        "outline": [{"course": "c1", "lesson": f"l{i}"} for i in (1, 2, 3, 4)],
        "enrollments": [],
        "progress": [],
        "quizzes": [],
        "submissions": [],
        "certificates": [],
        "users": users("a@x.io", "b@x.io"),
    }
    base.update(over)
    return base


def run(data: dict[str, list[dict[str, Any]]], excluded: tuple[str, ...] = ()):
    return assemble(lambda name: data[name], excluded)


def done(member: str, *lessons: str, status: str = "Complete") -> list[dict[str, Any]]:
    return [
        {"member": member, "course": "c1", "lesson": lesson, "status": status, "modified": T2}
        for lesson in lessons
    ]


def test_status_order() -> None:
    assert status_for(True, 0, 0) == "Certified"
    assert status_for(False, 4, 4) == "Ready for certificate"
    assert status_for(False, 1, 4) == "In progress"
    assert status_for(False, 0, 4) == "Not started"
    assert status_for(False, 0, 0) == "Not started"  # a course with no lessons


def test_rounding_and_percent() -> None:
    assert round_half_up(145, 2) == 73  # 72.5
    assert progress_percent(2, 3) == 66
    assert progress_percent(0, 0) == 0
    assert progress_percent(4, 4) == 100


def test_quiz_state_rules() -> None:
    assert quiz_state(85, 1, 3, 80) == "Passed"
    assert quiz_state(60, 3, 3, 80) == "Locked"
    assert quiz_state(60, 50, 0, 80) == "In progress"  # unlimited is never locked
    assert quiz_state(None, 0, 3, 80) == "Not attempted"
    assert quiz_state(85, 3, 3, 80) == "Passed"  # passed beats locked


def test_happy_path_with_quizzes() -> None:
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        progress=done("a@x.io", "l1", "l2"),
        outline=[{"course": "c1", "lesson": f"l{i}"} for i in (1, 2, 3, 4)],
        quizzes=[
            {
                "name": "q1",
                "title": "Q1",
                "lesson": "l1",
                "max_attempts": 3,
                "passing_percentage": 80,
            },
            {
                "name": "q2",
                "title": "Q2",
                "lesson": "l2",
                "max_attempts": 0,
                "passing_percentage": 80,
            },
        ],
        submissions=[
            {"member": "a@x.io", "quiz": "q1", "percentage": 85, "creation": T1},
            {"member": "a@x.io", "quiz": "q2", "percentage": 60, "creation": T3},
        ],
    )
    progress, quizzes = run(data)
    assert len(progress) == 1
    row = progress[0]
    assert (row["status"], row["lessons_done"], row["lessons_total"], row["progress"]) == (
        "In progress",
        2,
        4,
        50,
    )
    assert (row["quizzes_passed"], row["quizzes_total"], row["avg_best"]) == (1, 2, 73)
    assert row["last_activity"] == T3
    assert [q["state"] for q in quizzes] == ["Passed", "In progress"]
    assert quizzes[1]["attempts_allowed"] == "Unlimited"


def test_slot_ended_keeps_the_row_and_enrolled_filter_hides_it() -> None:
    data = world(
        progress=done("a@x.io", "l1"),
        certificates=[
            {
                "name": "cert1",
                "member": "a@x.io",
                "course": "c1",
                "issue_date": "2026-01-01",
                "published": 0,
                "creation": T1,
            },
            {
                "name": "cert2",
                "member": "a@x.io",
                "course": "c1",
                "issue_date": "2026-02-01",
                "published": 1,
                "creation": T2,
            },
        ],
    )
    progress, _ = run(data)
    assert [(r["enrolled"], r["status"], r["certificate"], r["published"]) for r in progress] == [
        ("No", "Certified", "cert2", "Yes")
    ]
    assert filter_progress_rows(progress, enrolled_only=True) == []


def test_outline_change_never_exceeds_100() -> None:
    data = world(progress=done("a@x.io", "l1", "l2", "l3", "l4", "gone"))
    row = run(data)[0][0]
    assert (row["lessons_done"], row["progress"], row["status"]) == (
        4,
        100,
        "Ready for certificate",
    )


def test_lesson_listed_twice_and_incomplete_rows() -> None:
    data = world(
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c1", "lesson": "l1"}],
        progress=done("a@x.io", "l1", status="Incomplete"),
    )
    row = run(data)[0][0]
    assert (row["lessons_total"], row["lessons_done"], row["status"]) == (1, 0, "Not started")


def test_exclusions() -> None:
    data = world(
        users=users("a@x.io", "svc@x.io", "mcp@x.io", "Administrator", "idle@x.io"),
        courses=[
            {"name": "c1", "title": "Course One", "nile_key": "one"},
            {"name": "c2", "title": "Unmanaged", "nile_key": None},
        ],
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c2", "lesson": "m1"}],
        progress=[
            *done("a@x.io", "l1"),
            *done("svc@x.io", "l1"),
            *done("mcp@x.io", "l1"),
            *done("Administrator", "l1"),
            {
                "member": "a@x.io",
                "course": "c2",
                "lesson": "m1",
                "status": "Complete",
                "modified": T1,
            },
        ],
    )
    progress, _ = run(data, ("svc@x.io", "mcp@x.io", None))  # type: ignore[arg-type]
    assert [(r["learner"], r["course_name"]) for r in progress] == [("a@x.io", "c1")]


def test_disabled_user_keeps_row() -> None:
    data = world(progress=done("a@x.io", "l1"))
    data["users"][0]["enabled"] = 0
    assert run(data)[0][0]["enabled"] == "No"


def test_quiz_uses_current_pass_mark_and_lock() -> None:
    data = world(
        progress=done("a@x.io", "l1"),
        quizzes=[
            {
                "name": "q1",
                "title": "Q1",
                "lesson": "l1",
                "max_attempts": 3,
                "passing_percentage": 90,
            }
        ],
        submissions=[{"member": "a@x.io", "quiz": "q1", "percentage": 85, "creation": T1}] * 3,
    )
    progress, quizzes = run(data)
    assert quizzes[0]["state"] == "Locked"
    assert progress[0]["quizzes_passed"] == 0
    assert filter_quiz_rows(quizzes, state="Locked") == quizzes
    assert filter_quiz_rows(quizzes, state="Passed") == []


def test_filters_combine_and_validate() -> None:
    data = world(progress=[*done("a@x.io", "l1"), *done("b@x.io", "l1", "l2", "l3", "l4")])
    progress, _ = run(data)
    assert [r["learner"] for r in filter_progress_rows(progress, learner="B@X")] == ["b@x.io"]
    assert [r["learner"] for r in filter_progress_rows(progress, status="In progress")] == [
        "a@x.io"
    ]
    assert filter_progress_rows(progress, course="not-managed") == []
    with pytest.raises(ValueError, match="Status"):
        filter_progress_rows(progress, status="Bogus")
    with pytest.raises(ValueError, match="State"):
        filter_quiz_rows([], state="Bogus")


def test_empty_when_no_managed_course() -> None:
    assert run(world(courses=[])) == ([], [])


def test_fetch_calls_do_not_grow_with_learners() -> None:
    def count(n: int) -> int:
        names = [f"u{i}@x.io" for i in range(n)]
        data = world(users=users(*names), progress=[r for m in names for r in done(m, "l1")])
        calls: list[str] = []

        def fetch(name: str) -> list[dict[str, Any]]:
            calls.append(name)
            return data[name]

        assemble(fetch)
        return len(calls)

    assert count(5) == count(200) == len(DATASETS)
