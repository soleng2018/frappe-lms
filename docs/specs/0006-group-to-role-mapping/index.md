# 0006. Map Authentik groups to LMS roles with an override of the OIDC callback

**Date**: 2026-11-03
**Status**: In Progress

## Summary

When someone signs in through Authentik, `nile_auth` reads the list of groups Authentik sends with the login. A member of `hol-admins` becomes an admin. A member of a `NileWorkshopNAdmin` group becomes a student and is put in the batch for that group and in every published course. Anyone else is refused with a plain 403 page. Groups here are testbed assignments that change from course to course, so nothing is ever deleted when a student leaves a group: progress, attempts, and certificates stay. Roles follow the groups at every login. The work is one small override of Frappe's OIDC callback, one pure function that classifies group names, and one new field on User that records the current groups.

## Requirements

**User stories**:
- As a student, I want to sign in with my Authentik account and land in the LMS with every published course ready, so that I can start my lab.
- As a student who gets a new testbed group for a new course, I want my old progress and certificates to stay, so that my whole record is kept.
- As a hol-admin, I want to sign in and get admin rights without anyone editing the LMS by hand, so that I can track students and reset attempts.
- As the operator, I want a user in no workshop group to be refused, and a removed admin to lose admin rights, so that access follows Authentik.
- As the operator, I want a broken Authentik setting to stop logins loudly instead of demoting everyone, so that one fault is easy to find and fix.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: A user whose groups include at least one `NileWorkshopNAdmin` group (and not `hol-admins`) is signed in as a Website User with the LMS Student role. For each matching group they have a Batch Enrollment in the LMS Batch whose `nile_group` equals the group name (the batch is created if missing, with the spec 0004 values). They have an LMS Enrollment in every published course, and every one of their batches carries a Batch Course row for every published course.
- **AC-2**: A member of `hol-admins` has the Moderator, Course Creator, and Desk User roles, which makes Frappe treat them as a System User (the type follows the roles, `nile_auth` never sets it). If the same user is also in one or more workshop groups, they additionally get the LMS Student role and the batch and course enrollments of AC-1. An admin in no workshop group gets no batch and no enrollment.
- **AC-3**: A user whose group list is present but holds no `hol-admins` and no matching workshop group is refused with an HTTP 403 page and no redirect. No User is created for them. An existing user of that kind loses the managed roles (LMS Student, Moderator, Course Creator, Desk User) and keeps everything else, including their `enabled` flag and every record in AC-5.
- **AC-4**: Group names match exactly and with case. The admin group is exactly the site config value `nile_admin_group` (default `hol-admins`). A workshop group is the site config `nile_student_group_prefix`, then a positive whole number with no leading zero, then `nile_student_group_suffix` (defaults give `^NileWorkshop[1-9][0-9]*Admin$`; prefix and suffix are escaped, never used as a pattern). Any other name (`nileworkshop3admin`, `NileWorkshop0Admin`, `NileWorkshop03Admin`, `NileWorkshopAdmin`, `NileWorkshop3Admin2`) is ignored and counts for nothing. If any of the three site config values is missing or empty, the login is refused as a setup fault (AC-7) and nothing changes.
- **AC-5**: Group changes apply at the next login. The managed roles are set to exactly what the groups now say (the user type follows from them), and other roles are left alone. LMS gives every new user LMS Student on insert, so the reconcile runs after that, and an admin in no workshop group ends without it. A group the user has left removes nothing: their Batch Enrollments, LMS Enrollments, Course Progress, Quiz Submissions, and Certificates all stay. The User field `nile_groups` holds exactly the matching groups from this login, one per line. "Matching" includes `hol-admins` when present. Workshop groups sort by their number (group 2 before group 10), and `hol-admins` comes last.
- **AC-6**: Logging in again changes nothing that already exists: no second batch, Batch Enrollment, LMS Enrollment, Batch Course row, or role row. Two first logins at the same moment for the same group leave exactly one batch.
- **AC-7**: If the userinfo has no `groups` list (missing, null, or not a list of text), or a group name setting from AC-4 is missing, the login is refused with a setup fault page, an error is logged, and no User, role, or enrollment changes. Only a list that is present, even an empty one, can change roles.
- **AC-8**: A login that resolves to `Administrator`, to the service user named in site config `nile_service_user`, or to any existing user who holds the System Manager role is refused with the generic page (HTTP 403), and nothing about that user is changed. A login whose existing user already has a social login id for this provider that differs from the userinfo `sub` is refused the same way, so a changed email in Authentik cannot take over another person's record. A userinfo with no email is refused with its own outcome (AC-12).
- **AC-9**: An existing user whose account is disabled stays disabled and signs in nowhere. Nothing from the provisioning steps is kept for them.
- **AC-10**: Provisioning is all or nothing. If any step fails, nothing is kept, the user is not signed in, the error is logged, and a retry page (HTTP 500) is shown. This covers a bad or reused code, an IDP timeout, a deadlock, and a lock wait timeout. A callback whose `state` token is missing or expired is refused (HTTP 417) before the code exchange, with no write and no lock. Nothing else is committed until Frappe has accepted the login. The one thing that escapes a rollback is the queued batch notification job, which build task 5 switches off.
- **AC-11**: A course published after a student's last login reaches them at their next login: an LMS Enrollment for the user and a Batch Course row on each of their batches.
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
| LMS Batch | none | Looked up only by the unique `nile_group` field (spec 0004). |
| LMS Batch Enrollment | rows added, never removed | One per user and matching workshop group. |
| LMS Enrollment | rows added, never removed | One per user and published course. |
| Has Role (on User) | managed roles added and removed | Managed roles: LMS Student, Moderator, Course Creator, Desk User. All other roles are left alone, including the Portal Settings default role Frappe adds on the first social link. |

**Module layout** (in `apps/nile_auth/nile_auth/`):

| Module | Holds | Imports Frappe? |
|---|---|---|
| `groups.py` | `decide(groups, admin_group, prefix, suffix) -> Decision`: pure classification. `Decision` is a frozen record with `kind`, `reason` (`claim` or `settings` for `no_claim`), `workshop_groups` (tuple sorted by number), `matched_groups` (workshop groups plus `hol-admins`, feeds `nile_groups`), `is_admin`, and `desired_roles`. Names are deduplicated, nothing is trimmed, and a list holding any non text item is `no_claim` as a whole | No, so it is testable outside Frappe |
| `login.py` | `custom(code, state)` (the override), `provision(info, decision)`, `refuse(...)`, the response pages. Reads the three group settings from `frappe.conf` | Yes |
| `constants.py` | Existing file. Gains `MANAGED_ROLES`, `USER_GROUPS_FIELD`, the site config key names, and the refusal texts. It holds no group name | No |

`decision.kind` is one of `member`, `no_group`, or `no_claim`. `no_claim` means the `groups` value is absent, null, or not a list of text, or a group setting is empty. `member` means at least one group matched.

**Login flow** (what `custom` does). It is marked `@frappe.whitelist(allow_guest=True)`, takes `code` and `state`, and the whole flow below runs inside one handler that turns any exception into the retry page and an `error` log line:
1. Read the provider name from `frappe.request.path` as Frappe's own `custom` does. If the Social Login Key does not exist, return an empty response as Frappe does. Capture `code`, `state`, and the provider now, because switching user later clears the request data.
2. Peek at the `state` token without consuming it (a cache read). If it is missing or expired, show Frappe's 417 page and stop, before any code exchange, write, or lock (`bad_state`). Frappe's `login_oauth_user` still consumes it later.
3. Read the three group settings and `nile_service_user` from `frappe.conf`. If any is empty, log `setup_fault_settings` and show the setup fault page (HTTP 500). Checked at every login.
4. Call `get_info_via_oauth(provider, code, decoder_compat)` (imported from `frappe.integrations.oauth2_logins`) to get the userinfo. Take the email with Frappe's `get_email`. If it is empty, refuse with `no_email` (HTTP 403).
5. `decide(info.get("groups"), admin_group, prefix, suffix)`. If the kind is `no_claim`, log `setup_fault_claim`, show the setup fault page (HTTP 500), and change nothing (AC-7).
6. Look up the user by lowercased email. Refuse (`refused_protected`, HTTP 403) if it is `Administrator`, equals `nile_service_user`, or holds System Manager. Refuse (`refused_identity`, HTTP 403) if it has a social login id for this provider that differs from the userinfo `sub`. If it exists and is disabled, skip to step 9 (`disabled`, Frappe refuses).
7. If the kind is `no_group`: strip the managed roles from an existing user in one save, commit, log `refused_no_group`, and show the 403 page (AC-3). The state was already checked in step 2.
8. Otherwise, as `Administrator` (via `frappe.set_user`), in one transaction:
   - Create the User if missing: a random password, no welcome email, names from Frappe's `get_first_name` and `get_last_name`.
   - Set the managed roles to exactly `desired_roles` by editing the role rows and saving once, after LMS's own insert hook has run. Do not set `user_type`.
   - Write `nile_groups` from `matched_groups`.
   - For each workshop group, in sorted order: get the LMS Batch with a locking read on `nile_group`, create it if missing (catching a duplicate on `nile_group` or on the name, then re reading with the locking read), then add the missing Batch Course rows for published courses, then add the Batch Enrollment with `confirmation_email_sent` set to 1 if missing.
   - For each published course, in sorted order: add the LMS Enrollment if missing, with `enrollment_from_batch` set to the first batch in sorted order.
9. Restore the Guest user. Do not commit. Call Frappe's `login_oauth_user(info, provider=provider, state=state)`. It consumes `state`, links the social login id, logs the user in, and commits. If it refuses (disabled user), the uncommitted writes are rolled back at the end of the GET request.
10. Any exception, deadlock, or lock wait timeout in steps 1 to 9: roll back, log with `frappe.log_error`, show the retry page, and do not sign in (AC-10).

`desired_roles` is derived, never stored: `Moderator`, `Course Creator`, and `Desk User` if `is_admin`; `LMS Student` if there is at least one matching workshop group. Frappe then derives the user type from the roles: an admin is a System User, anyone else a Website User.

**State transitions** (one user, at each login; "managed" means the four managed roles):

| Before | Groups now | After |
|---|---|---|
| no user | workshop only | Website User, LMS Student, batches, enrollments |
| no user | `hol-admins` | System User (from Desk User), Moderator, Course Creator, no LMS Student |
| no user | neither | refused, no user created |
| student | adds `hol-admins` | admin roles added, LMS Student kept if still in a workshop group |
| admin | `hol-admins` removed, workshop group kept | admin roles removed, so Website User |
| any | no workshop group left | LMS Student removed, enrollments and history kept |
| any | neither | managed roles removed, login refused |

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/method/frappe.integrations.oauth2_logins.custom/<provider>` | GET | `code` (req), `state` (req), both from the IDP redirect | Frappe's redirect to the desk (System User) or the website (Website User), or an error page | Guest. The IDP `code` is the credential. | 417 bad `state` (Frappe's), 403 refused or protected or no email, 500 setup fault, 500 retry page |
| `nile_auth.groups.decide(groups, admin_group, prefix, suffix)` | function | `groups`: any value from the userinfo; the three names from site config | `Decision` | internal | none, it never raises |
| `nile_auth.login.provision(info, decision)` | function | the userinfo dict, a `Decision` | an outcome record (user, roles added and removed, batches created, enrollments created) | runs as Administrator | any DB error propagates so the caller rolls back |

The route is the one Frappe already registers for a Social Login Key, so no new endpoint and no new guest surface is added.

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Read the login | user id | the userinfo `email` (Frappe's `get_email`, which also tries `upn` and `unique_name`), lowercased |
| Read the login | groups | the userinfo `groups` list. Authentik's standard `profile` scope returns it. Feature 6 must request that scope. |
| Classify | admin or workshop membership | `decide`, using site config `nile_admin_group`, `nile_student_group_prefix`, `nile_student_group_suffix`, written by `create-site` from `.env` (spec 0002) |
| Create a user | `first_name`, `last_name` | Frappe's `get_first_name` and `get_last_name` on the userinfo |
| Create a user | password | `frappe.generate_hash()`, never shown, since login is only through the IDP |
| Provision | `user_type` | not set. Frappe derives it from the roles (admin roles include Desk User) |
| Provision | roles | `desired_roles` from the decision, merged with the user's other roles |
| Provision | `nile_groups` | `matched_groups` from the decision, joined with newlines, workshop groups by number then `hol-admins`. Other groups are never stored. |
| Create a batch | `title`, `nile_group` | the group name |
| Create a batch | dates, times, timezone, description, publish flags | spec 0004's table, from `constants.py` |
| Create a batch | `instructors` | the service user, read from site config `nile_service_user`, which `create-site` writes from `LMS_SERVICE_USER` (build task 2). Missing value: setup fault (AC-7). |
| Add Batch Course rows | the courses | every LMS Course with `published` = 1 |
| Add an LMS Enrollment | `member`, `course` | the user and each published course. Batch Enrollment already enrolls the user in the Batch Course rows, so this fill covers courses added to a batch later. `enrollment_from_batch` is the first batch in sorted order. Any other required field is read from the live doctype in build task 1. |
| Add a Batch Enrollment | `confirmation_email_sent` | 1, set before insert so LMS sends no confirmation email |
| Refuse | page title, text, status | constants in `constants.py`: 403 for refused, protected, identity, and no email; 500 for setup fault and retry. Text never names the rule that failed. |
| Log | line content | logger `nile_auth`, email, the outcome word of AC-12, `matched_groups`, counts of rows created or removed |

**Key invariants**:
- The `state` token is checked before the code exchange and before any write. Nothing but the role strip of step 7 is committed before Frappe accepts the login.
- `nile_auth` never deletes a Batch, Batch Enrollment, LMS Enrollment, Course Progress, Quiz Submission, or Certificate. It adds rows, and it changes only the managed roles and `nile_groups`.
- `nile_auth` never changes `enabled`, and never signs in a disabled user.
- `nile_auth` never grants System Manager, so a hol-admin cannot change the Social Login Key or site settings.
- Roles outside the managed four are never added or removed.
- A batch is found only by `nile_group`, with a locking read, because a plain read under MariaDB's REPEATABLE READ cannot see the row another login just committed. On a duplicate key error (on `nile_group` or on the name LMS derives from the title) it rolls back to a savepoint and reads again with the locking read. The loser waits for the winner's whole request, up to the lock wait limit.
- Batches are locked in sorted order, then courses in sorted order, matching LMS's own order, so two logins cannot deadlock. Two first logins by the same new person may collide on the User insert and get the retry page, which is acceptable.
- The batch row is locked while Batch Course rows are added, so two logins cannot add the same course twice.
- A missing or malformed `groups` value never changes anyone's roles.
- A user who is a protected account is refused before any write.

**Security model**:
- The identity is proven by the IDP code exchange. Frappe's own `state` check still guards against a forged callback (AC-10).
- Frappe links an IDP login to a local user by email and ignores a different stored social id. AC-8 closes that: protected accounts and a social id mismatch are refused, so a changed or edited email cannot take over another record. Feature 6 must also stop users editing their own email in Authentik.
- The page for a refused user says only that they are not in a workshop group, or that the account cannot use this login. It does not list group names or reveal which rule refused them.
- A removed user loses the managed roles at their next login attempt. Frappe clears the role cache when roles change, so a session that is already open loses access at that moment (checked live, build task 1).
- No regulated data. Names, emails, and group names only. No compliance scope applies.
- A student can be locked out only by Authentik, never by a bad `groups` value, since only a present list changes roles.

**Configuration required**: no new `.env` key. The three group keys already exist (`AUTHENTIK_ADMIN_GROUP`, `AUTHENTIK_STUDENT_GROUP_PREFIX`, `AUTHENTIK_STUDENT_GROUP_SUFFIX`) and `create-site` already writes them to site config. This spec adds one more site config line, `nile_service_user`, written by `create-site` from the existing `LMS_SERVICE_USER` (already in its environment). Nothing is added to the `backend` environment. The managed roles stay constants (spec 0004).

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: a first login by a `NileWorkshop3Admin` member creates a Website User with LMS Student, the batch, the Batch Enrollment, and an enrollment in every published course, verifies **AC-1**.
- Happy path: a `hol-admins` member becomes a System User with Moderator, Course Creator, and Desk User, with no LMS Student, no batch, and no enrollment, and a member of both groups also gets LMS Student and the enrollments, verifies **AC-2**.
- Pure test: `decide` is given `hol-admins`, `NileWorkshop12Admin`, and the near misses of AC-4, and returns exactly the right kind and sorted groups, verifies **AC-4**.
- Failure case: groups `["staff"]` gives a 403 page and no User. The same email as an existing student loses LMS Student and keeps `enabled`, verifies **AC-3**.
- Failure case: a user moves from `NileWorkshop2Admin` to `NileWorkshop3Admin`. Both batch enrollments exist, `nile_groups` shows only group 3, and their progress and certificate are untouched, verifies **AC-5**.
- Failure case: two logins run at the same moment for a new group and leave one batch, and a repeat login adds nothing, verifies **AC-6**.
- Failure case: userinfo with no `groups` key is refused with the setup page, and an existing admin keeps their roles, verifies **AC-7**.
- Auth and permission: an Authentik user whose email matches `Administrator` is refused and `Administrator` is unchanged, verifies **AC-8**.
- Failure case: a disabled student stays disabled and nothing is kept, verifies **AC-9**.
- Failure case: an error is forced halfway through step 7 and no batch, role, or enrollment remains, verifies **AC-10**. A callback with a wrong `state` leaves nothing behind, verifies **AC-10**.
- Happy path: a course published after the first login appears as an enrollment and a Batch Course row at the next login, verifies **AC-11**.
- Failure case: the log lines for a success, a refusal, and a fault contain the email and outcome and no code or token, verifies **AC-12**.

## Build plan

Tracer Bullet: prove the real route end to end on the live site with one student first, then widen. Feature 6 (IDP login) is not built yet, so the live tests call `provision` directly through `bench execute`, and the route is proven with a throwaway Social Login Key that the test creates and deletes. The full sign in with Authentik is checked when feature 6 lands.

1. Probe the live site and write the findings in `verify.md`: that overriding `custom` routes `/api/method/...custom/<provider>` for a throwaway Social Login Key, that writes left uncommitted in a GET are rolled back, that the admin roles plus Desk User give a System User after save, that LMS's insert hook adds LMS Student to a new user, the live Portal Settings default role, that removing a role clears an open session's access, that `set_user` clears the request data, the required fields of LMS Enrollment and what Batch Enrollment already creates, and the LMS Settings batch notification switch, satisfies **AC-1**, **AC-2**, **AC-5**, **AC-10**
2. Make `create-site.sh` also run `set-config nile_service_user "$LMS_SERVICE_USER"` (rerun safe), satisfies **AC-1**
2a. Add `MANAGED_ROLES`, `USER_GROUPS_FIELD`, the site config key names, and the page texts to `constants.py`, add the pure `groups.decide` (names passed in, not read) with unit tests for every near miss, odd prefix and suffix characters, and the `no_claim` shapes, and make sure `make test` collects them, satisfies **AC-4**, **AC-7**
3. Thin thread: add `login.custom` and the `override_whitelisted_methods` entry, create the User with LMS Student for a workshop member and refuse everyone else, and log in through the throwaway Social Login Key with a fake userinfo, satisfies **AC-1**, **AC-3**
4. Add the `nile_groups` custom field to `fixtures/custom_field.json` and write it at every login, satisfies **AC-5**
5. Add the batch get or create with the locking read and savepoint, the sorted lock order, the Batch Course top up, the Batch Enrollment with `confirmation_email_sent` set, and the LMS Enrollment fill. Check that LMS Settings has batch notifications off (and set it off through `create-site` if not), satisfies **AC-1**, **AC-6**, **AC-11**
6. Add admin and both path handling, the managed role reconcile (one save, after LMS's insert hook), and the role strip on refusal, satisfies **AC-2**, **AC-3**, **AC-5**
7. Add the early `state` peek, the protected account and social id mismatch refusals, the no email refusal, the disabled account pass through, the setup fault pages, the whole flow error handler, and the rollback, satisfies **AC-7**, **AC-8**, **AC-9**, **AC-10**
8. Add the log lines with the fixed outcome words and a test that they hold no secret, satisfies **AC-12**
9. Add an `integration` test in `tools/tests/` that drives `provision` and the route on the live site for every scenario above, including the concurrent first login, satisfies **AC-1** to **AC-11**
10. Update `apps/nile_auth/README.md` with the flow, the managed roles, and the live findings, and bump the `nile_auth` version in `pyproject.toml` and `deploy/versions.env` together (the deploy rule), satisfies **AC-1**
11. After feature 6: sign in with a real Authentik test user in a test group (created and later deleted by the script) as a student, an admin, and a user in neither, and tick the results in `verify.md`, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-7**

## Consequences

**Positive**:
- Access follows Authentik at every login, with no manual role editing.
- A student's record from earlier courses and testbeds is never lost to a group change.
- The decision logic is a pure function, so the most dangerous rules (what counts as a group, what counts as a fault) are tested without a running Frappe.
- A broken Authentik scope stops logins with a clear message and a log line, and does not demote anyone.
- No new guest endpoint and no new secret in the LMS containers.

**Negative / tradeoffs**:
- The override copies a small part of Frappe's own `custom` flow (the path parsing). A Frappe upgrade that changes that function must re check this one. The live probe and the integration test are the guard.
- Roles only change at login. A user removed in Authentik keeps their rights until their next login attempt, which can be as long as the session lasts. Closing that gap needs a scheduled check against Authentik, which is not built.
- Frappe links a login to a user by email. If a person's email changes in Authentik, they get a second Frappe account and their progress splits.
- Because admins in a workshop group also get enrollments, they appear as students in the manager views and the report unless feature 12 filters them out.
- A student's batch list grows with every testbed. The batch list is history, and `nile_groups` is the only record of the current groups.

**Neutral**:
- Where a student lands after login is decided by Frappe and LMS, not by `nile_auth`. Feature 6 checks the landing page.
- Spec 0004 AC-4 describes the same outcome in short form. This spec refines it (admins who are also in a workshop group, and group changes).

## Follow-up

- [ ] Feature 6 must lock email editing for users in Authentik, since Frappe links by email.
- [ ] Feature 6 (IDP login) must request the scope that returns `groups`, use the userinfo endpoint as the Social Login Key API endpoint, and hide the password form for everyone but `Administrator` and the service user. Nothing here works with a real login until it does.
- [ ] Feature 6 may also bind the Authentik application to the two group kinds, so a user in neither never reaches the LMS. This spec still refuses them, so the Authentik rule is optional defence in depth.
- [ ] Spec 0004 AC-4 and its follow up about leaving a group should point to this spec. Update spec 0004 when this feature is built.
- [ ] Feature 12 (manager progress view) must decide whether to show admins who are also students, and should read the current group from `nile_groups`.
- [ ] A scheduled check that disables or demotes a removed admin without waiting for their next login is not built. Revisit if the session length is long.
- [ ] Revisit the email match if Authentik emails can change. Linking by the IDP subject id instead would keep progress through an email change.
- [ ] `apps/nile_auth/` may need its own `pytest` entry so `make test` finds the pure tests. Build task 2 checks this and records the result in `deploy/AGENTS.md` or `tools/AGENTS.md` (`/sync` owns those files).
