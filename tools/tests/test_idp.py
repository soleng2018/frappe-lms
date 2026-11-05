"""Unit tests for the Authentik sign in rules and the `idp setup` thin thread (no network)."""

import json
from typing import Any

import httpx
import pytest
from fake_lms import FakeLms

from nile_tools import authentik, idp, idp_run
from nile_tools.authentik import AuthentikError

VALUES = {
    "AUTHENTIK_HOSTNAME": "auth.example.com",
    "AUTHENTIK_APP_SLUG": "nile-lms",
    "LMS_HOSTNAME": "lms.example.com",
}
REFS = idp.Refs("flow-a", "flow-i", "key-1", ("m-open", "m-email", "m-profile", "m-groups"))


class FakeAuthentik:
    """Just enough of the Authentik API: lists ignore filters, like the real application list."""

    def __init__(self, *, groups_mapping: bool = True, marked: bool = True) -> None:
        self.apps: dict[str, dict[str, Any]] = {}
        self.providers: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.groups_mapping = groups_mapping
        self.marked = marked
        self.version = idp.TESTED_VERSION
        self.email_edit = False
        self.user_groups: list[str] = ["Some Course"]

    def client(self) -> authentik.Authentik:
        return authentik.connect("auth.test", "tok", transport=httpx.MockTransport(self.handle))

    def _maps(self) -> list[dict[str, Any]]:
        default = "authentik default OAuth Mapping: "
        maps = [{"pk": f"m-{s}", "name": default + s, "scope_name": s} for s in idp.SCOPE_NAMES]
        if self.groups_mapping:
            maps.append({"pk": "m-groups", "name": idp.GROUPS_MAPPING_NAME, "scope_name": "groups"})
        return maps

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v3/")
        self.calls.append((request.method, path))
        body = json.loads(request.content) if request.content else {}
        table: dict[str, Any] = {
            "propertymappings/provider/scope/": self._maps(),
            "flows/instances/": [
                {"pk": "flow-x", "slug": s}
                for s in (idp.IMPLICIT_CONSENT_SLUG, idp.INVALIDATION_SLUG)
            ],
            "crypto/certificatekeypairs/": [{"pk": "key-1", "name": idp.SIGNING_KEY_NAME}],
            "core/applications/": list(self.apps.values()),
            "providers/oauth2/": list(self.providers.values()),
            "core/users/": [{"pk": 7, "username": "real-user"}],
        }
        if path == "admin/version/":
            return httpx.Response(200, json={"version_current": self.version})
        if path == "admin/settings/":
            return httpx.Response(200, json={"default_user_change_email": self.email_edit})
        if path.endswith("/test/"):
            claims = {"groups": self.user_groups}
            return httpx.Response(200, json={"successful": True, "result": json.dumps(claims)})
        if request.method == "DELETE":
            key = path.split("/")[-2]
            if path.startswith("providers"):
                self.providers = {k: v for k, v in self.providers.items() if str(v["pk"]) != key}
                for a in self.apps.values():
                    a["provider"] = None if a["provider"] == int(key) else a["provider"]
            else:
                self.apps = {k: v for k, v in self.apps.items() if v["slug"] != key}
            return httpx.Response(204)
        if request.method == "GET":
            return httpx.Response(200, json={"results": table[path]})
        if request.method == "POST":
            store = self.apps if path.startswith("core") else self.providers
            item = {"pk": len(store) + 1, **body, "provider": None}
            if store is self.providers:
                item |= {"client_id": "cid", "client_secret": "s3cret-value"}
            store[body["name"]] = item
            return httpx.Response(201, json=item)
        key = path.split("/")[-2]
        if path.startswith("providers"):
            item = next(p for p in self.providers.values() if str(p["pk"]) == key)
        else:
            item = next(a for a in self.apps.values() if a["slug"] == key)
        item.update(body)
        return httpx.Response(200, json=item)


def test_wanted_state_builds_every_item_from_config():
    wanted = idp.wanted_state(VALUES, REFS)
    assert wanted.provider["redirect_uris"] == [
        {
            "matching_mode": "strict",
            "url": "https://lms.example.com/api/method/frappe.integrations.oauth2_logins.custom/authentik",
        }
    ]
    assert wanted.provider["client_type"] == "confidential"
    assert wanted.application["meta_description"] == idp.MARKER
    assert wanted.application["meta_launch_url"] == "https://lms.example.com/lms"
    key = wanted.frappe_key
    assert key["authorize_url"] == "https://auth.example.com/application/o/authorize/"
    assert "groups" in json.loads(key["auth_url_data"])["scope"]
    assert "client_secret" not in key and "client_id" not in key


def test_wanted_state_names_every_missing_key():
    with pytest.raises(idp.ConfigProblem, match="AUTHENTIK_HOSTNAME, LMS_HOSTNAME"):
        idp.wanted_state({"AUTHENTIK_APP_SLUG": "x"}, REFS)


def test_lookup_refs_reads_the_shared_items_by_name():
    refs = idp_run.lookup_refs(FakeAuthentik().client())
    assert refs.property_mappings == ("m-openid", "m-email", "m-profile", "m-groups")
    assert refs.signing_key == "key-1"


def test_lookup_refs_stops_when_the_groups_mapping_is_missing():
    fake = FakeAuthentik(groups_mapping=False)
    with pytest.raises(AuthentikError, match="HOL: OpenID groups scope"):
        idp_run.lookup_refs(fake.client())
    assert all(method == "GET" for method, _ in fake.calls)


def test_setup_creates_application_provider_and_frappe_key(capsys):
    fake, lms = FakeAuthentik(), FakeLms()
    said: list[str] = []
    assert idp_run.setup(fake.client(), lms.client(), VALUES, said.append) == 0
    app = fake.apps["Nile Workshop LMS"]
    assert app["meta_description"] == idp.MARKER
    assert app["provider"] == fake.providers["nile-lms provider"]["pk"]
    key = next(iter(lms.of("Social Login Key").values()))
    assert key["client_id"] == "cid" and key["client_secret"] == "s3cret-value"
    assert said[:3] == ["created application", "created provider", "created frappe-key"]
    assert said[3:5] == [
        "fixed system-settings: disable_user_pass_login",
        "fixed system-settings: login_with_email_link",
    ]
    assert all("s3cret-value" not in line for line in said)
    assert said[-1] == "Sign in at https://lms.example.com/login"


def test_setup_refuses_an_application_without_the_marker():
    fake = FakeAuthentik()
    fake.apps["x"] = {"pk": 9, "slug": "nile-lms", "meta_description": "", "provider": None}
    with pytest.raises(AuthentikError, match="without the ownership marker"):
        idp_run.setup(fake.client(), FakeLms().client(), VALUES, lambda _: None)
    assert not [c for c in fake.calls if c[0] != "GET"]


def test_setup_refuses_a_provider_whose_application_is_missing():
    fake = FakeAuthentik()
    fake.providers["nile-lms provider"] = {"pk": 5, "name": "nile-lms provider"}
    with pytest.raises(AuthentikError, match="provider is not ours"):
        idp_run.setup(fake.client(), FakeLms().client(), VALUES, lambda _: None)
    assert not [c for c in fake.calls if c[0] != "GET"]


def run_setup(fake: FakeAuthentik, lms: FakeLms, **kwargs: Any) -> list[str]:
    said: list[str] = []
    assert idp_run.setup(fake.client(), lms.client(), VALUES, said.append, **kwargs) == 0
    return said[:-1]  # drop the sign in line


def test_a_second_run_changes_nothing_and_keeps_the_secret():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    writes = len(fake.calls), len(lms.writes)
    secret = lms.of("Social Login Key")["authentik"]["client_secret"]
    fake.calls.clear()
    assert run_setup(fake, lms) == [
        "unchanged application",
        "unchanged provider",
        "unchanged frappe-key",
        "unchanged system-settings",
    ]
    assert not [c for c in fake.calls if c[0] != "GET"]
    assert len(lms.writes) == writes[1]
    assert lms.of("Social Login Key")["authentik"]["client_secret"] == secret


def test_an_edited_provider_is_put_back_and_extras_are_removed():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    provider = fake.providers["nile-lms provider"]
    provider["redirect_uris"] = [
        *provider["redirect_uris"],
        {"matching_mode": "regex", "url": ".*", "redirect_uri_type": "authorization"},
    ]
    provider["property_mappings"] = ["m-open"]
    said = run_setup(fake, lms)
    assert "fixed provider: redirect_uris" in said and "fixed provider: property_mappings" in said
    assert provider["redirect_uris"] == idp.wanted_state(VALUES, REFS).provider["redirect_uris"]
    assert run_setup(fake, lms)[1] == "unchanged provider"


def test_an_edited_application_and_a_detached_provider_are_fixed():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    app = fake.apps["Nile Workshop LMS"]
    app.update({"meta_launch_url": "https://evil.example/", "provider": None})
    said = run_setup(fake, lms)
    assert said[:2] == ["fixed application: meta_launch_url", "fixed application: provider"]
    assert app["meta_launch_url"] == "https://lms.example.com/lms"
    assert app["provider"] == fake.providers["nile-lms provider"]["pk"]


def test_an_edited_frappe_key_is_fixed_without_touching_the_secret():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    key = lms.of("Social Login Key")["authentik"]
    key.update({"enable_social_login": 0, "auth_url_data": "{}"})
    said = run_setup(fake, lms)
    assert "fixed frappe-key: enable_social_login" in said
    assert "fixed frappe-key: auth_url_data" in said
    assert key["enable_social_login"] == 1
    assert key["client_secret"] == "s3cret-value"
    assert not any("client_secret" in line for line in said)


def test_a_changed_client_id_rewrites_the_secret_too():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    lms.of("Social Login Key")["authentik"].update({"client_id": "old", "client_secret": "old"})
    said = run_setup(fake, lms)
    assert "fixed frappe-key: client_id" in said and "fixed frappe-key: client_secret" in said
    assert lms.of("Social Login Key")["authentik"]["client_secret"] == "s3cret-value"


def test_resync_secret_rewrites_only_the_secret():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    lms.of("Social Login Key")["authentik"]["client_secret"] = "stale"
    said = run_setup(fake, lms, resync_secret=True)
    assert said[2:3] == ["fixed frappe-key: client_secret"]
    assert lms.of("Social Login Key")["authentik"]["client_secret"] == "s3cret-value"


def test_a_half_done_setup_is_finished_by_running_it_again():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    # The run stopped after creating the application: no provider, no key, nothing attached.
    fake.providers.clear()
    lms.docs.pop("Social Login Key")
    fake.apps["Nile Workshop LMS"]["provider"] = None
    said = run_setup(fake, lms)
    assert said[1:3] == ["created provider", "created frappe-key"]
    assert fake.apps["Nile Workshop LMS"]["provider"] == fake.providers["nile-lms provider"]["pk"]


def test_diff_is_empty_when_equal_and_names_each_edited_field():
    wanted = idp.wanted_state(VALUES, REFS).provider
    live = {**wanted, "redirect_uris": [{**wanted["redirect_uris"][0], "redirect_uri_type": "x"}]}
    assert idp.diff("provider", wanted, live) == []
    live = {**live, "client_type": "public", "sub_mode": "user_id"}
    assert [c.field for c in idp.diff("provider", wanted, live)] == ["client_type", "sub_mode"]
    assert [c.field for c in idp.diff("provider", wanted, {})] == list(wanted)


def test_reads_are_retried_on_5xx_but_a_create_is_not():
    answers = iter([503, 503, 200])

    def flaky(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(answers), json={"results": []})

    ak = authentik.connect(
        "auth.test", "tok", transport=httpx.MockTransport(flaky), tries=5, retry_wait=0
    )
    assert authentik.find(ak, "/core/applications/") == []
    seen: list[str] = []

    def down(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(502, json={})

    ak = authentik.connect(
        "auth.test", "tok", transport=httpx.MockTransport(down), tries=3, retry_wait=0
    )
    with pytest.raises(AuthentikError, match="HTTP 502"):
        authentik.create(ak, "/core/applications/", {})
    assert seen == ["POST"]


def test_an_unreachable_authentik_gives_one_error_naming_the_url():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    ak = authentik.connect(
        "auth.test", "tok", transport=httpx.MockTransport(refuse), tries=3, retry_wait=0
    )
    with pytest.raises(AuthentikError, match=r"GET https://auth.test/api/v3/core/applications/"):
        authentik.find(ak, "/core/applications/")


def test_a_client_error_is_not_retried():
    seen: list[int] = []

    def deny(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(403, json={})

    ak = authentik.connect(
        "auth.test", "tok", transport=httpx.MockTransport(deny), tries=5, retry_wait=0
    )
    with pytest.raises(AuthentikError):
        authentik.find(ak, "/core/applications/")
    assert len(seen) == 1


def test_a_failed_request_names_the_url_and_not_the_token():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "no"})

    ak = authentik.connect("auth.test", "tok-123", transport=httpx.MockTransport(refuse))
    with pytest.raises(AuthentikError) as e:
        authentik.find(ak, "/core/applications/")
    assert "https://auth.test/api/v3/core/applications/" in str(e.value)
    assert "tok-123" not in str(e.value)


def settings(lms: FakeLms) -> tuple[int, int]:
    doc = lms.of("System Settings")["System Settings"]
    return doc["disable_user_pass_login"], doc["login_with_email_link"]


def test_setup_closes_the_password_form_and_the_email_link():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    assert settings(lms) == (1, 0)


def test_password_login_on_opens_only_the_form_and_off_closes_it_again():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    said: list[str] = []
    assert idp_run.password_login(lms.client(), "on", said.append) == 0
    assert settings(lms) == (0, 0)  # the email link stays off
    assert said == ["fixed system-settings: disable_user_pass_login", "password login is on"]
    said.clear()
    assert idp_run.password_login(lms.client(), "off", said.append) == 0
    assert settings(lms) == (1, 0)
    assert said[-1] == "password login is off"


def test_password_login_is_idempotent():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    writes = len(lms.writes)
    said: list[str] = []
    idp_run.password_login(lms.client(), "off", said.append)
    assert said == ["unchanged system-settings", "password login is off"]
    assert len(lms.writes) == writes


def test_a_rerun_closes_a_break_glass_left_open():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    idp_run.password_login(lms.client(), "on", lambda _: None)
    assert run_setup(fake, lms)[-1] == "fixed system-settings: disable_user_pass_login"
    assert settings(lms) == (1, 0)


@pytest.mark.parametrize("enabled", [None, 0])
def test_off_refuses_without_an_enabled_authentik_key(enabled):
    lms = FakeLms()
    if enabled is not None:
        lms.seed("Social Login Key", "authentik", enable_social_login=enabled)
    with pytest.raises(idp.Refused, match="stays as it is"):
        idp_run.password_login(lms.client(), "off", lambda _: None)
    assert settings(lms) == (0, 1)
    assert not lms.writes


def test_on_needs_no_key():
    lms = FakeLms()
    assert idp_run.password_login(lms.client(), "on", lambda _: None) == 0
    assert settings(lms) == (0, 0)


def test_login_form_state_never_turns_the_email_link_on():
    live = {"language": "en"}
    assert idp.login_form_state(True, live)["login_with_email_link"] == 0
    assert idp.login_form_state(False, live) == {
        "disable_user_pass_login": 1,
        "login_with_email_link": 0,
    }
    assert not idp.key_enabled(None) and idp.key_enabled({"enable_social_login": 1})


def test_a_blank_language_is_filled_because_frappe_will_not_save_without_it():
    fake, lms = FakeAuthentik(), FakeLms()
    lms.of("System Settings")["System Settings"]["language"] = None
    assert "fixed system-settings: language" in run_setup(fake, lms)
    assert lms.of("System Settings")["System Settings"]["language"] == "en"
    assert settings(lms) == (1, 0)


# --- idp check and idp remove (AC-7, AC-8) ---

REDIRECT = idp.redirect_uri(VALUES["LMS_HOSTNAME"])


def public_client(
    *,
    oauth_error: str = "invalid_grant",
    login: str = "Login with Authentik",
    callback: int = 417,
    discovery: int = 200,
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/application/o/token/":
            return httpx.Response(
                400 if oauth_error == "invalid_grant" else 401, json={"error": oauth_error}
            )
        if path.endswith("openid-configuration"):
            return httpx.Response(discovery, json={})
        if path == "/login":
            return httpx.Response(200, text=login)
        return httpx.Response(callback)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def run_check(fake: FakeAuthentik, lms: FakeLms, public: httpx.Client, **kwargs: Any):
    said: list[str] = []
    code = idp_run.check(fake.client(), lms.client(), public, VALUES, said.append, **kwargs)
    return code, said


def good_setup() -> tuple[FakeAuthentik, FakeLms]:
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    return fake, lms


def test_check_on_a_good_setup_is_all_pass_and_writes_nothing():
    fake, lms = good_setup()
    fake.calls.clear()
    writes = len(lms.writes)
    public, seen = public_client()
    code, said = run_check(fake, lms, public, user="real-user")
    assert code == 0
    assert all(line.startswith("PASS") for line in said), said
    assert len(said) == 11
    posts = [path for method, path in fake.calls if method != "GET"]
    assert len(posts) == 1 and posts[0].endswith("/test/")  # the mapping test stores nothing
    assert len(lms.writes) == writes
    assert [r.method for r in seen].count("POST") == 1  # only the dummy token call


def test_check_warns_for_each_known_case_and_still_exits_0():
    fake, lms = good_setup()
    fake.version, fake.email_edit = "2026.9.0", True
    lms.of("System Settings")["System Settings"]["disable_user_pass_login"] = 0
    lms.password_denied = True
    code, said = run_check(fake, lms, public_client()[0])
    assert code == 0
    warns = [line for line in said if line.startswith("WARN")]
    assert len(warns) == 5  # version, groups untested, email edit, secret unread, form on
    assert any("secret not verified, run selftest" in line for line in warns)


def test_check_fails_and_exits_1_when_the_secret_is_rejected():
    fake, lms = good_setup()
    code, said = run_check(fake, lms, public_client(oauth_error="invalid_client")[0])
    assert code == 1
    assert any(line.startswith("FAIL") and "idp setup --resync-secret" in line for line in said)
    assert all("s3cret-value" not in line for line in said)


def test_check_fails_on_an_edited_provider_and_a_disabled_key_and_a_missing_groups_claim():
    fake, lms = good_setup()
    fake.providers["nile-lms provider"]["redirect_uris"] = []
    lms.of("Social Login Key")["authentik"]["enable_social_login"] = 0
    fake.user_groups = []
    code, said = run_check(fake, lms, public_client()[0], user="real-user")
    fails = [line for line in said if line.startswith("FAIL")]
    assert code == 1 and len(fails) == 3
    assert any("redirect_uris" in line for line in fails)


def test_check_fails_on_the_public_checks():
    fake, lms = good_setup()
    public, _ = public_client(login="<form>", callback=200, discovery=404)
    code, said = run_check(fake, lms, public)
    assert code == 1
    assert sum(line.startswith("FAIL") for line in said) == 3


def test_check_fails_on_a_missing_application_and_marker():
    fake, lms = FakeAuthentik(), FakeLms()
    code, said = run_check(fake, lms, public_client()[0])
    assert code == 1 and any("application 'nile-lms' is missing" in line for line in said)
    fake.apps["x"] = {"pk": 9, "slug": "nile-lms", "meta_description": "", "provider": None}
    assert idp.judge_application(fake.apps["x"], "nile-lms").level == idp.FAIL


def test_check_names_the_url_when_authentik_is_unreachable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    ak = authentik.connect("auth.test", "tok", transport=httpx.MockTransport(down), tries=1)
    with pytest.raises(AuthentikError, match=r"auth.test/api/v3/admin/version/"):
        idp_run.check(ak, FakeLms().client(), public_client()[0], VALUES, lambda _: None)


def run_remove(fake: FakeAuthentik, lms: FakeLms) -> list[str]:
    said: list[str] = []
    assert idp_run.remove(fake.client(), lms.client(), VALUES, said.append) == 0
    return said


def test_remove_deletes_the_key_then_the_provider_then_the_application():
    fake, lms = good_setup()
    fake.calls.clear()
    said = run_remove(fake, lms)
    assert said[:3] == ["removed frappe-key", "removed provider", "removed application"]
    assert "idp password-login on" in said[3]
    assert [c[0] for c in fake.calls if c[0] == "DELETE"] == ["DELETE", "DELETE"]
    assert [c[1].split("/")[0] for c in fake.calls if c[0] == "DELETE"] == ["providers", "core"]
    assert not lms.of("Social Login Key") and not fake.apps and not fake.providers
    assert lms.writes[-1] == ("DELETE", "Social Login Key", "authentik")


def test_a_second_remove_changes_nothing():
    fake, lms = good_setup()
    run_remove(fake, lms)
    fake.calls.clear()
    writes = len(lms.writes)
    assert run_remove(fake, lms)[:3] == [
        "absent frappe-key",
        "absent provider",
        "absent application",
    ]
    assert {m for m, _ in fake.calls} == {"GET"} and len(lms.writes) == writes


def test_remove_refuses_an_unmarked_application_and_changes_nothing():
    fake, lms = good_setup()
    fake.apps["Nile Workshop LMS"]["meta_description"] = ""
    fake.calls.clear()
    with pytest.raises(AuthentikError, match="without the ownership marker"):
        idp_run.remove(fake.client(), lms.client(), VALUES, lambda _: None)
    assert {m for m, _ in fake.calls} == {"GET"}
    assert lms.of("Social Login Key")


def test_remove_keeps_frappe_users_and_the_password_form_as_it_is():
    fake, lms = good_setup()
    lms.seed("User", "student@example.com")
    before = dict(lms.of("System Settings")["System Settings"])
    run_remove(fake, lms)
    assert "student@example.com" in lms.of("User")
    assert lms.of("System Settings")["System Settings"] == before


def test_a_remove_stopped_after_the_key_delete_is_finished_by_a_second_run():
    fake, lms = good_setup()
    lms.docs["Social Login Key"].clear()  # the first run died right after this delete
    said = run_remove(fake, lms)
    assert said[:3] == ["absent frappe-key", "removed provider", "removed application"]
    assert not fake.providers and not fake.apps


def test_a_remove_stopped_after_the_provider_delete_leaves_no_orphan():
    fake, lms = good_setup()
    lms.docs["Social Login Key"].clear()
    fake.providers.clear()
    fake.apps["Nile Workshop LMS"]["provider"] = None
    assert run_remove(fake, lms)[:3] == [
        "absent frappe-key",
        "absent provider",
        "removed application",
    ]
    assert not fake.apps


def test_the_check_judges_are_pure_and_total():
    assert idp.judge_version(idp.TESTED_VERSION).level == idp.PASS
    assert idp.judge_version("1").level == idp.WARN
    assert idp.judge_secret("invalid_grant").level == idp.PASS
    assert idp.judge_secret("invalid_client").level == idp.FAIL
    assert idp.judge_secret(None).level == idp.WARN
    assert idp.judge_secret("HTTP 500").level == idp.WARN
    assert idp.judge_groups(None, None).level == idp.WARN
    assert idp.judge_groups("u", {"groups": ["a"]}).level == idp.PASS
    assert idp.judge_groups("u", {"groups": []}).level == idp.FAIL
    assert (
        idp.judge_form({"disable_user_pass_login": 1, "login_with_email_link": 0}).level == idp.PASS
    )
    assert (
        idp.judge_form({"disable_user_pass_login": 1, "login_with_email_link": 1}).level == idp.WARN
    )
    assert idp.judge_bad_state(None).level == idp.FAIL
    assert idp.judge_frappe_key(None, {}, None).level == idp.FAIL


def test_the_provider_grants_the_authorization_code_or_authentik_refuses_every_login():
    wanted = idp.wanted_state(VALUES, REFS)
    assert wanted.provider["grant_types"] == ["authorization_code"]
    live = {**wanted.provider, "grant_types": []}  # what Authentik 2026.8 gives when none is sent
    assert [c.field for c in idp.diff("provider", wanted.provider, live)] == ["grant_types"]
