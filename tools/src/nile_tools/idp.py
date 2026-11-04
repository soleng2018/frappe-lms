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
    "ConfigProblem",
    "Refs",
    "Wanted",
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
AUTH_URL_DATA = '{"response_type":"code","scope":"openid profile email groups"}'


class ConfigProblem(Exception):
    """A needed setting is missing; the message names the key."""


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
