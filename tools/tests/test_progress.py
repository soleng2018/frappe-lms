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


def quiz(
    name: str, lesson: str, title: str = "", allowed: int = 0, mark: int = 80
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title or name,
        "lesson": lesson,
        "max_attempts": allowed,
        "passing_percentage": mark,
    }


def sub(member: str, quiz_name: str, pct: int, when: datetime) -> dict[str, Any]:
    return {"member": member, "quiz": quiz_name, "percentage": pct, "creation": when}


def test_progress_rows_order_by_course_title_then_learner_name() -> None:
    """AC-7: ordered by course title, then learner name, case blind, across courses."""
    data = world(
        courses=[
            {"name": "c1", "title": "Zeta Course", "nile_key": "z"},
            {"name": "c2", "title": "alpha course", "nile_key": "a"},
        ],
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c2", "lesson": "m1"}],
        users=[
            {"name": "x@x.io", "full_name": "bob", "enabled": 1},
            {"name": "y@x.io", "full_name": "Alice", "enabled": 1},
        ],
        enrollments=[
            {"member": m, "course": c} for m in ("x@x.io", "y@x.io") for c in ("c1", "c2")
        ],
    )
    progress, _ = run(data)
    assert [(r["course"], r["full_name"]) for r in progress] == [
        ("alpha course", "Alice"),
        ("alpha course", "bob"),
        ("Zeta Course", "Alice"),
        ("Zeta Course", "bob"),
    ]


def test_learner_without_full_name_sorts_by_email() -> None:
    """AC-7: a missing full name falls back to the email for the sort."""
    data = world(
        users=[
            {"name": "m@x.io", "full_name": None, "enabled": 1},
            {"name": "a@x.io", "full_name": "Zed", "enabled": 1},
        ],
        enrollments=[{"member": "m@x.io", "course": "c1"}, {"member": "a@x.io", "course": "c1"}],
    )
    progress, _ = run(data)
    assert [r["learner"] for r in progress] == ["m@x.io", "a@x.io"]


def test_quiz_rows_follow_outline_position_not_name_or_insert_order() -> None:
    """AC-8: quizzes list in outline order even when names and fetch order disagree."""
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        quizzes=[quiz("qa", "l3"), quiz("qb", "l1"), quiz("qc", "l2")],
    )
    _, quizzes = run(data)
    assert [q["quiz"] for q in quizzes] == ["qb", "qc", "qa"]


def test_average_is_empty_when_no_quiz_was_attempted() -> None:
    """AC-5: avg_best is None, not 0, when the learner has not tried any quiz."""
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        quizzes=[quiz("q1", "l1")],
    )
    progress, quizzes = run(data)
    assert progress[0]["avg_best"] is None
    assert progress[0]["quizzes_total"] == 1
    assert (quizzes[0]["best_score"], quizzes[0]["state"]) == (None, "Not attempted")
    assert quizzes[0]["last_attempt"] is None


def test_average_rounds_half_up_over_attempted_quizzes_only() -> None:
    """AC-5: 85 and 60 average to 72.5 which shows as 73; an untried quiz is left out."""
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        quizzes=[quiz("q1", "l1"), quiz("q2", "l2"), quiz("q3", "l3")],
        submissions=[sub("a@x.io", "q1", 85, T1), sub("a@x.io", "q2", 60, T1)],
    )
    assert run(data)[0][0]["avg_best"] == 73


def test_best_score_is_the_highest_attempt_not_the_latest() -> None:
    """AC-5: a later, worse attempt does not lower the best score."""
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        quizzes=[quiz("q1", "l1")],
        submissions=[sub("a@x.io", "q1", 90, T1), sub("a@x.io", "q1", 50, T3)],
    )
    _, quizzes = run(data)
    assert (quizzes[0]["best_score"], quizzes[0]["attempts_used"], quizzes[0]["last_attempt"]) == (
        90,
        2,
        T3,
    )


def test_last_activity_ignores_quizzes_outside_the_outline() -> None:
    """AC-6: a submission on a quiz outside the course outline does not move last activity."""
    data = world(
        progress=done("a@x.io", "l1"),
        quizzes=[quiz("stray", "not-in-outline")],
        submissions=[sub("a@x.io", "stray", 100, T3)],
    )
    progress, quizzes = run(data)
    assert progress[0]["last_activity"] == T2
    assert quizzes == []


def test_last_activity_is_empty_for_a_row_with_no_activity() -> None:
    """AC-6: an enrolled learner who did nothing has no last activity."""
    progress, _ = run(world(enrollments=[{"member": "a@x.io", "course": "c1"}]))
    assert progress[0]["last_activity"] is None


def test_certificate_tie_on_issue_date_goes_to_the_newest_creation() -> None:
    """AC-3: equal issue dates fall back to the most recently created certificate."""
    base = {"member": "a@x.io", "course": "c1", "issue_date": "2026-01-01"}
    data = world(
        certificates=[
            {**base, "name": "old", "published": 1, "creation": T1},
            {**base, "name": "new", "published": 0, "creation": T3},
        ]
    )
    row = run(data)[0][0]
    assert (row["certificate"], row["published"]) == ("new", "No")


def test_no_certificate_leaves_the_certificate_columns_empty() -> None:
    """AC-3: no certificate means empty, not "No"."""
    row = run(world(enrollments=[{"member": "a@x.io", "course": "c1"}]))[0][0]
    assert (row["certificate"], row["issue_date"], row["published"]) == (None, None, None)


def test_certificate_alone_creates_a_row_even_without_enrollment_or_progress() -> None:
    """AC-2: a row exists when only a certificate exists."""
    data = world(
        certificates=[
            {
                "name": "c",
                "member": "b@x.io",
                "course": "c1",
                "issue_date": "2026-01-01",
                "published": 1,
                "creation": T1,
            }
        ]
    )
    row = run(data)[0][0]
    assert (row["learner"], row["enrolled"], row["status"]) == ("b@x.io", "No", "Certified")


def test_unknown_user_in_progress_is_skipped() -> None:
    """AC-2: progress for a user record that no longer exists does not crash or show."""
    data = world(progress=done("ghost@x.io", "l1"))
    assert run(data) == ([], [])


def test_quiz_with_no_pass_mark_or_attempt_limit_uses_zero_defaults() -> None:
    """AC-8: None for pass mark or attempts means a 0 pass mark and unlimited attempts."""
    q = {**quiz("q1", "l1"), "max_attempts": None, "passing_percentage": None}
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1"}],
        quizzes=[q],
        submissions=[sub("a@x.io", "q1", 0, T1)],
    )
    _, quizzes = run(data)
    assert (quizzes[0]["attempts_allowed"], quizzes[0]["pass_mark"], quizzes[0]["state"]) == (
        "Unlimited",
        0,
        "Passed",
    )


def test_quiz_scores_filters_by_course_and_learner() -> None:
    """AC-8: course matches by id, learner matches name or email, both together with AND."""
    data = world(
        courses=[
            {"name": "c1", "title": "One", "nile_key": "one"},
            {"name": "c2", "title": "Two", "nile_key": "two"},
        ],
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c2", "lesson": "m1"}],
        quizzes=[quiz("q1", "l1"), quiz("q2", "m1")],
        enrollments=[
            {"member": m, "course": c} for m in ("a@x.io", "b@x.io") for c in ("c1", "c2")
        ],
    )
    _, quizzes = run(data)
    assert {q["quiz"] for q in filter_quiz_rows(quizzes, course="c2")} == {"q2"}
    assert {q["learner"] for q in filter_quiz_rows(quizzes, learner=" A@X ")} == {"a@x.io"}
    both = filter_quiz_rows(quizzes, course="c1", learner="b@x.io")
    assert [(q["learner"], q["quiz"]) for q in both] == [("b@x.io", "q1")]


def test_learner_filter_matches_the_full_name() -> None:
    """AC-7: typing part of the name finds the learner."""
    progress, _ = run(world(enrollments=[{"member": "a@x.io", "course": "c1"}]))
    assert len(filter_progress_rows(progress, learner="a")) == 1  # full name is "A"
    assert filter_progress_rows(progress, learner="nobody") == []


@pytest.mark.parametrize(
    ("done_count", "total", "expected"),
    [(0, 3, 0), (1, 3, 33), (2, 3, 66), (3, 3, 100), (5, 3, 100), (0, -1, 0)],
)
def test_progress_percent_rounds_down_and_caps_at_100(
    done_count: int, total: int, expected: int
) -> None:
    """AC-4: a learner only reads 100 when every lesson is done."""
    assert progress_percent(done_count, total) == expected


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [(0, 1, 0), (1, 2, 1), (1, 3, 0), (2, 3, 1), (5, 2, 3), (7, 1, 7)],
)
def test_round_half_up_table(numerator: int, denominator: int, expected: int) -> None:
    """AC-5: halves go up, everything else rounds to the nearest whole."""
    assert round_half_up(numerator, denominator) == expected


def test_quiz_state_at_the_pass_mark_boundary() -> None:
    """AC-8: exactly the pass mark passes; one below does not."""
    assert quiz_state(80, 1, 3, 80) == "Passed"
    assert quiz_state(79, 1, 3, 80) == "In progress"
