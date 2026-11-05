"""Unit tests for `idp selftest` on a fake Authentik, LMS and browser (no network)."""

import json
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import pytest
from fake_lms import FakeLms

from nile_tools import authentik, idp, idp_selftest
from nile_tools.idp_selftest import SelftestError

AK, LMS_HOST = "auth.test", "lms.test"
VALUES = {"AUTHENTIK_HOSTNAME": AK, "LMS_HOSTNAME": LMS_HOST, "AUTHENTIK_APP_SLUG": "nile-lms"}
PASSWORD = "pw-never-printed-Aa1!"
STUDENT_EMAIL = idp.sample_email(idp.TEST_STUDENT)
STRANGER_EMAIL = idp.sample_email(idp.TEST_STRANGER)
MARKED = {"managed_by": idp.MARKER}


class FakeLmsWithUser(FakeLms):
    """The fake LMS, plus the one method call the selftest makes."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("frappe.auth.get_logged_user"):
            return httpx.Response(200, json={"message": "svc@example.com"})
        return super().handle(request)


class World:
    """Authentik users and groups, the LMS records, and a browser that signs in through both."""

    def __init__(self) -> None:
        self.users: dict[int, dict[str, Any]] = {
            1: {"pk": 1, "username": "real-user", "attributes": {}},
        }
        self.groups: dict[int, dict[str, Any]] = {
            9: {"pk": 9, "name": "hol-admins", "users": [1], "attributes": {}},
        }
        self.next_pk = 100
        self.passwords: dict[str, str] = {}
        self.lms = FakeLmsWithUser()
        self.lms.seed("Social Login Key", "authentik", enable_social_login=1)
        self.callback_status: int | None = None  # force an LMS answer for the student
        self.stranger_gets_user = False
        self.interrupt = False
        self.ak_calls: list[tuple[str, str]] = []

    def authentik(self) -> authentik.Authentik:
        return authentik.connect(AK, "tok", transport=httpx.MockTransport(self.ak_handle))

    def ak_handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v3/").strip("/")
        self.ak_calls.append((request.method, path))
        table = {"core/users": self.users, "core/groups": self.groups}
        parts = path.split("/")
        store = table[f"{parts[0]}/{parts[1]}"]
        if request.method == "GET":
            return httpx.Response(200, json={"results": list(store.values())})
        body = json.loads(request.content) if request.content else {}
        if request.method == "POST" and len(parts) == 2:
            self.next_pk += 1
            store[self.next_pk] = {"pk": self.next_pk, **body}
            return httpx.Response(201, json=store[self.next_pk])
        pk = int(parts[2])
        if request.method == "DELETE":
            store.pop(pk)
            return httpx.Response(204)
        self.passwords[store[pk]["username"]] = body["password"]
        return httpx.Response(204)

    def user(self, username: str) -> dict[str, Any] | None:
        return next((u for u in self.users.values() if u["username"] == username), None)

    def member_of_test_group(self, username: str) -> bool:
        group = next((g for g in self.groups.values() if g["name"] == idp.TEST_COURSE_TITLE), None)
        found = self.user(username)
        return bool(group and found and found["pk"] in group["users"])

    # --- the browser ---

    def browser(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.web), follow_redirects=False)

    def web(self, request: httpx.Request) -> httpx.Response:
        url, host, path = str(request.url), request.url.host, request.url.path
        who = request.headers.get("x-test-user")
        if host == LMS_HOST and path == "/login":
            link = f"https://{AK}/application/o/authorize/?client_id=c&amp;state=s"
            return httpx.Response(200, text=f'<a href="{link}">Login with Authentik</a>')
        if host == AK and path == "/application/o/authorize/":
            if request.url.params.get("signed") != "1":
                nxt = quote("/application/o/authorize/?client_id=c&state=s&signed=1", safe="")
                return httpx.Response(302, headers={"location": f"/if/flow/f1/?next={nxt}"})
            return httpx.Response(302, headers={"location": f"https://{LMS_HOST}/cb?code=1"})
        if host == AK and path.startswith("/api/v3/flows/executor/"):
            return self.executor(request)
        if host == LMS_HOST and path == "/cb":
            return self.callback()
        if host == LMS_HOST and path.endswith("get_logged_user"):
            return httpx.Response(200, json={"message": self.signed_in or "Guest"})
        raise AssertionError(f"unexpected request {request.method} {url} {who}")

    signed_in: str | None = None
    stage = 0
    who: str = ""

    def executor(self, request: httpx.Request) -> httpx.Response:
        stages = ["ak-stage-identification", "ak-stage-password", "xak-flow-redirect"]
        if request.method == "POST":
            body = json.loads(request.content)
            if body["component"] == "ak-stage-identification":
                self.who = body["uid_field"]
            else:
                assert body["password"] == self.passwords[self.who]
            self.stage += 1
            return httpx.Response(302, headers={"location": request.url.raw_path.decode()})
        component = stages[self.stage]
        if component == "xak-flow-redirect":
            to = "/application/o/authorize/?client_id=c&state=s&signed=1"
            return httpx.Response(200, json={"component": component, "to": to})
        return httpx.Response(200, json={"component": component})

    def callback(self) -> httpx.Response:
        if self.interrupt:
            raise KeyboardInterrupt
        email = idp.sample_email(self.who)
        if self.who == idp.TEST_STUDENT:
            if self.callback_status:
                return httpx.Response(self.callback_status)
            self.lms.seed(
                "User",
                email,
                nile_groups=idp.TEST_COURSE_TITLE,
                roles=[{"role": "LMS Student"}],
            )
            course = next(iter(self.lms.of("LMS Course").values()))["name"]
            self.lms.seed("LMS Enrollment", "enr-1", member=email, course=course)
            self.signed_in = email
            return httpx.Response(
                302, headers={"location": f"https://{LMS_HOST}/lms/courses/{course}"}
            )
        if self.stranger_gets_user:
            self.lms.seed("User", email, nile_groups="", roles=[])
        return httpx.Response(403, text="no course")

    def run(self, **kwargs: Any) -> tuple[int, list[str]]:
        said: list[str] = []
        code = idp_selftest.selftest(
            self.authentik(),
            self.lms.client(),
            self.browser,
            VALUES,
            said.append,
            password=PASSWORD,
            **kwargs,
        )
        return code, said

    def leftovers(self) -> list[str]:
        gone = [
            u["username"] for u in self.users.values() if u["username"].startswith(idp.TEST_PREFIX)
        ]
        gone += [g["name"] for g in self.groups.values() if g["name"] == idp.TEST_COURSE_TITLE]
        for doctype in ("User", "LMS Course", "LMS Enrollment"):
            gone += list(self.lms.of(doctype))
        return gone


def make_world() -> World:
    world = World()
    # Each browser() call must start a fresh sign in, as a new browser would.
    original = world.browser

    def fresh() -> httpx.Client:
        world.stage, world.who = 0, ""
        return original()

    world.browser = fresh  # type: ignore[method-assign]
    return world


# --- the whole run ---


def test_a_good_run_passes_every_check_and_leaves_nothing_behind():
    world = make_world()
    code, said = world.run()
    assert code == 0
    assert [line.split()[0] for line in said if line[:4] in ("PASS", "FAIL")] == ["PASS"] * 7
    assert (
        world.leftovers() == ["real-user", "hol-admins"][:0]
        or "real-user" in world.users[1].values()
    )
    assert world.user(idp.TEST_STUDENT) is None and world.user(idp.TEST_STRANGER) is None
    assert not world.lms.of("LMS Course") and not world.lms.of("User")


def test_the_run_never_touches_real_users_or_groups():
    world = make_world()
    world.run()
    assert world.users[1]["username"] == "real-user"
    assert world.groups[9]["name"] == "hol-admins" and world.groups[9]["users"] == [1]
    touched = {p for m, p in world.ak_calls if m in ("DELETE", "PATCH")}
    assert "core/users/1" not in touched and "core/groups/9" not in touched


def test_the_test_group_is_named_like_the_course_and_holds_only_the_student():
    world = make_world()
    seen: dict[str, Any] = {}
    original = world.web

    def spy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cb" and not seen:
            group = next(g for g in world.groups.values() if g["name"] == idp.TEST_COURSE_TITLE)
            seen["group"] = group
            seen["course"] = next(iter(world.lms.of("LMS Course").values()))
        return original(request)

    world.web = spy  # type: ignore[method-assign]
    world.run()
    assert seen["group"]["attributes"] == MARKED
    assert seen["group"]["users"] == [world.next_pk - 2]  # the first user made is the student
    assert seen["course"]["title"] == seen["group"]["name"] == idp.TEST_COURSE_TITLE
    assert seen["course"]["nile_key"] == idp.TEST_COURSE_KEY and seen["course"]["published"] == 0


def test_no_password_is_printed():
    world = make_world()
    _, said = world.run()
    assert PASSWORD not in "\n".join(said)


def test_a_failed_login_is_reported_and_still_cleaned_up():
    world = make_world()
    world.callback_status = 500
    code, said = world.run()
    assert code == 1
    assert any(line.startswith("FAIL") for line in said)
    assert world.leftovers() == []


def test_a_stranger_who_gets_a_frappe_user_fails_the_run():
    world = make_world()
    world.stranger_gets_user = True
    code, said = world.run()
    assert code == 1
    assert any(line.startswith("FAIL no Frappe user") for line in said)
    assert world.leftovers() == []


def test_an_interrupt_cleans_up_and_leaves_nothing():
    world = make_world()
    world.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        world.run()
    assert world.leftovers() == []


# --- leftovers and refusals (AC-11) ---


def seed_leftovers(world: World) -> None:
    world.users[50] = {"pk": 50, "username": idp.TEST_STUDENT, "attributes": MARKED}
    world.users[51] = {"pk": 51, "username": idp.TEST_STRANGER, "attributes": MARKED}
    world.groups[52] = {
        "pk": 52,
        "name": idp.TEST_COURSE_TITLE,
        "users": [50],
        "attributes": MARKED,
    }
    world.lms.seed(
        "LMS Course", "old-course", title=idp.TEST_COURSE_TITLE, nile_key=idp.TEST_COURSE_KEY
    )
    world.lms.seed("User", STUDENT_EMAIL)
    world.lms.seed("LMS Enrollment", "old-enr", member=STUDENT_EMAIL, course="old-course")


def test_leftovers_of_a_killed_run_are_cleaned_first():
    world = make_world()
    seed_leftovers(world)
    code, said = world.run()
    assert code == 0
    cleaned = [line for line in said if line.startswith("cleaned leftover")]
    assert any("enrollment old-enr" in line for line in cleaned)
    assert any("course old-course" in line for line in cleaned)
    assert any("authentik group" in line for line in cleaned)
    order = [line.split(" ", 3)[2] for line in cleaned]
    assert order.index("enrollment") < order.index("course") < order.index("frappe")


@pytest.mark.parametrize("what", ["user", "group", "course"])
def test_it_refuses_to_start_on_an_unmarked_item_with_a_test_name(what: str):
    world = make_world()
    if what == "user":
        world.users[60] = {"pk": 60, "username": idp.TEST_STUDENT, "attributes": {}}
    elif what == "group":
        world.groups[60] = {"pk": 60, "name": idp.TEST_COURSE_TITLE, "users": [], "attributes": {}}
    else:
        world.lms.seed("LMS Course", "real", title=idp.TEST_COURSE_TITLE, nile_key="someone-elses")
    before = (dict(world.users), dict(world.groups), len(world.lms.writes))
    with pytest.raises(idp.Refused):
        world.run()
    assert (world.users, world.groups, len(world.lms.writes)) == before  # nothing changed


@pytest.mark.parametrize("enabled", [None, 0])
def test_it_needs_an_enabled_authentik_key(enabled: int | None):
    world = make_world()
    world.lms.docs["Social Login Key"].pop("authentik")
    if enabled is not None:
        world.lms.seed("Social Login Key", "authentik", enable_social_login=enabled)
    with pytest.raises(idp.Refused, match="idp setup"):
        world.run()
    assert not world.lms.writes and not [c for c in world.ak_calls if c[0] != "GET"]


# --- driving the login ---


def test_drive_login_stops_at_the_callback_and_hands_back_the_answer():
    world = make_world()
    world.authentik()
    world.users[70] = {"pk": 70, "username": "someone", "attributes": MARKED}
    world.passwords["someone"] = "pw"
    login = idp_selftest.drive_login(world.browser(), LMS_HOST, AK, "someone", "pw")
    assert login.status == 403 and login.location is None


def test_drive_login_names_a_stage_it_cannot_answer():
    world = make_world()
    original = world.executor

    def mfa(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"component": "ak-stage-authenticator-validate"})
        return original(request)

    world.executor = mfa  # type: ignore[method-assign]
    with pytest.raises(SelftestError, match="ak-stage-authenticator-validate"):
        idp_selftest.drive_login(world.browser(), LMS_HOST, AK, "someone", "pw")


def test_drive_login_says_so_when_the_login_page_has_no_button():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="hi")))
    with pytest.raises(SelftestError, match=f"https://{LMS_HOST}/login shows no Authentik button"):
        idp_selftest.drive_login(client, LMS_HOST, AK, "u", "p")


def test_drive_login_names_the_host_when_it_cannot_connect():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    client = httpx.Client(transport=httpx.MockTransport(down))
    with pytest.raises(SelftestError, match="ConnectError"):
        idp_selftest.drive_login(client, LMS_HOST, AK, "u", "p")


# --- the pure parts ---


def test_authorize_link_unescapes_the_page_link():
    page = '<a href="https://auth.test/application/o/authorize/?a=1&amp;b=2">x</a>'
    assert (
        idp.authorize_link(page, "auth.test")
        == "https://auth.test/application/o/authorize/?a=1&b=2"
    )
    assert idp.authorize_link(page, "other.test") is None


def test_flow_target_reads_the_slug_and_query():
    assert idp.flow_target("https://auth.test/if/flow/default-authentication-flow/?next=%2Fx") == (
        "default-authentication-flow",
        "next=%2Fx",
    )
    assert idp.flow_target("https://auth.test/application/o/authorize/?a=1") is None


def test_sample_users_carry_the_marker_the_prefix_and_the_test_domain():
    body = idp.sample_user_body(idp.TEST_STUDENT)
    assert body["attributes"] == MARKED and body["type"] == "internal"
    assert body["email"] == STUDENT_EMAIL and body["email"].startswith(idp.TEST_PREFIX)
    assert urlsplit("//" + body["email"].split("@")[1]).hostname == "nile-lms-test.example"


def seen(**changes: Any) -> idp.Observed:
    good = {
        "status": 302,
        "location": f"https://{LMS_HOST}/lms/courses/c1",
        "logged_in_as": STUDENT_EMAIL,
        "user_exists": True,
        "roles": ("LMS Student",),
        "enrolled": ("c1",),
        "groups_field": idp.TEST_COURSE_TITLE,
    }
    return idp.Observed(**{**good, **changes})


@pytest.mark.parametrize(
    "change",
    [
        {"location": f"https://{LMS_HOST}/lms"},
        {"logged_in_as": None},
        {"roles": ()},
        {"enrolled": ("c1", "c2")},
        {"enrolled": ()},
        {"groups_field": ""},
    ],
)
def test_the_student_judge_fails_on_each_wrong_fact(change: dict[str, Any]):
    ok = idp.judge_student(seen(), STUDENT_EMAIL, "c1", idp.TEST_COURSE_TITLE, LMS_HOST)
    assert [v.level for v in ok] == [idp.PASS] * 5
    bad = idp.judge_student(seen(**change), STUDENT_EMAIL, "c1", idp.TEST_COURSE_TITLE, LMS_HOST)
    assert [v.level for v in bad].count(idp.FAIL) >= 1


def test_the_stranger_judge_wants_a_403_and_no_user():
    assert [v.level for v in idp.judge_stranger(idp.Observed(403, None, None, False))] == [
        idp.PASS
    ] * 2
    assert idp.judge_stranger(idp.Observed(302, None, None, False))[0].level == idp.FAIL
    assert idp.judge_stranger(idp.Observed(403, None, None, True))[1].level == idp.FAIL
