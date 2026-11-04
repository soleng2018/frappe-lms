# 0008 rationale. Sign in through Authentik, set up by one script

**Date**: 2026-11-04
**Status**: Proposed

## Context

> ⚠️ Premise note: Spec 0006 assumes Authentik's standard `profile` scope returns the `groups` list. In this Authentik (version 2026.8.3) it does not. Groups come from a custom scope mapping named `HOL: OpenID groups scope`, whose scope name is `groups`, so the app must request the `groups` scope and the provider must carry that mapping. Without both, every login is refused as a setup fault by spec 0006, which is safe but useless. This spec fixes the premise and the build checks it first.

Mode: new FEATURE on the existing stack (Python `tools/`, Docker Compose, Frappe `version-16` with LMS, the `nile_auth` app, Traefik, Cloudflare in front). Scope row 6 says: a script creates the OIDC application in Authentik through its API (only items it creates), configures Frappe through its API, and students and teachers log in only this way. Done when running it on a clean setup lets a student sign in and land in the LMS, and running it twice changes nothing.

What the live Authentik showed (read only, 2026-11-04):
- Four applications exist: `hol` (the reservations app, an OAuth2 provider with no group binding), `hol-labs` (the provider Cloudflare Access uses, with a booking learner policy and no course group binding), and two proxy apps. There is no `nile-lms` application yet.
- Cloudflare gets the `groups` list through `HOL: OpenID groups scope` and checks exact group names itself. Authentik authenticates, the relying party decides. `nile_auth` plays the same role for the LMS.
- Groups: `hol-admins` and the lab access groups the reservation app manages, which the LMS ignores (spec 0009).
- The default implicit consent flow, a default invalidation flow, and a self signed key exist and are used by the other providers.
- `default_user_change_email` is already false, so people cannot edit their own email today.

What the live Frappe showed: the `/login` page of the LMS has a password form, a "Login with Email Link" option, and no social button yet. The callback route answers 200 with no Social Login Key. Two ways around the Authentik group check exist today. An email link login needs no password, and Frappe's Forgot password would let a student set a password. Roles change only at an Authentik login (spec 0006), so a student removed from a group could keep access by either route.

Constraints from earlier specs: scripts touch only items they created (spec 0001, requirements), no secret in git or compose and all settings in one `.env` (spec 0002), the OIDC client id and secret belong to Authentik and Frappe and stay out of the file (spec 0002), Python functional style with the side effects at the edges (AGENTS.md), and the route and the claims `nile_auth` expects (spec 0006).

The cost of not deciding: with no script, the sign in is a manual set of clicks in two systems that is lost on a rebuild, and no student can reach the LMS.

## Options considered

### Option 1: An `idp` command group in `tools`, REST on both sides

A pure function builds the wanted state from the config, the shell reads the live state from the Authentik and Frappe REST APIs and applies the difference. The application carries an ownership marker. Commands: `setup`, `check`, `remove`, `password-login`, `selftest`.

**Pros**:
- Matches how `sync` and `verify` already work: Python, pure functions, tests on canned responses.
- Nothing new to install or operate. Uses the master token and service user that already exist.
- Easy to make idempotent: compare wanted with live, fix the difference.

**Cons**:
- The Authentik API field names are tied to the Authentik version, so an upgrade needs a re check.
- The client secret passes through the tools container, which is accepted since that container already holds the master token.

### Option 2: An Authentik blueprint file plus a small Frappe script

Authentik can apply a YAML blueprint from a folder inside its own container. The Frappe side would still need a script.

**Pros**:
- Blueprints are Authentik's own idempotent mechanism.

**Cons**:
- Needs a file inside the Authentik container, which belongs to another stack on this server and is not ours to mount into.
- The client secret would have to be chosen by us and written to a file, against the rule that Authentik owns it.
- Two mechanisms to maintain instead of one.

### Option 3: Terraform or another infrastructure tool

**Pros**:
- Mature state tracking.

**Cons**:
- A new tool, a new state file to protect, and a new language for a one app setup. Fails the boring technology test.

### Option 4: Manual setup written in the README

**Pros**:
- No code.

**Cons**:
- Breaks the requirement that the IDP is configured by the script, and "run it twice changes nothing" cannot be checked.

### Sub decisions

| Decision | Chosen | Runner up |
|---|---|---|
| Group binding in Authentik | None (same as Cloudflare) | An expression policy that matches the names, which would put the group rule in two places |
| Email edit lock | Check and warn | Change the global setting, which breaks the rule about only touching our own items |
| Password form and email link | Off, with a documented break glass command | Keep the form, which leaves the reset bypass open |
| Groups mapping | Reuse `HOL: OpenID groups scope` (engineer's choice) | Create our own `nile-lms: groups` mapping |
| Consent flow | Default implicit consent | Explicit consent, an extra click for every student |
| Landing page | `/lms` for everyone | Admins to `/app`, or leave it to Frappe |
| Logout | Frappe only | Also end the Authentik session |
| Drift | Fix in place | Report only |
| Proof | Selftest with throwaway user plus one manual admin sign in | Manual only |

## Rationale

Option 1 fits the forces. The tools package already has the pattern, the client, the retry rule, and the masking, so this is new modules and not a new kind of thing. The other options add a second mechanism, a new tool, or a hand step, each with no benefit at one application and one server. Authentik must own the client secret, and only a REST call reads it back without us inventing one.

No binding and the same split as Cloudflare keeps one owner of the group rule, `nile_auth`, so a new course group needs no change in Authentik. The cost is that a person with no course group, who is not already a learner, reaches the 403 page after authenticating, which is fine.

The password form and email link go off because the whole safety of spec 0006 rests on roles changing at each Authentik login. A path that logs in without Authentik quietly breaks that promise. The break glass command keeps the operator able to get in, and setup always closes it so a forgotten open form is fixed by the next run.

The engineer asked to reuse the HOL groups mapping. I would have created our own copy, because an edit to the shared mapping by someone else could stop every login here and in Cloudflare. That choice is valid and costs nothing to build now. It requires the consequence to be managed: the script treats the mapping as a read only reference, `setup` stops before creating anything if it is missing, and `check` proves the userinfo has `groups`. Making our own mapping later is a small change if the shared one proves fragile.

The marker lives in the application `meta_description` because Authentik gives applications a free text field and it needs no new object type. The provider is owned because the owned application points to it. Test objects carry an attribute instead.

The selftest does not put a test account in `hol-admins`, because that group also grants Cloudflare Access, and a throwaway account must not inherit that. The admin path is one manual sign in by a real admin, which is cheap and proves the real group.

## Evidence

Facts read from the live systems on 2026-11-04, kept here so the build probe has a baseline:

- Authentik version `2026.8.3` (latest `2026.8.5`).
- Application `hol-labs`: provider `HOL Labs`, redirect URI `https://soleng2018.cloudflareaccess.com/cdn-cgi/access/callback`, `sub_mode` hashed user id, one binding to the expression policy `hol-labs-access`.
- Application `hol`: provider `Provider for HOL`, two redirect URIs (one regex for a local address, one strict for the reservations host), `sub_mode` user id, no bindings.
- Both OAuth2 providers use the mappings openid, email, profile, access codes valid 1 minute, access tokens 1 hour, refresh tokens 30 days, the self signed key, and per provider issuer mode.
- Scope mapping `HOL: OpenID groups scope` returns `{"groups": [group.name for group in request.user.ak_groups.all()]}` under the scope name `groups`.
- Flows for authorization: default explicit consent, default implicit consent, `hol-authorization`, `hol-lab-authorization`, `nile-authorization`.
- Settings: `default_user_change_email` false, `default_user_change_name` true, `default_user_change_username` false.
- Frappe `/login` at `guide.nile.global`: a password form, "Login with Email Link", no social button. The custom callback with provider `authentik` returns 200 with no key.
