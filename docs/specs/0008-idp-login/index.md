# 0008. Sign in through Authentik, set up by one script

**Date**: 2026-11-04
**Status**: In Progress

## Summary

One script, `idp setup`, creates the sign in application in Authentik and the matching login entry in Frappe, so students and admins reach the LMS only through Authentik. It can be run again at any time and then changes nothing, or puts back anything someone edited. The same script can check the setup, remove only what it created, switch Frappe's own password form on or off for emergencies, and run a self test with a throwaway Authentik user. The password form and the email link are turned off, because they would let someone skip Authentik and its group check. People always land on `/lms` after signing in.

## Requirements

**User stories**:
- As a student, I want to click one button, sign in with my Authentik account, and land in the LMS, so that I can start my lab.
- As the operator, I want one command that sets up Authentik and Frappe and is safe to run again, so that a rebuild or a drift never needs hand editing.
- As the operator, I want nobody to be able to sign in without Authentik, so that removing someone from a group really removes their access.
- As the operator, I want a documented way back in when Authentik is down, so that I am never locked out of my own LMS.
- As the operator, I want the script to touch only the items it created in Authentik, so that Cloudflare and the other apps are never at risk.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: On a setup with no `nile-lms` application, `idp setup` creates in Authentik one OAuth2 provider and one application (slug from `AUTHENTIK_APP_SLUG`, no group bindings), and in Frappe one Social Login Key of type Custom. The provider is confidential, with the one strict redirect URI of the Frappe callback, the implicit consent flow, and the scopes `openid`, `profile`, `email`, and `groups`. The Frappe key points at the Authentik authorize, token, and userinfo URLs, requests the scope string `openid profile email groups`, and is enabled. The command prints each item as `created`, exits 0, and prints no secret.
- **AC-2**: Running `idp setup` again with nothing edited reports every item as `unchanged` and writes nothing, and the client secret is not rotated. If a managed field was edited on either side (redirect URI, scopes, URLs, the enabled flag, the scope string), the run puts it back and reports `fixed <item>: <field>`. The items are `provider`, `application`, `frappe-key`, and `system-settings`, and every status line uses that one format. `redirect_uris` and `property_mappings` are compared as exact sets, so an extra entry someone added is removed. A `--resync-secret` flag rewrites the Frappe client secret from Authentik. If an application with the slug exists but lacks the ownership marker, the run stops with an error naming the slug and changes nothing.
- **AC-3**: A student can sign in end to end. `idp selftest` creates a throwaway Authentik user, a throwaway course in the LMS, and a group named exactly like that course, drives the real OIDC login over HTTPS, and checks that the login ends signed in as that user, on that course's page, with the LMS Student role and an enrollment in only that course (spec 0009). The same run signs in a second throwaway user who is in no course group and checks that the result is the 403 page and that no Frappe user exists for them. The operator also does one real browser sign in as a `hol-admins` member and ticks it in `verify.md`. The admin path is not automated, because putting a test account in `hol-admins` would also give it Cloudflare Access.
- **AC-4**: The userinfo for a signed in user carries a `groups` list. This needs the `groups` scope on both sides and the existing `HOL: OpenID groups scope` mapping on the provider. `idp setup` stops before creating anything if that mapping is missing. `idp check` runs Authentik's property mapping test for a named real user and fails if the result has no `groups` (a read only check holds no user token, so it cannot fetch a userinfo). `idp selftest` asserts the real userinfo has `groups`. The script never edits that mapping.
- **AC-5**: After `idp setup`, the Frappe login page shows the Authentik button and no username and password form and no email link option, and a password or email link login is refused by Frappe. `idp password-login on` brings the form back so `Administrator` can sign in, and does not bring back the email link. `idp password-login off` hides it again, and `off` (and setup) refuse to run unless an enabled Authentik Social Login Key exists, so nobody is locked out. The service user's API key and secret work in both states. Setup always ends with the form off, so a rerun closes a break glass left open, and `idp check` warns while it is on. If the probe shows `Administrator` cannot sign in even with the form on, the break glass is a `bench execute` step, written in the README.
- **AC-6**: The client id and secret exist only in Authentik and in Frappe's encrypted Social Login Key. They are read from the Authentik API and sent to the Frappe API in memory, and appear in no `.env` key, log line, output, file, or compose entry. No new `.env` key is added. The Authentik master token is read only by the `tools` container.
- **AC-7**: `idp check` is a read only report. It never writes. Each line is PASS, WARN, or FAIL, and the exit code is 1 if any line is FAIL. The lines are: Authentik reachable and its version (PASS when it equals the tested constant `2026.8.3`, otherwise WARN), the application and its marker, the provider fields, the `HOL: OpenID groups scope` mapping present and yielding groups, `default_user_change_email` off in Authentik (WARN if on, because Frappe links people by email), the Frappe key fields and its enabled flag, the client secret (a call to the Authentik token endpoint with a dummy code and the secret Frappe holds: `invalid_grant` is PASS, `invalid_client` is FAIL and says to run `setup --resync-secret`; if the secret cannot be read, WARN with "secret not verified, run selftest"), the password form and email link switched off (WARN if on), the public discovery document at `/application/o/<slug>/.well-known/openid-configuration`, a `/login` page that shows the Authentik button, and a callback with a bad `state` answered with 417.
- **AC-8**: `idp remove` deletes only items that carry the ownership marker, in this order: the Frappe Social Login Key named `authentik`, then the provider (its id read first from the application), then the application. It never deletes a Frappe user, a batch, an enrollment, or any Authentik item without the marker. A second run changes nothing, and a slug without the marker is refused like AC-2. After a remove the password form stays as it is, so the report prints the break glass command (`idp password-login on`) and says so.
- **AC-9**: When Authentik or the LMS cannot be reached, the command fails with one message naming the URL, after the same 5 minute retry the LMS client already uses. The retry applies only to connection errors and 5xx answers, and every create is preceded by a read by name or slug, so a timed out create that succeeded is never repeated. A setup that stopped halfway is finished by running it again. No step needs a manual cleanup.
- **AC-10**: After a successful sign in, a person lands on `/lms`, whatever their role. A deep link kept by Frappe in `redirect_to` is honored only when it is a path on this site (starts with a single `/`, with no backslash, no control character, and no `%2F` or `%5C` right after the first `/`). An absolute URL, a `//host` value, or any other form is ignored and the person lands on `/lms`. The tail decodes `redirect_to` from the `state` before Frappe's `login_oauth_user` consumes it.
- **AC-11**: `idp selftest` creates and deletes only items it made: a user, a group, and the Frappe records the login made (user, enrollments, and the throwaway course). Every Authentik test item carries the ownership marker and fixed names. It removes them on pass, fail, and interrupt. At the start of every run it first cleans leftovers of an earlier killed run, by the fixed test email and the fixed test course group name, and only for records whose email carries the test prefix. It refuses to start if an Authentik item with those names exists without the marker. It never touches `hol-admins` or any real group or user.
- **AC-12**: The `backend` container can reach Authentik for the token and userinfo calls, and the `redirect_uri` Frappe sends is exactly the registered `https://` one (if it is `http://`, setup's prerequisite is site config `host_name` set to `https://<LMS_HOSTNAME>`, which spec 0001 already requires). If the live probe shows it cannot resolve or reach the Authentik hostname, `compose.yaml` gives `backend` an `extra_hosts` line for it, and the static compose check covers it. The probe on 2026-11-04 found that `backend` reaches Authentik through public DNS, so no line is needed. `idp selftest` passing is the proof.

## Decision

**Chosen option**: Option 1: one `idp` command group in the existing `tools` package, talking to Authentik and Frappe through their REST APIs, with a small landing page tail in the `nile_auth` callback.

`idp setup` builds the wanted state as plain data from the config file and the looked up references (flows, key, mappings), reads the live state, and a pure function compares them. The shell around it creates or fixes the difference. Authentik items are marked as ours with the application's `meta_description`, whose value is the fixed text `managed-by: nile-lms idp setup` (students see it on their Authentik dashboard). The Frappe Social Login Key named `authentik` counts as ours, and spec 0006's throwaway test key must use a different name. If someone edits the marker away, setup and remove refuse until the text is put back by hand, and the README says so.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`) · `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: no new Frappe records and no new fields. The script manages these existing kinds of record. "Ours" means created by `idp setup` or `idp selftest`.

| System | Record | Fields the script manages | Notes |
|---|---|---|---|
| Authentik | OAuth2 Provider, name `<slug> provider` | `client_type` confidential, `redirect_uris` (one strict entry), `authorization_flow` (implicit consent, by slug), `invalidation_flow` (default provider flow, by slug), `signing_key` (the existing self signed key, by name), `property_mappings` (openid, email, profile, and `HOL: OpenID groups scope`), `sub_mode` hashed user id, `issuer_mode` per provider, `include_claims_in_id_token` true | `client_id` and `client_secret` are generated by Authentik and never chosen by us |
| Authentik | Application, slug `AUTHENTIK_APP_SLUG`, name `Nile Workshop LMS` | `provider`, `meta_launch_url` `https://<LMS_HOSTNAME>/lms`, `policy_engine_mode` any, `meta_description` (the ownership marker) | No policy or group bindings |
| Authentik | Test user and test group (selftest only) | name, email, password, `attributes.managed_by` marker | Exist only during a selftest |
| Frappe | Social Login Key, name `authentik` | `provider_name`, `social_login_provider` Custom, `enable_social_login`, `client_id`, `client_secret` (a password field), `base_url`, `custom_base_url`, `authorize_url`, `access_token_url`, `redirect_url`, `api_endpoint` (userinfo), `auth_url_data` (scope and response type), `sign_ups`, `user_id_property` `sub` | Exact field names and the record name are fixed by build task 1 |
| Frappe | System Settings (single record) | `disable_user_pass_login`, `login_with_email_link` | Names fixed by build task 1. Set by setup and `password-login`. |

**Module layout**:

| Module | Holds | Imports httpx? |
|---|---|---|
| `tools/src/nile_tools/idp.py` | Pure functions: `wanted_state(config, refs)` (`refs` holds the looked up flow, key, and mapping ids) returns frozen records for the Authentik and Frappe items, `diff(wanted, live)` returns a list of `Change(item, field, wanted)`, the `check` judges (each takes parsed responses and returns PASS, WARN, or FAIL with a message), `safe_return_path(value)` for AC-10, and the constants (key name, marker text, test names) | No |
| `tools/src/nile_tools/authentik.py` | A small Authentik client: connect with the base URL and bearer token, get, create, update, and delete for providers, applications, mappings, flows, keys, users, groups, and the settings read. One error type that names the URL. | Yes |
| `tools/src/nile_tools/idp_run.py` | The command bodies: `setup`, `check`, `remove`, `password_login`, `selftest`. They glue the pure functions to the two clients and print results. | Uses both clients |
| `tools/src/nile_tools/lms.py` | Existing LMS client. Gains Social Login Key and System Settings helpers. | Yes |
| `tools/src/nile_tools/cli.py` | Gains the `idp` command group | No |
| `apps/nile_auth/nile_auth/login.py` | The landing tail (AC-10) at the end of `custom`, after Frappe accepts the login | Frappe |

**Command flow, `idp setup`** (order matters, each step is safe to repeat):
1. Read and validate config (`config check --for tools-authentik` rules): `AUTHENTIK_HOSTNAME`, `AUTHENTIK_API_TOKEN`, `AUTHENTIK_APP_SLUG`, `LMS_HOSTNAME`, and the service user key and secret.
2. Read from Authentik, writing nothing: the `HOL: OpenID groups scope` mapping, the openid, email, and profile mappings, the implicit consent flow, the invalidation flow, the signing key, and any application with the slug. Stop with a named error if a needed item is missing (AC-4), or if the slug exists without the marker (AC-2).
3. Create or fix the marked application first (with no provider if it is new), then the provider, then attach the provider to the application, from `wanted_state` and `diff`. Because the application exists before the provider, a half done run leaves an owned application the rerun can finish. Read back `client_id` and `client_secret` from the provider, and register the secret with the output masker at once, before anything can log it. HTTP debug logging of bodies stays off.
4. Create or fix the Frappe Social Login Key. A new key, a changed `client_id`, or `--resync-secret` also writes the secret. The Frappe API returns a password field masked, so the secret is never compared, only written when one of those three holds (`idp check` verifies it with the token call of AC-7).
5. Set the two System Settings so the form and the email link are off, only after the key exists and is enabled.
6. Print one line per item (`created`, `unchanged`, or `fixed <item>: <field>`) and the sign in URL `https://<LMS_HOSTNAME>/login`. Never print a secret.

**State transitions**:

| Item | Before | After |
|---|---|---|
| Authentik items | missing | created, marked |
| Authentik items | present and marked, fields differ | fixed in place |
| Authentik items | present and marked, same | unchanged |
| Authentik app | present, no marker | refused, nothing changes |
| Frappe key | missing, or `client_id` differs | created or fixed, secret written |
| Password form | on (break glass) | off after any setup |
| After `remove` | everything marked present | marked items gone, Frappe users and records kept |

**API surface**:

| Endpoint or command | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `make tools CMD="idp setup [--resync-secret]"` | CLI | config file | one status line per item, exit code | operator on the server | 1 on any named error |
| `idp check` | CLI | config file | PASS, WARN, FAIL lines | same | exit 1 on FAIL |
| `idp remove` | CLI | config file | status lines | same | refuses an unmarked slug |
| `idp password-login on\|off` | CLI | the word `on` or `off` | the new state | same | exit 1 if Frappe is unreachable |
| `idp selftest` | CLI | config file | PASS or FAIL per scenario, cleanup report | same | exit 1 on FAIL |
| Authentik `/api/v3/providers/oauth2/`, `/core/applications/`, `/propertymappings/provider/scope/`, `/flows/instances/`, `/crypto/certificatekeypairs/`, `/admin/settings/`, `/core/users/`, `/core/groups/` | REST | bearer master token | JSON | `AUTHENTIK_API_TOKEN` | 401, 403, 404, 400 with field errors |
| Frappe `/api/resource/Social Login Key`, `/api/resource/System Settings` | REST | token auth of the service user | records | `LMS_API_KEY` and `LMS_API_SECRET` | 401, 403, 409 duplicate |
| `/api/method/frappe.integrations.oauth2_logins.custom/authentik` | GET | `code`, `state` | redirect to `/lms` | Guest, the IDP code is the credential | owned by spec 0006 |

No new guest endpoint is added. The route is the one spec 0006 already overrides.

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Build the redirect URI | `https://<LMS_HOSTNAME>/api/method/frappe.integrations.oauth2_logins.custom/authentik` | `LMS_HOSTNAME` from config, the fixed route from spec 0006, the key name constant `authentik` |
| Build the Authentik URLs | base, authorize, token, userinfo | `https://` plus `AUTHENTIK_HOSTNAME`, and the paths `/application/o/authorize/`, `/application/o/token/`, `/application/o/userinfo/` (checked against the live discovery document in build task 1) |
| Create the provider | `client_id`, `client_secret` | generated by Authentik, read back from the provider |
| Create the provider | flows, signing key, mappings | looked up by slug or name at run time (implicit consent flow, default provider invalidation flow, the self signed key, the four mappings). Their ids are never stored. |
| Create the application | slug, name, launch URL | `AUTHENTIK_APP_SLUG`, the fixed name `Nile Workshop LMS`, `https://<LMS_HOSTNAME>/lms` |
| Mark ownership | marker text | the constant `managed-by: nile-lms idp setup` in `idp.py`, stored in the application `meta_description`. Test objects carry `attributes.managed_by` with the same text. |
| Create the Frappe key | `client_id`, `client_secret` | the provider read back in step 3 |
| Create the Frappe key | scope string | the constant `auth_url_data` = `{"response_type":"code","scope":"openid profile email groups"}`. Needed because the HOL mapping's scope is named `groups`. |
| Create the Frappe key | `provider_name`, `base_url`, `custom_base_url`, `redirect_url`, `sign_ups` | constants in `idp.py`: `provider_name` is `Authentik` (the button label `idp check` looks for), `base_url` is `https://<AUTHENTIK_HOSTNAME>` with `custom_base_url` 1, `redirect_url` is the relative route path, and `sign_ups` is `Deny` if the probe shows `nile_auth` always creates the user before `login_oauth_user` (a second guard), else `Allow`. The probe settles the exact names and forms. |
| Selftest | Authentik login flow, user type, email domain, password | the authentication flow slug found by the probe (a flow with an MFA or captcha stage makes selftest stop with a clear message), user type `internal`, email domain `nile-lms-test.example`, a 32 character random password that meets Authentik's default policy |
| Selftest | Frappe cleanup | delete in this order: the LMS Enrollment rows, the throwaway course, the User's social login rows, then the User. The probe records any link that blocks a User delete, and the fallback is `bench execute`. |
| Selftest | test course title and group name | one fixed text, such as `Nile Test Course 900`, used as both the throwaway course title and the group name (spec 0009), that no real group uses and the `hol-labs-access` policy cannot match (the probe reads that policy and confirms) |
| Set the form state | `disable_user_pass_login`, `login_with_email_link` | the constants set by `setup` and `password-login` |
| Landing page | where to redirect | `/lms`, unless the state's `redirect_to` is a path on this site (`safe_return_path`) |
| Selftest | user name, email, password, course and group name | fixed names with a `nile-lms-test` prefix, the one test course and group text (spec 0009), a password generated in memory and never printed |
| Check the email lock | `default_user_change_email` | Authentik `/admin/settings/` |
| Retry window | 5 minutes, 5 second step | the existing LMS client rule from spec 0001 |

**Key invariants**:
- The script creates, changes, or deletes only items that carry its marker (the application with the marker, the provider that application points to, the Frappe key it created, and the selftest user and group). The one exception is that it reads other items (flows, keys, mappings, settings) and never writes them.
- The `HOL: OpenID groups scope` mapping, the shared flows, and the signing key are read only references.
- Running `setup` twice changes nothing. Running `remove` twice changes nothing.
- No secret is printed, logged, or written to a file. Output goes through the existing masking.
- Setup leaves the password form and email link off.
- `remove` never deletes a Frappe user or any learning record.
- A step that fails leaves a state that the next `setup` completes.

**Security model**:
- Only the operator on the server can run these commands, and they need the master Authentik token and the service user key from the `.env` file. Neither is placed anywhere else.
- Authentik authenticates and `nile_auth` decides, the same split Cloudflare Access uses with the same groups claim. The application has no group binding, so a person in no course group, who is not already a learner, signs in to Authentik and gets the 403 page.
- Turning off the password form and the email link closes two ways around the group check. Without that, a student removed from a group could keep access by a password they reset or by an email link, because roles change only at an Authentik login.
- Email editing by users is already off in Authentik (`default_user_change_email` is false at this time). The script checks it and warns, and never changes it, since it is a global setting.
- Break glass: with Authentik down, the operator runs `idp password-login on`, signs in as `Administrator`, and runs `idp password-login off` after. Setup always ends with it off.
- No regulated data. Names, emails, and group names only. No compliance scope applies.

**Configuration required**: no new `.env` key. Existing keys used: `AUTHENTIK_HOSTNAME`, `AUTHENTIK_API_TOKEN`, `AUTHENTIK_APP_SLUG`, `LMS_HOSTNAME`, `LMS_API_KEY`, `LMS_API_SECRET`. The OIDC client id and secret stay out of the file, as spec 0002 decided. Prerequisite: the `HOL: OpenID groups scope` mapping, the default implicit consent flow, and the self signed key must exist in Authentik. All three exist today.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: `idp setup` on a clean setup, then `idp selftest`, signs in a throwaway student and lands on `/lms` with LMS Student, verifies **AC-1**, **AC-3**, **AC-10**.
- Happy path: run `idp setup` twice, the second run reports `unchanged` for every item and the secret still works, verifies **AC-2**.
- Failure case: edit the provider redirect URI by hand, then `setup` reports `fixed` and the login works again, verifies **AC-2**.
- Failure case: an application with the slug and no marker makes `setup` and `remove` stop and change nothing, verifies **AC-2**, **AC-8**.
- Failure case: rename the HOL mapping in a test double and `setup` stops before it creates anything, verifies **AC-4**.
- Auth and permission: the login page has no form and no email link, a posted password login is refused, the service user key still works, `password-login on` and `off` flip it, verifies **AC-5**.
- Auth and permission: a throwaway user in no course group gets the 403 page and no Frappe user is created, verifies **AC-3**.
- Failure case: Authentik unreachable gives one error naming the URL, and a rerun after a half done setup finishes it, verifies **AC-9**.
- Pure test: `safe_return_path` accepts `/lms/courses/x`, and rejects `//evil.example`, `https://evil.example`, and `/\evil`, verifies **AC-10**.
- Pure test: `diff` of wanted and live state returns nothing when equal and one `Change` per edited field, verifies **AC-2**.
- Integration test: a run of `setup`, `check`, and `selftest` leaves no client secret or token in its output or logs, and the masker knows the secret before anything is logged, verifies **AC-6**.
- Failure case: a selftest interrupted halfway leaves nothing behind after the next run's cleanup, and refuses to start on an unmarked item with a test name, verifies **AC-11**.
- Happy path: `idp check` on a good setup is all PASS (WARN only for known cases) and writes nothing, verifies **AC-7**.
- Happy path: `idp remove` deletes the three marked items, keeps the Frappe user from the selftest login until the selftest cleans it, and a second run changes nothing, verifies **AC-8**.
- Happy path: the selftest passes. The token and userinfo calls inside it are made by the real `backend` container, and the `redirect_uri` it sends is the registered one, verifies **AC-12**.
- Failure case: `password-login off` and setup refuse when no enabled Authentik key exists, verifies **AC-5**.
- Failure case: a `remove` stopped after the key delete is finished by a second run, and no orphan provider remains, verifies **AC-8**, **AC-9**.

## Build plan

Tracer Bullet: one real student sign in as early as possible, then thicken. Everything is proven on the live dev site and the real Authentik.

1. Probe the live Authentik (version 2026.8.3) and Frappe and write the findings in `verify.md`: the exact Authentik field names for the provider and application (redirect URIs as a list of matching mode and URL, `meta_description`), the slugs of the implicit consent flow and the default invalidation flow, the key and mapping names and ids, whether a provider can be created and deleted with the master token, the discovery document URLs, the Frappe Social Login Key record name, field names, button label, and whether the REST API creates it and masks the secret, the System Settings field names, whether `Administrator` can still sign in when the form is off (and how, so the README can say), that the service user token still works then, whether `backend` can reach Authentik, the exact `redirect_uri` Frappe sends, what location Frappe redirects to after login, the authentication flow slug and whether it has an MFA or captcha stage, whether the `hol-labs-access` policy can match the test course group name, which links block a Frappe User delete, and that spec 0006's throwaway key name differs from `authentik`, satisfies **AC-1**, **AC-2**, **AC-5**, **AC-10**, **AC-12**
2. Thin thread: remove the Authentik `extra_hosts` line from the `tools` service (its host gateway mapping hits this host's Traefik, which answers 404 for Authentik, so `tools` must use public DNS; specs 0001 and 0002 are amended to match), update the `deploy/AGENTS.md` gotcha, add `authentik.py`, the pure `wanted_state` in `idp.py`, and `idp setup` that creates the provider, the application, and the Frappe key. Prove it with one real browser style sign in by hand, satisfies **AC-1**, **AC-4**, **AC-6**
3. Make setup safe to rerun: the marker, the pure `diff`, the fix in place, the secret rule and `--resync-secret`, the pre checks (HOL mapping, flows, key), the refusal on an unmarked slug, the retry and error messages, and unit tests on canned responses, satisfies **AC-2**, **AC-4**, **AC-9**
4. Close the bypasses: set the two System Settings in setup, add `idp password-login on|off`, and prove with the live site that the form and email link are gone and the service user still works, satisfies **AC-5**
5. Add `idp check` (the judges are pure and unit tested) and `idp remove` with its marker rule, satisfies **AC-7**, **AC-8**
6. Add the landing tail to `nile_auth.login.custom` with `safe_return_path` and a unit test, the probe showed `backend` needs no `extra_hosts`, so only extend the static compose check to fail if `tools` or `backend` gains a host gateway mapping for Authentik, and bump the `nile_auth` version in `pyproject.toml` and `deploy/versions.env` together (the deploy rule), satisfies **AC-10**, **AC-12**
7. Add `idp selftest` (throwaway user and group, the OIDC login driven with httpx, the no group case, the cleanup), the `integration` test that runs it, and the one manual browser sign in as a `hol-admins` member ticked in `verify.md`. Tick spec 0006's open real sign in task from this result, satisfies **AC-3**, **AC-11**, **AC-12**
8. Update `README.md`: the `idp` commands, the break glass steps, and the prerequisite that the HOL mapping and the default flows must exist. Then regenerate nothing else, since no `.env` key is added, satisfies **AC-5**, **AC-6**

## Consequences

**Positive**:
- A clean setup gets a working Authentik sign in from one command, and a rebuild or a drift is fixed by running it again.
- Nothing can skip the group check: no password, no reset link, no email link.
- The script touches only what it made, so Cloudflare and the other Authentik apps stay safe.
- The selftest makes the done when sentence checkable at any time, and also proves the real container to Authentik path.

**Negative / tradeoffs**:
- The app depends on the shared `HOL: OpenID groups scope` mapping, which other apps and Cloudflare also use. An edit or delete of it by someone else stops every login here. The setup pre check and `idp check` catch it, and the spec 0006 refusal of a missing `groups` claim keeps anyone from being demoted.
- With the form off, a local `Administrator` sign in works only after `idp password-login on`. If Authentik is down, the operator needs shell access to the server.
- Logging out of the LMS leaves the Authentik session open, so on a shared computer the next click on Login signs in as the same person. Ending the Authentik session would also sign people out of Cloudflare Access and other apps.
- The admin sign in is proven by a manual check, not by the selftest.
- The Authentik API field names belong to version 2026.8.3. An Authentik upgrade must re run the probe and `idp check`.
- Frappe links people by email, so a person whose email changes in Authentik gets a second account. The global Authentik setting that stops self edits is only checked, not owned, by this script.

**Neutral**:
- Spec 0006 said the standard `profile` scope returns `groups`. For this Authentik it does not, so the `groups` scope is needed. This spec records the correction.
- `AUTHENTIK_APP_SLUG` is a frozen key (spec 0002), so the slug and the marker cannot change after the first setup.
- Authentik shows the application on a user's Authentik dashboard with the launch URL `/lms`.

## Follow-up

- [ ] Spec 0006 Value sourcing row "groups" says `profile` returns groups. Amend it to name the `groups` scope when feature 6 is built. Its follow ups about the password form, the email lock, and the scope are closed here.
- [ ] Spec 0006 build task 11 (a real Authentik sign in) is closed by build task 7 here, as student and neither by the selftest and as admin by the manual check.
- [ ] Spec 0001 says REST creation of the Social Login Key was unverified and feature 6 proves it. Build task 1 does, and the `bench execute` fallback is used only if the probe shows REST cannot create it.
- [ ] Spec 0002 follow up asked whether feature 6 needs a new key. None is needed. Update that note when `/sync` runs.
- [ ] If sign in latency or a stale Authentik session on shared computers becomes a problem, revisit ending the Authentik session at logout.
- [ ] A scheduled check that disables or demotes a removed admin before their next login is still not built (spec 0006). Revisit if sessions are long.
- [ ] `/sync` should add the new `idp` commands and modules to `tools/AGENTS.md` and `deploy/AGENTS.md` after the build.
