# Verify: group to role mapping · spec 0006 · updated 2026-11-03
_Steps derived from spec 0006 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual (needs feature 6, the real Authentik sign in)
- [ ] Sign in with an Authentik test user in a `NileWorkshopNAdmin` test group → lands in the LMS as a student with every published course enrolled → AC-1
- [ ] Sign in with an Authentik test user in `hol-admins` → opens the Desk, has Moderator, Course Creator, Desk User, no LMS Student → AC-2
- [ ] Sign in with a user in neither group → 403 page, no User created → AC-3
- [ ] Remove the test user from `hol-admins` in Authentik and sign in again → admin rights are gone, no System User → AC-5
- [ ] Take the `groups` claim out of the Authentik scope and sign in → setup fault page, no one is demoted → AC-7
- [ ] Change the test user's email in Authentik and sign in → refused, the old record is untouched → AC-8
- [ ] Disable the test user in the LMS and sign in → "User is disabled", nothing changed → AC-9
- [ ] With a session already open, remove the group and sign in again in another browser → the first session loses access at once (Value sourcing: roles) → AC-5

## Commands
- [x] `make test` → groups unit tests pass (35 cases, every near miss, odd prefix and suffix) → AC-4, AC-7
- [x] `uv run --directory tools pytest -m integration tests/test_group_role_mapping_integration.py` → 14 pass → AC-1 to AC-11
- [ ] `curl -s -o /dev/null -w '%{http_code}' -H 'Host: <site>' 'http://127.0.0.1:8000/api/method/frappe.integrations.oauth2_logins.custom/<provider>?code=x&state=bogus'` from the backend container → `417` before any code exchange → AC-10
- [ ] `tail sites/<site>/logs/nile_auth.log` after the logins above → one line per login with email, outcome word, and groups, and no code or token → AC-12
- [ ] Vary the group names (`NileWorkshop03Admin`, `nileworkshop3admin`, `NileWorkshop3Admin2`) in the Authentik test group → counted for nothing (Value sourcing: Classify) → AC-4
- [ ] Publish a new course and sign in again as the student → new LMS Enrollment and a Batch Course row on each current batch (Value sourcing: Add Batch Course rows) → AC-11
- [ ] Two first logins for a brand new group at the same moment → one batch, both finish (Value sourcing: transaction isolation level) → AC-6

## Acceptance-criteria coverage
- AC-1 … integration `first`, UI step 1 · AC-2 … `admin`, `admin_both`, UI step 2 · AC-3 … `nogroup_*`, UI step 3 · AC-4 … unit tests, near miss step · AC-5 … `moved`, `after_strip`, UI steps 4 and 8 · AC-6 … `repeat_same`, the concurrent test · AC-7 … `no_claim`, `bad_claim`, UI step 5 · AC-8 … `administrator`, `service`, `system_manager_user`, `identity`, UI step 6 · AC-9 … `disabled`, UI step 7 · AC-10 … route test, `bad_state`, `fault` · AC-11 … `late` · AC-12 … the log step
