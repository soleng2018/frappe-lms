"""Spec 0008 on the live site: `idp selftest` signs real users in (pytest -m integration).

Needs the running stack, a finished `idp setup`, and a real `.env`. The selftest makes and removes
its own throwaway items; the refusal test makes one more Authentik user and removes it itself.
"""

import shutil
from pathlib import Path

import httpx
import pytest

from nile_tools import authentik, cli, config, idp, lms

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def values() -> dict[str, str]:
    if shutil.which("docker") is None or not (REPO / ".env").exists():
        pytest.skip("needs docker and a .env")
    return dict(config.load_env(REPO).values)


def _secrets(values: dict[str, str]) -> list[str]:
    """The Authentik token, the service secret and the OIDC client secret Frappe holds."""
    connection = cli._lms_from_env(values)
    client_secret = lms.get_password(
        connection, "Social Login Key", idp.FRAPPE_KEY_NAME, "client_secret"
    )
    return [
        values["AUTHENTIK_API_TOKEN"],
        values["LMS_API_SECRET"],
        *([client_secret] if client_secret else []),
    ]


def _leftovers(values: dict[str, str]) -> list[str]:
    ak = cli._authentik_from_env(values)
    found = [u["username"] for u in authentik.find(ak, "/core/users/", search=idp.TEST_PREFIX)]
    found += [g["name"] for g in authentik.find(ak, "/core/groups/", name=idp.TEST_COURSE_TITLE)]
    connection = cli._lms_from_env(values)
    found += [
        c["name"]
        for c in lms.list_records(
            connection, "LMS Course", filters=[["nile_key", "=", idp.TEST_COURSE_KEY]]
        )
    ]
    found += [
        u["name"]
        for u in lms.list_records(
            connection, "User", filters=[["name", "like", f"{idp.TEST_PREFIX}%"]]
        )
    ]
    return found


def test_setup_check_and_selftest_pass_leave_nothing_and_print_no_secret(values, capsys):
    """AC-1, AC-3, AC-4, AC-6, AC-10, AC-11, AC-12: the real container to Authentik path works."""
    assert cli.idp_setup(REPO) == 0
    assert cli.idp_check(REPO) == 0
    assert cli.idp_selftest(REPO) == 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    passes = [ln for ln in out.splitlines() if ln.startswith("PASS student lands")]
    assert len(passes) == 1, out
    assert not [ln for ln in out.splitlines() if ln.startswith("FAIL")], out
    for secret in _secrets(values):
        assert secret not in out
    assert _leftovers(values) == []


def test_it_refuses_an_unmarked_item_with_a_test_name_and_changes_nothing(values, capsys):
    """AC-11: an Authentik user with a test name and no marker stops the run before any write."""
    ak = cli._authentik_from_env(values)
    made = authentik.create(
        ak,
        "/core/users/",
        {"username": idp.TEST_STUDENT, "name": "Not ours", "type": "internal", "attributes": {}},
    )
    try:
        assert cli.idp_selftest(REPO) == 1
        assert "without the ownership marker" in capsys.readouterr().err
        assert authentik.get_one(ak, "/core/users/", username=idp.TEST_STUDENT) is not None
        assert _leftovers(values) == [idp.TEST_STUDENT]
    finally:
        authentik.delete(ak, f"/core/users/{made['pk']}/")
    assert _leftovers(values) == []


def test_a_leftover_of_a_killed_run_is_cleaned_by_the_next_run(values, capsys):
    """AC-11: marked items left behind are removed at the start of the next run."""
    ak = cli._authentik_from_env(values)
    authentik.create(ak, "/core/users/", idp.sample_user_body(idp.TEST_STRANGER))
    assert cli.idp_selftest(REPO) == 0
    assert f"cleaned leftover authentik user {idp.TEST_STRANGER}" in capsys.readouterr().out
    assert _leftovers(values) == []


def test_the_login_page_shows_the_button_without_a_password_form(values):
    """AC-5: what the selftest drives is the page a student sees."""
    page = httpx.get(f"https://{values['LMS_HOSTNAME']}/login", timeout=30).text
    assert idp.authorize_link(page, values["AUTHENTIK_HOSTNAME"]) is not None
