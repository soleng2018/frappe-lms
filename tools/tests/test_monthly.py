"""Unit tests for nile_auth.monthly (spec 0014 AC-2 to AC-9, AC-11, AC-12). No Frappe needed."""

from datetime import date, datetime
from typing import Any

import pytest
from nile_auth.monthly import (
    DATASETS,
    Window,
    as_of,
    build_rows,
    filter_rows,
    monthly_rows,
    parse_month,
    totals,
)
from nile_auth.progress import assemble

TODAY = date(2026, 11, 5)
OCT = Window(date(2026, 10, 1), date(2026, 11, 1))
SEP = Window(date(2026, 9, 1), date(2026, 10, 1))


def users(*names: str) -> list[dict[str, Any]]:
    return [{"name": n, "full_name": n.split("@")[0].title(), "enabled": 1} for n in names]


def world(**over: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base: dict[str, list[dict[str, Any]]] = {
        "courses": [{"name": "c1", "title": "Course One", "nile_key": "one"}],
        "outline": [{"course": "c1", "lesson": f"l{i}"} for i in (1, 2, 3)],
        "enrollments": [],
        "progress": [],
        "quizzes": [],
        "submissions": [],
        "certificates": [],
        "users": users("a@x.io", "b@x.io"),
    }
    base.update(over)
    return base


def quiz(lesson: str = "l3", allowed: int = 3, mark: int = 80, name: str = "q1") -> dict[str, Any]:
    return {
        "name": name,
        "title": name.upper(),
        "lesson": lesson,
        "max_attempts": allowed,
        "passing_percentage": mark,
    }


def done(member: str, when: datetime, *lessons: str) -> list[dict[str, Any]]:
    return [
        {
            "member": member,
            "course": "c1",
            "lesson": lesson,
            "status": "Complete",
            "modified": when,
            "creation": when,
        }
        for lesson in lessons
    ]


def sub(member: str, pct: int | None, when: datetime, quiz_name: str = "q1") -> dict[str, Any]:
    return {"member": member, "quiz": quiz_name, "percentage": pct, "creation": when}


def cert(member: str, issued: date | None, created: datetime | None = None) -> dict[str, Any]:
    return {
        "name": f"cert-{member}",
        "member": member,
        "course": "c1",
        "issue_date": issued,
        "published": 1,
        "creation": created or datetime(2026, 1, 1),
    }


def by_user(
    data: dict[str, list[dict[str, Any]]], window: Window = OCT
) -> dict[str, dict[str, Any]]:
    return {r["learner"]: r for r in build_rows(data, (), window)}


OCT5 = datetime(2026, 10, 5, 9)
OCT9 = datetime(2026, 10, 9, 9)
SEP5 = datetime(2026, 9, 5, 9)
NOV1 = datetime(2026, 11, 1)


def test_parse_month_accepts_a_month_and_gives_a_half_open_window() -> None:
    assert parse_month("2026-10", TODAY) == OCT
    assert parse_month(" 2026-12 ", date(2027, 1, 3)) == Window(date(2026, 12, 1), date(2027, 1, 1))
    assert parse_month("2026-11", TODAY) == Window(date(2026, 11, 1), date(2026, 12, 1))


def test_blank_month_is_the_last_full_month_and_wraps_the_year() -> None:
    assert parse_month("", TODAY) == OCT
    assert parse_month(None, TODAY) == OCT
    assert parse_month("  ", date(2027, 1, 15)) == Window(date(2026, 12, 1), date(2027, 1, 1))


@pytest.mark.parametrize(
    "bad", ["2026-13", "2026-00", "abc", "2026-1", "26-10", "2026-10-01", "2026/10", "2026-12"]
)
def test_bad_or_future_months_raise(bad: str) -> None:
    with pytest.raises(ValueError, match="Month"):
        parse_month(bad, TODAY)


def test_old_months_are_accepted() -> None:
    assert parse_month("2019-01", TODAY).start == date(2019, 1, 1)


def test_all_lessons_complete_and_no_quizzes_is_done_with_a_done_date() -> None:
    data = world(progress=done("a@x.io", OCT5, "l1", "l2") + done("a@x.io", OCT9, "l3"))
    row = by_user(data)["a@x.io"]
    assert (row["result"], row["outcome"]) == ("Done", "Passed")
    assert row["done_date"] == date(2026, 10, 9)
    assert row["completed_this_month"] == "Yes"
    assert row["lessons_done"] == 3 and row["lessons_left"] == 0


def test_missing_lesson_is_behind_with_no_outcome_or_done_date() -> None:
    row = by_user(world(progress=done("a@x.io", OCT5, "l1", "l2")))["a@x.io"]
    assert (row["result"], row["outcome"], row["done_date"]) == ("Behind", None, None)
    assert row["completed_this_month"] == "No"
    assert row["lessons_left"] == 1


def test_course_with_no_lessons_is_never_done() -> None:
    data = world(outline=[], enrollments=[{"member": "a@x.io", "course": "c1", "creation": OCT5}])
    assert by_user(data)["a@x.io"]["result"] == "Behind"


def test_a_failed_quiz_with_no_attempts_left_is_done_but_not_passed() -> None:
    data = world(
        quizzes=[quiz()],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[
            sub("a@x.io", 40, OCT5),
            sub("a@x.io", 50, OCT5.replace(day=6)),
            sub("a@x.io", 60, OCT9),
        ],
    )
    row = by_user(data)["a@x.io"]
    assert (row["result"], row["outcome"]) == ("Done", "Not passed")
    assert row["locked_quizzes"] == 1
    assert row["done_date"] == date(2026, 10, 9)  # the third attempt locked the quiz
    assert row["lessons_left"] == 1  # the quiz lesson never completes


def test_a_quiz_with_attempts_left_keeps_the_learner_behind() -> None:
    data = world(
        quizzes=[quiz()],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 40, OCT5)],
    )
    assert by_user(data)["a@x.io"]["result"] == "Behind"


def test_an_unlimited_quiz_is_never_locked() -> None:
    data = world(
        quizzes=[quiz(allowed=0)],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 10, datetime(2026, 10, d)) for d in range(1, 10)],
    )
    row = by_user(data)["a@x.io"]
    assert row["result"] == "Behind"
    assert row["locked_quizzes"] == 0


def test_passing_the_quiz_is_done_and_passed_with_the_pass_date() -> None:
    data = world(
        quizzes=[quiz()],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 50, OCT5), sub("a@x.io", 90, OCT9)],
    )
    row = by_user(data)["a@x.io"]
    assert (row["result"], row["outcome"], row["done_date"]) == (
        "Done",
        "Passed",
        date(2026, 10, 9),
    )


def test_a_certificate_makes_a_learner_done_even_if_attempts_were_deleted() -> None:
    data = world(
        quizzes=[quiz()],
        certificates=[cert("a@x.io", date(2026, 10, 20), datetime(2026, 10, 20))],
    )
    row = by_user(data)["a@x.io"]
    assert (row["result"], row["outcome"]) == ("Done", "Passed")
    assert row["done_date"] == date(2026, 10, 20)
    assert row["certificate"] == "cert-a@x.io"
    assert row["certificate_issued"] == "Yes"


def test_a_certificate_dated_after_the_month_does_not_make_the_learner_done() -> None:
    data = world(certificates=[cert("a@x.io", date(2026, 11, 2), datetime(2026, 10, 3))])
    row = by_user(data)["a@x.io"]
    assert row["result"] == "Behind"
    assert row["certificate"] is None


def test_a_certificate_with_no_issue_date_is_not_held() -> None:
    row = by_user(world(certificates=[cert("a@x.io", None, OCT5)]))["a@x.io"]
    assert (row["result"], row["certificate"]) == ("Behind", None)


def test_done_by_certificate_with_a_locked_quiz_is_passed() -> None:
    data = world(
        quizzes=[quiz()],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 10, OCT5)] * 3,
        certificates=[cert("a@x.io", date(2026, 10, 25))],
    )
    row = by_user(data)["a@x.io"]
    assert (row["result"], row["outcome"], row["locked_quizzes"]) == ("Done", "Passed", 1)
    assert row["done_date"] == date(2026, 10, 5)  # the third failed attempt locked it on Oct 5


def test_the_done_date_is_the_earlier_of_the_finish_and_the_certificate() -> None:
    data = world(
        progress=done("a@x.io", OCT9, "l1", "l2", "l3"),
        certificates=[cert("a@x.io", date(2026, 10, 3))],
    )
    assert by_user(data)["a@x.io"]["done_date"] == date(2026, 10, 3)


def test_a_learner_is_behind_before_and_done_after_the_finishing_month() -> None:
    data = world(progress=done("a@x.io", datetime(2026, 10, 3), "l1", "l2", "l3"))
    assert by_user(data, SEP).get("a@x.io") is None  # no record before October
    data["enrollments"] = [{"member": "a@x.io", "course": "c1", "creation": SEP5}]
    assert by_user(data, SEP)["a@x.io"]["result"] == "Behind"
    assert by_user(data, OCT)["a@x.io"]["result"] == "Done"
    nov = Window(date(2026, 11, 1), date(2026, 12, 1))
    row = by_user(data, nov)["a@x.io"]
    assert (row["result"], row["completed_this_month"]) == ("Done", "No")  # stays Done


def test_rows_need_a_record_before_the_cutoff() -> None:
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": datetime(2026, 10, 1)}]
    )
    assert "a@x.io" not in by_user(data, SEP)  # enrolled on the first of October
    assert "a@x.io" in by_user(data, OCT)


def test_an_attempt_on_the_first_day_of_the_next_month_does_not_count() -> None:
    data = world(
        quizzes=[quiz()],
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": SEP5}],
        submissions=[sub("a@x.io", 95, datetime(2026, 10, 1))],
    )
    sep = by_user(data, SEP)["a@x.io"]
    assert (sep["attempts"], sep["quizzes_first_passed"]) == (0, 0)
    assert by_user(data, OCT)["a@x.io"]["attempts"] == 1


def test_a_certificate_created_in_april_but_dated_march_gives_a_march_row() -> None:
    march = Window(date(2026, 3, 1), date(2026, 4, 1))
    data = world(certificates=[cert("a@x.io", date(2026, 3, 15), datetime(2026, 4, 2))])
    assert by_user(data, march)["a@x.io"]["result"] == "Done"


def test_a_certificate_alone_is_a_row_and_the_current_month_cutoff_is_month_end() -> None:
    nov = Window(date(2026, 11, 1), date(2026, 12, 1))
    data = world(certificates=[cert("a@x.io", date(2026, 11, 20), datetime(2026, 11, 1))])
    assert by_user(data, nov)["a@x.io"]["result"] == "Done"


def test_month_activity_counts_only_records_inside_the_month() -> None:
    data = world(
        quizzes=[quiz(allowed=0)],
        progress=done("a@x.io", SEP5, "l1") + done("a@x.io", OCT5, "l2"),
        submissions=[
            sub("a@x.io", 50, SEP5),
            sub("a@x.io", 72, OCT5),
            sub("a@x.io", 73, OCT9),  # 72 and 73 average 72.5, so 73
            sub("a@x.io", 90, NOV1),
        ],
    )
    row = by_user(data)["a@x.io"]
    assert row["lessons_completed"] == 1
    assert row["lessons_done"] == 2
    assert row["attempts"] == 2
    assert row["avg_attempt_score"] == 73
    assert row["attempt_score_sum"] == 145


def test_quiz_first_passed_counts_the_earliest_pass_once() -> None:
    first = [sub("a@x.io", 90, SEP5), sub("a@x.io", 95, OCT5)]
    data = world(
        quizzes=[quiz(allowed=0)],
        submissions=first,
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": SEP5}],
    )
    assert by_user(data, SEP)["a@x.io"]["quizzes_first_passed"] == 1
    assert (
        by_user(data, OCT)["a@x.io"]["quizzes_first_passed"] == 0
    )  # passed again, not counted twice
    data["submissions"] = [sub("a@x.io", 20, SEP5), sub("a@x.io", 85, OCT5)]
    assert by_user(data, OCT)["a@x.io"]["quizzes_first_passed"] == 1


def test_null_percentage_counts_as_zero() -> None:
    data = world(
        quizzes=[quiz(allowed=0)],
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": OCT5}],
        submissions=[sub("a@x.io", None, OCT5), sub("a@x.io", 51, OCT9)],
    )
    row = by_user(data)["a@x.io"]
    assert row["attempt_score_sum"] == 51 and row["avg_attempt_score"] == 26  # 25.5 up


def test_pass_mark_zero_means_any_attempt_passes() -> None:
    data = world(
        quizzes=[quiz(mark=0)],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 0, OCT9)],
    )
    assert by_user(data)["a@x.io"]["outcome"] == "Passed"


def test_a_quiz_locked_then_passed_after_a_reset_counts_as_passed() -> None:
    data = world(
        quizzes=[quiz(allowed=2)],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 10, OCT5), sub("a@x.io", 20, OCT5), sub("a@x.io", 90, OCT9)],
    )
    row = by_user(data)["a@x.io"]
    assert (row["outcome"], row["locked_quizzes"]) == ("Passed", 0)
    assert row["done_date"] == date(2026, 10, 5)  # it first settled when it locked


def test_attempts_made_at_the_same_time_keep_their_input_order() -> None:
    data = world(
        quizzes=[quiz(allowed=2)],
        progress=done("a@x.io", OCT5, "l1", "l2"),
        submissions=[sub("a@x.io", 90, OCT9), sub("a@x.io", 10, OCT9)],
    )
    assert by_user(data)["a@x.io"]["outcome"] == "Passed"


def test_a_lesson_outside_the_outline_is_ignored() -> None:
    data = world(progress=done("a@x.io", OCT5, "l1", "gone"))
    row = by_user(data)["a@x.io"]
    assert (row["lessons_done"], row["lessons_left"]) == (1, 2)
    assert row["lessons_completed"] == 1


def test_incomplete_progress_rows_do_not_count_but_give_a_row() -> None:
    data = world(progress=[{**done("a@x.io", OCT5, "l1")[0], "status": "Partially Complete"}])
    row = by_user(data)["a@x.io"]
    assert row["lessons_done"] == 0 and row["result"] == "Behind"


def test_enrolled_and_enabled_are_the_current_values() -> None:
    data = world(
        certificates=[cert("a@x.io", date(2026, 10, 2))],
        users=[{"name": "a@x.io", "full_name": "A", "enabled": 0}],
    )
    row = by_user(data)["a@x.io"]
    assert (row["enrolled"], row["enabled"]) == ("No", "No")


def test_exclusions_match_learner_progress() -> None:
    data = world(
        enrollments=[
            {"member": u, "course": "c1", "creation": OCT5}
            for u in ("a@x.io", "svc@x.io", "Administrator")
        ],
        users=users("a@x.io", "svc@x.io", "Administrator"),
        courses=[
            {"name": "c1", "title": "Course One", "nile_key": "one"},
            {"name": "c2", "title": "Plain", "nile_key": None},
        ],
    )
    rows = build_rows(data, ("svc@x.io",), OCT)
    assert [r["learner"] for r in rows] == ["a@x.io"]


def test_rows_are_ordered_by_course_title_then_name_then_learner() -> None:
    data = world(
        courses=[
            {"name": "c1", "title": "Zulu", "nile_key": "z"},
            {"name": "c2", "title": "alpha", "nile_key": "a"},
        ],
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c2", "lesson": "l9"}],
        enrollments=[
            {"member": m, "course": c, "creation": OCT5}
            for c in ("c1", "c2")
            for m in ("b@x.io", "a@x.io")
        ],
    )
    rows = build_rows(data, (), OCT)
    assert [(r["course"], r["learner"]) for r in rows] == [
        ("alpha", "a@x.io"),
        ("alpha", "b@x.io"),
        ("Zulu", "a@x.io"),
        ("Zulu", "b@x.io"),
    ]


def test_the_current_month_matches_learner_progress() -> None:
    nov = Window(date(2026, 11, 1), date(2026, 12, 1))
    data = world(
        quizzes=[quiz()],
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": datetime(2026, 11, 1)}],
        progress=done("b@x.io", datetime(2026, 11, 2), "l1", "l2")
        + done("a@x.io", datetime(2026, 11, 2), "l1"),
        submissions=[sub("b@x.io", 90, datetime(2026, 11, 3))],
        certificates=[cert("b@x.io", date(2026, 11, 4))],
    )
    progress_rows, _quiz = assemble(lambda name: data[name], ())
    lp = {r["learner"]: r for r in progress_rows}
    monthly = {r["learner"]: r for r in build_rows(data, (), nov)}
    assert set(lp) == set(monthly)
    for who, row in monthly.items():
        assert row["lessons_done"] == lp[who]["lessons_done"]
        assert row["enrolled"] == lp[who]["enrolled"]
        assert row["enabled"] == lp[who]["enabled"]
        assert row["certificate"] == lp[who]["certificate"]


def test_as_of_trims_by_creation_and_the_earlier_certificate_date() -> None:
    data = world(
        enrollments=[
            {"member": "a@x.io", "course": "c1", "creation": SEP5},
            {"member": "b@x.io", "course": "c1", "creation": NOV1},
        ],
        progress=done("a@x.io", OCT5, "l1"),
        certificates=[
            cert("a@x.io", date(2026, 12, 1), datetime(2026, 10, 3)),
            cert("b@x.io", date(2026, 12, 1), NOV1),
        ],
    )
    trimmed = as_of(data, SEP)
    assert [e["member"] for e in trimmed["enrollments"]] == ["a@x.io"]
    assert trimmed["progress"] == []
    assert trimmed["certificates"] == []
    assert len(as_of(data, OCT)["certificates"]) == 1


def test_filters_combine_and_validate() -> None:
    data = world(
        courses=[
            {"name": "c1", "title": "One", "nile_key": "1"},
            {"name": "c2", "title": "Two", "nile_key": "2"},
        ],
        outline=[{"course": "c1", "lesson": "l1"}, {"course": "c2", "lesson": "l2"}],
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": OCT5}],
        progress=done("b@x.io", OCT5, "l1"),
        certificates=[],
    )
    data["progress"] += [{**done("b@x.io", OCT5, "l2")[0], "course": "c2"}]
    rows = build_rows(data, (), OCT)
    assert len(rows) == 3
    assert [r["learner"] for r in filter_rows(rows, course="c1")] == ["a@x.io", "b@x.io"]
    assert [r["learner"] for r in filter_rows(rows, learner="A@X")] == ["a@x.io"]
    assert [r["course_name"] for r in filter_rows(rows, result="Done", learner="b")] == ["c1", "c2"]
    assert filter_rows(rows, course="no-such-course") == []
    assert filter_rows(rows, enrolled_only=True)[0]["learner"] == "a@x.io"
    with pytest.raises(ValueError, match="Result"):
        filter_rows(rows, result="Finished")


def test_totals_use_the_mean_of_every_attempt_not_of_row_means() -> None:
    def row(attempts: int, total: int, result: str = "Done", issued: str = "No") -> dict[str, Any]:
        return {
            "attempts": attempts,
            "attempt_score_sum": total,
            "result": result,
            "certificate_issued": issued,
        }

    rows = [row(1, 100), row(3, 150, "Behind", "Yes")]  # row means 100 and 50; mean of all is 62.5
    assert totals(rows) == {
        "done": 1,
        "behind": 1,
        "certified": 1,
        "attempts": 4,
        "avg_attempt_score": 63,
    }
    assert totals([]) == {
        "done": 0,
        "behind": 0,
        "certified": 0,
        "attempts": 0,
        "avg_attempt_score": 0,
    }


def test_empty_when_there_are_no_managed_courses() -> None:
    data = world(courses=[{"name": "c1", "title": "x", "nile_key": None}])
    assert build_rows(data, (), OCT) == []


def test_fetch_calls_do_not_grow_with_learners_or_months() -> None:
    def count(n: int, month: str | None) -> int:
        names = [f"u{i}@x.io" for i in range(n)]
        data = world(
            users=users(*names),
            enrollments=[{"member": m, "course": "c1", "creation": OCT5} for m in names],
        )
        calls: list[str] = []

        def fetch(name: str) -> list[dict[str, Any]]:
            calls.append(name)
            return data[name]

        monthly_rows(fetch, (), TODAY, month=month)
        return len(calls)

    assert count(5, None) == count(200, "2026-10") == count(50, "2024-01") == len(DATASETS) == 8


def test_bad_filters_fail_before_any_fetch() -> None:
    def fetch(name: str) -> list[dict[str, Any]]:
        raise AssertionError(f"fetched {name}")

    with pytest.raises(ValueError, match="Month"):
        monthly_rows(fetch, (), TODAY, month="2027-01")
    with pytest.raises(ValueError, match="Result"):
        monthly_rows(fetch, (), TODAY, result="x")


def test_a_duplicate_complete_row_counts_the_lesson_only_in_its_earliest_month() -> None:
    both = done("a@x.io", SEP5, "l1") + done("a@x.io", OCT5, "l1")
    data = world(
        enrollments=[{"member": "a@x.io", "course": "c1", "creation": SEP5}], progress=both
    )
    assert by_user(data, SEP)["a@x.io"]["lessons_completed"] == 1
    assert by_user(data, OCT)["a@x.io"]["lessons_completed"] == 0
