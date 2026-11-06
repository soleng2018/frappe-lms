# 0014. Give managers one Monthly Report: who finished the lab, who is behind, and what happened that month

**Date**: 2026-11-05
**Status**: Accepted

## Summary

Admins in `hol-admins` get a third Desk report, **Monthly Report**. You pick a month, and it lists every learner and course with a clear **Done** or **Behind**, plus what happened in that month (lessons, quiz attempts, scores, certificates). Five totals sit above the table and the rows download as CSV with the report's own Export. A learner is Done when nothing is left to do, so someone who failed a quiz and ran out of attempts still counts as Done, with the Outcome "Not passed". It reuses the plain Python rules from spec 0013, so the numbers match the progress view, and it adds no new records, settings, or setup steps.

## Context

> ⚠️ Premise note: "Done even if they fail" cannot be read from LMS lesson progress. LMS only marks a quiz lesson Complete when the quiz is passed (`save_progress_after_quiz` returns early below the pass mark, and spec 0010 AC-2 says the same). A rule of "all lessons complete" would therefore call a learner who failed a quiz behind forever, the opposite of what the program wants. Done is defined from quiz states (Passed or Locked) instead of lesson progress for quiz lessons.

Spec 0013 gave admins two live reports: Learner Progress (one row per learner and course, with a status as of now) and Quiz Scores. Feature 13 in the scope asks for a monthly view of the same data: completions, scores, and who is behind, as a page an admin opens, with a CSV download, whose numbers match the progress view.

Facts that shape the design:

- Learners come and go. Spec 0009 removes a learner's enrollment when their course group goes away, so rows must come from progress, enrollment, or certificates, exactly as 0013 does. The one function that decides "who has a row" must be shared, not copied.
- A month is a window in the past. "Behind" has to be judged as of the end of that month, or an old report would change every day. That needs a date for each event: when a lesson was completed, when a quiz attempt was made, when a certificate was issued, and when the learner first appeared. Course Progress rows for ordinary lessons are created once, already Complete, so their `creation` is the completion time. Quiz Submission has `creation` for each attempt. LMS Certificate has `issue_date` and `creation`. LMS Enrollment has `creation`.
- The pass check uses the quiz's current `passing_percentage`, and the attempt limit is the quiz's current `max_attempts` (0010, 0013). The monthly report must use the same values.
- Everything is computed at read time. The program is small (a few hundred rows), as in 0013. An admin can reset a locked learner by deleting their attempts, and a content sync can change a course outline, so a past month can shift after the fact.
- The brief says managers "pull a monthly report". The scope also lists an emailed monthly report as deferred, which is a future reuse of the same pure code.

## Requirements

**User stories**:
- As a hol-admin, I want to pick a month and see every learner and course marked Done or Behind as of the end of that month, so that I know who still has to finish the lab.
- As a hol-admin, I want to see what each learner did in that month (lessons, quiz attempts and scores, certificate), so that I can report activity for the period.
- As a hol-admin, I want to count learners who finished in that month and learners who finished but did not pass, so that completions and results are reported honestly.
- As a hol-admin, I want five totals above the table and a CSV of the rows, so that I can paste the month into a report.
- As a hol-admin, I want these numbers to agree with the Learner Progress report, so that I can trust both.
- As a student, I want other learners' data to stay private, so that only managers see it.
- As the operator, I want the report installed by the normal migrate with no manual step.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: A user with the Moderator or System Manager role can run Monthly Report. A user with neither (an LMS Student, any Website User, or a Guest) gets a permission error (HTTP 403), receives no rows and no totals, and the report is not listed for them. `hol-admins` members pass because spec 0006 gives them Moderator. The Report record sets `ref_doctype` to `LMS Course` and carries exactly the roles Moderator and System Manager.
- **AC-2**: The **Month** filter is a Select whose options the report JS fills, and the server validates it either way. After stripping spaces the value must match `^\d{4}-(0[1-9]|1[0-2])$`. The report window runs from the first day of that month (`start`) up to but not including the first day of the next month (`next_start`), using dates as stored (the site time zone, no conversion). **Every rule below uses `next_start` as the cutoff**: a datetime such as `creation` is "by month end" when it is before `next_start` at midnight, and a date such as `issue_date` when it is before `next_start`. The current month uses the same cutoff (its month end, not now), so a certificate dated later in the month counts. A blank Month means the last full calendar month. A malformed value, or a month after the current month, raises a validation error. Any older month is accepted through the API. The Desk dropdown offers the current month and the 24 months before it, newest first, and defaults to the last full month. Its labels read "Month Year" (for example "October 2026") while the values stay `YYYY-MM` (`2026-10`), so the server, the API, and the CSV see only the value. The server takes today from `frappe.utils.getdate()` and the JS from `frappe.datetime.now_date()`, both in the system time zone.
- **AC-3**: There is one row per (User, managed course), where a **managed course** is an LMS Course with a `nile_key`. A row exists when the learner qualifies under the same rule as Learner Progress (spec 0013 AC-2: an Enrollment, any Course Progress row, or a Certificate), and the earliest date among those records is before the cutoff (AC-2). That date is `creation` for an Enrollment or a Course Progress row, and the earlier of `creation` and `issue_date` for a Certificate, so a certificate created in April but dated March still gives a March row. The exclusions are the same as 0013 (courses with no `nile_key`, `Administrator`, `nile_service_user`, `nile_mcp_user`, users with no qualifying record). For the current month the row set equals the Learner Progress row set.
- **AC-4**: **Result** is **Done** or **Behind**, judged as of the cutoff (every record below must be dated before `next_start`). A learner is Done when either: (a) they hold an LMS Certificate whose `issue_date` is before the cutoff, published or not (as in 0013 Certified); or (b) the course has at least 1 lesson, every lesson of the course outline that has no LMS Quiz is Complete in LMS Course Progress, and every counted quiz (AC-5 of spec 0013) is **Passed** or **Locked** using only the attempts made before the cutoff. A pass mark of 0 or empty counts as 0, so any attempt passes (inherited from 0013). A quiz with no attempt limit (`max_attempts` 0) is never Locked, so a learner who keeps failing it stays Behind. A quiz lesson is a lesson that has an LMS Quiz. A course with no quizzes is Done when every lesson is Complete. A course with 0 lessons is never Done. Anyone not Done is Behind. Passed and Locked use the 0013 `quiz_state` rule with the quiz's current `passing_percentage` and `max_attempts`.
- **AC-5**: **Outcome** is empty for a Behind row. For a Done row it is **Not passed** when the learner has no certificate before the cutoff and at least one counted quiz is Locked at the cutoff (not Passed), and **Passed** otherwise. Outcome uses the quiz state at the cutoff, so a quiz that was Locked and later Passed (after a reset or a raised attempt limit) counts as Passed. **Done date** is the earlier of two dates, when they exist: the date the finish rule (b) first held (the latest of the creation of the earliest Complete row for each non quiz lesson, and, for each counted quiz, the creation of the attempt that first made it Passed or Locked, replaying attempts in order of `creation` with input order breaking ties), and the earliest certificate `issue_date` before the cutoff. It is shown as a date (the date part of a datetime). It is empty for Behind. **Completed this month** is Yes when the Done date falls inside the chosen month, else No.
- **AC-6**: The month's activity columns count only records dated inside the chosen month: **Lessons completed** (distinct outline lessons whose Complete row was created in the month), **Quizzes first passed** (counted quizzes whose earliest attempt at or above the current pass mark, across all history before the cutoff, was made in the month, so a later pass is never counted twice), **Attempts** (quiz attempts on counted quizzes), **Average attempt score** (the mean `percentage` of those attempts, each taken as `int(percentage or 0)`, rounded half up to a whole number, empty when there are none), and **Certificate issued** (Yes when a certificate has an `issue_date` in the month, else No).
- **AC-7**: The chase columns are judged as of the cutoff: **Lessons done** and **Lessons left** (outline lessons with and without a Complete row; a completed lesson that is no longer in the outline is ignored, as in 0013 AC-4), **Locked quizzes** (counted quizzes in state Locked), and **Certificate** (a link to the newest certificate dated before the cutoff, empty when none). **Enrolled** and **Enabled** are the current values, as in 0013, and the column labels say so.
- **AC-8**: The filters are **Month** (AC-2), **Course** (managed courses only; a value that is not a managed course returns an empty table), **Result** (blank, Done, or Behind; any other value raises a validation error), **Learner** (matches full name or email, any part, any case), and **Currently enrolled only** (default off). Filters combine with AND, and totals follow these report filters (not the Desk's inline column filters in the datatable). Rows are ordered by course title, then learner name, then learner id, then course name.
- **AC-9**: Five totals show above the table and follow the filtered rows: **Done**, **Behind**, **Certified this month** (rows with Certificate issued Yes), **Attempts this month**, and **Average attempt score** (the mean of every attempt percentage in the month across the shown rows, not the mean of row averages, rounded half up; 0 when there are no attempts). An empty table shows zeros.
- **AC-10**: A `hol-admins` member (a Moderator who is not a System Manager) can download the shown rows as CSV with the report's built in Export, with the same visible columns as the table (the hidden `course_name` and `attempt_score_sum` are left out; the probe confirms how Frappe treats hidden columns). No CSV cell starts with `=`, `+`, `-`, or `@` unescaped. If the live probe shows that a Moderator is refused or that formulas are not escaped, a Download CSV button calls a whitelisted method that runs the same report and sanitizes the cells, behind the same access check.
- **AC-11**: For the current month, each row's Lessons done, Enrolled, and Enabled equal the same row in Learner Progress, and so does Certificate for rows with no certificate dated after the current month. The count of Done rows is at least the count of Certified rows there, apart from certificates with a future or empty `issue_date`. Both reports call the same pure functions for the row set, the outline, and the quiz states.
- **AC-12**: The report never writes data. It runs the same fixed 8 fetches as 0013 whatever the number of learners or the chosen month (no query per row), and returns in a few seconds for a few hundred rows. It is a standard Script Report that exists after `bench migrate` with no manual step. If there are no managed courses, or no row matches the filters, it returns an empty table with zero totals and no error.

## Options considered

### Option 1: A third Script Report, Monthly Report, on the shared pure module

A standard Desk Script Report with a Month filter, summary tiles, and the built in Export, calling a new pure module that reuses the 0013 rules and shared row key function.

**Pros**:
- Matches 0013's pattern, so filters, sorting, column choice, export, and the role check come for free.
- The month rules are pure functions that a unit test can count and replay, and the future emailed report can call them.
- No new records, settings, or containers.

**Cons**:
- Plain Desk look, no charts.
- Built in Export for a Moderator is unproven (the open 0013 follow-up); this feature must prove it or ship a fallback button.
- A small refactor of `progress.py` to expose the shared row key function.

### Option 2: Add a Month filter to Learner Progress

One report, with month columns added to the existing one.

**Pros**:
- Fewer reports to find.

**Cons**:
- It changes the contract of a shipped, tested report (spec 0013), and the columns, status, and summary mean different things for "now" and "a past month". Two questions in one table is harder to read and to test.

### Option 3: Custom Desk page with its own CSV endpoint

A hand built page with month picker, tiles, and a download endpoint.

**Pros**:
- Full control of layout and CSV format.

**Cons**:
- More JS and API code to keep, and it loses the free filters, sorting, and export.

### Option 4: Monthly snapshots

A scheduled job stores each month's rows in a new record, and the report reads the snapshot.

**Pros**:
- Old months never shift after a reset or content change.

**Cons**:
- A new record type, a migration, a scheduler job, and a failure mode (a missed month). It is the weight 0013 avoided, for a program of a few hundred rows.

## Decision

**Chosen option**: Option 1: A third Script Report, Monthly Report, on the shared pure module

Ship **Monthly Report** as a standard Script Report in `nile_auth`, with the month rules in a new pure module `monthly.py` that shares its row set, outline, and quiz rules with `progress.py`.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`)

## Rationale

Admins already work in the Desk, and 0013 showed that a Script Report on a pure module gives filters, sorting, export, and the role check at the smallest cost. The monthly question is the same data judged at a date, so the honest design is the same reports pattern with dates, not a second system. The data volume removes any reason for a snapshot job (Option 4), and the pure module is what makes "the numbers match the progress view" true by construction instead of by checking: both reports ask one function who has a row and one function whether a quiz is Passed or Locked.

Option 2 was refused because the progress view is shipped and tested and answers "where are they now". The monthly report answers "where were they at the end of that month and what did they do in it", which needs different columns, a different row cutoff, and a different Done rule. Keeping them apart means a mistake in one cannot break the other.

Done is defined from quiz states because LMS refuses to complete a quiz lesson on a failed attempt (Context). A learner who has passed or used up every quiz and finished the other lessons has nothing left to do, which is what the program means by "completed the lab even if they fail". A certificate on or before month end also counts as Done, so a learner whose attempts an admin later reset does not fall back to Behind in an old month. The Outcome column keeps pass and fail visible so that Done never hides a failure.

Computing live and accepting that a reset or outline change can shift a past month matches 0013 and the program's size. It is written in the README so that an admin who re runs an old month and sees a different number knows why.

## Feature design

**Data model sketch**: no new records and no new fields. The report reads the 8 lists of spec 0013 (`progress.DATASETS`), only for managed courses, as the server. Two existing lists gain one field each, which adds no query:

| Record | Fields read | Used for |
|---|---|---|
| LMS Course | `name`, `title`, `nile_key` | managed courses, course filter, ordering |
| Chapter Reference and Lesson Reference | `course`, `lesson` (ordered) | the outline: lessons total, quiz lessons |
| LMS Enrollment | `member`, `course`, **`creation`** (new) | Enrolled flag, first record date |
| LMS Course Progress | `member`, `course`, `lesson`, `status`, `modified`, **`creation`** (new) | lessons done by date, completed in month, first record date |
| LMS Quiz | `name`, `title`, `lesson`, `max_attempts`, `passing_percentage` | counted quizzes, pass mark, attempts allowed |
| LMS Quiz Submission | `member`, `quiz`, `percentage`, `creation` | attempts by date, quiz states, first pass |
| LMS Certificate | `name`, `member`, `course`, `issue_date`, `published`, `creation` | Done by certificate, issued in month, link |
| User | `name`, `full_name`, `enabled` | learner name, Enabled |

Row key: (User, managed course). One hidden numeric field, `attempt_score_sum`, on each row, together with the visible `attempts`, feeds the Average attempt score total, so it is a true mean.

**Columns** (fieldname, label, type):
`learner` (Learner, Link to User), `full_name` (Name, Data), `course` (Course, Data, the title), `course_name` (hidden Link to LMS Course), `result` (Result, Data Done or Behind), `outcome` (Outcome, Data Passed or Not passed or empty), `done_date` (Date), `completed_this_month` (Data Yes or No), `lessons_completed` (Lessons completed in month, Int), `quizzes_first_passed` (Quizzes first passed in month, Int), `attempts` (Attempts in month, Int), `avg_attempt_score` (Average attempt score in month, Percent), `certificate_issued` (Certificate issued in month, Data Yes or No), `lessons_done` (Lessons done, Int), `lessons_left` (Lessons left, Int), `locked_quizzes` (Locked quizzes, Int), `certificate` (Certificate, Link to LMS Certificate), `enrolled` (Enrolled now, Data Yes or No), `enabled` (Enabled now, Data Yes or No).

**State transitions**: none stored. Result and Outcome are derived each run (AC-4, AC-5). One learner and course over time: not Done, then Done on the Done date, and it stays Done in later months (a later quiz reset does not undo a certificate, but can undo rule (b)).

**API surface**: standard Frappe report calls, no custom endpoint unless the AC-10 fallback is needed.

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/method/frappe.desk.query_report.run` | POST | `report_name` Monthly Report, `filters` JSON (`month`, `course`, `result`, `learner`, `enrolled_only`) | columns, rows, report summary | Moderator or System Manager session | 403 for any other user; validation error for a bad `month` or `result` |
| `/api/method/frappe.desk.query_report.export_query` | POST | the same filters, file format CSV | the CSV file | same | 403 for any other user |
| Report code `execute(filters)` | called by the first | as above | `(columns, rows, None, None, summary)` | `frappe.only_for` second check | PermissionError |
| `monthly_report.download_csv` (only if the AC-10 probe fails) | POST | the same filters | sanitized CSV | same check | 403 |

**Value sourcing** (every value the report produces or displays, and where it comes from):

| Action | Value produced / displayed | Source |
|---|---|---|
| Run | Window `start`, `next_start` (the cutoff) | the `month` filter; blank means last full month from today's date, passed into the pure function as a parameter (`frappe.utils.getdate()` at the edge) |
| Run | Dropdown months | the report JS builds the current month and the 24 before it from `frappe.datetime.now_date()` |
| Run | Time zone | dates as stored by the server, no conversion (same as 0013) |
| Rows | Who has a row | the shared row key function in `progress.py` (spec 0013 AC-2), then the earliest `creation` of the learner's Enrollment, Course Progress rows, and Certificates for the course must be before the cutoff; for a Certificate the earlier of `creation` and `issue_date` |
| Rows | Excluded users, managed courses | as 0013: `Administrator`, site config `nile_service_user`, `nile_mcp_user`; LMS Course `nile_key` |
| Result | Quiz lessons, non quiz lessons | an outline lesson is a quiz lesson when an LMS Quiz has it as `lesson` |
| Result | Quiz state at month end | `quiz_state(best, used, allowed, pass_mark)` from 0013, using Quiz Submission rows with `creation` before the cutoff, the quiz's current `passing_percentage` and `max_attempts` |
| Result | Non quiz lesson Complete | Course Progress `status` Complete and `creation` before the cutoff, lesson in the current outline |
| Result | Certificate held | LMS Certificate `issue_date` before the cutoff, published or not |
| Outcome | Passed or Not passed | derived: certificate held, else any counted quiz in state Locked |
| Done date | Date | derived: earlier of the finish date (rule b) and the earliest certificate `issue_date`; finish date from Course Progress `creation` and the attempt `creation` that first made a quiz Passed or Locked |
| Month columns | Lessons completed, quizzes first passed, attempts, average attempt score | Course Progress `creation`, Quiz Submission `creation` and `percentage` inside the window; a `null` percentage counts as 0, as in 0013 |
| Month columns | Certificate issued | a Certificate `issue_date` inside the window |
| Chase columns | Lessons done, lessons left, locked quizzes, certificate link | derived as of the cutoff (AC-7); certificate is the newest by `issue_date`, ties by `creation` (0013 rule) |
| Chase columns | Enrolled now, Enabled now | LMS Enrollment exists now; User `enabled` now |
| Totals | Done, Behind, Certified this month, Attempts, Average attempt score | counted or summed from the filtered rows and their hidden `attempts` and `attempt_score_sum` |
| CSV | Rows and header | the report's own columns and rows, passed through the Frappe export (or the fallback method) |
| Report record | Roles and install | roles Moderator and System Manager, `ref_doctype` `LMS Course`, `is_standard` Yes, `report_type` Script Report, module Nile Auth, JSON in `apps/nile_auth/nile_auth/nile_auth/report/monthly_report/` with `modified` bumped on every change |

**Key invariants**:
- The report never inserts, updates, or deletes a record.
- Design shape: a pure `as_of(data, next_start)` trims every list to records dated before the cutoff (enrollments, progress, and submissions by `creation`, certificates by the earlier of `creation` and `issue_date`, with `date.min` as the sentinel for an empty date). The shared 0013 row, outline, and quiz state functions then run on the trimmed data, so AC-11 holds by construction. A separate pass over the untrimmed records handles the month columns and the Done date replay. Dates are real `date` and `datetime` objects, never strings, and are never compared across types.
- The row set, outline, quiz lessons, and quiz states come only from functions in `progress.py`, imported by `monthly.py`. `monthly.py` imports nothing from Frappe. The Script Report only fetches plain lists, calls the pure function, and formats links and tiles.
- Done never depends on lesson progress for a quiz lesson, so it holds whether LMS enforces quiz completion or not.
- The month window is a half open range: a record belongs to the month when its date is on or after the first day and before the first day of the next month. Nothing is counted twice across two months.
- A quiz that was passed or Locked and a certificate that exists can only make a learner Done, never Behind.
- Query count does not grow with the number of learners or months.

**Security model**:
- Access is the Moderator and System Manager roles on the Report record, with `frappe.only_for` in the code as a second check, as in 0013. LMS Student, Website Users, and Guests are refused.
- The queries read as the server. The report and the CSV contain student names, emails, and scores, so access must stay limited to the two roles. A downloaded CSV leaves the system, so the README tells admins to handle it as personal data.
- No audit log: nothing is changed.
- CSV cells are protected against spreadsheet formulas (AC-10), because names come from outside.
- No regulated data class beyond what spec 0013 already covers.

**Configuration required**: none new. It reads the existing site config keys `nile_service_user` and `nile_mcp_user`.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: a learner with all non quiz lessons complete, one quiz passed and one Locked after 3 failed attempts, all before the month end, is Done with Outcome Not passed and the right Done date; a learner who passed everything and holds a certificate is Done with Outcome Passed, verifies **AC-4**, **AC-5**.
- Behind: a learner with a quiz that has attempts left, or a lesson not complete, is Behind; the same learner in a later month, after finishing, is Done; in the earlier month they are still Behind, verifies **AC-4**.
- Past month cutoff: a learner who enrolled in March has no row in the February report; an attempt made on the first day of March does not count in February, verifies **AC-3**, **AC-6**.
- Certificate rule: a certified learner whose attempts were later deleted is still Done in the month the certificate was issued and after, with Outcome Passed, verifies **AC-4**, **AC-5**.
- Edge rules: a course with 0 lessons is never Done; a course with no quizzes is Done when every lesson is Complete; an unlimited quiz is never Locked, so it never finishes a learner by itself, verifies **AC-4**.
- Month activity: lessons completed, quizzes first passed, attempts, and the average attempt score count only records inside the month, with half up rounding (72.5 gives 73), verifies **AC-6**.
- Totals: the Average attempt score tile is the mean of all attempts, not the mean of row averages, and an empty table shows zeros, verifies **AC-9**, **AC-12**.
- Match with 0013: for the current month, lessons done, enrolled, enabled, and certificate equal Learner Progress for every row, and the row sets are equal, verifies **AC-3**, **AC-11**.
- Month filter: a blank month gives the last full month; `2026-13`, `abc`, and a future month raise a validation error; the current month is accepted; the dropdown lists 25 months, verifies **AC-2**.
- Filters: Result, Course, Learner, and Currently enrolled only combine with AND, an invalid Result raises, an unmanaged course returns an empty table, verifies **AC-8**.
- Auth: a learner session gets 403 and no rows or totals; a member of `hol-admins` who is not a System Manager gets rows, verifies **AC-1**.
- CSV: that same Moderator exports the rows with the built in Export, and a learner named `=1+1` appears as text, not a formula. If either fails, the fallback button is built and the same check passes on it, verifies **AC-10**.
- Query count: a unit test with an injected fetcher shows the same 8 fetch calls for 5 and for 200 learners and for any month, verifies **AC-12**.
- Install: after `bench migrate` on a clean site the report exists with the two roles and `ref_doctype` `LMS Course`, verifies **AC-1**, **AC-12**.

## Build plan

Build approach: Tracer Bullet (from `AGENTS.md`). The first task is one thin report through every layer (shared rules, query, access, month filter, install, export probe); the rest thicken it.

1. [x] Thin thread and live probes. In `progress.py`, move the row key rule out of `assemble` into a public function (with `outline_by_course` and the quiz grouping helpers) so both reports call it, and keep every 0013 unit test green. Add `creation` to the `enrollments` and `progress` datasets in `progress_data.py` and update the `DATASETS` comments. Add `nile_auth/monthly.py` with month parsing and the Done rule (AC-4 parts a and b, no dates beyond the cutoff yet). Add the Monthly Report Script Report (JSON, Python, JS) with learner, course, Result, and the Month filter, plus the role check. Run `bench migrate`, open it as a `hol-admins` member and as a student, and probe and record: that the report syncs on migrate, that a Moderator who is not a System Manager can use the built in Export, whether a name starting with `=` is escaped in the CSV, that a non SCORM Course Progress row's `creation` is the completion time, and that quiz lessons stay incomplete after a failed attempt on this site. Satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-12**.
2. [x] Complete the finish rules. Add Outcome, Done date, Completed this month, the date cutoff for rows, certificate rule, and the first date quiz states, with unit tests for every edge in AC-4 and AC-5. Satisfies **AC-3**, **AC-4**, **AC-5**.
3. [x] Month activity and chase columns. Add lessons completed, quizzes first passed, attempts, average attempt score, certificate issued, lessons done and left, locked quizzes, certificate link, enrolled and enabled, and the five filters, ordering, and empty case. Satisfies **AC-6**, **AC-7**, **AC-8**, **AC-12**.
4. [x] Totals, month dropdown, and CSV. Add the five summary tiles (true mean for the score), the JS month list and default, and the CSV result of the task 1 probe: either nothing more to build, or the Download CSV fallback with its sanitizer and the same access check. Satisfies **AC-2**, **AC-9**, **AC-10**.
5. [x] Integration tests (marker `integration`) against the live site: the scenarios above, the 0013 comparison for the current month, the access check, the CSV check, and the query count. Satisfies **AC-1** to **AC-12**.
6. [x] README: add the admin steps (where to open Monthly Report, how to pick a month, what Done, Behind, and Outcome mean, why a Done learner can show lessons left, how to download the CSV and handle it as personal data, and that a reset or content change can shift a past month). Note the new report in the `nile_auth` README. Satisfies **AC-9**, **AC-10**, **AC-12**.

## Consequences

**Positive**:
- Admins see in one page who finished, who is behind, and what happened in the month, and can download it.
- The numbers match the progress view by construction, because both use the same row set and quiz rules.
- Failing a quiz no longer makes a learner look behind forever, and Outcome still shows the failure.
- No new records, settings, or containers. The pure module is ready for the deferred emailed monthly report.

**Negative / tradeoffs**:
- Past months are computed from current records. Resetting a learner's attempts, or a content sync that changes the outline, a pass mark, or an attempt limit, can change an old month. A certificate keeps its holder Done. A row can also vanish from an old month when spec 0009 deleted the enrollment that was the learner's only earlier record.
- A learner can show Done with Outcome Not passed in one month and Passed in the next, once a certificate is issued. The README says so, and says an unlimited quiz never finishes a learner who keeps failing.
- SCORM lessons are out of scope: a Course Progress row that starts Partially Complete would date a completion too early. The nile courses do not use SCORM.
- The pass mark and attempt limit are read as they are now, not as they were in that month.
- Plain Desk look, and the totals are not in the CSV.
- Enrolled and Enabled are today's values, not the month's.
- A Done learner can show Lessons left above 0 (a failed quiz lesson never completes). The README explains it.
- Small refactor of `progress.py`, with the risk of breaking 0013 if its tests are not kept green.

**Neutral**:
- Month boundaries use the stored dates in the site time zone, like 0013's last activity.
- Per course managers (deferred) would need row filtering later, a code change as in 0013.

## Follow-up

- [x] Task 1 probes (run on the live site, 2026-11-05): the report syncs on `make up` with both roles. A Moderator who is not a System Manager can use the built in Export; hidden columns (`course_name`, `attempt_score_sum`) are left out; a learner named `=1+1` is saved as `'=1+1`, so no Download CSV fallback was built. A real `save_progress` creates the Course Progress row already Complete, with `creation` equal to `modified` at the completion time. Quiz lessons staying incomplete after a failed attempt is already proven by spec 0010 AC-2 (`lms_behaviour.pyscript`), not repeated here. This closes the open Export follow-up in spec 0013.
- [x] In build task 1, fix two 0013 weak points the shared code now depends on: `_newest_certificate` compares `issue_date or ""` (a None next to a date raises), so use `date.min`; and read percentages as `int(percentage or 0)`. Keep the 0013 unit tests green.
- [ ] Spec 0013 invariants say row assembly is in `progress.py`; update that line to mention the shared row key function when this ships (`/sync` can flag it).
- [ ] The scope's "Emailed monthly report" (deferred) can call `monthly.py` directly; design it later with outbound email.
- [ ] Decide later whether a past month needs a frozen snapshot if resets turn out to be common (Option 4).
