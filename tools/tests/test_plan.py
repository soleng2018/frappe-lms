"""Unit tests for nile_tools.plan: creates, updates, detaches, progress (AC-1 to 6, 8)."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

from courses import LabLesson, QuizLesson, VideoLesson

from nile_tools import plan
from nile_tools.content import (
    Chapter,
    Course,
    Option,
    Question,
    Quiz,
    lesson_quiz_key,
)
from nile_tools.plan import (
    Detach,
    Found,
    Ref,
    Unmanaged,
    Update,
    course_progress,
    outline_changed,
    plan_creates,
    plan_sync,
)

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
                (
                    VideoLesson("v", "Video", "dQw4w9WgXcQ"),
                    QuizLesson("ql", "Quiz lesson", "q"),
                ),
            ),
            Chapter("ch2", "Two", (LabLesson("lab", "Lab", "# Lab\n& more"),)),
        ),
        quizzes=(
            Quiz(
                "q",
                "Quiz",
                "ql",
                (
                    Question("q1", "One?", options=OPTIONS),
                    Question("q2", "Two?", options=OPTIONS, marks=2),
                ),
            ),
        ),
    )


def synced(c: Course) -> Found:
    """The LMS state after a perfect sync of `c`, with names `N-<key>`."""
    lessons = [(ch.key, x) for ch in c.chapters for x in ch.lessons]
    quiz_of = {x.key: k for _, x in lessons if (k := lesson_quiz_key(x))}
    doc_course = {"name": "N-c", "nile_key": c.key, **plan._course_fields(c)}
    doc_course["chapters"] = [{"chapter": f"N-{ch.key}"} for ch in c.chapters]
    chapters = tuple(
        {
            "name": f"N-{ch.key}",
            "nile_key": ch.key,
            "title": ch.title,
            "course": "N-c",
            "lessons": [{"lesson": f"N-{x.key}"} for x in ch.lessons],
        }
        for ch in c.chapters
    )
    docs = tuple(
        {
            "name": f"N-{x.key}",
            "nile_key": x.key,
            "title": x.title,
            "chapter": f"N-{ck}",
            **plan._lesson_fields(x, f"N-{quiz_of[x.key]}" if x.key in quiz_of else None),
        }
        for ck, x in lessons
    )
    quizzes = tuple(
        {
            "name": f"N-{q.key}",
            "nile_key": q.key,
            "title": q.title,
            "course": "N-c",
            "passing_percentage": q.passing_percentage,
            "max_attempts": q.max_attempts,
            "lesson": f"N-{q.lesson_key}",
            "questions": [{"question": f"N-{x.key}", "marks": x.marks} for x in q.questions],
        }
        for q in c.quizzes
    )
    questions = tuple(
        {"name": f"N-{x.key}", "nile_key": x.key, **plan._question_fields(x)}
        for q in c.quizzes
        for x in q.questions
    )
    return Found(doc_course, chapters, docs, quizzes, questions)


def edit(found: Found, doctype: str, key: str, **fields: Any) -> Found:
    attr = {
        plan.CHAPTER: "chapters",
        plan.LESSON: "lessons",
        plan.QUIZ: "quizzes",
        plan.QUESTION: "questions",
    }.get(doctype)
    if attr is None:
        assert found.course is not None
        return replace(found, course={**found.course, **fields})
    docs = tuple({**d, **fields} if d["nile_key"] == key else d for d in getattr(found, attr))
    changes: dict[str, Any] = {attr: docs}
    return replace(found, **changes)


def only_update(actions: tuple[plan.Action, ...]) -> Update:
    updates = [a for a in actions if isinstance(a, Update)]
    assert len(updates) == 1, actions
    return updates[0]


def test_a_synced_course_needs_nothing() -> None:
    found = synced(course())
    assert plan_creates(course(), found) == ()
    assert plan_sync(course(), found) == ()


def test_an_empty_lms_needs_everything_in_dependency_order() -> None:
    creates = plan_creates(course(), Found())
    kinds = [c.doctype for c in creates]
    assert kinds == [
        plan.COURSE,
        *[plan.CHAPTER] * 2,
        *[plan.QUESTION] * 2,
        plan.QUIZ,
        *[plan.LESSON] * 3,
    ]
    assert [c.key for c in creates][:3] == ["c", "ch1", "ch2"]


def test_creates_carry_only_what_is_needed_and_refs_for_what_is_not_made_yet() -> None:
    by_key = {c.key: c for c in plan_creates(course(), Found())}
    assert by_key["ch1"].fields == {"title": "One", "course": Ref(plan.COURSE, "c")}
    quiz = by_key["q"].fields
    assert quiz["questions"] == [
        {"question": Ref(plan.QUESTION, "q1"), "marks": 1},
        {"question": Ref(plan.QUESTION, "q2"), "marks": 2},
    ]
    assert "lesson" not in quiz  # the back link is written last
    assert by_key["ql"].fields == {"title": "Quiz lesson", "chapter": Ref(plan.CHAPTER, "ch1")}
    assert by_key["v"].fields["body"] == '{{ YouTubeVideo("dQw4w9WgXcQ") }}'
    assert by_key["lab"].fields["body"] == "# Lab\n& more"
    assert by_key["c"].fields["published"] == 0
    assert by_key["c"].fields["enable_certification"] == 1
    assert by_key["c"].fields["enforce_lesson_completion"] == 0


def test_the_question_fields_hold_options_in_file_order_and_blank_the_rest() -> None:
    fields = {c.key: c for c in plan_creates(course(), Found())}["q1"].fields
    assert (fields["option_1"], fields["is_correct_1"]) == ("yes", 1)
    assert (fields["option_2"], fields["is_correct_2"]) == ("no", 0)
    assert (fields["option_3"], fields["is_correct_3"]) == ("", 0)
    assert fields["type"] == "Choices"


def test_option_explanations_fill_their_own_field_and_clear_the_rest() -> None:
    question = Question("q1", "Which?", options=(Option("a", True, "Because"), Option("b")))
    fields = plan._question_fields(question)
    assert fields["explanation_1"] == "Because"
    assert [fields[f"explanation_{i}"] for i in (2, 3, 4)] == ["", "", ""]


def _with_explanation(text: str) -> Course:
    c = course()
    q = c.quizzes[0]
    first = replace(q.questions[0], options=(Option("yes", True, text), Option("no")))
    return replace(c, quizzes=(replace(q, questions=(first, *q.questions[1:])),))


def test_adding_an_option_explanation_is_an_update_of_that_field() -> None:
    # covers: AC-11
    update = only_update(plan_sync(_with_explanation("Because"), synced(course())))
    assert (update.key, [(x.field, x.wanted) for x in update.changes]) == (
        "q1",
        [("explanation_1", "Because")],
    )


def test_removing_an_option_explanation_clears_the_field() -> None:
    # covers: AC-11
    update = only_update(plan_sync(course(), synced(_with_explanation("Because"))))
    assert [(x.field, x.found, x.wanted) for x in update.changes] == [
        ("explanation_1", "Because", "")
    ]


def test_a_synced_explanation_or_a_null_one_needs_nothing() -> None:
    # covers: AC-8, AC-11. A second run changes nothing; an empty LMS value may be null.
    assert plan_sync(_with_explanation("Because"), synced(_with_explanation("Because"))) == ()
    found = edit(synced(course()), plan.QUESTION, "q1", explanation_1=None, explanation_3=None)
    assert plan_sync(course(), found) == ()


def test_only_missing_records_are_created() -> None:
    found = synced(course())
    found = replace(found, lessons=tuple(d for d in found.lessons if d["nile_key"] != "lab"))
    assert [c.key for c in plan_creates(course(), found)] == ["lab"]


def test_a_title_change_updates_the_same_record_with_one_field() -> None:
    c = course()
    renamed = replace(c, chapters=(replace(c.chapters[0], title="Uno"), c.chapters[1]))
    update = only_update(plan_sync(renamed, synced(c)))
    assert (update.doctype, update.key, update.name) == (plan.CHAPTER, "ch1", "N-ch1")
    assert [(x.field, x.found, x.wanted) for x in update.changes] == [("title", "One", "Uno")]


def test_frappe_escaping_of_rich_text_is_not_a_difference() -> None:
    found = edit(synced(course()), plan.COURSE, "c", description="A &amp; B\n")
    found = edit(found, plan.QUESTION, "q1", question="One?  ")
    assert plan_sync(course(), found) == ()


def test_an_edit_made_in_the_lms_is_found_and_names_what_each_side_holds() -> None:
    found = edit(synced(course()), plan.LESSON, "lab", body="edited in the desk")
    update = only_update(plan_sync(course(), found))
    assert (update.key, update.changes[0].found, update.changes[0].wanted) == (
        "lab",
        "edited in the desk",
        "# Lab\n& more",
    )


def test_a_changed_option_or_pass_mark_is_an_update() -> None:
    found = edit(synced(course()), plan.QUESTION, "q2", option_2="maybe")
    assert only_update(plan_sync(course(), found)).changes[0].field == "option_2"
    found = edit(synced(course()), plan.QUIZ, "q", passing_percentage=50)
    assert only_update(plan_sync(course(), found)).changes[0].field == "passing_percentage"


def test_a_lesson_moved_to_another_chapter_updates_the_lesson_and_both_tables() -> None:
    c = course()
    moved = replace(
        c,
        chapters=(
            replace(c.chapters[0], lessons=c.chapters[0].lessons[1:]),
            replace(c.chapters[1], lessons=(c.chapters[0].lessons[0], *c.chapters[1].lessons)),
        ),
    )
    updates = {u.key: u for u in plan_sync(moved, synced(c)) if isinstance(u, Update)}
    assert set(updates) == {"v", "ch1", "ch2"}
    assert updates["v"].changes[0].wanted == "N-ch2"
    assert updates["ch1"].changes[0].wanted == ("N-ql",)
    assert updates["ch2"].changes[0].wanted == ("N-v", "N-lab")
    assert outline_changed((), tuple(updates.values()))


def test_reordering_lessons_rewrites_the_table() -> None:
    c = course()
    swapped = replace(
        c, chapters=(replace(c.chapters[0], lessons=c.chapters[0].lessons[::-1]), c.chapters[1])
    )
    assert only_update(plan_sync(swapped, synced(c))).changes[0].wanted == ("N-ql", "N-v")


def test_a_removed_lesson_is_detached_and_dropped_from_the_outline_not_deleted() -> None:
    c = course()
    slim = replace(
        c,
        chapters=(replace(c.chapters[0], lessons=c.chapters[0].lessons[:1]), c.chapters[1]),
        quizzes=(),
    )
    actions = plan_sync(slim, synced(c))
    assert Detach(plan.LESSON, "ql", "N-ql") in actions
    chapter = next(a for a in actions if isinstance(a, Update) and a.key == "ch1")
    assert chapter.changes[0].wanted == ("N-v",)
    assert chapter.notes == ()  # a detached lesson is reported as detached, not as unmanaged
    assert outline_changed((), actions)


def test_a_removed_chapter_is_detached_and_dropped_from_the_course() -> None:
    c = course()
    slim = replace(c, chapters=c.chapters[:1])
    actions = plan_sync(slim, synced(c))
    assert Detach(plan.CHAPTER, "ch2", "N-ch2") in actions
    assert Detach(plan.LESSON, "lab", "N-lab") in actions
    course_update = next(a for a in actions if isinstance(a, Update) and a.doctype == plan.COURSE)
    assert course_update.changes[0].wanted == ("N-ch1",)


def test_a_removed_quiz_is_detached_and_its_lesson_link_cleared_but_the_course_kept() -> None:
    c = course()
    lesson_gone = replace(
        c,
        chapters=(replace(c.chapters[0], lessons=c.chapters[0].lessons[:1]), c.chapters[1]),
        quizzes=(),
    )
    actions = plan_sync(lesson_gone, synced(c))
    assert Detach(plan.QUIZ, "q", "N-q") in actions
    cleared = next(a for a in actions if isinstance(a, Update) and a.doctype == plan.QUIZ)
    assert [(x.field, x.wanted) for x in cleared.changes] == [("lesson", "")]


def test_a_removed_question_is_detached_and_its_row_leaves_the_quiz() -> None:
    c = course()
    fewer = replace(c, quizzes=(replace(c.quizzes[0], questions=c.quizzes[0].questions[:1]),))
    actions = plan_sync(fewer, synced(c))
    assert Detach(plan.QUESTION, "q2", "N-q2") in actions
    quiz = next(a for a in actions if isinstance(a, Update) and a.doctype == plan.QUIZ)
    assert quiz.changes[0].wanted == (("N-q1", 1),)


def test_marks_come_from_the_quiz_row_and_a_change_rewrites_the_rows() -> None:
    c = course()
    heavier = replace(
        c,
        quizzes=(
            replace(
                c.quizzes[0],
                questions=(replace(c.quizzes[0].questions[0], marks=5), c.quizzes[0].questions[1]),
            ),
        ),
    )
    quiz = only_update(plan_sync(heavier, synced(c)))
    assert quiz.changes[0].wanted == (("N-q1", 5), ("N-q2", 2))
    assert plan.payload("questions", quiz.changes[0].wanted) == [
        {"question": "N-q1", "marks": 5},
        {"question": "N-q2", "marks": 2},
    ]


def test_records_made_in_the_lms_without_a_key_are_listed_and_their_rows_dropped() -> None:
    found = synced(course())
    stray = {"name": "N-stray", "title": "Stray", "chapter": "N-ch1"}
    found = replace(found, lessons=(*found.lessons, stray))
    chapters = tuple(
        {**d, "lessons": [*d["lessons"], {"lesson": "N-stray"}]} if d["nile_key"] == "ch1" else d
        for d in found.chapters
    )
    found = replace(found, chapters=chapters)
    actions = plan_sync(course(), found)
    assert Unmanaged(plan.LESSON, "N-stray") in actions
    chapter = only_update(actions)
    assert chapter.notes == ("removed unmanaged row N-stray",)
    assert chapter.changes[0].wanted == ("N-v", "N-ql")


def test_a_question_without_a_key_in_a_quiz_is_dropped_with_a_note() -> None:
    found = synced(course())
    quizzes = tuple(
        {**d, "questions": [*d["questions"], {"question": "QTS-stray", "marks": 1}]}
        for d in found.quizzes
    )
    quiz = only_update(plan_sync(course(), replace(found, quizzes=quizzes)))
    assert quiz.notes == ("removed unmanaged row QTS-stray",)


def test_a_run_that_stopped_before_the_quiz_links_finishes_on_the_next_run() -> None:
    found = edit(synced(course()), plan.LESSON, "ql", quiz_id=None, body="")
    found = edit(found, plan.QUIZ, "q", lesson=None, course=None)
    actions = plan_sync(course(), found)
    fields = {(a.key, c.field) for a in actions if isinstance(a, Update) for c in a.changes}
    assert fields == {("ql", "quiz_id"), ("ql", "body"), ("q", "lesson"), ("q", "course")}
    order = [a.key for a in actions if isinstance(a, Update)]
    assert order.index("ql") < order.index("q")  # the back link is written last


def test_the_quiz_lesson_body_uses_the_name_lms_gave_not_the_title() -> None:
    found = synced(course())
    renamed = tuple({**d, "name": "quiz-2"} if d["nile_key"] == "q" else d for d in found.quizzes)
    found = replace(found, quizzes=renamed)
    lesson = next(a for a in plan_sync(course(), found) if isinstance(a, Update) and a.key == "ql")
    wanted = {c.field: c.wanted for c in lesson.changes}
    assert wanted == {"quiz_id": "quiz-2", "body": '{{ Quiz("quiz-2") }}'}


def test_records_not_in_the_lms_yet_are_left_to_the_creates() -> None:
    found = Found(course={"name": "N-c", "nile_key": "c", **plan._course_fields(course())})
    assert plan_sync(course(), found) == ()
    assert [c.key for c in plan_creates(course(), found)][:2] == ["ch1", "ch2"]


def test_no_course_in_the_lms_means_no_updates() -> None:
    assert plan_sync(course(), Found()) == ()


def test_the_plan_does_not_change_its_input() -> None:
    found = synced(course())
    before = deepcopy(found)
    plan_sync(course(), found)
    assert found == before


def test_outline_changed_is_false_for_a_title_change_and_true_for_a_new_lesson() -> None:
    c = course()
    renamed = replace(c, chapters=(replace(c.chapters[0], title="Uno"), c.chapters[1]))
    assert not outline_changed((), plan_sync(renamed, synced(c)))
    creates = plan_creates(c, replace(synced(c), lessons=synced(c).lessons[:1]))
    assert outline_changed(creates, ())


def test_progress_counts_only_lessons_still_in_the_outline() -> None:
    assert course_progress({"a", "b", "gone"}, ["a", "b"]) == 100.0
    assert course_progress({"a"}, ["a", "b", "c"]) == 33.333
    assert course_progress(set(), ["a"]) == 0.0
    assert course_progress({"a"}, []) == 0.0


def test_a_record_already_out_of_the_outline_is_not_detached_again() -> None:
    c = course()
    slim = replace(
        c,
        chapters=(c.chapters[0], replace(c.chapters[1], lessons=c.chapters[1].lessons[:1])),
        quizzes=c.quizzes[:1],
    )
    found = synced(c)
    found = edit(found, plan.CHAPTER, "ch2", lessons=[{"lesson": "N-lab"}])
    found = edit(found, plan.QUIZ, "q2", lesson="")
    assert plan_sync(slim, found) == ()


def test_a_question_used_by_a_quiz_of_another_course_is_held_elsewhere() -> None:
    # covers: AC-7. The LMS keeps one nile_key per record type for the whole site.
    other = {"name": "N-other", "title": "Elsewhere", "nile_key": "other"}
    have = synced(course())
    quiz = {**have.quizzes[0], "name": "O-q", "nile_key": "o-q", "course": "N-other"}
    found = Found(None, (), (), (quiz,), have.questions, (other,))
    note = plan.held_elsewhere(course(), found)
    assert note is not None and "Elsewhere" in note and "Course Question" not in note


def test_a_question_used_only_by_this_course_is_not_held_elsewhere() -> None:
    assert plan.held_elsewhere(course(), synced(course())) is None


def test_no_cover_in_git_clears_the_cover_in_the_lms() -> None:
    # covers: AC-4. Removing `image:` from course.yaml must not leave an old cover behind.
    found = edit(synced(course()), "course", "c", image="/files/old.png")
    update = only_update(plan_sync(course(), found))
    assert [(x.field, x.found, x.wanted) for x in update.changes] == [
        ("image", "/files/old.png", "")
    ]
