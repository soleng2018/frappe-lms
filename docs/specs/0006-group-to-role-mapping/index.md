# 0006. Map Authentik groups to LMS roles with an override of the OIDC callback

**Date**: 2026-11-03
**Status**: In Progress
**Superseded in part**: by [0009](../0009-course-access-from-groups/index.md). Spec 0009 replaces how a login becomes a student, which course the student gets, the batch, and the two student group settings. This spec still governs admins, protected accounts, disabled users, the state check, all or nothing provisioning, and the log lines.

## Summary

When someone signs in through Authentik, `nile_auth` reads the list of groups Authentik sends with the login. A member of `hol-admins` becomes an admin. A member of a course group (a group named exactly like a course, see spec 0009) becomes a student with that one course. Anyone else is refused with a plain 403 page, unless Frappe already knows them as a learner. Roles follow the groups at every login, and a learner's progress, attempts, and certificates are never deleted. The work is one small override of Frappe's OIDC callback, one pure function that classifies group names, and one new field on User that records the current groups. Spec 0009 replaced the earlier student rule and the batch.

## Requirements

**User stories**:
- As a student, I want to sign in with my Authentik account and land in the LMS with my course ready, so that I can start my lab.
- As a student who books a new course, I want my old progress and certificates to stay, so that my whole record is kept.
- As a hol-admin, I want to sign in and get admin rights without anyone editing the LMS by hand, so that I can track students and reset attempts.
- As the operator, I want a user in no course group to be refused, and a removed admin to lose admin rights, so that access follows Authentik.
- As the operator, I want a broken Authentik setting to stop logins loudly instead of demoting everyone, so that one fault is easy to find and fix.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: Superseded by spec 0009 AC-1. A learner is signed in as a Website User with the LMS Student role and is enrolled in the one course named by their course group.
- **AC-2**: A member of `hol-admins` has the Moderator, Course Creator, and Desk User roles, which makes Frappe treat them as a System User (the type follows the roles, `nile_auth` never sets it). If the same user also has a course group, they additionally get the LMS Student role and the enrollment of spec 0009 AC-1. An admin with no course group gets no enrollment.
- **AC-3**: Superseded by spec 0009 AC-3 and AC-4. A known learner with no course group reaches results mode, and a stranger with no course group is refused with an HTTP 403 page and no redirect, as before.
- **AC-4**: Superseded in part by spec 0009 AC-5. The admin group is exactly the site config value `nile_admin_group` (default `hol-admins`) and names match exactly and with case. If that value is missing or empty, the login is refused as a setup fault (AC-7) and nothing changes.
- **AC-5**: Group changes apply at the next login. The admin roles are set to exactly what the groups now say (the user type follows from them), and other roles are left alone. LMS gives every new user LMS Student on insert, so the reconcile runs after that. Enrollments and the User field `nile_groups` follow spec 0009 AC-1, AC-3, and AC-10. A group the user has left never deletes their Course Progress, Quiz Submissions, or Certificates.
- **AC-6**: Superseded by spec 0009 AC-9. The login no longer creates batches, so the batch race is gone.
- **AC-7**: If the userinfo has no `groups` list (missing, null, or not a list of text), or the admin group setting from AC-4 is missing, the login is refused with a setup fault page, an error is logged, and no User, role, or enrollment changes. Only a list that is present, even an empty one, can change roles.
- **AC-8**: A login that resolves to `Administrator`, to the service user named in site config `nile_service_user`, to the MCP user named in site config `nile_mcp_user` (when set), or to any existing user who holds the System Manager role is refused with the generic page (HTTP 403), and nothing about that user is changed. A login whose existing user already has a social login id for this provider that differs from the userinfo `sub` is refused the same way, so a changed email in Authentik cannot take over another person's record. A userinfo with no email is refused with its own outcome (AC-12).
- **AC-9**: An existing user whose account is disabled stays disabled and signs in nowhere. Nothing from the provisioning steps is kept for them.
- **AC-10**: Provisioning is all or nothing. If any step fails, nothing is kept, the user is not signed in, the error is logged, and a retry page (HTTP 500) is shown. This covers a bad or reused code, an IDP timeout, a deadlock, and a lock wait timeout. A callback whose `state` token is missing or expired is refused (HTTP 417) before the code exchange, with no write and no lock. Nothing else is committed until Frappe has accepted the login. The one thing that escapes a rollback is the queued batch notification job, which build task 5 switches off.
- **AC-11**: Superseded by spec 0009. Courses stay unpublished and a learner has one enrollment, the live course.
- **AC-12**: Every login attempt writes one log line at info level (warning for refusals, error for faults) on the Frappe logger `nile_auth`, with the email (or `none`), the outcome, and the matching groups. The outcome is one of `ok`, `refused_no_group`, `refused_protected`, `refused_identity`, `disabled`, `no_email`, `bad_state`, `setup_fault_claim`, `setup_fault_settings`, `error`. No token, code, or secret appears in the log.

## Decision

**Chosen option**: Option 1: override Frappe's OIDC callback method, prepare the user and enrollments in one transaction, then hand over to Frappe's normal login.

Add `override_whitelisted_methods` in `hooks.py` that replaces `frappe.integrations.oauth2_logins.custom` with `nile_auth.login.custom`. It reads the groups claim from the userinfo, classifies it with a pure function, provisions or refuses, and only then calls Frappe's own `login_oauth_user`.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: no new record types. Spec 0004 already defines the batch, Batch Enrollment, and enrollment records. This spec adds one field.

| Record | Change | Notes |
|---|---|---|
| User | New custom field `nile_groups` (Small Text, read only in the UI, module Nile Auth) | One matching group name per line, sorted, rewritten at every successful login. Empty text for a user with no matching group. Shipped in `fixtures/custom_field.json`. |
| LMS Batch | none | Not used by the login (spec 0009). |
| LMS Batch Enrollment | none | Not written by the login (spec 0009). |
| LMS Enrollment | rows added and removed (spec 0009) | One per learner, for the live course. |
| Has Role (on User) | managed roles added and removed | Managed roles: Moderator, Course Creator, Desk User (admin roles), and LMS Student (added at a live login and never removed, spec 0009). All other roles are left alone, including the Portal Settings default role Frappe adds on the first social link. |

**Module layout** (in `apps/nile_auth/nile_auth/`):

| Module | Holds | Imports Frappe? |
|---|---|---|
| `groups.py` | The pure classification of the groups (`decide`), defined by spec 0009 (Decision rules) | No, so it is testable outside Frappe |
| `login.py` | `custom(code, state)` (the override), `provision(info, decision)`, `refuse(...)`, the response pages. Reads the admin group setting from `frappe.conf` | Yes |
| `constants.py` | Existing file. Gains `MANAGED_ROLES`, `USER_GROUPS_FIELD`, the site config key names, and the refusal texts. It holds no group name | No |

`decision.kind` and its rules are defined by spec 0009 (Decision rules).

**Login flow**: replaced by spec 0009 (Login flow). What this spec still owns, unchanged: the override of Frappe's OIDC callback and its route (`@frappe.whitelist(allow_guest=True)`, `code` and `state`), the early check of the `state` token, the refusal of protected accounts and of a social login id that differs from the userinfo `sub`, the pass through of a disabled user to Frappe's own login, the handover to `login_oauth_user`, and the single handler that turns any exception into the retry page.

**State transitions**: see spec 0009 (State transitions), which replaces the table that was here.

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/method/frappe.integrations.oauth2_logins.custom/<provider>` | GET | `code` (req), `state` (req), both from the IDP redirect | Frappe's redirect to the desk (System User) or the website (Website User), or an error page | Guest. The IDP `code` is the credential. | 417 bad `state` (Frappe's), 403 refused or protected or no email, 500 setup fault, 500 retry page |
| `nile_auth.groups.decide(...)` | function | defined by spec 0009 | `Decision` | internal | none, it never raises |
| `nile_auth.login.provision(info, decision)` | function | the userinfo dict, a `Decision` | an outcome record (user, roles added and removed, enrollments created and removed) | runs as Administrator | any DB error propagates so the caller rolls back |

The route is the one Frappe already registers for a Social Login Key, so no new endpoint and no new guest surface is added.

**Value sourcing**: see spec 0009 (Value sourcing) for the course, enrollment, role, and landing values. Still from this spec: the user id is the userinfo `email` (Frappe's `get_email`, which also tries `upn` and `unique_name`), lowercased; a new user's names come from Frappe's `get_first_name` and `get_last_name` and the password from `frappe.generate_hash()`, never shown; `user_type` is never set, Frappe derives it from the roles; the refusal pages and statuses are constants in `constants.py` (403 for refused, protected, identity, and no email; 500 for setup fault and retry) and their text never names the rule that failed; the log line is written on the logger `nile_auth` with the email, the outcome word, and the matched groups.

**Key invariants**:
- The `state` token is checked before the code exchange and before any write. Nothing but the role strip of step 7 is committed before Frappe accepts the login.
- `nile_auth` never deletes a Batch, Batch Enrollment, Course Progress, Quiz Submission, Assignment Submission, or Certificate (spec 0009 AC-10 lists the one kind of row it does delete).
- `nile_auth` never changes `enabled`, and never signs in a disabled user.
- `nile_auth` never grants System Manager, so a hol-admin cannot change the Social Login Key or site settings.
- Roles outside the managed roles are never added or removed.
- The login creates no batch and takes no batch or course lock (spec 0009); its concurrency rules are in spec 0009 (Key invariants).
- A missing or malformed `groups` value never changes anyone's roles.
- A user who is a protected account is refused before any write.

**Security model**:
- The identity is proven by the IDP code exchange. Frappe's own `state` check still guards against a forged callback (AC-10).
- Frappe links an IDP login to a local user by email and ignores a different stored social id. AC-8 closes that: protected accounts and a social id mismatch are refused, so a changed or edited email cannot take over another record. Feature 6 must also stop users editing their own email in Authentik.
- The page for a refused user says only that they have no course, or that the account cannot use this login. It does not list group names or reveal which rule refused them.
- A removed user loses the managed roles at their next login attempt. Frappe clears the role cache when roles change, so a session that is already open loses access at that moment (checked live, build task 1).
- No regulated data. Names, emails, and group names only. No compliance scope applies.
- A student can be locked out only by Authentik, never by a bad `groups` value, since only a present list changes roles.

**Configuration required**: no new `.env` key. `AUTHENTIK_ADMIN_GROUP` already exists and `create-site` writes it to site config. This spec added one more site config line, `nile_service_user`, written by `create-site` from the existing `LMS_SERVICE_USER` (already in its environment). Nothing is added to the `backend` environment. The managed roles stay constants (spec 0004). The two student group keys this spec once used are retired by spec 0009.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements; the scenarios for AC-1 to AC-6 and AC-11 are replaced by spec 0009):
- Failure case: userinfo with no `groups` key is refused with the setup page, and an existing admin keeps their roles, verifies **AC-7**.
- Auth and permission: an Authentik user whose email matches `Administrator` is refused and `Administrator` is unchanged, verifies **AC-8**.
- Failure case: a disabled user stays disabled and nothing is kept, verifies **AC-9**.
- Failure case: an error is forced halfway and nothing remains, and a callback with a wrong `state` leaves nothing behind, verifies **AC-10**.
- Failure case: the log lines for a success, a refusal, and a fault contain the email and outcome and no code or token, verifies **AC-12**.

## Build plan

Built and ticked on the scope: the live probe, the `nile_service_user` site setting, the pure group check, the callback override, `nile_groups`, enrollments, admin roles, the safety rules, the log lines, the live integration test, and the README. The student rule and the batch parts of that work are replaced by spec 0009, whose Build plan removes them. The real Authentik sign in, the last task here, is covered by spec 0008 and spec 0009.

## Consequences

**Positive**:
- Access follows Authentik at every login, with no manual role editing.
- A student's record from earlier courses and testbeds is never lost to a group change.
- The decision logic is a pure function, so the most dangerous rules (what counts as a group, what counts as a fault) are tested without a running Frappe.
- A broken Authentik scope stops logins with a clear message and a log line, and does not demote anyone.
- No new guest endpoint and no new secret in the LMS containers.

**Negative / tradeoffs**:
- Until spec 0009's build removes it, the login changes the session isolation level for its own transaction and restores it. MariaDB refuses writes at READ COMMITTED when binary logging is on in statement format. The live site has binary logging off and the format set to MIXED, so it is fine (checked 2026-11-03).
- The override copies a small part of Frappe's own `custom` flow (the path parsing). A Frappe upgrade that changes that function must re check this one. The live probe and the integration test are the guard.
- Roles only change at login. A user removed in Authentik keeps their rights until their next login attempt, which can be as long as the session lasts. Closing that gap needs a scheduled check against Authentik, which is not built.
- Frappe links a login to a user by email. If a person's email changes in Authentik, they get a second Frappe account and their progress splits.
- Because admins who also have a course group get an enrollment, they appear as students in the manager views and the report unless feature 12 filters them out.
- `nile_groups` is the only record of a learner's current groups.

**Neutral**:
- Where a student lands after login is decided by Frappe and LMS, not by `nile_auth`. Feature 6 checks the landing page.
- Spec 0004 AC-4 describes the same outcome in short form. Spec 0009 replaces both for students.

## Follow-up

- [ ] Feature 6 must lock email editing for users in Authentik, since Frappe links by email.
- [ ] Feature 6 (IDP login) must request the scope that returns `groups`, use the userinfo endpoint as the Social Login Key API endpoint, and hide the password form for everyone but `Administrator` and the service user. Nothing here works with a real login until it does.
- [ ] Feature 6 may also bind the Authentik application to the two group kinds, so a user in neither never reaches the LMS. This spec still refuses them, so the Authentik rule is optional defence in depth.
- [ ] Spec 0004 AC-4 and its follow up about leaving a group should point to this spec. Update spec 0004 when this feature is built.
- [ ] Feature 12 (manager progress view) must decide whether to show admins who are also students, and should read the current group from `nile_groups`.
- [ ] A scheduled check that disables or demotes a removed admin without waiting for their next login is not built. Revisit if the session length is long.
- [ ] Revisit the email match if Authentik emails can change. Linking by the IDP subject id instead would keep progress through an email change.
- [ ] `apps/nile_auth/` may need its own `pytest` entry so `make test` finds the pure tests. Build task 2 checks this and records the result in `deploy/AGENTS.md` or `tools/AGENTS.md` (`/sync` owns those files).
