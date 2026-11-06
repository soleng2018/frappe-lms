# Review, main (feat/manager-progress-view, merged), 2026-11-05

**Reviewed by**: claude-opus-5-5 (author on a different session/model)
**Scope**: 13 files (progress feature only), branch range 93bf206..e3fa5df vs main
**Verdict**: Approve with nits

## Summary
The change adds two standard Script Reports (Learner Progress, Quiz Scores) to `nile_auth`, with every rule in a pure, Frappe-free module (`progress.py`) and an eight-query fetch layer (`progress_data.py`) injected as a function. The design follows spec 0013 closely: row existence from enrollment, progress, or certificate; outline-based totals; current pass mark; half-up rounding; double access check (Report roles plus `frappe.only_for`); static SQL; a fixed query count. No blockers or majors. The main issues are a cosmetic spec deviation (the learner cell shows the full name, so the email is not visible in the grid), some dead code, an un-updated `nile_auth` README, and a few untested branches (ordering, the "none attempted" average, and a positive Moderator access check).

## Minor

### 🟡 Learner email not visible in either grid, `apps/nile_auth/nile_auth/nile_auth/report/learner_progress/learner_progress.py:7`
**Problem**: The `learner` column is a Link to User, and Frappe 16 renders a User link by its title (full name). The next column, `full_name`, shows the same name again. The spec column list says `learner` "shows the email", and the value sourcing table lists "Learner name, email". Live verify confirmed the full name is shown. The same applies to `quiz_scores.py:7`.
**Why it matters**: An admin who needs the email (to match a learner to the IdP or group) has to hover or open the User. The Name column is a duplicate.
**Suggested fix**: In both report JS files, add a formatter for `learner` that renders the raw `data.learner` (escaped) as a link to `/app/user/<encoded name>`, as is already done for `quiz`. Or amend the spec to accept the title display and drop the duplicate column.

### 🟡 Dead code: `lesson_courses` is built and never read, `apps/nile_auth/nile_auth/progress.py:129-132`
**Problem**: The lesson-to-course map is computed and then never used.
**Why it matters**: Readers of the module that feature 13 must reuse will assume it affects the result.
**Suggested fix**: Delete it.

### 🟡 `nile_auth` README not updated, `apps/nile_auth/README.md`
**Problem**: Build plan step 5 says to note the new reports in the `nile_auth` README. Only the root README gained the admin paragraph, and that paragraph is good.
**Why it matters**: The app README lists what the app ships, and it is now incomplete.
**Suggested fix**: Add one line naming the two reports and `progress.py` as the shared rule module.

### 🟡 Untested branches in the pure rules, `tools/tests/test_progress.py`
**Problem**: TESTS = configured, and several spec rules have no direct assertion:
- AC-7 ordering by course title then learner name, across more than one course and learner.
- AC-8 quiz order by outline position when it differs from name or insert order. The happy path's q1/q2 order would match any sort.
- AC-5 `avg_best` being empty when no quiz was attempted.
- AC-6 last activity ignoring submissions on quizzes outside the outline.
- The certificate tie-break on `creation` when `issue_date` is equal.
- The `learner` and `course` (positive match) filters on Quiz Scores.
**Why it matters**: Feature 13 will reuse these exact functions. Ordering and empty-value rules are the ones most likely to regress silently.
**Suggested fix**: Add small table-style cases to the existing `world()` fixture.

### 🟡 AC-1 positive path only proven as Administrator, `tools/tests/live_scripts/progress_reports.pyscript:400`
**Problem**: The integration script runs the reports as `Administrator`, and `frappe.only_for` returns early for that user (frappe `__init__.py:557`). Neither a Moderator-only user nor a `hol-admins` member is exercised. The script also calls `frappe.desk.query_report.run` directly, so the HTTP 403 status is not asserted. The browser verify did cover a real admin.
**Why it matters**: The Report role rows and `ref_doctype` report permission for a non-Administrator Moderator are the security contract. Only a manual check guards it.
**Suggested fix**: In the live script, create a throwaway user with only Moderator, `set_user` to it, and assert that both reports return rows.

## Nits
- ⚪ `apps/nile_auth/nile_auth/progress.py:135`: `_group(data["quizzes"], "lesson")` is rebuilt inside the per-course loop. Hoist it above the loop.
- ⚪ `apps/nile_auth/nile_auth/progress.py:97`: list membership for dedup is O(n²). A side `set` is cleaner, though the volume makes this harmless.
- ⚪ `apps/nile_auth/nile_auth/progress.py:112`: `issue_date or ""` would compare `date` with `str` if one certificate lacked a date. LMS makes `issue_date` required (default Today), so this is safe today. A typed sentinel would be more robust.
- ⚪ `learner_progress.py:42` / `quiz_scores.py:30`: filters are validated after all eight queries run. Validate first (call `_check` early) to fail fast on a bad Status or State.
- ⚪ `learner_progress.py:53` / `quiz_scores.py:40`: `rows` is unbound if `throw_bad_filter` ever returned. It always raises, but annotating it `NoReturn` (or re-raising) makes that explicit.
- ⚪ `progress.py`: a quiz whose lesson sits in two managed courses yields two Quiz Scores rows for the same (User, quiz), one per course. This is consistent with AC-8's wording but not with the stated row key "(User, quiz)". Worth one line in the spec.

## Strengths
- Clean split: the pure `assemble(fetch, excluded)` takes the fetch layer as a function, so the AC-10 query-count test is real (`len(DATASETS)` calls for 5 and 200 learners). Feature 13 can reuse the rules without Frappe.
- Security is done right: Report roles are exactly Moderator and System Manager with `ref_doctype` LMS Course, `frappe.only_for` runs as a second check before any query, the SQL is static with no interpolation, and the Quiz Scores JS escapes the quiz title and URL-encodes both link parameters (tested under Node with hostile values).
- The rule edge cases match the spec precisely: Passed beats Locked, unlimited is never Locked, an off-outline completion is ignored, progress is floored and capped, and the average is rounded half up using integer math.
- The live integration script runs inside a rolled-back transaction and asserts nothing is left behind.

## Test coverage
Unit (17 passing): status order, rounding, quiz states, happy path (AC-3 to AC-6), slot ended plus the enrolled filter, outline change, duplicate lesson, exclusions (Administrator, service user, MCP user, unmanaged course, idle user), disabled user, current pass mark plus Locked, filter AND plus validation, empty case, query count, and the JS dropdown, link and escaping. Integration covers real records, both reports, the student PermissionError, and the raised pass mark. Gaps: ordering (AC-7, AC-8), the empty average, the last-activity quiz scoping, the certificate tie-break, Quiz Scores learner and course filters, a non-Administrator Moderator positive run (AC-1), and the clean-site migrate (AC-10, not run). `progress_data.fetch` has no unit test by nature and is exercised only by the integration test.
