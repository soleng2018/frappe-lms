"""Pure rules for the Authentik sign in: the wanted state of each item, built from the config."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "APP_NAME",
    "AUTH_URL_DATA",
    "FAIL",
    "FRAPPE_KEY_NAME",
    "GROUPS_MAPPING_NAME",
    "IMPLICIT_CONSENT_SLUG",
    "INVALIDATION_SLUG",
    "MARKER",
    "PASS",
    "SCOPE_NAMES",
    "SIGNING_KEY_NAME",
    "SYSTEM_SETTINGS",
    "TESTED_VERSION",
    "WARN",
    "Change",
    "ConfigProblem",
    "Refs",
    "Refused",
    "Verdict",
    "Wanted",
    "diff",
    "judge_application",
    "judge_bad_state",
    "judge_discovery",
    "judge_email_lock",
    "judge_form",
    "judge_frappe_key",
    "judge_groups",
    "judge_login_page",
    "judge_provider",
    "judge_secret",
    "judge_version",
    "key_enabled",
    "login_form_state",
    "wanted_state",
]

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
TESTED_VERSION = "2026.8.3"
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


@dataclass(frozen=True)
class Verdict:
    """One `idp check` line: PASS, WARN or FAIL, and what it found."""

    level: str
    message: str


def judge_version(version: str | None) -> Verdict:
    """PASS on the tested Authentik version, WARN on any other, since field names may differ."""
    if version == TESTED_VERSION:
        return Verdict(PASS, f"Authentik {version} is reachable (the tested version)")
    return Verdict(
        WARN, f"Authentik {version} is reachable but {TESTED_VERSION} was tested; re run the probe"
    )


def judge_application(app: Mapping[str, Any] | None, slug: str) -> Verdict:
    """FAIL unless the application exists, carries our marker and has a provider."""
    if app is None:
        return Verdict(FAIL, f"application '{slug}' is missing; run `idp setup`")
    if app.get("meta_description") != MARKER:
        return Verdict(FAIL, f"application '{slug}' exists without the ownership marker")
    if app.get("provider") is None:
        return Verdict(FAIL, f"application '{slug}' has no provider; run `idp setup`")
    return Verdict(PASS, f"application '{slug}' is ours and has a provider")


def judge_provider(provider: Mapping[str, Any] | None, wanted: Mapping[str, Any]) -> Verdict:
    """FAIL when the provider is missing or any managed field differs from the wanted one."""
    if provider is None:
        return Verdict(FAIL, "provider is missing; run `idp setup`")
    fields = [c.field for c in diff("provider", wanted, provider)]
    if fields:
        return Verdict(FAIL, f"provider fields differ: {', '.join(fields)}; run `idp setup`")
    return Verdict(PASS, "provider fields are as wanted")


def judge_groups(user: str | None, claims: Mapping[str, Any] | None) -> Verdict:
    """FAIL unless the mapping test claims for the named user hold a non empty `groups`."""
    if user is None:
        return Verdict(WARN, f"'{GROUPS_MAPPING_NAME}' not tested; pass --user NAME")
    groups = claims.get("groups") if claims else None
    if not groups:
        return Verdict(FAIL, f"'{GROUPS_MAPPING_NAME}' gives no groups for user '{user}'")
    return Verdict(PASS, f"'{GROUPS_MAPPING_NAME}' gives {len(groups)} groups for user '{user}'")


def judge_email_lock(settings: Mapping[str, Any]) -> Verdict:
    """WARN when Authentik lets people edit their own email, since Frappe links by email."""
    if settings.get("default_user_change_email"):
        return Verdict(WARN, "Authentik lets users change their email; Frappe links people by it")
    return Verdict(PASS, "Authentik stops users changing their own email")


def judge_frappe_key(
    record: Mapping[str, Any] | None, wanted: Mapping[str, Any], client_id: str | None
) -> Verdict:
    """FAIL when the Frappe key is missing, disabled, or holds a wrong field or client id."""
    if record is None:
        return Verdict(FAIL, f"Frappe Social Login Key '{FRAPPE_KEY_NAME}' is missing")
    if not key_enabled(record):
        return Verdict(FAIL, f"Frappe Social Login Key '{FRAPPE_KEY_NAME}' is not enabled")
    expected = {**wanted, **({"client_id": client_id} if client_id else {})}
    fields = [c.field for c in diff("frappe-key", expected, record)]
    if fields:
        return Verdict(FAIL, f"Frappe key fields differ: {', '.join(fields)}; run `idp setup`")
    return Verdict(PASS, "Frappe key is enabled and its fields are as wanted")


def judge_secret(error: str | None) -> Verdict:
    """Judge the dummy token call: `invalid_grant` means the secret works, `invalid_client` not.

    `error` is the OAuth error Authentik answered, or None when the call could not be made.
    """
    if error == "invalid_grant":
        return Verdict(PASS, "the client secret held by Frappe is accepted by Authentik")
    if error == "invalid_client":
        return Verdict(FAIL, "Authentik rejects the client secret; run `idp setup --resync-secret`")
    if error is None:
        return Verdict(WARN, "secret not verified, run selftest")
    return Verdict(WARN, f"secret not verified: Authentik answered '{error}', run selftest")


def judge_form(settings: Mapping[str, Any]) -> Verdict:
    """WARN while the password form or the email link is on, since either skips Authentik."""
    on = []
    if not settings.get("disable_user_pass_login"):
        on.append("password form")
    if settings.get("login_with_email_link"):
        on.append("email link")
    if on:
        return Verdict(WARN, f"{' and '.join(on)} on; `idp setup` closes them")
    return Verdict(PASS, "password form and email link are off")


def judge_discovery(status: int | None) -> Verdict:
    """FAIL unless the public discovery document answers 200."""
    if status == 200:
        return Verdict(PASS, "public discovery document answers")
    return Verdict(FAIL, f"public discovery document answered {status or 'nothing'}")


def judge_login_page(status: int | None, text: str) -> Verdict:
    """FAIL unless the public `/login` page shows the Authentik button."""
    if status == 200 and f"Login with {PROVIDER_BUTTON}" in text:
        return Verdict(PASS, "/login shows the Authentik button")
    return Verdict(FAIL, f"/login (HTTP {status or 'none'}) does not show the Authentik button")


def judge_bad_state(status: int | None) -> Verdict:
    """FAIL unless a callback with a made up `state` is refused with 417."""
    if status == 417:
        return Verdict(PASS, "a callback with a bad state is refused (417)")
    return Verdict(FAIL, f"a callback with a bad state answered {status or 'nothing'}, not 417")
