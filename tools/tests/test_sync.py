"""Unit tests for nile_tools.sync against a fake LMS: create, rerun, remove, fail (AC-1 to 8)."""

from dataclasses import replace

import httpx
import pytest
from fake_lms import FakeLms

from nile_tools.content import (
    Chapter,
    Course,
    LabLesson,
    Option,
    Question,
    Quiz,
    QuizLesson,
    VideoLesson,
)
from nile_tools.lms import LmsError
from nile_tools.sync import run_sync

OPTIONS = (Option("yes", True), Option("no"))


def course() -> Course:
    return Course(
        key="c",
        title="Course",
        short_introduction="short",
        description="A & B",
        chapters=(
            Chapter(
                "ch1",
                "One",
                (VideoLesson("v", "Video", "dQw4w9WgXcQ"), QuizLesson("ql", "Quiz", "q")),
            ),
            Chapter(
                "ch2", "Two", (LabLesson("lab", "Lab", "# Lab"), QuizLesson("lq", "Quiz", "q2"))
            ),
        ),
        quizzes=(
            Quiz("q", "Quiz", "ql", (Question("q1", "One?", options=OPTIONS),)),
            Quiz("q2", "Quiz", "lq", (Question("q3", "Three?", options=OPTIONS, marks=2),)),
        ),
    )


def run(
    fake: FakeLms, c: Course | None = None, *, check: bool = False, admin: str = "hol-admins"
) -> tuple[int, list[str]]:
    said: list[str] = []
    code = run_sync(fake.client(), c or course(), check=check, say=said.append, admin_group=admin)
    return code, said


def built() -> FakeLms:
    fake = FakeLms()
    assert run(fake)[0] == 0
    return fake


def test_a_clean_site_gets_the_whole_course() -> None:
    fake = built()
    kinds = {
        t: len(d)
        for t, d in fake.docs.items()
        if d and t not in ("System Settings", "LMS Settings")
    }
    assert kinds == {
        "LMS Course": 1,
        "Course Chapter": 2,
        "Course Lesson": 4,
        "LMS Quiz": 2,
        "LMS Question": 2,
    }
    assert all(
        d["nile_key"]
        for t, docs in fake.docs.items()
        if t not in ("System Settings", "LMS Settings")
        for d in docs.values()
    )
    c = fake.by_key("LMS Course", "c")
    assert (
        c["published"],
        c["status"],
        c["enable_certification"],
        c["enforce_lesson_completion"],
    ) == (0, "Approved", 1, 0)
    assert [r["chapter"] for r in c["chapters"]] == [
        fake.by_key("Course Chapter", k)["name"] for k in ("ch1", "ch2")
    ]


def test_lessons_hold_the_bodies_spec_0004_wants_and_the_quiz_links_back() -> None:
    fake = built()
    assert fake.by_key("Course Lesson", "v")["body"] == '{{ YouTubeVideo("dQw4w9WgXcQ") }}'
    assert fake.by_key("Course Lesson", "lab")["body"] == "# Lab"
    for lesson_key, quiz_key in (("ql", "q"), ("lq", "q2")):
        quiz, lesson = fake.by_key("LMS Quiz", quiz_key), fake.by_key("Course Lesson", lesson_key)
        assert lesson["quiz_id"] == quiz["name"]
        assert lesson["body"] == f'{{{{ Quiz("{quiz["name"]}") }}}}'
        assert (quiz["lesson"], quiz["course"]) == (
            lesson["name"],
            fake.by_key("LMS Course", "c")["name"],
        )


def test_two_quizzes_with_one_title_use_the_name_lms_gave_each() -> None:
    fake = built()
    names = {fake.by_key("LMS Quiz", k)["name"] for k in ("q", "q2")}
    assert names == {"quiz", "quiz-2"}
    assert fake.by_key("Course Lesson", "lq")["quiz_id"] == fake.by_key("LMS Quiz", "q2")["name"]


def test_the_quiz_is_created_before_its_lesson_and_linked_last() -> None:
    fake = built()
    order = [(m, t) for m, t, _ in fake.writes]
    assert order.index(("POST", "LMS Quiz")) < order.index(("POST", "Course Lesson"))
    last_put = max(i for i, (m, t) in enumerate(order) if m == "PUT" and t == "LMS Quiz")
    last_lesson_put = max(
        i for i, (m, t) in enumerate(order) if m == "PUT" and t == "Course Lesson"
    )
    assert last_lesson_put < last_put


def test_a_second_run_writes_nothing_and_says_so() -> None:
    fake = built()
    before = len(fake.writes)
    code, said = run(fake)
    assert (code, said) == (0, ["nothing to change"])
    assert len(fake.writes) == before


def test_a_renamed_title_updates_the_same_record_without_a_duplicate() -> None:
    fake = built()
    c = course()
    renamed = replace(c, chapters=(replace(c.chapters[0], title="Uno"), c.chapters[1]))
    name = fake.by_key("Course Chapter", "ch1")["name"]
    code, said = run(fake, renamed)
    assert code == 0
    assert fake.of("Course Chapter")[name]["title"] == "Uno"
    assert len(fake.of("Course Chapter")) == 2
    assert "updated Course Chapter ch1: title" in said
    assert any("Course Chapter ch1 title: LMS has 'One', git has 'Uno'" in line for line in said)


def test_an_edit_in_the_lms_is_warned_about_then_overwritten() -> None:
    fake = built()
    fake.by_key("Course Lesson", "lab")["body"] = "edited in the desk"
    code, said = run(fake)
    assert code == 0
    assert any("LMS has 'edited in the desk', git has '# Lab'" in line for line in said)
    assert fake.by_key("Course Lesson", "lab")["body"] == "# Lab"


def test_check_changes_nothing_and_exits_1_on_an_edit() -> None:
    fake = built()
    fake.by_key("Course Lesson", "lab")["body"] = "edited"
    before = len(fake.writes)
    code, said = run(fake, check=True)
    assert code == 1
    assert len(fake.writes) == before
    assert any(line.startswith("differs: Course Lesson lab body") for line in said)


def test_check_on_a_clean_state_exits_0() -> None:
    assert run(built(), check=True) == (0, ["nothing to change"])


def test_check_lists_creates_for_what_git_added() -> None:
    fake = built()
    c = course()
    more = replace(
        c, chapters=(*c.chapters, Chapter("ch3", "Three", (LabLesson("l3", "Lab 3", "x"),)))
    )
    code, said = run(fake, more, check=True)
    assert code == 1
    assert "would create Course Chapter ch3" in said
    assert "would create Course Lesson l3" in said
    assert len(fake.of("Course Chapter")) == 2


def test_check_on_an_empty_site_lists_every_create_and_writes_nothing() -> None:
    fake = FakeLms()
    code, said = run(fake, check=True)
    assert code == 1
    assert "would create LMS Course c" in said
    assert fake.writes == []


def test_check_lists_a_record_with_no_key_as_unmanaged() -> None:
    fake = built()
    fake.seed(
        "Course Lesson",
        "stray",
        title="Stray",
        chapter="x",
        course=fake.by_key("LMS Course", "c")["name"],
    )
    code, said = run(fake, check=True)
    assert code == 1
    assert "unmanaged Course Lesson stray: has no nile_key" in said


def test_a_removed_lesson_leaves_the_outline_but_is_kept() -> None:
    fake = built()
    c = course()
    slim = replace(
        c,
        chapters=(c.chapters[0], replace(c.chapters[1], lessons=c.chapters[1].lessons[:1])),
        quizzes=c.quizzes[:1],
    )
    code, said = run(fake, slim)
    assert code == 0
    ch2 = fake.by_key("Course Chapter", "ch2")
    assert [r["lesson"] for r in ch2["lessons"]] == [fake.by_key("Course Lesson", "lab")["name"]]
    assert "Course Lesson lq" in " ".join(s for s in said if s.startswith("detached"))
    assert fake.by_key("Course Lesson", "lq")  # kept
    assert "Course Lesson" in fake.docs and len(fake.of("Course Lesson")) == 4
    assert fake.by_key("LMS Quiz", "q2")["lesson"] == ""
    assert fake.by_key("LMS Quiz", "q2")["course"] == fake.by_key("LMS Course", "c")["name"]


def test_a_rerun_after_a_removal_has_nothing_left_to_detach() -> None:
    fake = built()
    c = course()
    slim = replace(
        c,
        chapters=(c.chapters[0], replace(c.chapters[1], lessons=c.chapters[1].lessons[:1])),
        quizzes=c.quizzes[:1],
    )
    run(fake, slim)
    before = len(fake.writes)
    assert run(fake, slim) == (0, ["nothing to change"])
    assert run(fake, slim, check=True) == (0, ["nothing to change"])
    assert len(fake.writes) == before


def test_a_removed_question_is_detached_and_kept() -> None:
    fake = built()
    c = course()
    fewer = replace(
        c,
        quizzes=(
            c.quizzes[0],
            replace(c.quizzes[1], questions=(Question("q4", "Four?", options=OPTIONS),)),
        ),
    )
    code, said = run(fake, fewer)
    assert code == 0
    assert any(s.startswith("detached LMS Question q3") for s in said)
    assert fake.by_key("LMS Question", "q3")
    rows = fake.by_key("LMS Quiz", "q2")["questions"]
    assert [r["question"] for r in rows] == [fake.by_key("LMS Question", "q4")["name"]]


def test_progress_reaches_100_after_a_lesson_is_removed() -> None:
    fake = built()
    course_name = fake.by_key("LMS Course", "c")["name"]
    lessons = {k: fake.by_key("Course Lesson", k)["name"] for k in ("v", "ql", "lab", "lq")}
    fake.seed("LMS Enrollment", "e1", course=course_name, member="s@x", progress=75.0)
    for k in ("v", "ql", "lab"):
        fake.seed(
            "LMS Course Progress",
            f"p-{k}",
            course=course_name,
            member="s@x",
            lesson=lessons[k],
            status="Complete",
        )
    c = course()
    slim = replace(
        c,
        chapters=(c.chapters[0], replace(c.chapters[1], lessons=c.chapters[1].lessons[:1])),
        quizzes=c.quizzes[:1],
    )
    run(fake, slim)
    assert fake.of("LMS Enrollment")["e1"]["progress"] == 100.0


def test_a_progress_row_of_a_detached_lesson_does_not_count() -> None:
    fake = built()
    course_name = fake.by_key("LMS Course", "c")["name"]
    gone = fake.by_key("Course Lesson", "lq")["name"]
    fake.seed("LMS Enrollment", "e1", course=course_name, member="s@x", progress=25.0)
    fake.seed(
        "LMS Course Progress",
        "p1",
        course=course_name,
        member="s@x",
        lesson=gone,
        status="Complete",
    )
    c = course()
    slim = replace(
        c,
        chapters=(c.chapters[0], replace(c.chapters[1], lessons=c.chapters[1].lessons[:1])),
        quizzes=c.quizzes[:1],
    )
    run(fake, slim)
    assert fake.of("LMS Enrollment")["e1"]["progress"] == 0.0


def test_no_batch_is_touched_and_a_hand_published_course_is_set_back() -> None:
    fake = built()
    fake.seed("LMS Batch", "b1", courses=[])
    name = fake.by_key("LMS Course", "c")["name"]
    fake.docs["LMS Course"][name]["published"] = 1
    assert run(fake)[0] == 0
    assert fake.of("LMS Course")[name]["published"] == 0
    assert fake.of("LMS Batch")["b1"]["courses"] == []
    assert run(fake)[1] == ["nothing to change"]


def test_a_retitle_prints_old_and_new_title_in_check_and_in_a_real_run() -> None:
    fake = built()
    new = replace(course(), title="Renamed")
    for check in (True, False):
        said = run(fake, new, check=check)[1]
        assert any(
            "'Renamed'" in line and "Authentik group name must change" in line for line in said
        )
        if check:
            assert not any(line.startswith("updated") for line in said)


def test_a_duplicate_title_is_refused_with_the_case_kept_and_nothing_is_written() -> None:
    fake = FakeLms()
    fake.seed("LMS Course", "hand-made", title=course().title)
    with pytest.raises(LmsError, match="hand-made"):
        run(fake)
    assert not fake.writes
    fake = FakeLms()
    fake.seed("LMS Course", "hand-made", title=course().title.upper())
    assert run(fake)[0] == 0


def test_a_title_equal_to_the_admin_group_is_refused() -> None:
    with pytest.raises(LmsError, match="admin group"):
        run(FakeLms(), admin=course().title)


def test_a_failed_write_stops_and_a_rerun_finishes_the_job() -> None:
    fake = FakeLms()
    fake.fail_write = lambda n, m, d: (
        httpx.Response(500, json={"exc_type": "ValidationError"}) if n == 3 else None
    )
    with pytest.raises(LmsError, match="HTTP 500, ValidationError"):
        run(fake)
    assert len(fake.writes) == 2
    fake.fail_write = lambda n, m, d: None
    assert run(fake)[0] == 0
    assert len(fake.of("Course Lesson")) == 4
    assert run(fake) == (0, ["nothing to change"])


def test_a_create_that_saved_but_timed_out_is_found_by_key_on_the_rerun() -> None:
    fake = FakeLms()
    fake.seed("LMS Course", "saved", nile_key="c", title="Course")
    code, said = run(fake)
    assert code == 0
    assert len(fake.of("LMS Course")) == 1
    assert "created LMS Course c" not in said


def test_a_half_finished_run_is_completed_by_the_next() -> None:
    fake = built()
    lesson = fake.by_key("Course Lesson", "ql")
    lesson["quiz_id"] = None
    lesson["body"] = ""
    quiz = fake.by_key("LMS Quiz", "q")
    quiz["lesson"], quiz["course"] = None, None
    assert run(fake)[0] == 0
    assert lesson["quiz_id"] == quiz["name"]
    assert quiz["lesson"] == lesson["name"]


def test_escaped_rich_text_does_not_cause_a_write_on_the_next_run() -> None:
    fake = built()
    assert fake.by_key("LMS Course", "c")["description"] == "A & B"
    assert run(fake)[1] == ["nothing to change"]


def test_the_output_never_holds_the_secret() -> None:
    fake = FakeLms()
    fake.fail_write = lambda n, m, d: httpx.Response(403, json={"exc_type": "PermissionError"})
    with pytest.raises(LmsError) as e:
        run(fake)
    assert "token" not in str(e.value)


def test_a_removed_chapter_settles_and_check_then_passes() -> None:
    # covers: AC-2, AC-6. The lessons of a detached chapter must not stay "detached" forever.
    fake = built()
    c = course()
    gone = replace(c, chapters=c.chapters[:1], quizzes=c.quizzes[:1])
    assert run(fake, gone)[0] == 0
    assert run(fake, gone) == (0, ["nothing to change"])
    assert run(fake, gone, check=True) == (0, ["nothing to change"])


def test_a_lesson_removed_from_a_kept_chapter_settles_after_one_run() -> None:
    # covers: AC-2, AC-5
    fake = built()
    c = course()
    first = c.chapters[0]
    gone = replace(c, chapters=(replace(first, lessons=first.lessons[1:]), c.chapters[1]))
    code, said = run(fake, gone)
    assert code == 0
    assert "detached Course Lesson v (kept in the LMS, out of the course)" in said
    assert run(fake, gone) == (0, ["nothing to change"])


def test_moving_a_lesson_between_chapters_is_not_called_unmanaged() -> None:
    # covers: AC-5, AC-6
    fake = built()
    c = course()
    one, two = c.chapters
    moved = replace(
        c,
        chapters=(
            replace(one, lessons=one.lessons[1:]),
            replace(two, lessons=(*two.lessons, one.lessons[0])),
        ),
    )
    code, said = run(fake, moved)
    assert code == 0
    assert not any("unmanaged" in line for line in said)


def test_text_with_a_tag_is_escaped_by_the_lms_and_still_settles() -> None:
    # covers: AC-2. Frappe escapes `&` only in values that hold an HTML tag.
    fake = FakeLms()
    c = replace(course(), description="<p>A & B</p>")
    assert run(fake, c)[0] == 0
    assert fake.by_key("LMS Course", "c")["description"] == "<p>A &amp; B</p>"
    assert run(fake, c) == (0, ["nothing to change"])
