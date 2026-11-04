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
        slug = path.split("/")[-2]
        app = next(a for a in self.apps.values() if a["slug"] == slug)
        app.update(body)
        return httpx.Response(200, json=app)


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
    assert said[0] == "created application: nile-lms"
    assert all("s3cret-value" not in line for line in said)
    assert said[-1] == "Sign in at https://lms.example.com/login"


def test_setup_refuses_an_application_without_the_marker():
    fake = FakeAuthentik()
    fake.apps["x"] = {"pk": 9, "slug": "nile-lms", "meta_description": "", "provider": None}
    with pytest.raises(AuthentikError, match="without the ownership marker"):
        idp_run.setup(fake.client(), FakeLms().client(), VALUES, lambda _: None)
    assert not [c for c in fake.calls if c[0] != "GET"]


def test_a_failed_request_names_the_url_and_not_the_token():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "no"})

    ak = authentik.connect("auth.test", "tok-123", transport=httpx.MockTransport(refuse))
    with pytest.raises(AuthentikError) as e:
        authentik.find(ak, "/core/applications/")
    assert "https://auth.test/api/v3/core/applications/" in str(e.value)
    assert "tok-123" not in str(e.value)
