"""Unit tests for the MCP user self check (pure Python from nile_auth)."""

from nile_auth.mcp_user import MCP_ROLES, mcp_user_problems

GOOD = set(MCP_ROLES)


def test_a_good_user_has_no_problems():
    assert mcp_user_problems("System User", GOOD, []) == []


def test_every_fault_is_reported_together():
    problems = mcp_user_problems("Website User", {"System Manager", "LMS Student"}, ["Moderator"])
    assert len(problems) == 4
    text = " ".join(problems)
    for word in ("Website User", "Desk User", "Moderator", "System Manager"):
        assert word in text


def test_lms_roles_are_the_four_plus_desk_user():
    assert set(MCP_ROLES) == {
        "Desk User",
        "LMS Student",
        "Course Creator",
        "Moderator",
        "Batch Evaluator",
    }
