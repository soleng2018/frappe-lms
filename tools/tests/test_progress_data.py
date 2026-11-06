"""Unit tests for nile_auth.progress_data and the two report scripts (spec 0013).

No site, no network. A small fake `frappe` is put in sys.modules for the length of each test, so
the real modules import and run against it. Only the Frappe boundary is faked.
"""

import importlib
import sys
import types
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

PROGRESS_REPORT = "nile_auth.nile_auth.report.learner_progress.learner_progress"
QUIZ_REPORT = "nile_auth.nile_auth.report.quiz_scores.quiz_scores"
OWNED = ("nile_auth.progress_data", PROGRESS_REPORT, QUIZ_REPORT)


class FakeValidationError(Exception):
    """Stands in for frappe.ValidationError."""


class FakeState:
    """What the fake frappe records and serves."""

    def __init__(self) -> None:
        self.roles: set[str] = set()
        self.conf: dict[str, Any] = {}
        self.get_all_calls: list[tuple[str, dict[str, Any]]] = []
        self.sql_calls: list[str] = []
        self.thrown: list[tuple[str, type]] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeState]:
    """Install a fake frappe, import the modules fresh, and remove them again afterwards."""
    st = FakeState()
    frappe = types.ModuleType("frappe")

    def only_for(roles: tuple[str, ...] | str) -> None:
        wanted = {roles} if isinstance(roles, str) else set(roles)
        if not wanted & st.roles:
            raise PermissionError("Not permitted")

    def get_all(doctype: str, **kwargs: Any) -> list[dict[str, Any]]:
        st.get_all_calls.append((doctype, kwargs))
        return st.rows.get(doctype, [])

    def sql(query: str, **_kw: Any) -> list[dict[str, Any]]:
        st.sql_calls.append(query)
        return st.rows.get("outline", [])

    def throw(message: str, exc: type = Exception) -> None:
        st.thrown.append((message, exc))
        raise exc(message)

    frappe.only_for = only_for  # type: ignore[attr-defined]
    frappe.get_all = get_all  # type: ignore[attr-defined]
    frappe.db = SimpleNamespace(sql=sql)  # type: ignore[attr-defined]
    frappe.conf = st.conf  # type: ignore[attr-defined]
    frappe.throw = throw  # type: ignore[attr-defined]
    frappe.ValidationError = FakeValidationError  # type: ignore[attr-defined]
    frappe._ = lambda text: text  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "frappe", frappe)
    for name in OWNED:
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield st
    for name in OWNED:
        sys.modules.pop(name, None)


def data_module() -> Any:
    return importlib.import_module("nile_auth.progress_data")


def report(path: str) -> Any:
    return importlib.import_module(path)


def seed_one_learner(st: FakeState) -> None:
    """One managed course with one quiz, one enrolled learner who passed it."""
    st.roles = {"Moderator"}
    st.rows = {
        "LMS Course": [{"name": "c1", "title": "Course One", "nile_key": "one"}],
        "outline": [{"course": "c1", "lesson": "l1"}],
        "LMS Enrollment": [{"member": "a@x.io", "course": "c1"}],
        "LMS Course Progress": [],
        "LMS Quiz": [
            {
                "name": "q1",
                "title": "Q1",
                "lesson": "l1",
                "max_attempts": 0,
                "passing_percentage": 80,
            }
        ],
        "LMS Quiz Submission": [
            {"member": "a@x.io", "quiz": "q1", "percentage": 90, "creation": 1}
        ],
        "LMS Certificate": [],
        "User": [{"name": "a@x.io", "full_name": "Ann", "enabled": 1}],
    }


# AC-1: access


@pytest.mark.parametrize("role", ["Moderator", "System Manager"])
def test_moderator_and_system_manager_pass_the_access_check(state: FakeState, role: str) -> None:
    """AC-1: both allowed roles may run the reports."""
    state.roles = {role}
    data_module().require_report_access()


@pytest.mark.parametrize("roles", [set(), {"LMS Student"}, {"Website User"}, {"Guest"}])
def test_other_roles_are_refused(state: FakeState, roles: set[str]) -> None:
    """AC-1: a student, website user, guest, or user with no role gets a permission error."""
    state.roles = roles
    with pytest.raises(PermissionError):
        data_module().require_report_access()


def test_access_is_checked_before_any_data_is_read(state: FakeState) -> None:
    """AC-1: a refused user triggers no query at all, so no data can leak."""
    state.roles = {"LMS Student"}
    with pytest.raises(PermissionError):
        data_module().load_rows()
    assert state.get_all_calls == []
    assert state.sql_calls == []


@pytest.mark.parametrize("path", [PROGRESS_REPORT, QUIZ_REPORT])
def test_each_report_refuses_a_student_and_returns_no_rows(state: FakeState, path: str) -> None:
    """AC-1: both reports raise for a student rather than return an empty table."""
    seed_one_learner(state)
    state.roles = {"LMS Student"}
    with pytest.raises(PermissionError):
        report(path).execute({})


def test_report_roles_are_exactly_moderator_and_system_manager(state: FakeState) -> None:
    """AC-1: the role list is the contract, so a change to it is a deliberate one."""
    assert set(data_module().REPORT_ROLES) == {"Moderator", "System Manager"}


# excluded users


def test_excluded_users_come_from_site_config(state: FakeState) -> None:
    """The service user and the MCP user are left out of the reports."""
    state.conf.update({"nile_service_user": "svc@x.io", "nile_mcp_user": "mcp@x.io"})
    assert data_module().excluded_users() == ["svc@x.io", "mcp@x.io"]


def test_missing_or_blank_config_excludes_nothing(state: FakeState) -> None:
    """A missing or empty key is skipped instead of excluding None or an empty name."""
    state.conf.update({"nile_service_user": "", "nile_mcp_user": None})
    assert data_module().excluded_users() == []


def test_load_rows_leaves_the_configured_users_out(state: FakeState) -> None:
    """AC-2: a configured service user with progress does not get a row."""
    seed_one_learner(state)
    state.rows["LMS Enrollment"].append({"member": "svc@x.io", "course": "c1"})
    state.rows["User"].append({"name": "svc@x.io", "full_name": "Svc", "enabled": 1})
    state.conf["nile_service_user"] = "svc@x.io"
    progress, _ = data_module().load_rows()
    assert [r["learner"] for r in progress] == ["a@x.io"]


# fetch


def test_every_dataset_name_has_a_query(state: FakeState) -> None:
    """AC-10: each dataset the rules ask for is served, and none is missing from fetch."""
    seed_one_learner(state)
    mod = data_module()
    from nile_auth.progress import DATASETS

    for name in DATASETS:
        assert isinstance(mod.fetch(name), list)


def test_unknown_dataset_raises_and_names_the_choices(state: FakeState) -> None:
    """A typo in a dataset name fails loudly and lists the valid names."""
    with pytest.raises(ValueError, match=r"Unknown dataset nope.*courses"):
        data_module().fetch("nope")


def test_courses_query_only_asks_for_managed_courses(state: FakeState) -> None:
    """AC-2: a course without a nile_key is filtered out by the query itself."""
    data_module().fetch("courses")
    doctype, kwargs = state.get_all_calls[-1]
    assert doctype == "LMS Course"
    assert kwargs["filters"] == {"nile_key": ["is", "set"]}


@pytest.mark.parametrize(
    "name", ["enrollments", "progress", "quizzes", "submissions", "certificates", "users"]
)
def test_list_queries_are_not_capped_at_the_default_page_size(state: FakeState, name: str) -> None:
    """AC-10: limit_page_length=0 so a big site is never cut off at 20 rows."""
    data_module().fetch(name)
    assert state.get_all_calls[-1][1]["limit_page_length"] == 0


def test_outline_query_is_static_and_ordered(state: FakeState) -> None:
    """AC-8: the outline comes ordered by chapter then lesson position, with no f-string."""
    data_module().fetch("outline")
    (query,) = state.sql_calls
    assert "order by cr.parent, cr.idx, lr.idx" in query
    assert "%" not in query
    assert "{" not in query


def test_one_run_makes_a_fixed_number_of_queries(state: FakeState) -> None:
    """AC-10: one report run is eight queries, however many learners exist."""
    seed_one_learner(state)
    data_module().load_rows()
    assert len(state.get_all_calls) + len(state.sql_calls) == 8


# filter errors


def test_throw_bad_filter_raises_a_validation_error_with_the_message(state: FakeState) -> None:
    """AC-7: a bad filter value becomes a validation error carrying the reason."""
    with pytest.raises(FakeValidationError, match="Status must be one of"):
        data_module().throw_bad_filter(ValueError("Status must be one of: a, b"))
    assert state.thrown[0][1] is FakeValidationError


# reports


def run_report(path: str, filters: dict[str, Any] | None = None) -> tuple[list[dict], list[dict]]:
    return report(path).execute(filters)


def test_learner_progress_columns_match_the_row_keys(state: FakeState) -> None:
    """AC-8: every column points at a key the rows really carry, so no cell renders blank."""
    seed_one_learner(state)
    columns, rows = run_report(PROGRESS_REPORT)
    assert rows
    assert {c["fieldname"] for c in columns} <= set(rows[0])


def test_quiz_scores_columns_match_the_row_keys(state: FakeState) -> None:
    """AC-8: the same check for Quiz Scores."""
    seed_one_learner(state)
    columns, rows = run_report(QUIZ_REPORT)
    assert rows
    assert {c["fieldname"] for c in columns} <= set(rows[0])


def test_learner_progress_runs_with_no_filters_at_all(state: FakeState) -> None:
    """AC-2: execute(None) works, as the desk calls it before any filter is set."""
    seed_one_learner(state)
    _, rows = run_report(PROGRESS_REPORT, None)
    assert [(r["learner"], r["status"]) for r in rows] == [("a@x.io", "Not started")]


def test_learner_progress_enrolled_only_accepts_the_desk_check_value(state: FakeState) -> None:
    """AC-7: the checkbox arrives as 0, 1, "0" or "1" and is read as a flag."""
    seed_one_learner(state)
    state.rows["LMS Certificate"] = [
        {
            "name": "cert",
            "member": "b@x.io",
            "course": "c1",
            "issue_date": "2026-01-01",
            "published": 1,
            "creation": 1,
        }
    ]
    state.rows["User"].append({"name": "b@x.io", "full_name": "Bo", "enabled": 1})
    assert len(run_report(PROGRESS_REPORT, {"enrolled_only": "0"})[1]) == 2
    for flag in (1, "1"):
        rows = run_report(PROGRESS_REPORT, {"enrolled_only": flag})[1]
        assert [r["learner"] for r in rows] == ["a@x.io"]


def test_learner_progress_bad_status_is_a_validation_error(state: FakeState) -> None:
    """AC-7: a status outside the four values is refused, not silently empty."""
    seed_one_learner(state)
    with pytest.raises(FakeValidationError, match="Status"):
        run_report(PROGRESS_REPORT, {"status": "Bogus"})


def test_quiz_scores_bad_state_is_a_validation_error(state: FakeState) -> None:
    """AC-8: a state outside the four values is refused."""
    seed_one_learner(state)
    with pytest.raises(FakeValidationError, match="State"):
        run_report(QUIZ_REPORT, {"state": "Bogus"})


@pytest.mark.parametrize("path", [PROGRESS_REPORT, QUIZ_REPORT])
def test_no_managed_course_gives_an_empty_table_without_error(state: FakeState, path: str) -> None:
    """AC-11: nothing to show is an empty list, never an error."""
    seed_one_learner(state)
    state.rows["LMS Course"] = []
    columns, rows = run_report(path)
    assert columns
    assert rows == []


@pytest.mark.parametrize("path", [PROGRESS_REPORT, QUIZ_REPORT])
def test_unmanaged_course_filter_gives_an_empty_table(state: FakeState, path: str) -> None:
    """AC-7, AC-11: a course id that is not managed returns no rows and no error."""
    seed_one_learner(state)
    _, rows = run_report(path, {"course": "some-other-course"})
    assert rows == []


def test_quiz_scores_filters_reach_the_rules(state: FakeState) -> None:
    """AC-8: the state and learner filters narrow the rows."""
    seed_one_learner(state)
    assert len(run_report(QUIZ_REPORT, {"state": "Passed"})[1]) == 1
    assert run_report(QUIZ_REPORT, {"state": "Locked"})[1] == []
    assert run_report(QUIZ_REPORT, {"learner": "nobody"})[1] == []


def test_course_id_column_is_hidden_and_the_learner_column_links_to_user(state: FakeState) -> None:
    """AC-9: the learner cell links to the User; the helper course id column stays out of sight."""
    for path in (PROGRESS_REPORT, QUIZ_REPORT):
        by_name = {c["fieldname"]: c for c in report(path).COLUMNS}
        assert by_name["course_name"]["hidden"] == 1
        assert by_name["learner"]["options"] == "User"


def test_certificate_column_links_to_the_certificate(state: FakeState) -> None:
    """AC-9: the certificate cell links to the LMS Certificate."""
    cols = {c["fieldname"]: c for c in report(PROGRESS_REPORT).COLUMNS}
    assert (cols["certificate"]["fieldtype"], cols["certificate"]["options"]) == (
        "Link",
        "LMS Certificate",
    )
