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
        }
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
    assert said[2:] == ["fixed frappe-key: client_secret"]
    assert lms.of("Social Login Key")["authentik"]["client_secret"] == "s3cret-value"


def test_a_half_done_setup_is_finished_by_running_it_again():
    fake, lms = FakeAuthentik(), FakeLms()
    run_setup(fake, lms)
    # The run stopped after creating the application: no provider, no key, nothing attached.
    fake.providers.clear()
    lms.docs.clear()
    fake.apps["Nile Workshop LMS"]["provider"] = None
    said = run_setup(fake, lms)
    assert said[1:] == ["created provider", "created frappe-key"]
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
