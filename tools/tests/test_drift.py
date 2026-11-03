"""Unit tests for nile_tools.drift: edits made in the LMS and unmanaged records (AC-9)."""

from nile_tools.drift import Difference, Record, compare


def test_no_drift_when_fields_match() -> None:
    wanted = [Record("Course Lesson", "v1", {"title": "A", "youtube": "x"})]
    found = [
        Record(
            "Course Lesson", "v1", {"title": "A", "youtube": "x", "course": "filled by LMS"}, "L1"
        )
    ]
    assert compare(wanted, found).differences == ()


def test_lists_a_changed_field() -> None:
    wanted = [Record("Course Lesson", "v1", {"title": "New"})]
    found = [Record("Course Lesson", "v1", {"title": "Old"}, "L1")]
    drift = compare(wanted, found)
    assert drift.differences == (Difference("Course Lesson", "v1", "title", "New", "Old"),)
    assert drift.unmanaged == ()


def test_unset_and_empty_are_the_same() -> None:
    wanted = [Record("LMS Course", "c", {"description": "", "published": 1})]
    found = [Record("LMS Course", "c", {"description": None, "published": 1}, "C1")]
    assert compare(wanted, found).differences == ()


def test_zero_is_not_empty() -> None:
    wanted = [Record("LMS Course", "c", {"enforce_lesson_completion": 0})]
    found = [Record("LMS Course", "c", {}, "C1")]
    assert len(compare(wanted, found).differences) == 1


def test_same_key_in_another_doctype_is_not_matched() -> None:
    wanted = [Record("Course Lesson", "k", {"title": "A"})]
    found = [Record("Course Chapter", "k", {"title": "B"}, "X")]
    assert compare(wanted, found).differences == ()


def test_record_not_in_lms_yet_is_a_create_not_drift() -> None:
    assert compare([Record("Course Lesson", "v1", {"title": "A"})], []).differences == ()


def test_lists_records_with_no_key() -> None:
    mine = Record("Course Lesson", None, {"title": "Hand made"}, "L9")
    drift = compare([], [Record("Course Lesson", "v1", {}, "L1"), mine])
    assert drift.unmanaged == (mine,)
