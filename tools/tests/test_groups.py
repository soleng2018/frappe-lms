"""Unit tests for nile_auth.groups.decide (spec 0006 AC-4, AC-5, AC-7). No Frappe needed."""

import pytest
from nile_auth.groups import decide, landing_path, safe_return_path

ARGS = ("hol-admins", "NileWorkshop", "Admin")


def test_a_workshop_member_is_a_student() -> None:
    d = decide(["NileWorkshop3Admin", "other"], *ARGS)
    assert d.kind == "member"
    assert d.workshop_groups == ("NileWorkshop3Admin",)
    assert d.matched_groups == ("NileWorkshop3Admin",)
    assert not d.is_admin
    assert d.desired_roles == ("LMS Student",)


def test_an_admin_only_gets_admin_roles_and_no_student_role() -> None:
    d = decide(["hol-admins"], *ARGS)
    assert d.is_admin
    assert d.workshop_groups == ()
    assert d.matched_groups == ("hol-admins",)
    assert d.desired_roles == ("Moderator", "Course Creator", "Desk User")


def test_an_admin_in_a_workshop_group_gets_both() -> None:
    d = decide(["hol-admins", "NileWorkshop2Admin"], *ARGS)
    assert d.matched_groups == ("NileWorkshop2Admin", "hol-admins")
    assert set(d.desired_roles) == {"LMS Student", "Moderator", "Course Creator", "Desk User"}


def test_workshop_groups_sort_by_number_and_admin_comes_last() -> None:
    d = decide(
        ["hol-admins", "NileWorkshop10Admin", "NileWorkshop2Admin", "NileWorkshop2Admin"], *ARGS
    )
    assert d.workshop_groups == ("NileWorkshop2Admin", "NileWorkshop10Admin")
    assert d.matched_groups == ("NileWorkshop2Admin", "NileWorkshop10Admin", "hol-admins")


@pytest.mark.parametrize(
    "name",
    [
        "nileworkshop3admin",
        "NileWorkshop0Admin",
        "NileWorkshop03Admin",
        "NileWorkshopAdmin",
        "NileWorkshop3Admin2",
        "xNileWorkshop3Admin",
        "NileWorkshop-3Admin",
        "NileWorkshop3 Admin",
        " NileWorkshop3Admin",
        "NileWorkshop३Admin",
        "HOL-ADMINS",
        "hol-admins ",
    ],
)
def test_near_misses_count_for_nothing(name: str) -> None:
    assert decide([name], *ARGS).kind == "no_group"


def test_a_user_in_no_matching_group_is_no_group() -> None:
    assert decide([], *ARGS).kind == "no_group"
    assert decide(["staff"], *ARGS).kind == "no_group"


def test_prefix_and_suffix_are_text_not_patterns() -> None:
    d = decide(["a.b7(x)", "axb7(x)"], "adm", "a.b", "(x)")
    assert d.workshop_groups == ("a.b7(x)",)


@pytest.mark.parametrize(
    "value", [None, "hol-admins", {"a": 1}, ("hol-admins",), 5, ["ok", 3], [None]]
)
def test_a_bad_groups_value_is_no_claim(value: object) -> None:
    d = decide(value, *ARGS)
    assert (d.kind, d.reason) == ("no_claim", "claim")
    assert d.desired_roles == ()


@pytest.mark.parametrize("which", [0, 1, 2])
@pytest.mark.parametrize("bad", ["", None, 4])
def test_an_empty_setting_is_a_settings_fault(which: int, bad: object) -> None:
    args: list[object] = list(ARGS)
    args[which] = bad
    d = decide(["hol-admins"], *args)
    assert (d.kind, d.reason) == ("no_claim", "settings")


def test_the_decision_is_immutable() -> None:
    with pytest.raises(AttributeError):
        decide(["hol-admins"], *ARGS).kind = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value", ["/lms/courses/x", "/lms", "/app?a=b", "/lms/%2Fok".replace("%2F", "a")]
)
def test_safe_return_path_accepts_paths_on_this_site(value) -> None:
    assert safe_return_path(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "//evil.example",
        "https://evil.example",
        "/\\evil",
        "/%2Fevil",
        "/%5cevil",
        "/a\nb",
        "",
        None,
        5,
    ],
)
def test_safe_return_path_rejects_everything_else(value) -> None:
    assert safe_return_path(value) is None


def test_landing_path_defaults_to_lms() -> None:
    assert landing_path("") == "/lms"
    assert landing_path("//evil.example") == "/lms"
    assert landing_path("/lms/courses/x") == "/lms/courses/x"
