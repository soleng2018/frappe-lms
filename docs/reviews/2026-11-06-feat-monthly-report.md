# Review, feat/monthly-report, 2026-11-06

**Reviewed by**: claude-opus-5-5 (author on sonnet)
**Scope**: 14 files, branch vs main (merge base 1eb4bd2, already merged as PR #18)
**Verdict**: Approve with nits

## Summary
The change adds the Monthly Report Script Report (spec 0014). It has a pure `monthly.py` that reuses the 0013 row set, outline, quiz state and certificate rules, now made public in `progress.py`. It also adds two `creation` fields to the existing fetches and has good unit and live coverage. I traced AC-2 through AC-12 against the code and found no correctness bugs. The month window is half open. The row cutoff uses the earlier of the certificate `creation` and `issue_date`. The replay order is stable. The Done date, the Outcome and the true-mean total all match the spec. The 0013 refactor is behavior-preserving apart from the intended `int(percentage or 0)` and `date.min` fixes. The remaining findings are small. One activity counter can count a lesson twice across months when an LMS row is duplicated. The live script depends on the course having exactly two quizzes, and one of its comments is wrong. There are a few public-surface and wording nits.

## Minor

### 🟡 "Lessons completed in month" can count the same lesson in two months, `apps/nile_auth/nile_auth/monthly.py:161-170`
**Problem**: A lesson is added to `completed_in_month` when *any* of its Complete rows was created in the window. It does not check that the row is the earliest one. If a learner has two Complete rows for one lesson, one in September and one in October, the lesson counts in both months. Lessons done and the Done date already use the earliest row (`complete_at`).
**Why it matters**: The spec invariant says "Nothing is counted twice across two months". Quizzes first passed handles this case on purpose, but lessons do not. LMS normally keeps one row per lesson, so the impact is low. Duplicates can still appear through SCORM, a manual import, or a race.
**Suggested fix**: After the loop, count the lessons whose `complete_at[lesson]` is on or after `window.first`. This uses the earliest Complete row, the same rule as quiz first pass. Add a unit test with two Complete rows in different months.

### 🟡 The live script assumes the course has exactly two quizzes, and its comment says the opposite of the code, `tools/tests/live_scripts/monthly_report.pyscript:23-25,51`
**Problem**: The comment says the other quizzes are made "unlimited and unattempted". The code does neither. It leaves their limits alone and adds a 90% attempt on each one (`for q in others: sub(failed, q, 90, ...)`). The integration assertions are fixed numbers: `attempts == "4"`, `quizzes_first_passed == "1"`, `attempt_score_sum == "265"` and `lessons_left == "2"`. They only hold when `others` is empty. If the authored content ever adds a third quiz, these tests break. If that quiz's pass mark is above 90, the "failed" learner also becomes Behind.
**Why it matters**: A content change in `content/` would make the AC-4/AC-6 live proof fail even though the code is correct. The misleading comment makes the failure hard to diagnose.
**Suggested fix**: Pick one approach and make the comment say it:
- set `max_attempts` 0 and add no attempts on the other quizzes, which makes them unlimited and leaves them blocking, so the Done path has to change; or
- set their pass mark to 80, then build the expected attempts and score sum from `len(others)`; or
- skip the test when the course does not have exactly two quizzes.

The script already records `out["others"]`, so the test can at least assert `others == 0` and fail with a clear message.

### 🟡 `except ValueError` covers the whole computation, not just filter parsing, `apps/nile_auth/nile_auth/nile_auth/report/monthly_report/monthly_report.py:81-93`
**Problem**: `monthly_rows` checks the filters, fetches, builds and filters inside one `try`. Any `ValueError` from the data path is shown to the admin as a filter validation message. Examples are `int(filters.get("enrolled_only"))` on `"true"`, or `int()` on an odd percentage. Learner Progress uses the same pattern.
**Why it matters**: A data bug would look like a user input error, and its traceback would be lost.
**Suggested fix**: Either check the filters first (call `parse_month` and `_check_result`, which `monthly_rows` already runs before fetching) and keep the `try` around that call only, or narrow the catch. Low priority, and you could change both reports together.

### 🟡 README wording on the Done date for a Not passed learner, `README.md:137`
**Problem**: The README says that for a learner who ran out of attempts, "the Done date is the day the last attempt locked the quiz". The code (and AC-5) uses the *latest* of every non-quiz lesson completion and every quiz's settling attempt. A learner who locks a quiz and then finishes a plain lesson gets the lesson's date.
**Why it matters**: An admin comparing dates would see a mismatch with the README.
**Suggested fix**: Say the Done date is the day the last remaining item was finished: the last lesson, or the attempt that passed or locked the last quiz.

## Nits
- ⚪ `apps/nile_auth/nile_auth/progress.py:107`: `_latest` was renamed to public `latest`, but it is not in `__all__`, has no docstring, and `monthly.py` does not use it. Either keep it private or export and document it, to match the project's "deliberate public surface" rule.
- ⚪ `apps/nile_auth/nile_auth/monthly.py:126`: 111 columns when a tab counts as 4. Ruff passes, so this depends on the configured tab width. Wrap the long `_replay` docstring if the rule is meant strictly.
- ⚪ `apps/nile_auth/nile_auth/progress_data.py` `throw_bad_filter` is annotated `-> None` even though it always raises. In `execute`, `rows`/`totals` would look unbound to a reader. `NoReturn` would say what it does.
- ⚪ `tools/tests/live_scripts/monthly_report.pyscript:69`: `cur, _ = rows("")` is dead, because it is overwritten two lines later. It does exercise a blank month, but nothing asserts on the result.
- ⚪ `docs/specs/0014-monthly-report.md:149`: the value sourcing table says the JS uses `frappe.datetime.get_today()`, but AC-2 (and the code) use `now_date()`. The spec contradicts itself.

## Strengths
- The pure `monthly.py` follows the spec's design shape exactly. `as_of` trims the data for the row set, and the shared `row_keys`, `outline_by_course`, `counted_quizzes`, `quiz_state` and `newest_certificate` then run on it. So AC-11 holds by construction, not by copying code. The 0013 refactor (for example, building `counted_quizzes` once instead of rebuilding the lesson grouping on every loop) is a quiet improvement, and all 0013 tests stay green (87 passed).
- Edge handling is careful:
  - the month window is half open, with `Window.first` and `Window.cut` as datetimes so a datetime is never compared with a date;
  - a stable sort keeps input order on ties;
  - `date.min`/`datetime.min` act as sentinels;
  - the score total is a true mean through the hidden `attempt_score_sum`;
  - the filters are checked before any fetch.
- The live script proves the risky Frappe behavior on the real site: a Moderator who is not a System Manager can export, hidden columns are dropped, `=1+1` is escaped, a student gets a 403, and the script rolls back with a leftover check. This closes the open 0013 Export follow-up with evidence.

## Test coverage
The unit tests (`tools/tests/test_monthly.py`, 40+ cases) map well to the spec's critical scenarios:
- the AC-4 and AC-5 edges: 0 lessons, no quizzes, unlimited quiz, Locked then Passed, a certificate after attempts were deleted, a certificate with no date, the earlier Done date;
- the cutoff boundaries: an attempt at midnight on the 1st, a certificate created in April but dated March;
- month activity, first pass counted once, null percentage, pass mark 0, tie order;
- exclusions, ordering, the current month matching Learner Progress, filters, totals and the empty case;
- the fixed 8 fetches whatever the number of learners or the month, and bad filters failing before any fetch.

The integration test covers access, CSV export and escaping, validation errors, the 0013 comparison, and the main Done/Behind/Not passed paths on real records.

Gaps:
- No test for duplicate Complete rows across months (see Minor).
- `summary()` and the `execute` error mapping are checked only through the live test, by label, not by value.
- The JS month list (25 entries, the labels, the default) has no runner, by design. `/check verify` should exercise it.
