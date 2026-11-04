"""The `idp` command bodies: they glue the pure rules to the Authentik and LMS clients."""

from collections.abc import Callable, Mapping

from nile_tools import authentik, config, idp, lms
from nile_tools.authentik import Authentik, AuthentikError
from nile_tools.idp import Refs
from nile_tools.lms import Lms, LmsError

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


def setup(ak: Authentik, connection: Lms, values: Mapping[str, str], say: Say) -> int:
    """Create the application, the provider and the Frappe key (first cut: creates only)."""
    wanted = idp.wanted_state(values, lookup_refs(ak))
    slug = str(wanted.application["slug"])
    app = authentik.get_one(ak, "/core/applications/", slug=slug)
    if app is None:
        app = authentik.create(ak, "/core/applications/", wanted.application)
        say(f"created application: {slug}")
    elif app.get("meta_description") != idp.MARKER:
        raise AuthentikError(f"Authentik application '{slug}' exists without the ownership marker")
    provider = authentik.get_one(ak, "/providers/oauth2/", name=str(wanted.provider["name"]))
    if provider is None:
        provider = authentik.create(ak, "/providers/oauth2/", wanted.provider)
        say(f"created provider: {wanted.provider['name']}")
    if app.get("provider") != provider["pk"]:
        authentik.update(ak, f"/core/applications/{slug}/", {"provider": provider["pk"]})
    client_id, client_secret = str(provider["client_id"]), str(provider["client_secret"])
    config.install_masking([client_secret])  # before anything can log it
    existing = lms.list_records(
        connection, SOCIAL_KEY, filters=[["name", "=", idp.FRAPPE_KEY_NAME]], fields=["name"]
    )
    if not existing:
        body = {**wanted.frappe_key, "client_id": client_id, "client_secret": client_secret}
        try:
            lms.create_record(
                connection, SOCIAL_KEY, body, label=f"{SOCIAL_KEY} {idp.FRAPPE_KEY_NAME}"
            )
        except LmsError:
            raise
        say(f"created frappe-key: {idp.FRAPPE_KEY_NAME}")
    say(f"Sign in at https://{values['LMS_HOSTNAME']}/login")
    return 0
