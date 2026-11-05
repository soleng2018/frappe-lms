"""`idp selftest`: sign throwaway users in through the real Authentik and LMS, then clean up."""

import secrets
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from nile_tools import authentik, config, idp, lms
from nile_tools.authentik import Authentik, AuthentikError
from nile_tools.lms import Lms, LmsError

__all__ = ["Login", "SelftestError", "drive_login", "selftest"]

Say = Callable[[str], None]
Browser = Callable[[], httpx.Client]
MAX_HOPS = 25
MAX_STAGES = 12
USER, COURSE, ENROLLMENT = "User", "LMS Course", "LMS Enrollment"
_REDIRECTS = (301, 302, 303, 307, 308)


class SelftestError(Exception):
    """The selftest could not run or finish a step; the message names the URL or item."""


@dataclass(frozen=True)
class Login:
    """The LMS answer to the callback, and the browser (with its cookies) that got it."""

    status: int
    location: str | None
    browser: httpx.Client


def _plain(url: object) -> str:
    """Return a URL without its query or fragment (they can carry a state or a code)."""
    parts = urlsplit(str(url))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _location(response: httpx.Response) -> str:
    """Return the redirect target of a response, or raise SelftestError naming the URL."""
    target = response.headers.get("location")
    if not target:
        raise SelftestError(f"{_plain(response.url)} answered a redirect with no location")
    return target


def _json(response: httpx.Response) -> dict[str, Any]:
    """Return a JSON object answer, or raise SelftestError naming the URL."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise SelftestError(f"{_plain(response.url)} did not answer a JSON object")
    return body


def _stage_body(component: str, username: str, password: str, url: str) -> dict[str, str]:
    """Answer one Authentik flow stage; only the identification and password stages are known."""
    if component == "ak-stage-identification":
        return {"component": component, "uid_field": username}
    if component == "ak-stage-password":
        return {"component": component, "password": password}
    raise SelftestError(
        f"Authentik flow at {url} asked for '{component}', which the selftest cannot answer "
        "(a flow with an MFA or captcha stage stops it)"
    )


def _run_flow(
    browser: httpx.Client, host: str, slug: str, query: str, username: str, password: str
) -> str:
    """Answer the stages of one Authentik flow; return where the flow sends the browser next."""
    url = f"https://{host}/api/v3/flows/executor/{slug}/"
    headers = {"Accept": "application/json"}
    challenge = browser.get(url, params={"query": query}, headers=headers)
    for _ in range(MAX_STAGES):
        if challenge.status_code in _REDIRECTS:  # Authentik sends a finished stage back to the get
            challenge = browser.get(urljoin(url, _location(challenge)), headers=headers)
            continue
        body = _json(challenge)
        component = str(body.get("component", ""))
        if component == "xak-flow-redirect":
            if not body.get("to"):
                raise SelftestError(f"Authentik flow at {url} sent a redirect with no target")
            return urljoin(url, str(body["to"]))
        if body.get("response_errors"):
            raise SelftestError(f"Authentik refused the selftest user at {url} ({component})")
        answer = _stage_body(component, username, password, url)
        posted = browser.post(url, params={"query": query}, json=answer, headers=headers)
        # Authentik answers a post with a redirect to a get
        if posted.status_code not in _REDIRECTS:
            raise SelftestError(f"POST {url} answered HTTP {posted.status_code}")
        challenge = browser.get(urljoin(url, _location(posted)), headers=headers)
    raise SelftestError(f"Authentik flow at {url} did not finish after {MAX_STAGES} stages")


def drive_login(
    browser: httpx.Client, lms_host: str, authentik_host: str, username: str, password: str
) -> Login:
    """Click the Authentik button on the LMS login page and sign in; stop at the LMS callback.

    Raises SelftestError when a request fails or Authentik asks for something unknown.
    """
    login_url = f"https://{lms_host}/login"
    try:
        link = idp.authorize_link(browser.get(login_url).text, authentik_host)
        if link is None:
            raise SelftestError(f"{login_url} shows no Authentik button; run `idp setup`")
        url = link
        for _ in range(MAX_HOPS):
            r = browser.get(url)
            if r.status_code not in _REDIRECTS:
                raise SelftestError(f"GET {url} answered HTTP {r.status_code}, not a redirect")
            target = urljoin(url, _location(r))
            if urlsplit(target).netloc == lms_host:
                final = browser.get(target)  # Frappe takes the code here, with the real backend
                return Login(final.status_code, final.headers.get("location"), browser)
            flow = idp.flow_target(target)
            url = _run_flow(browser, authentik_host, *flow, username, password) if flow else target
    except httpx.HTTPError as e:
        raise SelftestError(
            f"selftest sign in failed: {type(e).__name__} at {_plain(e.request.url)}"
        ) from None
    raise SelftestError(f"the sign in did not reach {lms_host} after {MAX_HOPS} redirects")


def _preflight(ak: Authentik, connection: Lms) -> None:
    """Refuse to start when an item with a test name exists and is not ours (AC-11)."""
    for username in (idp.TEST_STUDENT, idp.TEST_STRANGER):
        user = authentik.get_one(ak, "/core/users/", username=username)
        if user is not None and (user.get("attributes") or {}).get("managed_by") != idp.MARKER:
            raise idp.Refused(f"Authentik user '{username}' exists without the ownership marker")
    group = authentik.get_one(ak, "/core/groups/", name=idp.TEST_COURSE_TITLE)
    if group is not None and (group.get("attributes") or {}).get("managed_by") != idp.MARKER:
        raise idp.Refused(
            f"Authentik group '{idp.TEST_COURSE_TITLE}' exists without the ownership marker"
        )
    for course in lms.list_records(
        connection, COURSE, filters=[["title", "=", idp.TEST_COURSE_TITLE]]
    ):
        if course.get("nile_key") != idp.TEST_COURSE_KEY:
            raise idp.Refused(f"LMS course '{course['name']}' has the test title and is not ours")


def _remove_authentik(ak: Authentik) -> list[str]:
    removed = []
    for username in (idp.TEST_STUDENT, idp.TEST_STRANGER):
        user = authentik.get_one(ak, "/core/users/", username=username)
        if user is not None:
            authentik.delete(ak, f"/core/users/{user['pk']}/")
            removed.append(f"authentik user {username}")
    group = authentik.get_one(ak, "/core/groups/", name=idp.TEST_COURSE_TITLE)
    if group is not None:
        authentik.delete(ak, f"/core/groups/{group['pk']}/")
        removed.append(f"authentik group {idp.TEST_COURSE_TITLE}")
    return removed


def _remove_frappe(connection: Lms) -> list[str]:
    """Delete in the order the spec names: enrollments, the course, then the users."""
    removed = []
    emails = [idp.sample_email(u) for u in (idp.TEST_STUDENT, idp.TEST_STRANGER)]
    for email in emails:
        for row in lms.list_records(connection, ENROLLMENT, filters=[["member", "=", email]]):
            lms.delete_record(connection, ENROLLMENT, row["name"])
            removed.append(f"enrollment {row['name']}")
    for course in lms.list_records(
        connection, COURSE, filters=[["nile_key", "=", idp.TEST_COURSE_KEY]]
    ):
        lms.delete_record(connection, COURSE, course["name"])
        removed.append(f"course {course['name']}")
    for email in emails:
        if lms.list_records(connection, USER, filters=[["name", "=", email]]):
            lms.delete_record(connection, USER, email)
            removed.append(f"frappe user {email}")
    return removed


def _cleanup(ak: Authentik, connection: Lms, say: Say, label: str) -> bool:
    """Remove every selftest item; keep going after a failure. Return False if one failed."""
    ok = True
    for step in (lambda: _remove_frappe(connection), lambda: _remove_authentik(ak)):
        try:
            for item in step():
                say(f"{label} {item}")
        except (AuthentikError, LmsError) as e:
            say(f"FAIL cleanup: {e}")
            ok = False
    return ok


def _observe(
    connection: Lms, browser: httpx.Client, lms_host: str, email: str, login: Login
) -> idp.Observed:
    """Read what the LMS holds for the user after the login."""
    where = urljoin(f"https://{lms_host}/", login.location) if login.location else None
    if not lms.list_records(connection, USER, filters=[["name", "=", email]]):
        return idp.Observed(login.status, where, None, False)
    user = lms.get_record(connection, USER, email)
    enrolled = lms.list_records(connection, ENROLLMENT, filters=[["member", "=", email]])
    me_url = f"https://{lms_host}/api/method/frappe.auth.get_logged_user"
    try:
        me = browser.get(me_url)
    except httpx.HTTPError as e:
        raise SelftestError(f"selftest check failed: {type(e).__name__} at {me_url}") from None
    return idp.Observed(
        login.status,
        where,
        _json(me).get("message") if me.status_code == 200 else None,
        True,
        tuple(r["role"] for r in user.get("roles", [])),
        tuple(sorted(r["course"] for r in enrolled)),
        str(user.get("nile_groups") or ""),
    )


def _preconditions(connection: Lms, values: Mapping[str, str]) -> None:
    found = lms.list_records(
        connection, "Social Login Key", filters=[["name", "=", idp.FRAPPE_KEY_NAME]]
    )
    if not found or not idp.key_enabled(found[0]):
        raise idp.Refused(
            f"No enabled Social Login Key '{idp.FRAPPE_KEY_NAME}'; run `idp setup` first"
        )
    for key in ("AUTHENTIK_HOSTNAME", "LMS_HOSTNAME"):
        if not values.get(key):
            raise idp.ConfigProblem(f"Config key {key} is missing or blank in .env")


def selftest(
    ak: Authentik,
    connection: Lms,
    browser: Browser,
    values: Mapping[str, str],
    say: Say,
    *,
    password: str | None = None,
) -> int:
    """Sign a throwaway student and a stranger in for real, judge both, and always clean up."""
    _preconditions(connection, values)
    _preflight(ak, connection)
    ok = _cleanup(ak, connection, say, "cleaned leftover")
    secret = password or f"{secrets.token_urlsafe(20)}-Aa1!"
    env_secrets = [values[k.name] for k in config.KEYS if k.secret and values.get(k.name)]
    config.install_masking([secret, *env_secrets])
    lms_host, ak_host = values["LMS_HOSTNAME"], values["AUTHENTIK_HOSTNAME"]
    verdicts: list[idp.Verdict] = []
    stack = ExitStack()
    try:
        users = {}
        for username in (idp.TEST_STUDENT, idp.TEST_STRANGER):
            made = authentik.create(ak, "/core/users/", idp.sample_user_body(username))
            authentik.set_password(ak, made["pk"], secret)
            users[username] = made
        authentik.create(
            ak,
            "/core/groups/",
            {
                "name": idp.TEST_COURSE_TITLE,
                "users": [users[idp.TEST_STUDENT]["pk"]],
                "attributes": {"managed_by": idp.MARKER},
            },
        )
        course = lms.create_record(
            connection,
            COURSE,
            {
                "title": idp.TEST_COURSE_TITLE,
                "nile_key": idp.TEST_COURSE_KEY,
                "short_introduction": "Throwaway course made by idp selftest",
                "description": "Throwaway course made by idp selftest",
                "published": 0,
                "instructors": [{"instructor": lms.logged_user(connection)}],
            },
        )
        student_email = idp.sample_email(idp.TEST_STUDENT)
        student = stack.enter_context(browser())
        login = drive_login(student, lms_host, ak_host, idp.TEST_STUDENT, secret)
        seen = _observe(connection, student, lms_host, student_email, login)
        name = str(course["name"])
        verdicts += idp.judge_student(seen, student_email, name, idp.TEST_COURSE_TITLE, lms_host)
        stranger = stack.enter_context(browser())
        login = drive_login(stranger, lms_host, ak_host, idp.TEST_STRANGER, secret)
        stranger_email = idp.sample_email(idp.TEST_STRANGER)
        seen = _observe(connection, stranger, lms_host, stranger_email, login)
        verdicts += idp.judge_stranger(seen)
    finally:
        stack.close()
        ok = _cleanup(ak, connection, say, "removed") and ok
    for v in verdicts:
        say(f"{v.level} {v.message}")
    return 0 if ok and verdicts and all(v.level == idp.PASS for v in verdicts) else 1
