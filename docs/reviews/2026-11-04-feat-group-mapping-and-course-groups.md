# Review, group mapping (feature 7, spec 0006) and course access from groups (feature 17, spec 0009), 2026-11-04

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 22 files read closely (range `484b96e^..main`, limited to `apps/nile_auth`, `deploy`, `tools/src/nile_tools`, `content` and their tests; spec 0007 and 0008 code only where it touches the login)
**Verdict**: Changes requested

## Summary
The login override (`login.py`) and the pure classifier (`groups.py`) carry out spec 0009 closely: the state peek comes before the code exchange, the claim and two-course checks come before the protected checks, only admin roles are reconciled, enrollments are added and pruned for managed courses only, and the redirect is changed only after Frappe has accepted the login. Sync now keeps courses unpublished, warns on a retitle, and refuses title clashes. The retired keys give a clear line. 625 unit tests pass. Two things should be fixed before real learners arrive. First, the locking read on a User row that does not exist yet takes an InnoDB gap lock at REPEATABLE READ (confirmed live). So two *different* new learners signing in at the same moment can deadlock, and one of them gets the retry page. That is the normal case at the start of a workshop, and no test covers it. Second, AC-13 (course isolation) is only partly proven: the Program path, the catalog and list APIs, and quizzes are untested, and spec 0009 has no `verify.md` with the probe findings.

## Major

### 🟠 First logins of two different new learners can deadlock on the User gap lock, `apps/nile_auth/nile_auth/login.py:113`
**Problem**: `frappe.db.get_value("User", email, "name", for_update=True)` runs `SELECT ... WHERE name = %s FOR UPDATE`. For a user that does not exist yet, this takes a gap lock. The live database runs at `REPEATABLE-READ` (checked with `select @@transaction_isolation`), and the READ COMMITTED setting was removed in this change. Gap locks are compatible with each other. So learners A and B, whose emails fall between the same two existing User names, can both get the lock. Then A's `user.insert` waits on B's gap lock and B's insert waits on A's, and InnoDB kills one as a deadlock. The lock is held from step 6 until `login_oauth_user` commits, which covers the whole provisioning, so the window is not tiny. The rationale (and AC-9) only considers two logins of the *same* new person. The two-process test (`test_two_logins_of_one_person_at_once`) uses a single email, so it cannot see this.
**Why it matters**: At the start of a workshop many learners sign in for the first time within seconds. Some of them will get "Something went wrong" (HTTP 500) and an `error` log line plus an Error Log entry. Nothing is left half done and a retry works, so this is not data loss. But it is the first thing a learner sees, and it goes against the spec's own invariant that the lock "serializes two logins of the same person" and nothing else.
**Suggested fix**: Take the locking read only when the user already exists. For a new user, rely on the primary key on insert (the accepted same-person race). Or serialize on a per-email named lock (`GET_LOCK`) instead of a row or gap lock. Or retry the whole provisioning once in-process on a deadlock error. Then add a two-process test with two *different* new emails that sort next to each other, and record the result in the spec.

### 🟠 AC-13 course isolation is only partly proven, `tools/tests/test_group_role_mapping_integration.py:78`
**Problem**: AC-13 requires a live test with two courses showing that a learner live in A cannot read B (row, chapters, lessons, quizzes), cannot find it in the catalog, and cannot enroll themselves, "through the API, by URL, or through an LMS Program that holds it". The test checks only `can_access_course`, `can_access_lesson`, `chapter_has_permission` and a direct `LMS Enrollment` insert. The docstring and `apps/nile_auth/README.md:123` both say Programs are not covered. The catalog and list APIs (for example `lms.lms.utils.get_courses` or `/api/resource/LMS Course`), the quiz read, and a REST read of the course row are not exercised either. Build task 1 asked for the probe findings (Programs, the Portal Settings default role, side effects of an enrollment insert) to be written to `docs/specs/0009-course-access-from-groups/verify.md`. That file does not exist.
**Why it matters**: This is the security promise of the feature: a course title is an access key, and LMS's "published or enrolled or instructor" rule is the only gate. If LMS lets a Program member enroll in or read a course in that Program, a learner reaches a course they did not book. Nothing would catch this.
**Suggested fix**: Extend the scenario script to (a) list courses as the learner through the LMS catalog API and through `frappe.get_list("LMS Course")`, (b) read a quiz of B, and (c) create a throwaway LMS Program holding B with the learner as a member, then try a self enrollment through the Program path. Record the probe results in `verify.md`.

## Minor

### 🟡 A state that expires between the peek and the consume is logged as `ok`, `apps/nile_auth/nile_auth/login.py:145`
**Problem**: `_login` peeks at the state and later `login_oauth_user` consumes it. If the state is gone by then (it expired in the gap, or a double click or replay consumed it first), Frappe answers 417 and returns without signing anyone in. `_land` then does nothing, but `_login` still returns `OUTCOME_OK`. The provisioning is not committed (the request is a GET, so `sync_database` rolls it back), so the data is fine.
**Why it matters**: The log line says `ok` for a login that showed the 417 page, which misleads anyone reading `nile_auth.log` (AC-15).
**Suggested fix**: After `login_oauth_user`, return `OUTCOME_OK` only if `frappe.local.response.get("type") == "redirect"` and `frappe.session.user == email`. Otherwise return `bad_state`.

### 🟡 Enrollments of an `admin_only` user are not pruned, `apps/nile_auth/nile_auth/login.py:218`
**Problem**: Step 9 of the login flow says to "delete every managed enrollment that is not the live course" for every kind that is provisioned. The code prunes only for `live` and `results`. An admin who does not hold LMS Student but has a managed enrollment (made by hand, or left over from the old batch login on the dev site) keeps it forever.
**Why it matters**: This is a small gap from the spec, and admins can read every course anyway. It still leaves enrollments that AC-2 says an admin with no course group should not have, and they show up in feature 12's progress view.
**Suggested fix**: Prune for `KIND_ADMIN_ONLY` too, or say in the spec that it is left alone.

### 🟡 README still lists the retired keys as defaults you may change, `README.md:45`
**Problem**: The "Defaults you may change" line names `AUTHENTIK_STUDENT_GROUP_PREFIX` and `AUTHENTIK_STUDENT_GROUP_SUFFIX`. Line 149 of the same file says to delete them. Build task 11 asked for a sweep so that no file names the old student group model.
**Why it matters**: An operator who follows line 45 adds a key that makes every command fail with "retired". AGENTS.md requires the README to be current.
**Suggested fix**: Drop the two keys from line 45.

### 🟡 The "no job queued" check cannot see jobs queued after commit, `tools/tests/live_scripts/group_role_scenarios.pyscript:11`
**Problem**: The scenario run replaces `frappe.db.commit` with a no-op and rolls back at the end. Frappe pushes `enqueue(..., enqueue_after_commit=True)` jobs and realtime events only on commit, so `jobs_queued == 0` passes whether or not an enrollment insert or delete queues such a job. The concurrent script does commit, but it does not count jobs.
**Why it matters**: AC-10 ("a login queues no email, notification, or background job") is weakly proven for the after-commit path, which is how LMS notifications are usually sent.
**Suggested fix**: Count the RQ queues before and after in `group_role_concurrent.pyscript`, which really commits. Or count `frappe.local._realtime_log` and the after-commit queue (`frappe.db.after_commit`) before the rollback.

## Nits
- ⚪ `apps/nile_auth/nile_auth/login.py:227`, `_managed_courses` reads the managed courses a second time after `_login` already read them at line 115. The spec says to read them once after the lock. Pass the names in from the first read.
- ⚪ `apps/nile_auth/nile_auth/login.py:146`, if `_land` raises after `login_oauth_user` has committed and set the session, the handler shows the retry page to a person who is in fact signed in. `get_url` and a `get_value` make this unlikely. Wrapping `_land` on its own (log, keep Frappe's redirect) would be safer.
- ⚪ `apps/nile_auth/nile_auth/login.py:294`, `logger.setLevel` runs on every login. Set it once, or configure it at import.
- ⚪ `tools/tests/test_group_role_mapping_integration.py:181`, the AC-15 test checks only `mode=live` and `mode=results`. It does not check `mode=admin`, `mode=none`, or that refusals log at warning and faults at error.
- ⚪ `tools/tests/live_scripts/group_role_scenarios.pyscript:260`, the `Administrator` case logs in with the email `"Administrator"`, which matches by name. A real Authentik account carrying Administrator's email (`admin@example.com`) does not match by name, falls through to a User insert, and gets the retry page (500, from the unique email) instead of the 403 protected page. It is still safe, but the outcome is `error`, not `refused_protected`.

## Strengths
- `groups.py` is a clean pure core. `claim_fault`, `decide` and `landing_path` never raise, the frozen `Decision` carries everything the log and the landing need, and the unit tests cover every rule including near misses, the admin group named like a course, and unsafe deep links.
- The order of checks in `_login` follows the spec exactly (state, then settings, then email, then claim, then lock, then the two-course and bad-course checks, then protected, disabled, and no group). The live scenario script proves "changes nothing" for each refusal by comparing state snapshots.
- `_reconcile_roles` touches only admin roles in both directions, and drops LMS Student only for a user created in the same login as `admin_only`. This exactly matches the subtle rule in AC-2.
- Sync's `title_clash` compares titles in code with case kept, as the spec warns the REST filter would not. The retitle note now prints before the update in both a real run and `--check`.
- `RETIRED_KEYS` sits inside the one parser, so every command names the retired line, and it is unit tested.

## Test coverage
625 unit tests pass (`pytest -m "not integration"`). `groups.py`, sync's `published` 0 rule, the retitle note, the title refusals, and the retired-key parsing are well covered. The 18 live integration tests cover AC-1 to AC-12 and AC-15 in a rolled-back run, plus a two-process test of one person's concurrent logins with real commits. Gaps: concurrent first logins of *different* new users (Major above), the AC-13 Program, catalog and quiz paths (Major above), after-commit jobs (Minor), and the log levels and the `admin` and `none` modes (nit). The real `login_oauth_user` (social link, Portal Settings default role) runs only in the real Authentik sign-ins, not in the scripted run, which is acceptable given the live sign-in evidence.
