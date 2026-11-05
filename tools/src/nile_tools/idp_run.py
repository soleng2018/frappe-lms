"""The `idp` command bodies: they glue the pure rules to the Authentik and LMS clients."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from nile_tools import authentik, config, idp, lms
from nile_tools.authentik import Authentik, AuthentikError
from nile_tools.idp import Refs
from nile_tools.lms import Lms

__all__ = ["lookup_refs", "setup"]

Say = Callable[[str], None]
SOCIAL_KEY = "Social Login Key"


def _need(found: Mapping[str, object] | None, what: str) -> str:
    if not found:
        raise AuthentikError(f"Authentik has no {what}; setup stops before it creates anything")
    return str(found["pk"])


def lookup_refs(ak: Authentik) -> Refs:
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
            authentik.get_one(ak, flows, slug=idp.IMPLICIT_CONSENT_SLUG), "implicit consent flow"
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
    wanted = idp.wanted_state(values, lookup_refs(ak))
    slug = str(wanted.application["slug"])
    provider_name = str(wanted.provider["name"])
    # Read everything first, so a refusal happens before the first write.
    app = authentik.get_one(ak, "/core/applications/", slug=slug)
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
