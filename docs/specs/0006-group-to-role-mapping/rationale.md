# 0006. Rationale: Map Authentik groups to LMS roles

Companion to [index.md](index.md). This file holds the reasoning and the evidence. `/develop` does not read it.

## Context

> ⚠️ Premise note: This feature assumes the OIDC login of scope feature 6 (a Social Login Key of type Custom that returns a `groups` list), and feature 6 has no spec yet. Spec 0001 chose the mechanism, but nothing yet fixes the scope or the userinfo endpoint. The assumptions are written into the spec as constraints (the `groups` claim, the userinfo endpoint, the `profile` scope) and feature 6 is listed in Follow-up as the owner. The build proves the route with a throwaway Social Login Key, and the real sign in is the last build task.

Members of the existing Authentik groups `NileWorkshopNAdmin` (N is 1, 2, 3 and so on) and `hol-admins` must become LMS students and admins. The groups already exist and the LMS only reads them (requirements.md, Instructions 4). Spec 0004 fixed the outcome for each kind: a student is a Website User with LMS Student, a batch per group, and enrollments. An admin is a System User with Moderator and Course Creator.

What was left open is how the mapping reaches Frappe, and what the edge cases do. Frappe has no built in group to role mapping. Its OIDC callback `login_oauth_user` receives the whole userinfo dict from the IDP, but offers no hook that passes it to custom code, and the `on_login` hook sees only the user id. A user in no group must be refused, and group changes must apply at the next login.

Two facts from the engineer shaped the edge cases. The groups are testbed assignments, not courses: a student who signs up for a course is given a random testbed, which means a group, and for a later course they get another group. So membership is short lived, and the record of earlier courses and certificates must survive it. And an admin may also be a workshop member, for instance to test as a student.

Frappe links a login to a local user by email, and a failed login must leave no half made user behind. A GET request in Frappe rolls back writes it did not commit, which lets the code stage its writes and let Frappe's own login commit them.

## Options considered

### Option 1: Override the OIDC callback method

Replace `frappe.integrations.oauth2_logins.custom` through `override_whitelisted_methods`. The new method fetches the userinfo, decides, prepares the user, then calls Frappe's normal `login_oauth_user`.

**Pros**:
- A documented Frappe hook, so no monkey patching.
- Sees the full userinfo, so no extra network call and no extra secret.
- Hands the actual login, `state` check, and redirect back to Frappe.

**Cons**:
- Copies a few lines of Frappe's `custom` (the provider path parsing), which a Frappe upgrade could change.
- The route with the provider name in the path must be proven on the live site.

### Option 2: Patch `login_oauth_user` at app start

Wrap Frappe's internal function when the app loads.

**Pros**:
- Sees the userinfo and runs for every provider with one change.
- Does not copy the path parsing.

**Cons**:
- Wraps a private function, so a Frappe upgrade can break it without any error.
- Hidden control flow: the behaviour is not visible in `hooks.py`.

### Option 3: `on_login` hook with an Authentik lookup

Use the supported `on_login` hook and ask the Authentik API for the user's groups.

**Pros**:
- Fully supported hook, with no copy of Frappe code.

**Cons**:
- Puts the Authentik master token inside the Frappe containers, against the one secret per purpose rule.
- Adds a network call and a new failure mode to every login.
- The user already exists and has a session when the hook runs, so a refusal needs a logout.

## Decision

Option 1. Frappe offers it as a supported hook, it needs no extra secret, and it keeps the login, the `state` check, and the redirect in Frappe's hands.

## Rationale

Option 1 is the only choice that sees the groups, keeps the Authentik token out of the LMS containers, and uses a supported Frappe extension point. The cost is a short copy of the provider path parsing. That is small, and the integration test fails loudly if a Frappe upgrade changes it. Option 2 has no such test and no visible entry point, which is the usual way a quiet break reaches production. Option 3 reverses the secret rule of spec 0001 and logs the user in before it can refuse them.

The ordering inside the override follows from how Frappe commits. `login_oauth_user` commits only after a successful login and returns without committing when the `state` is bad or the user is disabled. So the writes are staged and left uncommitted until Frappe accepts the login. A forged callback or a disabled user then leaves nothing behind. The one exception is the role strip for a user in no group, which is committed after the code consumes the `state` token itself.

The engineer's answers fix the rest. Groups are testbeds, so nothing is deleted when a student leaves one, and the new `nile_groups` field is the only place that says which groups are current. Every student gets every published course, since a group does not imply a course. Admins who are also workshop members get the student role and enrollments, so they can test as students, and the cost is that the manager views must filter them. A missing `groups` claim is treated as a setup fault, not as "no groups", because the second reading would demote every admin at their next login after one wrong Authentik setting. Protecting `Administrator` and any System Manager is a generalization of the engineer's choice to protect the service user: `nile_auth` never grants System Manager, so holding it marks an account that must not be reachable by email match.

Cross check (second model, 2026-11-03) changed the draft in these ways, all applied: admins get Desk User as a fourth managed role because the user type is derived from role desk access and the LMS roles have none; the `state` token is peeked at the start instead of consumed on the refusal path; batch creation used a locking read first (replaced on 2026-11-03, see the update below); locks are taken in sorted order; the batch confirmation email and queued notification are switched off; the email takeover path is closed with a social id check; the whole flow sits in one error handler; outcome words, statuses, and the `decide` signature are fixed.

Decisions I made without asking the engineer:
- Read the group names from site config, as spec 0002 already decided (`create-site` writes them from `.env`), instead of hardcoding `hol-admins` and `NileWorkshop`. One source of truth. The pure function takes the names as arguments. Runner up: constants in code, rejected because it would duplicate the `.env` keys.
- Add one site config line, `nile_service_user`, for the batch instructors, since the `backend` container has no `LMS_SERVICE_USER` and spec 0002 keeps its environment empty.
- Store only matching groups in `nile_groups`, not every group, so unrelated group names (possible personal data) are not copied into the LMS.
- Record only matching group names, one per line, sorted, so a diff between logins is stable.
- Lock the batch row while adding Batch Course rows, and use a savepoint around batch creation for the duplicate key case. Runner up: a global named lock, rejected as heavier, and because a MariaDB named lock outlives Frappe's commit and so cannot be released at the right moment.
- Refuse with generic wording that does not reveal which rule failed.
- Log with the Frappe logger `nile_auth` and use Error Log for faults. Runner up: a new log table, rejected as unneeded for a dev site.
- Run the writes as `Administrator` and restore the session user afterwards, as spec 0004's live findings require.
- Give the pure function its own module without a Frappe import. Runner up: keep everything in `login.py`, rejected because the group rules are the part that most needs fast tests.

## Evidence: Frappe code read on the running backend (2026-11-03)

- `frappe/utils/oauth.py`: `login_via_oauth2` calls `get_info_via_oauth` and then `login_oauth_user(info, provider, state)`. `login_oauth_user` consumes the `state` token (a single use cache key, 600 second life), takes the email from `get_email`, calls `update_oauth_user`, then `login_manager.login_as(user)`, then `frappe.db.commit()` (commented "because of a GET request"). A disabled user gets a "Not Allowed" page and no commit.
- `update_oauth_user` creates the User as a Website User if missing (unless the Social Login Key denies sign ups) and adds only the Portal Settings default role. There is no group handling anywhere.
- `frappe/integrations/oauth2_logins.py`: `custom(code, state)` reads the provider from `frappe.request.path` (`/api/method/frappe.integrations.oauth2_logins.custom/<provider>`) and calls `login_via_oauth2`.
- `frappe/hooks.py`: `on_login` carries no user info beyond the login manager, and `override_whitelisted_methods` is the documented way to replace a whitelisted method.
- `get_info_via_oauth` reads the userinfo from the provider's `api_endpoint`, so a `groups` claim in the userinfo response reaches the override.

Not read or not proven yet (build task 1): that the override routes with the provider in the path, the GET rollback behaviour on this install, the required fields of LMS Enrollment, and the Authentik `profile` scope content on this Authentik version.

## Update 2026-11-03: how a new batch is found and made

The build ran the spec's batch step on the live site with two real processes logging in at the same moment, and it failed twice in two different ways. The first fix did not remove the second failure, so the decision needed a proper change.

**What the live site showed**:
1. The spec said to take a locking read on `nile_group` first, then insert if the row is missing. A locking read of a row that does not exist takes a gap lock (a lock on the empty space where the row would go). Both logins got that lock, then both tried to insert into it, and MariaDB ended one with a deadlock (error 1213). The loser got the retry page.
2. After reading plainly first and inserting inside a savepoint, the loser still failed. Under the default REPEATABLE READ the loser's transaction has a fixed picture of the data from its first read. After the duplicate key error a locking read can see the winner's row, but LMS's own checks use plain reads, and those cannot. The Batch Enrollment link check said `Could not find Batch`.

**Options for this sub decision**:
- **A. Locking read first (the original spec)**: deadlocks, as shown.
- **B. Plain read, savepoint insert, locking read after a duplicate, at REPEATABLE READ**: removes the deadlock but not the stale picture. Rejected, it failed live.
- **C. B plus READ COMMITTED for the login transaction (chosen)**: at READ COMMITTED each read sees the latest committed data, so the loser sees the winner's batch everywhere, and locking reads take no gap locks. Passed three runs in a row, and the full scenario file.
- **D. A named lock around batch creation**: serialises the logins, but a MariaDB named lock is not released by Frappe's commit, so it needs a release in a place the flow does not have. Rejected.
- **E. Restart the whole login on a duplicate (retry page for the loser)**: simple, but a class of students logging in together at the start of a new testbed would hit it. Rejected as poor for the main use.

**Why C**: it is the smallest change that makes both logins finish, and it removes the cause instead of the symptom. The cost is a session setting that `custom` sets and restores, and a database that allows READ COMMITTED writes (the live site has binary logging off and the format set to MIXED, so it does). The change is made by `SET SESSION TRANSACTION ISOLATION LEVEL`, because plain `SET TRANSACTION` is refused once Frappe has started its transaction, and Frappe starts the next one right after any commit.

Evidence: the integration file `tools/tests/test_group_role_mapping_integration.py`, test `test_two_first_logins_at_once_leave_one_batch`. The same update added the `nile_service_user` finding to the build: the `backend` container has no `LMS_SERVICE_USER`, which the spec already assumed.
