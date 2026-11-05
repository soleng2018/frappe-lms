# 0013. Show managers each learner's progress in two Desk reports

**Date**: 2026-11-05
**Status**: In Progress

## Summary

Admins in `hol-admins` get two new reports in the Desk (the LMS admin area they already use): **Learner Progress**, one line per learner and course with a status, and **Quiz Scores**, one line per learner and quiz. Both are read only, ship inside the `nile_auth` app, and need no new records, no new settings, and no setup step. Students cannot open them. The status and quiz rules live in one small plain Python module, so the monthly report (feature 13) reuses them and its numbers match this view.

## Context

> Spec 0009 removes a learner's enrollment when their course group goes away, and spec 0010 keeps certificates private until an admin publishes them. Both change what "current" means for a report.

Admins already have Desk access (spec 0006 gives `hol-admins` the Moderator, Course Creator, and Desk User roles), but the Desk has no screen that answers "who has not started, who is stuck, who is certified". The raw lists exist (Enrollment, Course Progress, Quiz Submission, Certificate), but none of them joins learner, course, lessons done, quiz results, and certificate.

Three facts shape the design:

- The enrollment is removed when the slot ends (0009), so a report built on Enrollment would lose the learners who matter most for certification. Progress must come from Course Progress rows, and the lesson total from the course outline (Chapter Reference then Lesson Reference).
- The quiz pass check uses the quiz's current `passing_percentage`, not the copy on the submission row (0010). The report has to use the same comparison, or an admin sees a different answer from the student.
- Volume is small (a lab program, up to a few hundred rows), so one run of a fixed set of queries is enough. No paging, no background job, no stored totals.

Feature 13 (monthly report) must show numbers that match this view, so the rules must exist once.

## Requirements

**User stories**:
- As a hol-admin, I want one list of every learner and course with a clear status, so that I can see who has not started, who is in progress, and who is certified.
- As a hol-admin, I want to see lessons done, quiz results, last activity, and certificate state per learner, so that I know who is behind or stuck.
- As a hol-admin, I want to open the attempts of a locked quiz in one click, so that I can reset them.
- As a student, I want other learners' progress to stay private, so that only managers see it.
- As the operator, I want the reports installed by the normal migrate with no manual step, so that a rebuild brings them back.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: A user with the Moderator or System Manager role can run both reports. A user with neither (an LMS Student, any Website User, or a Guest) gets a permission error (HTTP 403) from both, receives no rows, and the reports are not listed for them. `hol-admins` members pass because spec 0006 gives them Moderator. Both Report records set `ref_doctype` to `LMS Course` and carry exactly the roles Moderator and System Manager (a report with no roles is open to every Desk user). A Custom Role set in the Desk would override these roles; that is accepted.
- **AC-2**: Learner Progress has one row per (User, managed course). A **managed course** is an LMS Course with a `nile_key` (spec 0009). A row exists when the User has an LMS Enrollment, any LMS Course Progress row, or an LMS Certificate in that course. A learner whose slot has ended (no enrollment) but who has progress or a certificate still has their row, with Enrolled = No. A disabled user keeps their row, with Enabled = No. These never appear: courses with no `nile_key`, the `Administrator` user, the users named in site config `nile_service_user` and `nile_mcp_user`, and users with no enrollment, progress, or certificate. An admin who also takes a course does appear.
- **AC-3**: Status is the first rule that matches: **Certified** when at least one LMS Certificate exists for the User and course (LMS allows one per batch plus one with no batch), published or not; else **Ready for certificate** when lessons done equals lessons total and total is above 0; else **In progress** when lessons done is 1 or more; else **Not started**. A course with 0 lessons is Not started.
- **AC-4**: **Lessons total** is the number of distinct lessons in the course's current outline (a lesson referenced twice counts once). **Lessons done** is the number of those lessons for which the User has an LMS Course Progress row with status Complete. A completed lesson that is no longer in the outline is ignored, so progress never goes over 100. **Progress %** is done divided by total, rounded down to a whole number, so 100 only appears when every lesson is done. A course with 0 lessons shows Progress % 0.
- **AC-5**: Learner Progress shows **Quizzes passed of total** and **Average best score**. Quizzes total counts the LMS Quizzes whose `lesson` is in the course's outline (`LMS Quiz.course` is ignored). A quiz is passed when any attempt has `percentage` at or above the quiz's current `passing_percentage`. Best score is the highest `percentage` over a User's attempts on a quiz. Average best score is the mean of best scores over the counted quizzes the User attempted, rounded half up to a whole number (72.5 gives 73), and empty when none were attempted. Every rounding in the reports is half up.
- **AC-6**: Learner Progress shows **Last activity**, the latest of `modified` over the User's Course Progress rows for the course (any status) and `creation` over the User's Quiz Submissions on counted quizzes (matched on `quiz`, not on `LMS Quiz Submission.course`), empty when none. The certificate columns are certificate (link), issue date, and published (Yes or No). When several certificates exist, they show the one with the newest `issue_date` (ties broken by `creation`), and empty when there is none.
- **AC-7**: Learner Progress offers these filters: Course (managed courses only), Status (the four values), Learner (matches full name or email, any part, any case), and Currently enrolled only (default off). Status and State have a blank option meaning all, and Status is applied in Python after it is computed. A Course value that is not a managed course returns an empty table (AC-11); only a Status or State value outside the allowed list raises a validation error. In the JS the Course dropdown lists only courses with a `nile_key`. Filters combine with AND. Rows are ordered by course title, then learner name.
- **AC-8**: Quiz Scores has one row per (User, quiz) for every User and course that has a row in Learner Progress and every quiz counted by AC-5. Columns: learner, course, quiz (link to the LMS Quiz, shown by title), best score (empty when not attempted), attempts used, attempts allowed (the quiz's `max_attempts`; 0 or empty means unlimited, shown as "Unlimited"), pass mark, state, last attempt. State is the first match: **Passed** (any attempt at or above the pass mark); else **Locked** (attempts allowed is above 0 and attempts used is at or above it, so an unlimited quiz is never Locked); else **In progress** (1 or more attempts); else **Not attempted**. Filters: Course, Learner, State. Rows are ordered by course, learner, then quiz position in the outline.
- **AC-9**: The learner cell links to the User, the certificate cell links to the LMS Certificate, and in Quiz Scores a Locked row links to the LMS Quiz Submission list filtered to that learner and quiz, so an admin can reach the reset action (spec 0004 AC-6). The reports never write data.
- **AC-10**: The reports ship in `nile_auth` as standard Script Reports and exist after `bench migrate` with no manual step. They run a fixed number of queries whatever the number of learners (no query per row), and return in a few seconds for a few hundred rows. The fetch layer is passed to the pure assembly as a function, so a unit test counts its calls.
- **AC-11**: If there are no managed courses, or no row matches the filters, a report returns an empty table with no error.

## Options considered

### Option 1: Two Script Reports in `nile_auth` (Desk)

Standard Frappe Script Reports (Python query code plus a small JS file for filters and links), shipped in the app, calling pure functions for the rules.

**Pros**:
- Admins already work in the Desk; filters, sorting, column choice, and export come built in, and so does the role check.
- Smallest code; the rules sit in testable pure functions.

**Cons**:
- Plain look, no custom layout or charts.
- Frappe's own export depends on the report's document type permissions (a live check, see Follow-up).

### Option 2: SQL Query Report (no Python)

One saved SQL query per report.

**Pros**:
- No code to ship beyond the query.

**Cons**:
- The status, outline, and best score rules become one long SQL statement that cannot be unit tested or shared with feature 13.

### Option 3: Custom Desk page

A hand built Desk page with its own layout and API.

**Pros**:
- Full control of layout and drill down.

**Cons**:
- More JS and API code to build and keep, and it loses free filters, sorting, and export.

### Option 4: Page in the LMS frontend

A new screen in the LMS student app.

**Pros**:
- Same look as the student side.

**Cons**:
- The LMS frontend is a separate Vue app we do not own, so every upgrade risks the change. Heaviest option.

## Decision

**Chosen option**: Option 1: Two Script Reports in `nile_auth` (Desk)

Ship **Learner Progress** and **Quiz Scores** as standard Script Reports in `nile_auth`, with every rule in a pure module that feature 13 reuses.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`)

## Rationale

Admins are already System Users in the Desk (0006), so a Script Report costs the least and gives filters, sorting, column choice, and export for free. The data volume (a few hundred rows) removes any reason for a custom page, paging, or stored totals, and `AGENTS.md` favors boring, small solutions. A SQL Query Report was rejected because the rules (outline total, best score per quiz, pass mark comparison) are the part most likely to be wrong, and they need unit tests and reuse by feature 13.

Computing everything at read time from Course Progress, the outline, Quiz Submission, and Certificate is the only option that survives spec 0009, which deletes the enrollment and with it any progress stored on it. It also means the report cannot go stale after a content sync changes the outline.

## Feature design

**Data model sketch**: no new records and no new fields. The reports read these LMS records, as the server (permissions are checked once on the report, not per record), and only for managed courses:

| Record | Fields read | Used for |
|---|---|---|
| LMS Course | `name`, `title`, `nile_key` | managed courses, course filter, ordering |
| Chapter Reference (child of LMS Course) and Lesson Reference (child of Course Chapter) | `chapter`, `lesson`, `idx` | the outline: lessons total, quiz position |
| LMS Enrollment | `member`, `course` | Enrolled flag, row existence |
| LMS Course Progress | `member`, `course`, `lesson`, `status`, `modified` | lessons done, last activity, row existence |
| LMS Quiz | `name`, `title`, `course`, `lesson`, `max_attempts`, `passing_percentage` | quizzes of a course, pass mark, attempts allowed |
| LMS Quiz Submission | `member`, `quiz`, `percentage`, `creation` | attempts used, best score, last attempt |
| LMS Certificate | `name`, `member`, `course`, `issue_date`, `published` | Certified, certificate columns |
| User | `name`, `full_name`, `enabled` | learner name, email, Enabled |

Row keys: Learner Progress is (User, managed course). Quiz Scores is (User, quiz).

**Columns** (fieldname, label, type):
- Learner Progress: `learner` (Learner, Link to User, shows the email), `full_name` (Name, Data), `course` (Course, Data, the title), `course_name` (hidden Link to LMS Course), `status` (Status, Data), `enrolled` (Enrolled, Data Yes or No), `enabled` (Enabled, Data Yes or No), `lessons_done` and `lessons_total` (Int), `progress` (Progress %, Percent), `quizzes_passed` and `quizzes_total` (Int), `avg_best` (Average best score, Percent), `last_activity` (Datetime), `certificate` (Link to LMS Certificate), `issue_date` (Date), `published` (Data Yes or No).
- Quiz Scores: `learner` (Link to User), `full_name` (Data), `course` (Data), `quiz` (Link to LMS Quiz, shown by title), `best_score` (Percent), `attempts_used` (Int), `attempts_allowed` (Data, a number or Unlimited), `pass_mark` (Percent), `state` (Data), `last_attempt` (Datetime).

**State transitions**: none stored. Status and state are derived each run, by the rules in AC-3 and AC-8.

**API surface**: the standard Frappe report call, no custom endpoint.

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/method/frappe.desk.query_report.run` | POST | `report_name` (Learner Progress or Quiz Scores), `filters` JSON | columns and rows | Moderator or System Manager session | 403 for any other user; validation error for a Status or State value outside the list |
| Report code `execute(filters)` in each report | called by the above | `course`, `status` or `state`, `learner`, `enrolled_only` | `(columns, rows)` | same | `frappe.only_for` raises PermissionError again as a second check |

Filter inputs: `course` is a Link to LMS Course, `status` is a Select (Not started, In progress, Ready for certificate, Certified), `state` is a Select (Not attempted, In progress, Passed, Locked), `learner` is free text, `enrolled_only` is a Check.

**Value sourcing** (every value each report produces or displays, and where it comes from):

| Action | Value produced / displayed | Source |
|---|---|---|
| Learner Progress | Learner name, email | User `full_name`, `name` (the User name is the email) |
| Learner Progress | Enabled | User `enabled` |
| Learner Progress | Enrolled | an LMS Enrollment exists for (member, course) |
| Learner Progress | Course | LMS Course `title` |
| Learner Progress | Lessons total | count of lessons reached through Chapter Reference then Lesson Reference of the course |
| Learner Progress | Lessons done | Course Progress rows with status Complete and a lesson in that outline, per (member, course) |
| Learner Progress | Progress % | derived from lessons done and total (AC-4) |
| Learner Progress | Status | derived by the pure function from certificate exists, done, total |
| Learner Progress | Quizzes passed, total, average best score | derived from LMS Quiz (course, lesson in outline, `passing_percentage`) and Quiz Submission `percentage` (AC-5) |
| Learner Progress | Last activity | max of Course Progress `modified` and Quiz Submission `creation`; server timestamps, shown as stored (site time zone), no conversion |
| Learner Progress | Certificate, issue date, published | LMS Certificate `name`, `issue_date`, `published` |
| Learner Progress | Excluded users | `Administrator`, site config `nile_service_user`, site config `nile_mcp_user` (read with `frappe.conf.get`; a missing key excludes nothing) |
| Learner Progress | Managed course test | LMS Course `nile_key` is set |
| Quiz Scores | Best score, attempts used, last attempt | Quiz Submission `percentage` (max), row count, `creation` (max), per (member, quiz) |
| Quiz Scores | Attempts allowed, pass mark | LMS Quiz `max_attempts`, `passing_percentage` (the current values, spec 0010) |
| Quiz Scores | Quiz order | position of the quiz's lesson in the outline (chapter `idx`, then lesson `idx`) |
| Quiz Scores | Locked link | `/app/lms-quiz-submission?member=<user>&quiz=<quiz>` built in the report JS from the row |
| Learner Progress | Ready for certificate while Enrolled = No | shown as is; LMS refuses a certificate request without an enrollment (0010), so an admin must re-enroll the learner or create the certificate in the Desk |
| Quiz Scores | Locked link needs the quiz and learner | row values `quiz` (LMS Quiz name) and `learner` (User name), both URL encoded in the JS |
| Both | Report record | `ref_doctype` `LMS Course`, `is_standard` Yes, `report_type` Script Report, module Nile Auth, JSON in `apps/nile_auth/nile_auth/nile_auth/report/<name>/` with `modified` bumped on every change (migrate skips an unchanged `modified`) |
| Both | Who may run | roles Moderator and System Manager on the Report record, and `frappe.only_for` in the code |

**Key invariants**:
- The reports never insert, update, or delete a record.
- Status, quiz state, progress, and averages are computed only by the functions in `nile_auth/progress.py`, which import nothing from Frappe. The Script Reports only fetch plain lists, call the assembly, and format links. The unit tests for `progress.py` live in `tools/tests` (the `pythonpath` already reaches `apps/nile_auth`, as for `groups.py`). Feature 13 calls the same functions. Row assembly (the union that makes a row exist, the exclusions, the outline, and the rules) is in `progress.py` too and takes plain lists, so feature 13 cannot diverge.
- Progress % is at most 100, and 100 only when done equals total.
- The pass comparison is `percentage >= passing_percentage` using the quiz's current value, the same as LMS.
- Query count does not grow with the number of learners.

**Security model**:
- Access: the Report records list the roles Moderator and System Manager, and the code calls `frappe.only_for(("Moderator", "System Manager"))` as a second check. LMS Student and Website Users get a permission error, and the Desk is closed to them anyway (0004).
- The queries read as the server, so a Moderator needs no extra record permissions. The report returns student names, emails, and scores, so access must stay limited to these two roles. Personal data of learners is shown, but only to admins who can already read the same records in the Desk. No regulated data class beyond that is involved.
- No audit log: nothing is changed.

**Configuration required**: none new. Reads the existing site config keys `nile_service_user` and `nile_mcp_user` (spec 0006).

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: a learner with some lessons done, two quizzes (one passed at 85, one attempted at 60), and no certificate shows In progress, quizzes passed 1 of 2, average best 73 (rounded), the right last activity, verifies **AC-3**, **AC-4**, **AC-5**, **AC-6**.
- Status order: one learner each in Not started, In progress, Ready for certificate, and Certified (published and unpublished) shows the right status, and a 0 lesson course shows Not started, verifies **AC-3**.
- Slot ended: a learner with no enrollment but progress and a certificate still has a row with Enrolled = No; the Currently enrolled only filter hides them, verifies **AC-2**, **AC-7**.
- Outline change: a completed lesson removed from the outline is not counted, and Progress % never goes over 100, verifies **AC-4**.
- Quiz states: Passed, Locked (3 attempts, none passing), In progress, and Not attempted rows, using the quiz's current pass mark after it is raised, verifies **AC-8**.
- Exclusions: Administrator, the service user, the MCP user, an unmanaged course, and a user with no records never appear, verifies **AC-2**.
- Links: a Locked row links to the Quiz Submission list filtered to that learner and quiz, verifies **AC-9**.
- Auth: a learner session calling either report gets 403 and no rows; a member of `hol-admins` gets rows, verifies **AC-1**.
- Empty: no managed course, or a filter that matches nothing, returns an empty table without error, verifies **AC-11**.
- Roles: both Report records carry exactly Moderator and System Manager and `ref_doctype` `LMS Course`, verifies **AC-1**.
- Edge rules: an unlimited quiz (`max_attempts` 0) is never Locked, two certificates give Certified with the newest shown, and a 0 lesson course shows progress 0, verifies **AC-3**, **AC-4**, **AC-8**.
- Install: after `bench migrate` on a clean site both reports exist, verifies **AC-10**.
- Query count: a unit test with an injected fetcher shows the same number of fetch calls for 5 and for 200 learners, verifies **AC-10**.

## Build plan

Build approach: Tracer Bullet (from `AGENTS.md`). The first task is one thin report through every layer (rules, query, access, migrate install); the rest thicken it.

1. Thin thread and live probes. Add `nile_auth/progress.py` with the pure status function and its unit tests. Add the Learner Progress Script Report (JSON, Python, JS) with learner, course, lessons done and total, and status, from Course Progress, the outline, and Certificate only, with the role check. Run `bench migrate` on the live site and open it as a `hol-admins` member and as a student. Probe and record: that the Report syncs from the app on migrate and that a Website User is refused. Satisfies **AC-1**, **AC-3**, **AC-4**, **AC-10**.
2. Complete Learner Progress. Add enrolled and enabled flags, exclusions, the managed course filter, the quiz columns, last activity, the certificate columns, the four filters, ordering, and the empty case. The pure functions for best score, average, and quiz state come with unit tests. Satisfies **AC-2**, **AC-3**, **AC-5**, **AC-6**, **AC-7**, **AC-11**.
3. Quiz Scores report. Add it with its filters, the four states, outline ordering, and the link to the Quiz Submission list for Locked rows (and the learner and certificate links in both reports). Satisfies **AC-8**, **AC-9**, **AC-11**.
4. Integration tests (marker `integration`) against the live site: the scenarios above, the access check, and the query count check. Satisfies **AC-1** to **AC-11**.
5. README: add the admin steps (where to open the two reports, what each status means, how a Locked quiz leads to a reset), and note the new reports in the `nile_auth` README. Satisfies **AC-9**, **AC-10**.

## Consequences

**Positive**:
- Admins answer "who is not started, in progress, or certified" in one screen, and keep certified learners visible after the slot ends.
- The rules sit in one pure module, so feature 13 matches this view by construction.
- No new records, settings, or containers.

**Negative / tradeoffs**:
- Plain Desk look and no charts.
- Everything is computed on each run. Fine for a few hundred rows; thousands of learners would need SQL level aggregation (out of scope now).
- Because the pass mark is read from the quiz as it is now, raising a quiz's pass mark changes old results on the next run. This is the same rule LMS applies to the student.
- It supersedes one line of spec 0004's value sourcing table (manager views compare against the `passing_percentage` on the submission row); spec 0010 already established the current quiz value as LMS's rule.

**Neutral**:
- Per course managers (deferred in the scope) would need row filtering later. Because the code reads as the server, that is a code change, not a permission change.

## Follow-up

- [ ] Live check in build task 1: that a Moderator can use the report's built in Export now that `ref_doctype` is `LMS Course`. Export is a bonus here; feature 13 owns the CSV promise.
- [ ] Update the value sourcing line of spec 0004 ("Manager views") to point to this spec when this feature ships (`/sync` can flag it).
- [ ] Consider a "Ready for certificate" nudge email later (feature 15 outbound email); not part of this spec.
