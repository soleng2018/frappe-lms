# Verify: group to role mapping · spec 0006 · updated 2026-11-03
_Steps derived from spec 0006 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual (needs feature 6, the real Authentik sign in)
- [x] Superseded by spec 0009 AC-1: sign in with an Authentik test user in a course group → lands in that one course, enrolled in it only → AC-1 (proved by `idp selftest`, spec 0008)
- [x] Sign in with an Authentik test user in `hol-admins` → opens the Desk, has Moderator, Course Creator, Desk User, no LMS Student → AC-2 Done 2026-11-04 live: lands on `/lms`, roles Moderator, Course Creator, Desk User, System User, no enrollment.
- [x] Sign in with a user in neither group → 403 page, no User created → AC-3 (proved by `idp selftest`, spec 0008)
- [x] Remove the test user from `hol-admins` in Authentik and sign in again → admin rights are gone, no System User → AC-5 Done 2026-11-04 live: refused 403, roles gone, Website User.
- [x] Take the `groups` claim out of the Authentik scope and sign in → setup fault page, no one is demoted → AC-7 Done 2026-11-04 live with a throwaway provider, app, Frappe key and admin user (all removed): HTTP 500 setup fault page, admin roles and `nile_groups` untouched, log `setup_fault_claim`. Note: Authentik's default profile mapping also carries `groups`, so the claim is gone only when the provider has just the openid and email mappings.
- [x] Sign in as a throwaway Authentik user whose email matches an existing Frappe user that has a different social login id → refused 403, the old record is untouched → AC-8 (a new email that matches nobody makes a new user, which AC-8 allows; the live integration test `identity` proves the refusal, and the unit tests for `_refuse_if_protected` lock it)
- [x] Disable the test user in the LMS and sign in → "User is disabled", nothing changed → AC-9 Done 2026-11-04 live: callback shows the disabled page, no session, still disabled, nothing changed.
- [x] With a session already open, remove the group and sign in again in another browser → the first session loses access at once (Value sourcing: roles) → AC-5 Done 2026-11-04 live: the open session got 403 on the Desk API at once.

## Commands
- [x] `make test` → groups unit tests pass (35 cases, every near miss, odd prefix and suffix) → AC-4, AC-7
- [x] `uv run --directory tools pytest -m integration tests/test_group_role_mapping_integration.py` → 19 pass on 2026-11-04 → AC-1 to AC-11
- [x] `curl -s -o /dev/null -w '%{http_code}' -H 'Host: <site>' 'http://127.0.0.1:8000/api/method/frappe.integrations.oauth2_logins.custom/<provider>?code=x&state=bogus'` from the backend container → `417` before any code exchange → AC-10
- [x] `tail sites/<site>/logs/nile_auth.log` after the logins above → one line per login with email, outcome word, and groups, and no code or token → AC-12
- [ ] Superseded by spec 0009 AC-5: vary the case and spelling of a course group name in the Authentik test group → counted for nothing → AC-4
- [ ] Superseded by spec 0009: courses stay unpublished and a learner has one enrollment, the live course → AC-11
- [ ] Superseded by spec 0009 AC-9: two logins of one existing person at the same moment → one enrollment, both finish → AC-6

## Acceptance-criteria coverage
- AC-1 … integration `first`, UI step 1 · AC-2 … `admin`, `admin_both`, UI step 2 · AC-3 … `nogroup_*`, UI step 3 · AC-4 … unit tests, near miss step · AC-5 … `moved`, `after_strip`, UI steps 4 and 8 · AC-6 … `repeat_same`, the concurrent test · AC-7 … `no_claim`, `bad_claim`, UI step 5 · AC-8 … `administrator`, `service`, `system_manager_user`, `identity`, UI step 6 · AC-9 … `disabled`, UI step 7 · AC-10 … route test, `bad_state`, `fault` · AC-11 … `late` · AC-12 … the log step
