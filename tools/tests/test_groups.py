"""Unit tests for nile_auth.groups (spec 0009 AC-5, AC-6, AC-7, AC-11). No Frappe needed."""

import pytest
from nile_auth.groups import claim_fault, decide, landing_path, mode, safe_return_path

ADMIN = "hol-admins"
COURSES = [("nca", "Nile Certified Associate"), ("adv", "Advanced Lab")]
ROLES = ("Moderator", "Course Creator", "Desk User")


def test_one_course_group_is_live() -> None:
    d = decide(["staff", "Nile Certified Associate"], ADMIN, COURSES, False)
    assert (d.kind, d.course, d.course_group) == ("live", "nca", "Nile Certified Associate")
    assert d.matched_groups == ("Nile Certified Associate",)
    assert d.desired_roles == ("LMS Student",)
    assert not d.is_admin


def test_an_admin_in_a_course_group_gets_both() -> None:
    d = decide([ADMIN, "Advanced Lab"], ADMIN, COURSES, True)
    assert d.kind == "live"
    assert d.matched_groups == ("Advanced Lab", ADMIN)
    assert set(d.desired_roles) == {"LMS Student", *ROLES}
    assert d.is_admin


def test_an_admin_alone_is_admin_only() -> None:
    d = decide([ADMIN], ADMIN, COURSES, False)
    assert (d.kind, d.matched_groups, d.desired_roles) == ("admin_only", (ADMIN,), ROLES)


def test_a_known_learner_with_no_course_group_is_in_results_mode() -> None:
    d = decide(["staff"], ADMIN, COURSES, True)
    assert (d.kind, d.matched_groups, d.desired_roles) == ("results", (), ())


def test_a_known_learner_who_is_admin_stays_in_results_mode() -> None:
    d = decide([ADMIN], ADMIN, COURSES, True)
    assert (d.kind, d.desired_roles, d.is_admin) == ("results", ROLES, True)


def test_a_stranger_with_no_course_group_is_no_group() -> None:
    assert decide([], ADMIN, COURSES, False).kind == "no_group"
    assert decide(["staff"], ADMIN, COURSES, False).kind == "no_group"


@pytest.mark.parametrize(
    "name", ["staff", "Sales", "nile certified associate", "Nile Certified Associate "]
)
def test_near_misses_match_nothing(name: str) -> None:
    assert decide([name], ADMIN, COURSES, False).kind == "no_group"


def test_two_different_course_groups_are_refused_even_for_a_known_admin() -> None:
    d = decide([ADMIN, "Advanced Lab", "Nile Certified Associate"], ADMIN, COURSES, True)
    assert (d.kind, d.desired_roles, d.matched_groups) == ("two_courses", (), ())


def test_the_same_group_listed_twice_is_one_course_group() -> None:
    d = decide(["Advanced Lab", "Advanced Lab"], ADMIN, COURSES, False)
    assert d.kind == "live"


def test_one_group_equal_to_two_titles_is_a_bad_course() -> None:
    d = decide(["Dup"], ADMIN, [("a", "Dup"), ("b", "Dup")], False)
    assert (d.kind, d.course_group) == ("bad_course", "Dup")


def test_the_admin_group_is_never_a_course_group() -> None:
    d = decide([ADMIN], ADMIN, [("x", ADMIN)], False)
    assert d.kind == "admin_only"


@pytest.mark.parametrize("value", [None, ADMIN, {"a": 1}, (ADMIN,), 5, ["ok", 3], [None]])
def test_a_bad_groups_value_is_no_claim(value: object) -> None:
    assert claim_fault(value, ADMIN) == "claim"
    d = decide(value, ADMIN, COURSES, True)
    assert (d.kind, d.reason, d.desired_roles) == ("no_claim", "claim", ())


@pytest.mark.parametrize("bad", ["", None, 4])
def test_an_empty_admin_group_is_a_settings_fault(bad: object) -> None:
    assert claim_fault([], bad) == "settings"
    assert decide([], bad, COURSES, True).reason == "settings"


def test_an_empty_list_is_a_usable_claim() -> None:
    assert claim_fault([], ADMIN) is None


def test_the_decision_is_immutable() -> None:
    with pytest.raises(AttributeError):
        decide([ADMIN], ADMIN, COURSES, False).kind = "x"  # type: ignore[misc]


def test_modes() -> None:
    assert mode(decide(["Advanced Lab"], ADMIN, COURSES, False)) == "live"
    assert mode(decide([], ADMIN, COURSES, True)) == "results"
    assert mode(decide([ADMIN], ADMIN, COURSES, False)) == "admin"
    assert mode(decide([], ADMIN, COURSES, False)) == "none"


@pytest.mark.parametrize("value", ["/lms/courses/x", "/lms", "/app?a=b"])
def test_safe_return_path_accepts_paths_on_this_site(value: str) -> None:
    assert safe_return_path(value) == value


@pytest.mark.parametrize(
    "value", ["//evil.example", "https://evil.example", "/\\evil", "/%2Fevil", "/a\nb", "", None, 5]
)
def test_safe_return_path_rejects_everything_else(value: object) -> None:
    assert safe_return_path(value) is None


LIVE = decide(["Advanced Lab"], ADMIN, COURSES, False)
RESULTS = decide([], ADMIN, COURSES, True)
ADMIN_RESULTS = decide([ADMIN], ADMIN, COURSES, True)
ADMIN_LIVE = decide([ADMIN, "Advanced Lab"], ADMIN, COURSES, True)


def test_a_live_learner_lands_on_the_course() -> None:
    assert landing_path(LIVE, "kim") == "/lms/courses/adv"


def test_a_results_learner_lands_on_the_profile_url_encoded() -> None:
    assert landing_path(RESULTS, "kim") == "/lms/user/kim"
    assert landing_path(RESULTS, "a b/c") == "/lms/user/a%20b%2Fc"


def test_no_username_or_an_admin_lands_on_lms() -> None:
    assert landing_path(RESULTS, None) == "/lms"
    assert landing_path(RESULTS, "") == "/lms"
    assert landing_path(ADMIN_RESULTS, "kim") == "/lms"
    assert landing_path(ADMIN_LIVE, "kim") == "/lms"


@pytest.mark.parametrize(
    "absent", ["/", "/me", "/app", "/lms", "/lms/", "/lms/courses", "/lms/courses/", "", None]
)
def test_default_login_targets_count_as_absent(absent: str | None) -> None:
    assert landing_path(LIVE, "kim", absent) == "/lms/courses/adv"


def test_a_real_deep_link_wins_and_an_unsafe_one_does_not() -> None:
    assert (
        landing_path(LIVE, "kim", "/lms/courses/other/learn/1.1") == "/lms/courses/other/learn/1.1"
    )
    assert landing_path(ADMIN_LIVE, "kim", "/app/user") == "/app/user"
    assert landing_path(LIVE, "kim", "//evil.example") == "/lms/courses/adv"
