"""The `idp` command bodies: they glue the pure rules to the Authentik and LMS clients."""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from nile_tools import authentik, config, idp, lms
from nile_tools.authentik import Authentik, AuthentikError
from nile_tools.idp import Refs
from nile_tools.lms import Lms

__all__ = ["check", "lookup_refs", "password_login", "remove", "setup"]

Say = Callable[[str], None]
SOCIAL_KEY = "Social Login Key"
SETTINGS = "System Settings"


def _need(found: Mapping[str, object] | None, what: str) -> str:
    if not found:
        raise AuthentikError(f"Authentik has no {what}; setup stops before it creates anything")
    return str(found["pk"])


def _application(ak: Authentik, slug: str) -> Mapping[str, Any] | None:
    """Find our application by slug. Without `superuser_full_list` Authentik lists only what the
    token's user may open, and that list can come back empty after an application is made or
    deleted, so a lookup would wrongly say the application is missing.
    """
    return authentik.get_one(ak, "/core/applications/", slug=slug, superuser_full_list="true")


def _flow_slug(values: Mapping[str, str]) -> str:
    """Return the configured authorization flow slug, or the default implicit consent flow."""
    return values.get("AUTHENTIK_AUTHORIZATION_FLOW") or idp.IMPLICIT_CONSENT_SLUG


def lookup_refs(ak: Authentik, flow_slug: str = idp.IMPLICIT_CONSENT_SLUG) -> Refs:
    """Read the shared flows, signing key and scope mappings by slug or name; write nothing."""
    maps = authentik.find(ak, "/propertymappings/provider/scope/")
    by_name = {m["name"]: str(m["pk"]) for m in maps}
    by_scope = {
        m["scope_name"]: str(m["pk"])
        for m in maps
        if str(m["name"]).startswith("authentik default")
    }
    groups = by_name.get(idp.GROUPS_MAPPING_NAME)
    if groups is None:
        raise AuthentikError(
            f"Authentik has no scope mapping named '{idp.GROUPS_MAPPING_NAME}'; "
            "setup stops before it creates anything"
        )
    missing = [s for s in idp.SCOPE_NAMES if s not in by_scope]
    if missing:
        raise AuthentikError(f"Authentik has no default scope mapping for: {', '.join(missing)}")
    flows = "/flows/instances/"
    return Refs(
        authorization_flow=_need(
            authentik.get_one(ak, flows, slug=flow_slug), f"authorization flow '{flow_slug}'"
        ),
        invalidation_flow=_need(
            authentik.get_one(ak, flows, slug=idp.INVALIDATION_SLUG), "provider invalidation flow"
        ),
        signing_key=_need(
            authentik.get_one(
                ak, "/crypto/certificatekeypairs/", name=idp.SIGNING_KEY_NAME, has_key="true"
            ),
            "self signed signing key",
        ),
        property_mappings=(*(by_scope[s] for s in idp.SCOPE_NAMES), groups),
    )


def _report(item: str, created: bool, changes: Sequence[idp.Change], say: Say) -> None:
    """Print one status line per item, or one `fixed` line per changed field."""
    if created:
        say(f"created {item}")
    elif not changes:
        say(f"unchanged {item}")
    for change in changes:
        say(f"fixed {item}: {change.field}")


def _fields(changes: Sequence[idp.Change]) -> dict[str, Any]:
    return {c.field: c.wanted for c in changes}


def setup(
    ak: Authentik,
    connection: Lms,
    values: Mapping[str, str],
    say: Say,
    *,
    resync_secret: bool = False,
) -> int:
    """Create what is missing, fix what drifted, and report each item; a rerun changes nothing."""
    wanted = idp.wanted_state(values, lookup_refs(ak, _flow_slug(values)))
    slug = str(wanted.application["slug"])
    provider_name = str(wanted.provider["name"])
    # Read everything first, so a refusal happens before the first write.
    app = _application(ak, slug)
    provider = authentik.get_one(ak, "/providers/oauth2/", name=provider_name)
    if app is not None and app.get("meta_description") != idp.MARKER:
        raise AuthentikError(f"Authentik application '{slug}' exists without the ownership marker")
    if app is None and provider is not None:
        raise AuthentikError(
            f"Authentik provider '{provider_name}' exists but application '{slug}' does not, "
            "so the provider is not ours; setup changes nothing"
        )
    # The application goes first, so a half done run leaves an owned item that a rerun finishes.
    app_created = app is None
    app_changes: list[idp.Change] = []
    if app is None:
        app = authentik.create(ak, "/core/applications/", wanted.application)
    else:
        app_changes = idp.diff("application", wanted.application, app)
        if app_changes:
            authentik.update(ak, f"/core/applications/{slug}/", _fields(app_changes))
    provider_created = provider is None
    provider_changes: list[idp.Change] = []
    if provider is None:
        provider = authentik.create(ak, "/providers/oauth2/", wanted.provider)
    else:
        provider_changes = idp.diff("provider", wanted.provider, provider)
        if provider_changes:
            pk = provider["pk"]
            authentik.update(ak, f"/providers/oauth2/{pk}/", _fields(provider_changes))
    if app.get("provider") != provider["pk"]:
        authentik.update(ak, f"/core/applications/{slug}/", {"provider": provider["pk"]})
        if not app_created:
            app_changes.append(idp.Change("application", "provider", provider["pk"]))
    client_id, client_secret = str(provider["client_id"]), str(provider["client_secret"])
    config.install_masking([client_secret])  # before anything can log it
    _report("application", app_created, app_changes, say)
    _report("provider", provider_created, provider_changes, say)
    _frappe_key(connection, wanted.frappe_key, client_id, client_secret, resync_secret, say)
    _guest_access(connection, say)
    _login_form(connection, on=False, say=say)  # always ends closed, so a rerun shuts a break glass
    say(f"Sign in at https://{values['LMS_HOSTNAME']}/login")
    return 0


def _frappe_key(
    connection: Lms,
    wanted_key: Mapping[str, Any],
    client_id: str,
    client_secret: str,
    resync_secret: bool,
    say: Say,
) -> None:
    """Create or fix the Social Login Key. Frappe masks the secret, so it is never compared."""
    name = idp.FRAPPE_KEY_NAME
    wanted = {**wanted_key, "client_id": client_id}
    existing = lms.list_records(connection, SOCIAL_KEY, filters=[["name", "=", name]])
    if not existing:
        body = {**wanted, "client_secret": client_secret}
        lms.create_record(connection, SOCIAL_KEY, body, label=f"{SOCIAL_KEY} {name}")
        _report("frappe-key", True, [], say)
        return
    changes = idp.diff("frappe-key", wanted, lms.get_record(connection, SOCIAL_KEY, name))
    write = _fields(changes)
    if resync_secret or "client_id" in write:  # a new client id needs its own secret
        write["client_secret"] = client_secret
        changes = [*changes, idp.Change("frappe-key", "client_secret", None)]
    if write:
        lms.update_record(connection, SOCIAL_KEY, name, write, label=f"{SOCIAL_KEY} {name}")
    _report("frappe-key", False, changes, say)


def _require_enabled_key(connection: Lms) -> None:
    """Refuse to close the password form unless the Authentik button will work."""
    found = lms.list_records(connection, SOCIAL_KEY, filters=[["name", "=", idp.FRAPPE_KEY_NAME]])
    if not found or not idp.key_enabled(found[0]):
        raise idp.Refused(
            f"No enabled {SOCIAL_KEY} '{idp.FRAPPE_KEY_NAME}' exists, so the password form stays "
            "as it is; run `idp setup` first"
        )


def _login_form(connection: Lms, *, on: bool, say: Say) -> None:
    """Set the password form and email link; closing it needs an enabled Authentik key."""
    if not on:
        _require_enabled_key(connection)
    live = lms.get_record(connection, idp.SYSTEM_SETTINGS, idp.SYSTEM_SETTINGS)
    changes = idp.diff("system-settings", idp.login_form_state(on, live), live)
    if changes:
        lms.update_record(
            connection, idp.SYSTEM_SETTINGS, idp.SYSTEM_SETTINGS, _fields(changes), label=SETTINGS
        )
    _report("system-settings", False, changes, say)


def _guest_access(connection: Lms, say: Say) -> None:
    """Turn LMS guest access off, so a signed out visitor sees no page or site total."""
    live = lms.get_record(connection, idp.LMS_SETTINGS, idp.LMS_SETTINGS)
    changes = idp.diff("lms-settings", idp.GUEST_ACCESS_OFF, live)
    if changes:
        lms.update_record(
            connection, idp.LMS_SETTINGS, idp.LMS_SETTINGS, _fields(changes), label=idp.LMS_SETTINGS
        )
    _report("lms-settings", False, changes, say)


def password_login(connection: Lms, state: str, say: Say) -> int:
    """Switch Frappe's own password form `on` (break glass) or `off`, and report the state."""
    on = state == "on"
    _login_form(connection, on=on, say=say)
    say(f"password login is {state}")
    return 0


def _public(http: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response | None:
    """Make one unsigned request; None when the host cannot be reached."""
    try:
        return http.request(method, url, **kwargs)
    except httpx.HTTPError:
        return None


def _oauth_error(response: httpx.Response | None) -> str | None:
    """Read the OAuth `error` code out of a token endpoint answer."""
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    return str(error) if error else f"HTTP {response.status_code}"


def _group_claims(ak: Authentik, mapping: str, user: str) -> dict[str, Any] | None:
    """Run Authentik's property mapping test for a real user; None if it cannot be run."""
    found = authentik.get_one(ak, "/core/users/", username=user)
    if found is None:
        return None
    # The test is a POST, but it only evaluates the mapping and stores nothing.
    test = authentik.create(ak, f"/propertymappings/all/{mapping}/test/", {"user": found["pk"]})
    try:
        claims = json.loads(test.get("result") or "null") if test.get("successful") else None
    except ValueError:
        return None
    return claims if isinstance(claims, dict) else None


def check(
    ak: Authentik,
    connection: Lms,
    public: httpx.Client,
    values: Mapping[str, str],
    say: Say,
    *,
    user: str | None = None,
) -> int:
    """Report PASS, WARN or FAIL per setup item without writing; return 1 on any FAIL."""
    verdicts: list[idp.Verdict] = []
    slug, lms_host = values["AUTHENTIK_APP_SLUG"], values["LMS_HOSTNAME"]
    base = f"https://{values['AUTHENTIK_HOSTNAME']}"
    verdicts.append(idp.judge_version(authentik.get(ak, "/admin/version/").get("version_current")))
    app = _application(ak, slug)
    verdicts.append(idp.judge_application(app, slug))
    provider = authentik.get_one(ak, "/providers/oauth2/", name=f"{slug} provider")
    try:
        refs = lookup_refs(ak, _flow_slug(values))
    except AuthentikError as e:
        verdicts.append(idp.Verdict(idp.FAIL, f"shared Authentik items: {e}"))
        wanted = idp.wanted_state(values, Refs("", "", "", ()))
        verdicts.append(idp.Verdict(idp.WARN, "provider fields not compared, shared items missing"))
        verdicts.append(idp.judge_groups(user, None))
    else:
        wanted = idp.wanted_state(values, refs)
        verdicts.append(idp.judge_provider(provider, wanted.provider))
        claims = _group_claims(ak, refs.property_mappings[-1], user) if user else None
        verdicts.append(idp.judge_groups(user, claims))
    flow_slug = _flow_slug(values)
    flow = authentik.get_one(ak, "/flows/instances/", slug=flow_slug)
    # Bindings hang off the flow's policy binding model id, which is not the flow's own pk.
    target = str(flow.get("policybindingmodel_ptr_id") or flow["pk"]) if flow else ""
    bindings = len(authentik.find(ak, "/policies/bindings/", target=target)) if flow else 0
    verdicts.append(idp.judge_authorization_flow(flow_slug, flow is not None, bindings))
    verdicts.append(idp.judge_email_lock(authentik.get(ak, "/admin/settings/")))
    found = lms.list_records(connection, SOCIAL_KEY, filters=[["name", "=", idp.FRAPPE_KEY_NAME]])
    record = lms.get_record(connection, SOCIAL_KEY, idp.FRAPPE_KEY_NAME) if found else None
    client_id = str(provider["client_id"]) if provider else None
    verdicts.append(idp.judge_frappe_key(record, wanted.frappe_key, client_id))
    redirect = idp.redirect_uri(lms_host)
    verdicts.append(_judge_secret(public, connection, wanted, redirect, client_id))
    settings = lms.get_record(connection, SETTINGS, SETTINGS)
    verdicts.append(idp.judge_form(settings))
    verdicts.append(
        idp.judge_guest_access(lms.get_record(connection, idp.LMS_SETTINGS, idp.LMS_SETTINGS))
    )
    discovery = _public(
        public, "GET", f"{base}/application/o/{slug}/.well-known/openid-configuration"
    )
    verdicts.append(idp.judge_discovery(discovery.status_code if discovery else None))
    login = _public(public, "GET", f"https://{lms_host}/login")
    verdicts.append(
        idp.judge_login_page(login.status_code if login else None, login.text if login else "")
    )
    callback = _public(
        public,
        "GET",
        f"https://{lms_host}{idp.CALLBACK_PATH}",
        params={"code": "nile-check", "state": "nile-check"},
    )
    verdicts.append(idp.judge_bad_state(callback.status_code if callback else None))
    for v in verdicts:
        say(f"{v.level} {v.message}")
    return 1 if any(v.level == idp.FAIL for v in verdicts) else 0


def _judge_secret(
    public: httpx.Client, connection: Lms, wanted: idp.Wanted, redirect: str, client_id: str | None
) -> idp.Verdict:
    """Send a dummy code with the secret Frappe holds and judge how Authentik answers."""
    secret = lms.get_password(connection, SOCIAL_KEY, idp.FRAPPE_KEY_NAME, "client_secret")
    if secret is None or client_id is None:
        return idp.judge_secret(None)
    config.install_masking([secret])
    response = _public(
        public,
        "POST",
        wanted.frappe_key["access_token_url"],
        data={
            "grant_type": "authorization_code",
            "code": "nile-check",
            "redirect_uri": redirect,
            "client_id": client_id,
            "client_secret": secret,
        },
    )
    return idp.judge_secret(_oauth_error(response))


def remove(ak: Authentik, connection: Lms, values: Mapping[str, str], say: Say) -> int:
    """Delete the marked Frappe key, provider and application, in that order; a rerun is a no op."""
    slug = values.get("AUTHENTIK_APP_SLUG", "")
    if not slug:
        raise idp.ConfigProblem("Config key AUTHENTIK_APP_SLUG is missing or blank in .env")
    app = _application(ak, slug)
    if app is not None and app.get("meta_description") != idp.MARKER:
        raise AuthentikError(f"Authentik application '{slug}' exists without the ownership marker")
    name = idp.FRAPPE_KEY_NAME
    if lms.list_records(connection, SOCIAL_KEY, filters=[["name", "=", name]]):
        lms.delete_record(connection, SOCIAL_KEY, name, label=f"{SOCIAL_KEY} {name}")
        say("removed frappe-key")
    else:
        say("absent frappe-key")
    provider_pk = app.get("provider") if app else None
    if provider_pk is not None:
        authentik.delete(ak, f"/providers/oauth2/{provider_pk}/")
        say("removed provider")
    else:
        say("absent provider")
    if app is not None:
        authentik.delete(ak, f"/core/applications/{slug}/")
        say("removed application")
    else:
        say("absent application")
    say(
        "The password form was left as it is. If it is still off, run `idp password-login on` "
        "to sign in as Administrator."
    )
    return 0
