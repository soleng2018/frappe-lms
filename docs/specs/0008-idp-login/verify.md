# Verify: IDP login · spec 0008 · updated 2026-11-04

_Build task 1 findings from the live probe (Authentik 2026.8.3, Frappe version-16 site `guide.nile.global`). The verify steps are added when the build lands._

## Probe findings

- **Authentik version**: 2026.8.3 (latest 2026.8.5, so `outdated` is true; `idp check` will WARN only if the version differs from the tested constant).
- **API base**: `/api/v3/`. A path with a leading slash drops that prefix in httpx, so the client strips it.
- **List filters**: `core/applications/?slug=` is ignored (returns every application), so the client keeps exact matches itself. `flows/instances/?slug=` works.
- **Flows**: `default-provider-authorization-implicit-consent` and `default-provider-invalidation-flow` exist. The authentication flow is `default-authentication-flow`; its stages are not yet checked for MFA or captcha (task 7).
- **Signing key**: `authentik Self-signed Certificate` (has a private key).
- **Scope mappings**: the openid, email and profile mappings are named `authentik default OAuth Mapping: OpenID '<scope>'`. The group mapping `HOL: OpenID groups scope` (scope name `groups`) has no `managed` id, so it is found by name.
- **Provider fields**: `redirect_uris` is a list of `{matching_mode, url, redirect_uri_type}`. The master token can create providers and applications.
- **Discovery**: `/application/o/<slug>/.well-known/openid-configuration` answers 200. Authorize, token and userinfo URLs are `/application/o/authorize/`, `/token/` and `/userinfo/`. The discovery lists scopes `openid email profile`; `groups` comes from the mapping.
- **Email lock**: `default_user_change_email` is false.
- **Frappe Social Login Key**: the record name is `scrub(provider_name)`, so `provider_name` `Authentik` gives the name `authentik` with no name sent. The service user can create it over REST, and the client secret is stored (the API masks it on read).
- **System Settings** (before setup): `disable_user_pass_login` 0, `login_with_email_link` 1.
- **`sign_ups`**: `Deny` is safe, because `nile_auth` creates the user before Frappe's `login_oauth_user`.
- **`backend` to Authentik**: reachable over public DNS (HTTP 200 on the discovery document), so `backend` needs no `extra_hosts` (AC-12).
- **Site config**: `host_name` is `https://guide.nile.global`, so the `redirect_uri` is the registered `https://` one.
- **`tools` to Authentik**: the old host gateway mapping hit this host's Traefik, which answers 404 for Authentik. The mapping is removed (specs 0001, 0002 and 0008 amended).
- **Thin thread result**: `idp setup` created the application, the provider and the Frappe key. The login page shows `Login with Authentik`, and a callback with a bad `state` answers 417.

## Still to probe

- Whether `Administrator` can sign in with the form off, and the break glass wording (task 4).
- The authentication flow stages, the `hol-labs-access` policy against the test group name, and the links that block a Frappe User delete (task 7).
