"""Pure rules for the Authentik sign in: the wanted state of each item, built from the config."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "APP_NAME",
    "AUTH_URL_DATA",
    "FRAPPE_KEY_NAME",
    "GROUPS_MAPPING_NAME",
    "IMPLICIT_CONSENT_SLUG",
    "INVALIDATION_SLUG",
    "MARKER",
    "SCOPE_NAMES",
    "SIGNING_KEY_NAME",
    "SYSTEM_SETTINGS",
    "Change",
    "ConfigProblem",
    "Refs",
    "Refused",
    "Wanted",
    "diff",
    "key_enabled",
    "login_form_state",
    "wanted_state",
]

MARKER = "managed-by: nile-lms idp setup"
FRAPPE_KEY_NAME = "authentik"
GROUPS_MAPPING_NAME = "HOL: OpenID groups scope"
SCOPE_NAMES = ("openid", "email", "profile")
IMPLICIT_CONSENT_SLUG = "default-provider-authorization-implicit-consent"
INVALIDATION_SLUG = "default-provider-invalidation-flow"
SIGNING_KEY_NAME = "authentik Self-signed Certificate"
APP_NAME = "Nile Workshop LMS"
PROVIDER_BUTTON = "Authentik"
CALLBACK_PATH = f"/api/method/frappe.integrations.oauth2_logins.custom/{FRAPPE_KEY_NAME}"
SYSTEM_SETTINGS = "System Settings"
DEFAULT_LANGUAGE = "en"
# Both states keep the email link off; only the password form comes back for the break glass.
FORM_OFF = {"disable_user_pass_login": 1, "login_with_email_link": 0}
FORM_ON = {"disable_user_pass_login": 0, "login_with_email_link": 0}
AUTH_URL_DATA = '{"response_type":"code","scope":"openid profile email groups"}'


class ConfigProblem(Exception):
    """A needed setting is missing; the message names the key."""


class Refused(Exception):
    """A command declined to run because it would lock people out; the message says why."""


@dataclass(frozen=True)
class Refs:
    """Ids of the shared Authentik items we only read: flows, signing key and scope mappings."""

    authorization_flow: str
    invalidation_flow: str
    signing_key: str
    property_mappings: tuple[str, ...]


@dataclass(frozen=True)
class Wanted:
    """What each system should hold: the provider and application bodies, and the Frappe key."""

    provider: Mapping[str, Any]
    application: Mapping[str, Any]
    frappe_key: Mapping[str, Any]


@dataclass(frozen=True)
class Change:
    """One managed field whose live value differs from the wanted one."""

    item: str
    field: str
    wanted: Any


def _canonical(field: str, value: Any) -> Any:
    """Return a value in the form used to compare it: redirect URIs and mappings as exact sets."""
    if field == "redirect_uris":
        return frozenset((u.get("matching_mode"), u.get("url")) for u in value or [])
    if field == "property_mappings":
        return frozenset(str(v) for v in value or [])
    return value


def diff(item: str, wanted: Mapping[str, Any], live: Mapping[str, Any]) -> list[Change]:
    """List a Change for each wanted field that the live record lacks or holds differently."""
    return [
        Change(item, field, value)
        for field, value in wanted.items()
        if _canonical(field, live.get(field)) != _canonical(field, value)
    ]


def redirect_uri(lms_hostname: str) -> str:
    """Return the one callback URL registered with Authentik."""
    return f"https://{lms_hostname}{CALLBACK_PATH}"


def wanted_state(values: Mapping[str, str], refs: Refs) -> Wanted:
    """Build the wanted provider, application and Frappe key (no id or secret) from config."""
    keys = ("AUTHENTIK_HOSTNAME", "AUTHENTIK_APP_SLUG", "LMS_HOSTNAME")
    missing = [k for k in keys if not values.get(k)]
    if missing:
        raise ConfigProblem(f"Config key {', '.join(missing)} is missing or blank in .env")
    slug = values["AUTHENTIK_APP_SLUG"]
    lms = values["LMS_HOSTNAME"]
    base = f"https://{values['AUTHENTIK_HOSTNAME']}"
    provider = {
        "name": f"{slug} provider",
        "client_type": "confidential",
        "authorization_flow": refs.authorization_flow,
        "invalidation_flow": refs.invalidation_flow,
        "signing_key": refs.signing_key,
        "property_mappings": sorted(refs.property_mappings),
        "redirect_uris": [{"matching_mode": "strict", "url": redirect_uri(lms)}],
        "sub_mode": "hashed_user_id",
        "issuer_mode": "per_provider",
        "include_claims_in_id_token": True,
    }
    application = {
        "name": APP_NAME,
        "slug": slug,
        "meta_launch_url": f"https://{lms}/lms",
        "policy_engine_mode": "any",
        "meta_description": MARKER,
    }
    frappe_key = {
        "provider_name": PROVIDER_BUTTON,
        "social_login_provider": "Custom",
        "enable_social_login": 1,
        "base_url": base,
        "custom_base_url": 1,
        "authorize_url": f"{base}/application/o/authorize/",
        "access_token_url": f"{base}/application/o/token/",
        "redirect_url": CALLBACK_PATH,
        "api_endpoint": f"{base}/application/o/userinfo/",
        "auth_url_data": AUTH_URL_DATA,
        "sign_ups": "Deny",
        "user_id_property": "sub",
    }
    return Wanted(provider, application, frappe_key)


def login_form_state(on: bool, live: Mapping[str, Any]) -> dict[str, Any]:
    """Return the System Settings values for the form on (break glass) or off.

    Frappe will not save System Settings with a blank Language, so a blank one gets its default.
    """
    wanted: dict[str, Any] = dict(FORM_ON if on else FORM_OFF)
    if not live.get("language"):
        wanted["language"] = DEFAULT_LANGUAGE
    return wanted


def key_enabled(record: Mapping[str, Any] | None) -> bool:
    """Say whether the Social Login Key record exists and is switched on."""
    return record is not None and record.get("enable_social_login") in (1, True)
