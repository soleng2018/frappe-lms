# 0009. Give each learner only the course they booked

**Date**: 2026-11-04
**Status**: In Progress
**Supersedes in part**: [0004](../0004-data-model/index.md), [0005](../0005-content-sync/index.md), [0006](../0006-group-to-role-mapping/index.md). The exact parts are listed in Consequences.

## Summary

Today every learner who signs in is enrolled in every published course. This spec changes that. The reservation app puts a learner in one Authentik group named exactly like the course they booked, and Frappe enrolls them in that course only. When the group goes away, the learner can still sign in (Authentik decides who may), but their lessons close and they land on their profile, where their certificate is. Courses become unpublished so other courses stay hidden, and the login no longer uses batches.

## Requirements

**Terms** (used in every criterion below):
- A **managed course** is an LMS Course that has a `nile_key` (the content sync sets it). A course made by hand in the LMS is never matched, granted, or pruned.
- A **course group** is a group in the userinfo `groups` list whose text equals the title of a managed course exactly: same case, nothing trimmed. The admin group (site config `nile_admin_group`, default `hol-admins`) is never a course group. Every other group is ignored, including the lab access group the reservation app also adds.
- A **known learner** is an existing, enabled user who holds the LMS Student role.
- **Live** means the login has exactly one course group. **Results mode** means a known learner with no course group.

**User stories**:
- As a learner, I want to land in the course I booked and no other, so that I do the right lab and quizzes.
- As a learner whose slot has ended, I want to sign in and still reach my certificate, so that my result is never lost.
- As the operator, I want the reservation app and Authentik to decide who gets which course, so that I never edit roles or enrollments by hand.
- As the operator, I want an unclear case (two courses at once, two courses with one title) to stop the login with a clear message instead of a guess, so that nobody gets a course they did not book.
- As the operator, I want content sync to keep courses hidden and out of batches, so that a content update cannot undo the lock.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: A login with exactly one course group signs in as a Website User with the LMS Student role. The user is created if missing (random password, no welcome email). They have an LMS Enrollment in that course, made directly with no batch (`enrollment_from_batch` empty), and in no other managed course: an enrollment in another managed course is removed. A new enrollment starts with `progress` taken from the learner's existing Course Progress rows (LMS's own `get_course_progress`), so a returning learner who already finished every lesson of that course can still be certified.
- **AC-2**: A member of `hol-admins` has the Moderator, Course Creator, and Desk User roles, which makes Frappe treat them as a System User (the type follows the roles, `nile_auth` never sets it). These roles follow `hol-admins` at every login: added when present, removed when gone. An admin who is also live gets the LMS Student role and the enrollment of AC-1 as well. An admin with no course group gets no enrollment, and a user created for such an admin ends without the LMS Student role that LMS adds on insert.
- **AC-3**: A known learner with no course group signs in, keeps the LMS Student role, and loses every LMS Enrollment in a managed course, so lessons, chapters, and quizzes close to them. Their Course Progress, Quiz Submissions, Assignment Submissions, certificates, Batch Enrollments, and `enabled` flag stay as they were. At a later login with a course group they are enrolled again as in AC-1, and the progress figure stored on the removed enrollment is rebuilt from their Course Progress rows.
- **AC-4**: A login with no course group from someone who is not in `hol-admins` and is not a known learner is refused with an HTTP 403 page and no redirect. No User is created. An existing user of that kind loses the admin roles if they hold them, and keeps everything else, including `enabled`.
- **AC-5**: Matching is exact and keeps case, and the code does the comparison (the database ignores case). For a course titled `Nile Certified Associate`, the groups `staff`, `Sales`, and `nile certified associate` match nothing and change nothing. A group named like the admin group is never a course group, even if a course has that title.
- **AC-6**: A login with two or more different course groups is refused with an HTTP 403 page that says the account is linked to more than one course, whoever the user is (an admin or a known learner included). No User is created, and no role, enrollment, or `nile_groups` value changes. This is decided before the protected account, identity, and disabled checks of AC-8, so it holds for a disabled user too.
- **AC-7**: A login is refused with a setup fault page (HTTP 500), an error log line, and no change at all in these cases: the `groups` value is missing, null, or not a list of text; site config `nile_admin_group` or `nile_service_user` is empty; the one course group equals the title of two or more managed courses. Only a list that is present, even an empty one, can change anything.
- **AC-8**: Spec 0006 AC-8 (a login that resolves to `Administrator`, the service user, the MCP user, or a System Manager, or whose social login id differs from the userinfo `sub`, is refused with HTTP 403 and nothing changes) and AC-9 (a disabled user stays disabled, nothing from provisioning is kept) hold unchanged.
- **AC-9**: Logging in again changes nothing that exists: no second enrollment and no repeated role row. Two logins for the same existing person at the same moment end in the state one login gives, and neither deadlocks or gets the retry page. Two first logins of one new person may collide on the User insert, and one of them gets the retry page with nothing left half done (accepted, and tested). Provisioning stays all or nothing as in spec 0006 AC-10: any failure rolls back everything, shows the retry page (HTTP 500), and signs nobody in. A callback with a missing or expired `state` gets the 417 page before any write.
- **AC-10**: A login changes only these things: it creates the User if missing, sets the admin roles (and adds LMS Student at a live login), writes `nile_groups`, adds the LMS Enrollment of the live course, and removes LMS Enrollments of managed courses as AC-1 and AC-3 say (Frappe writes a Deleted Document row for each removal). It never deletes a User, Course Progress, Quiz Submission, Assignment Submission, certificate, Batch, or Batch Enrollment, and it creates no Batch, Batch Enrollment, or Batch Course row. A login queues no email, notification, or background job. `nile_groups` holds the course group, then `hol-admins` when present, one per line, and is empty text in results mode.
- **AC-11**: After Frappe accepts the login, the redirect goes to `/lms/courses/<course name>` for a live learner who is not an admin, to `/lms/user/<username>` for a learner in results mode who is not an admin, and to `/lms` for everyone else (an admin included, even one in results mode). `<course name>` is the LMS Course `name` (its slug), `<username>` is the User `username` field (URL encoded), and a user with no `username` goes to `/lms`. The login pages of Frappe and the LMS nearly always put a `redirect_to` in the login, so the values `/`, `/me`, `/app`, `/lms`, and `/lms/courses` (with or without a trailing slash) count as absent. Any other safe deep link (spec 0008 AC-10, once built) wins over this default. The redirect is changed only when Frappe's login left a redirect response and the session user is the person who signed in, so a refusal page is never overwritten. The new location is absolute (built with `frappe.utils.get_url`).
- **AC-12**: `sync` creates every course with `published` 0 and sets it back to 0 when a later run finds it changed. It no longer adds the course to any batch. When a run would change a course title, it first prints the old and new title and says the Authentik group name must change too (the dry run and `--check` print the same line). It refuses to create or retitle a course when another LMS Course already has that exact title (compared in code with the case kept, because the REST filter ignores case) or when the title equals the admin group name (`AUTHENTIK_ADMIN_GROUP`), and it names the clash.
- **AC-13**: A learner who is live in course A cannot read course B (its row, chapters, lessons, and quizzes), cannot find it in the catalog, and cannot enroll themselves in it, through the API, by URL, or through an LMS Program that holds it. A live integration test with two courses proves this.
- **AC-14**: The keys `AUTHENTIK_STUDENT_GROUP_PREFIX` and `AUTHENTIK_STUDENT_GROUP_SUFFIX` are gone from the key list, the sample, compose, `create-site`, and the tests. Every command that reads `.env` (`config check`, `make up`, `sync`, and the rest, through the one parser) fails once per retired key still in the file, with a line saying the key is retired and the line should be deleted, not a bare "unknown key". No other key changes.
- **AC-15**: Every login still writes one line on the Frappe logger `nile_auth` (info for `ok`, warning for refusals, error for faults) with the email (or `none`), the outcome, the mode (`live`; `results`, which includes an admin who holds LMS Student; `admin`, an admin with no learner role; or `none`), and the course group (or empty). Two outcome words are new: `refused_two_courses` and `setup_fault_course`. The others from spec 0006 AC-12 stay. No token, code, or secret appears in a line.

## Decision

**Chosen option**: Option 1: one course group, named like the course, is the only signal; courses stay unpublished; the login enrolls directly and removes the enrollment when the group is gone.

`nile_auth` reads the groups from the userinfo as in spec 0006, finds the course group by comparing group names with the titles of managed courses, and keeps the learner's enrollments equal to the one live course (or none). Frappe's own rule "published, enrolled, or instructor" does the hiding, so no new permission code is written.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**: no new record type and no new field.

| Record | Change | Notes |
|---|---|---|
| LMS Course | `published` is 0 for every managed course | `nile_key` (spec 0004) is the managed marker. Sync owns `published`. |
| LMS Enrollment | added for the live course, removed for every other managed course | `enrollment_from_batch` stays empty. Created as `Administrator`, which LMS lets past its unpublished and self learning checks. A new enrollment gets `progress` at insert from LMS's `get_course_progress(course, member)`. |
| User | `nile_groups` (spec 0006) holds the course group and `hol-admins`; the LMS Student role is kept | Empty text in results mode. |
| Has Role (on User) | admin roles follow `hol-admins` exactly; LMS Student is added at a live login and never removed by `nile_auth` | One exception: a user created in this login for an admin in no course group has the LMS Student role LMS adds on insert taken off again. The reconcile touches only the admin roles, in both directions; `MANAGED_ROLES` is retired. |
| LMS Batch, LMS Batch Enrollment, Batch Course | no longer written by the login or by sync | Existing rows stay. The `nile_group` field on LMS Batch is unused (Follow-up). |

**Module layout**:

| Module | Holds | Imports Frappe? |
|---|---|---|
| `apps/nile_auth/nile_auth/groups.py` | `claim_fault(groups, admin_group)` returns `claim`, `settings`, or `None`, pure, and needs no course list. `decide(groups, admin_group, courses, known_learner) -> Decision`, pure, which calls `claim_fault` first. `courses` is a list of `(name, title)` pairs. `landing_path(decision, username) -> str`, pure. `Decision` is a frozen record: `kind` (`live`, `results`, `admin_only`, `no_group`, `two_courses`, `no_claim`, `bad_course`), `reason` (`claim` or `settings` for `no_claim`), `course` (the LMS Course name), `course_group`, `matched_groups` (course group, then admin group), `is_admin`, `desired_roles` | No |
| `apps/nile_auth/nile_auth/login.py` | `custom(code, state)`, `provision(info, decision)`, the refusals and pages. Loses `_ensure_batch`, `_enroll_in_batch`, `_locked_batch`, `_new_batch`. `_reconcile_roles` and the `no_group` strip use `ADMIN_ROLES` only. | Yes |
| `apps/nile_auth/nile_auth/constants.py` | Loses `BATCH_*`, `CONF_STUDENT_*`, and `MANAGED_ROLES`. Gains the two outcome words and the two new page texts. | No |
| `apps/nile_auth/nile_auth/cleanup.py` | `clear_batch_courses(dry_run=True)`: lists, and with `dry_run=False` removes, the Batch Course rows of batches that carry `nile_group`. Run by `bench execute` on the dev site, after the operator reads the list. | Yes |
| `tools/src/nile_tools/plan.py`, `sync.py` | `published` 0, no `AddToBatch`, the title warning, the duplicate title and admin group title refusals | Sync talks to the LMS only through the existing client |
| `tools/src/nile_tools/config.py`, `deploy/compose.yaml`, `deploy/scripts/create-site.sh` | Retire the two keys. A small `RETIRED_KEYS` list, checked inside the one `.env` parser, gives the clear message of AC-14 on every path. | No |

**Decision rules** (`claim_fault` first, then `decide`; every name is compared in code, case kept):
1. `claim_fault`: an empty `admin_group` is `settings`; a `groups` value that is not a list of text is `claim`. `decide` returns `no_claim` with that reason.
2. Course groups = names in `groups` that are not the admin group and equal the title of at least one managed course.
3. Two or more different course groups: `two_courses`. One course group whose text equals two or more titles: `bad_course`.
4. One course group: `live`, with that course.
5. No course group: `results` if `known_learner`, else `admin_only` if the admin group is present, else `no_group`.

`is_admin` is true when the admin group is in `groups`. `desired_roles` holds the three admin roles when `is_admin`, plus LMS Student when `live`. The reconcile adds a missing desired role and removes only admin roles that are not desired. It removes LMS Student from nobody, except a user created in this same login whose kind is `admin_only` (LMS adds it on insert).

**Login flow** (what `custom` does; the same override as spec 0006, still `@frappe.whitelist(allow_guest=True)`, one handler that turns any exception into the retry page and an `error` log line):
1. Read the provider name from `frappe.request.path` as Frappe does, return an empty response if the Social Login Key is missing, and capture `code`, `state`, and the provider. The session isolation level is no longer changed.
2. Peek at the `state` token without consuming it. Missing or expired: Frappe's 417 page, `bad_state`, before any write.
3. Read `nile_admin_group` and `nile_service_user` from site config. Either empty: `setup_fault_settings`, the setup fault page.
4. Call `get_info_via_oauth`, take the email with Frappe's `get_email`. Empty: `no_email`, 403.
5. Run `claim_fault` on the `groups` value. A fault: `setup_fault_claim`, the setup fault page. No lock is held yet.
6. Commit the empty transaction. Then, as the first statement of the new transaction, take a locking read of the User row by lowercased email (it returns nothing for a new user). InnoDB opens its read view at the first plain read, so every later plain read sees what another login committed.
7. Read the managed courses (`name`, `title`) and the user's roles and enabled flag with plain reads. `known_learner` is true when the user exists, is enabled, and holds LMS Student. Call `decide`. Kind `two_courses`: `refused_two_courses`, the 403 page of AC-6, nothing changed. Kind `bad_course`: `setup_fault_course`, the setup fault page, nothing changed. Both come before the checks in step 8.
8. Refuse a protected account or a social login id mismatch exactly as spec 0006 step 6 (AC-8). A disabled user goes to Frappe's own login, which refuses (`disabled`).
9. Act on the kind. `no_group`: strip the admin roles from an existing user, commit, `refused_no_group`, 403 page. Otherwise, as `Administrator` in one transaction: create the User if missing; set the admin roles, add LMS Student for a live login, and write `nile_groups`, in one save after LMS's insert hook has run; read the user's LMS Enrollment rows in managed courses with one plain read; for a live login add the enrollment if it is missing (the insert sets its `progress`); delete every managed enrollment that is not the live course with `frappe.delete_doc("LMS Enrollment", name, ignore_permissions=True)`, which keeps Frappe's link checks on.
10. Restore the Guest user, call Frappe's `login_oauth_user(info, provider=provider, state=state)` (it consumes `state`, links the social login id, signs in, and commits), then change the redirect as AC-11 says.
11. Any exception, deadlock, or lock wait timeout in steps 6 to 10: roll back, `frappe.log_error` with the code and `state` scrubbed, show the retry page, sign nobody in.

**State transitions** (one user, at each login):

| Before | Groups now | After |
|---|---|---|
| no user | one course group | Website User, LMS Student, enrolled in that course, lands on it |
| no user | `hol-admins` only | System User, admin roles, no LMS Student, no enrollment |
| no user | neither | refused, no user created |
| known learner, enrolled in A | course group B | enrolled in B only, A removed |
| known learner, enrolled in A | no course group | results mode: A removed, lands on profile |
| known learner | two course groups | refused, nothing changes |
| admin | `hol-admins` removed | admin roles removed; a known learner stays one |
| any user | course group of a course with a duplicate title | setup fault, nothing changes |

**API surface**: one route, the one Frappe already registers for a Social Login Key, which spec 0006 overrides. No new endpoint and no new guest surface.

| Endpoint or command | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/method/frappe.integrations.oauth2_logins.custom/<provider>` | GET | `code`, `state` from the IDP redirect | redirect to the landing path, or an error page | Guest, the IDP code is the credential | 417 bad state, 403 refused or two courses, 500 setup fault or retry |
| `nile_auth.groups.decide(...)`, `landing_path(...)` | function | see Module layout | `Decision`, a path | internal | never raise |
| `make tools CMD="sync [--check]"` | CLI | `content/` | status lines, exit code | operator | refuses a duplicate title |
| `make tools CMD="config check"` | CLI | `.env` | PASS or FAIL lines | operator | retired key lines |

**Value sourcing**:

| Action | Value produced or displayed | Source |
|---|---|---|
| Read the login | groups | the userinfo `groups` list (spec 0008 requests the `groups` scope) |
| Classify | admin group name | site config `nile_admin_group`, written by `create-site` from `AUTHENTIK_ADMIN_GROUP` |
| Match | managed courses | `frappe.get_all("LMS Course", filters={"nile_key": ["is", "set"]}, fields=["name", "title"])`, read after the user lock, compared in code |
| Match | known learner | the existing User is enabled and holds the LMS Student role |
| Enroll | `member`, `course` | the user, and the `name` of the live course |
| Enroll | `progress` of the new enrollment | LMS's `get_course_progress(course, member)` (the probe confirms it counts only completed lessons of the current outline) |
| Prune | which enrollments to remove | LMS Enrollment rows of this user, read once, whose course is a managed course other than the live one |
| Land | the path | `/lms/courses/<LMS Course name>`, `/lms/user/<User username>` (URL encoded), or `/lms` (AC-11), made absolute with `frappe.utils.get_url` |
| Land | which `redirect_to` values count as absent | the fixed list in AC-11 |
| Log | mode, course group | `decide` result: `live`, `results`, `admin` (kind `admin_only`), or `none` |
| Refuse two courses | page title, text, status | constant in `constants.py`: 403, plain words that the account is linked to more than one course, no group names |
| Refuse duplicate title | page | the existing setup fault constant (500) |
| Sync title warning | old and new title | the live course title and `content/course.yaml` |
| Sync title refusals | admin group name | `AUTHENTIK_ADMIN_GROUP` from the config file |
| Dev site cleanup | which batches | those with `nile_group` set |
| Retired key line | key names | the `RETIRED_KEYS` list in `config.py` |

**Key invariants**:
- Frappe's rule for reading a course is "published, or enrolled, or instructor" (LMS v2.68.0). Every managed course is unpublished, so an enrollment is the only way a learner reaches a course. Nothing in `nile_auth` adds a permission rule.
- The course group is the only signal for the course. No other group is ever read for access, including the lab access group.
- Only managed courses are granted or pruned. Enrollments in other courses are left alone.
- The only lock `nile_auth` takes is a locking read of the existing User row, as the first statement after the commit in step 6. It serializes two logins of the same person, and every plain read after it sees what the other login committed. LMS takes the course row lock itself when it inserts an enrollment. No course row is locked for reads or deletes.
- The state token is checked before the code exchange and before any write. Nothing but the empty commit of step 6 and the role strip of step 9 is committed before Frappe accepts the login.
- A missing or malformed `groups` value never changes anyone's roles or enrollments. A refusal for two courses never changes anything.
- `nile_auth` never sets `enabled`, never signs in a disabled user, never grants System Manager, and never deletes the records AC-10 lists.
- A result visible to the learner after the slot (certificate, quiz attempts) lives in rows `nile_auth` never deletes. LMS lets a learner read their own certificate and their own submissions without an enrollment.

**Security model**:
- Authentik authenticates and the groups list names the course. A person with an Authentik account and no course group gets the 403 page unless Frappe already knows them as a learner. Revoking a learner is an Authentik action: deactivate the user, or remove the course group to drop them to results mode. The Authentik application has no group binding (spec 0008), so stopping one person's LMS sign in without stopping their other apps needs a binding, which is a Follow-up.
- A course title is now an access key. Only the owner and the reservation app's marked path (see the contract below) create course groups, and the admin group is never matched. A title equal to any other group in a user's claim would admit that group's members, so sync refuses a title equal to the admin group, and the contract below refuses a course group name that already exists in Authentik. A hol-admin can create or rename LMS courses and so change what a group grants, which is the trust an admin already has.
- Roles change only at login. A session open when the slot ends keeps its lessons until it expires or the person signs in again. Reservations ends the Authentik sessions, not the Frappe ones.
- Frappe links a login to a user by email, as in spec 0006. AC-8 closes takeover through a changed email.
- No regulated data. Names, emails, group names, course progress. No compliance scope applies.

**Contract for other repositories** (nothing here is built in this repo):
- *Reservations*: when an admin creates a course, create one Authentik group whose name is exactly the course title, with its own marker attribute, and refuse any name that already exists as an Authentik group, including the admin group and every testbed group. Add the learner to it while they should have the full course (recommended: the booking slot) and remove them when not. Guarantee at most one course group per learner at any time. Never rename a course group on its own. This needs its own spec there, and relaxes that repo's rule that the app never creates a group.
- *Authentik*: the LMS application requests the `groups` scope and uses the existing `HOL: OpenID groups scope` mapping (spec 0008). No new claim.
- *nile-idp*: the `Nile: memberOf` mapping sends every group of a user in the SAML assertion, so learners will now send course titles with spaces to the Nile Portal. Check that Nile ignores them, or limit the mapping to groups marked `hol_testbed_group`.

**Configuration required**: none new. Two keys are retired (AC-14). Site config loses `nile_student_group_prefix` and `nile_student_group_suffix` from `create-site`; sites already made keep the two stale lines, which nothing reads.

**Critical test scenarios** (each maps to an acceptance criterion):
- Happy path: first login with course group `Course A` creates a Website User with LMS Student, enrolled in A only, lands on `/lms/courses/<A>`, verifies **AC-1**, **AC-10**, **AC-11**.
- Happy path: a returning learner who finished every lesson of A is enrolled again and the new enrollment starts at 100 percent, so a certificate can be issued, verifies **AC-1**, **AC-3**.
- Happy path: `hol-admins` only becomes a System User with the admin roles and no LMS Student and no enrollment; admin plus a live course also gets the enrollment, verifies **AC-2**.
- Happy path: a learner enrolled in A signs in with no course group, loses the enrollment in A, keeps the role, progress, and certificate, and lands on `/lms/user/<username>`, verifies **AC-3**, **AC-11**.
- Failure case: groups `["staff"]` give a 403 page and no user; an existing non learner loses admin roles and keeps `enabled`, verifies **AC-4**.
- Pure test: `claim_fault` and `decide` with `Nile Certified Associate`, `nile certified associate`, `Sales`, the admin group named like a course title, and odd characters, verifies **AC-5**, **AC-7**.
- Failure case: groups naming two different courses give the two courses page, even for an admin, a known learner, and a disabled user, and change nothing, verifies **AC-6**.
- Failure case: no `groups` key, an empty `nile_admin_group`, and one group equal to two course titles each give the setup fault page and change nothing, verifies **AC-7**.
- Auth and permission: `Administrator`, the service user, and a social id mismatch are refused; a disabled user stays disabled, verifies **AC-8**.
- Failure case: two real processes log in as the same existing user at the same moment, with real commits, and leave one enrollment and no error; two first logins of one new person leave nothing half done; a repeat login adds nothing; an error forced halfway leaves nothing; a bad `state` gets 417, verifies **AC-9**.
- Failure case: a login leaves batches, Batch Enrollments, and Batch Course rows unchanged, queues no job, and deletes no progress, submission, or certificate (only enrollments, with their Deleted Document rows), verifies **AC-10**.
- Failure case: a `redirect_to` of `/lms` is treated as absent, a real deep link wins, and a refused or disabled login keeps its own page, verifies **AC-11**.
- Happy path: `sync` creates the course unpublished, sets it back after a hand edit, adds it to no batch, prints the title warning, refuses a duplicate title (case kept) and a title equal to the admin group, verifies **AC-12**.
- Auth and permission: a learner live in A gets nothing for course B from the list, detail, lesson, and quiz APIs, cannot insert an enrollment in B, and cannot reach B through an LMS Program, verifies **AC-13**.
- Failure case: every command that reads `.env` names each retired key as retired, verifies **AC-14**.
- Happy path: log lines for ok, refusal, and fault hold email, outcome, mode, and course group and no secret; an admin who holds LMS Student and has no course group logs mode `results` and lands on `/lms`, verifies **AC-15**, **AC-11**.

## Build plan

Tracer Bullet: prove one real learner end to end on the live dev site first, then widen. The order below is the order to build in.

1. Probe the live site and write the findings in `verify.md`: that an enrolled learner reads, lists, and completes an unpublished course (course detail, lesson, quiz, certificate); that a learner who is not enrolled is denied the same reads and cannot enroll themselves, also through an LMS Program; that `Administrator` can insert an enrollment with no batch and delete one, which doctypes link to LMS Enrollment, what `on_trash` does, and that Course Progress, submissions, and the certificate stay; that an enrollment insert or delete queues no email, notification, or job (and how to suppress one that does); how `get_course_progress` counts for a returning learner; that a learner with no enrollment reads their own certificate and profile; whether LMS fills the User `username`; the field names Frappe uses for the redirect after `login_oauth_user`, and which `redirect_to` values the login pages send; the default course tab of a learner with one unpublished course; the Frappe session length for a website user; whether LMS Student comes from anywhere besides the insert hook (the Portal Settings default role); and that Frappe v16 starts the next transaction without a consistent snapshot, so the locking read of step 6 is what opens the read view, satisfies **AC-1**, **AC-3**, **AC-9**, **AC-10**, **AC-11**, **AC-13**
2. Add `claim_fault`, `decide`, and `landing_path` as pure functions with unit tests for every rule and near miss, and drop the old student group pattern, satisfies **AC-5**, **AC-6**, **AC-7**, **AC-11**
3. Thin thread: rework `login.provision` and the login order of steps 1 to 9 for the live path (user lock first, create the user, add the one enrollment directly with its progress, no batch) and refuse everyone else, satisfies **AC-1**, **AC-4**, **AC-7**
4. Results mode and pruning: delete the other managed enrollments, keep LMS Student, write `nile_groups`, reconcile the admin roles only (retire `MANAGED_ROLES`), satisfies **AC-2**, **AC-3**, **AC-10**
5. Safety: the two courses page and `bad_course` ahead of the protected checks, the whole flow error handler, the log fields and the two new outcome words, satisfies **AC-6**, **AC-7**, **AC-8**, **AC-9**, **AC-15**
6. Landing: change the redirect after `login_oauth_user` as AC-11 says, satisfies **AC-11**
7. Content sync: `published` 0, remove `AddToBatch` and its tests, the title warning, the duplicate title and admin group title refusals, satisfies **AC-12**
8. Retire the two config keys everywhere (key list, `RETIRED_KEYS` inside the `.env` parser, sample, compose, `create-site`, tests), satisfies **AC-14**
9. Integration tests on the live site with two courses, the concurrent logins, the isolation test, the returning learner, and the no queued job check, satisfies **AC-1** to **AC-13**
10. Remove the batch code and the READ COMMITTED setting from `login.py` and the batch parts of the old tests, only after the two process test of task 9 passes without that setting (if it fails, keep the setting and drop only the batch code), satisfies **AC-9**, **AC-10**
11. Add `cleanup.clear_batch_courses`, update `README.md` (prerequisites and secrets first), `apps/nile_auth/README.md`, and `tools/AGENTS.md` and `deploy/AGENTS.md` if `/sync` has not, bump the `nile_auth` version in `pyproject.toml` and `deploy/versions.env` together, and sweep: no file outside git history and `docs/reviews/` may still name the old student group model (the group name pattern, `nile_group` lookups, batches made at login) or read the two retired keys, satisfies **AC-10**, **AC-14**

## Migration plan

**Strategy**: no migration needed for code, one coordinated step for the dev site. No feature flag: nothing but test users exists on the dev site, and no real Authentik login has happened yet (feature 6 is not built).

**Phases** (this is the order of work across the three repositories):
1. Accept this spec. Agree the contract with the reservation app (its own spec) and settle spec 0008's landing rule, since both depend on the decisions here.
2. This repository: build tasks 1 to 11 on branch `feat/course-groups`, one commit per milestone.
3. Deploy to the dev site: delete the two retired lines from `.env` (`config check` names them), bump the version, `make build` and `make up`, then run `sync` (sets the existing course unpublished) and, with confirmation after reading its list, `bench execute nile_auth.cleanup.clear_batch_courses`. Treat enrollments made by the old login as test data.
4. The reservation app builds course groups (its own spec and build). It can start after step 1, and it must be live before any real learner signs in.
5. Spec 0008 (the Authentik sign in) is built after step 2, because its selftest and landing rule depend on this spec. The `Nile: memberOf` check in nile-idp runs in parallel and must finish before the first real learner.
6. The first real end to end sign in: Authentik, the course group from reservations, and this login together.

**Rollback**: revert the commits and redeploy the previous `nile_auth` version, and put the two retired lines back in `.env` (the old key list requires them and the old `create-site` writes them). The old sync sets `published` back to 1, and the old login recreates enrollments only for members of the old student groups. This is safe only before the reservation app ships course groups: the old login strips LMS Student from anyone holding only a course group, which would erase the known learner marker for a later roll forward.

**Risks**: learners are locked out until reservations ships; a title edit silently stops matching (AC-12 warns); a Frappe session outlives the slot; a link or hook may block deleting an enrollment (the probe checks; if it does, this spec returns to `/architect`); the locking read of step 6 must really be the first statement of its transaction (the probe and the two process test check).

## Consequences

**Positive**:
- A learner reaches the one course they booked and nothing else, enforced by LMS itself, with no custom permission code.
- A learner keeps their certificate and can sign in after the slot, and Authentik stays the one place that revokes them.
- Less code: the batch creation, its locking, and (if the test passes) the isolation level change all go.
- An unclear case (two courses, a duplicate title) stops the login with a plain message instead of granting the wrong course.

**Negative / tradeoffs**:
- Courses are no longer listed in the LMS catalog, and the LMS has no public course pages. Only enrolled learners and admins see a course.
- A course title is an access key. A rename without renaming the Authentik group silently stops access for new learners.
- Roles and enrollments change only at login, so an open Frappe session keeps its lessons until it ends.
- A learner in results mode sees only the certificate natively. A list of quiz scores would be new work (not built).
- The progress figure stored on a removed enrollment is rebuilt from the Course Progress rows when the learner is enrolled again (AC-1), which adds a small calculation at enrollment.
- The reservation app needs a new capability (it creates groups), which breaks a rule that repo wrote down.
- Batches are no longer used, so the LMS has no roster per testbed. That lives in the reservation app's bookings.

**Neutral**:
- Parts of earlier specs that this one replaces:
  - Spec 0004: AC-4 (the login enrolls in a batch and every published course), the LMS Batch row of the data model and its Batch Course rows, and `published` 1 in the course creation values.
  - Spec 0005: the phrase "created published" in AC-1, and AC-8 (every batch gets the course).
  - Spec 0006: AC-1 (the old student rule, batch, every published course), the old student group parts of AC-2, AC-3 (a known learner is no longer refused), AC-4 (the old group name pattern and its two settings), AC-5 (old student groups in `nile_groups`, and "nothing is removed"), AC-6 (the batch race), AC-11 (every published course), the READ COMMITTED decision, and the Value sourcing rows about batches and the two settings. Its AC-7, AC-8, AC-9, AC-10, and AC-12 stand, with AC-12 extended by AC-15 here.
- Spec 0008 (written by another session, not built) needs amending; see Follow-up.
- The `LMS Batch` custom field `nile_group` stays in the fixtures and is unused.

## Follow-up

- [ ] Spec 0008 was reworded for course groups (its selftest now makes a throwaway course and a group named like it, in AC-3, AC-11, and the Value sourcing rows). Still open there: its AC-10 landing rule must defer to AC-11 here for learners, and its follow up about spec 0006 should name the `groups` scope.
- [ ] Write the reservations spec in that repo: a Course concept, the group per course with its own marker, the group guard, the membership timing, the at most one course group rule, and the changed `group-writes-scan`.
- [ ] Check the `Nile: memberOf` mapping in nile-idp against course titles with spaces, or limit it to marked testbed groups.
- [ ] Decide whether to bind the Authentik LMS application to a group, so one person's LMS access can be revoked without deactivating them everywhere (spec 0008 has no binding).
- [ ] If the probe finds that a link or a hook blocks deleting an LMS Enrollment, return to `/architect` before building tasks 4 and 5.
- [ ] Shorten the Frappe session for learners, if the probe shows it is long, so lessons close soon after the slot.
- [ ] A results page that lists quiz scores per course is not built. Add a feature if the certificate alone is not enough.
- [ ] Feature 12 (manager progress view) groups by course and reads the current course from `nile_groups`.
- [ ] If a title rename bites, add a fixed access name field on LMS Course (like `nile_group` on LMS Batch) and compare to it.
- [ ] Retire the unused `nile_group` field and the old test batches once nothing depends on them.
- [ ] `/sync` should update `tools/AGENTS.md` and `deploy/AGENTS.md` (the retired keys, `RETIRED_KEYS`, sync no longer touches batches).
