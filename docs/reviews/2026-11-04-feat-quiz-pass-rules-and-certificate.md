# Review, feat/quiz-pass-rules-and-certificate, 2026-11-04

**Reviewed by**: claude-opus-5-5 (author on a different model)
**Scope**: 12 files, branch vs main (merge base 5808ffc, committed plus uncommitted)
**Verdict**: Approve with nits

## Summary
The change raises the content check's pass mark floor to 80 (`MIN_PASSING_PERCENTAGE`), adds a single `stranded learner` warning in the `nile_auth` login cleanup (AC-9), and adds a live integration test plus README steps that prove the LMS's own pass mark, attempt limit, certificate, publish and reset rules (AC-2 to AC-8). The code is small, correct and well covered; unit tests pass (80 passed for `test_content.py` and `test_nile_auth_login.py`). The headline issues are drift between the spec and what was actually proven (the certificate link route and the rounding rule), and one unit test assertion that is weaker than it looks.

## Minor

### 🟡 Spec still names a different certificate link than the README and the test, `docs/specs/0010-quiz-pass-rules-and-certificate.md:33`
**Problem**: AC-4, AC-5, the API table (line 105) and the value sourcing row (line 118) say the link is `https://<LMS_HOSTNAME>/certificate/<certificate name>`. The README (`README.md:128`) and the integration test (`tools/tests/test_pass_certificate_integration.py:192-195`) use `/courses/<course>/<certificate name>`, and only that route is proven live.
**Why it matters**: The spec is the source of truth. A later reader (or `/check verify`) following the spec will test or document a route that is not the one proven, and the LinkedIn credential URL a student copies depends on it.
**Suggested fix**: Update AC-4, AC-5, the API table and value sourcing to the proven route (or also prove `/certificate/<name>` in the test if it is meant to work). Tick the guest-open follow-up at line 183, which the test now covers.

### 🟡 The "names the quiz" assertion is vacuous, `tools/tests/test_content.py:115`
**Problem**: `assert "quiz 'q1'" in problems[0] or "passing_percentage" in problems[0]` always passes because the next line already requires `passing_percentage`. The quiz name is never actually checked.
**Why it matters**: AC-1 requires the refusal to name the quiz; a regression that drops the name would go unnoticed.
**Suggested fix**: Assert `"quiz 'q1'" in problems[0]` on its own.

### 🟡 Rounding rule stated as fact but not proven by a test or recorded in the spec, `README.md:124`
**Problem**: The README says 79.5% is stored as 79 and fails. Build step 1 asked the probe to record this in the spec too, but the spec's tradeoffs (line 174) still say "may be cut to 79 ... or rounded to 80", and the integration test only probes 60% and 80% (whole-number scores from 5 questions).
**Why it matters**: Students and admins rely on the README for the boundary; if the probe result was wrong or the LMS changes on upgrade, nothing catches it.
**Suggested fix**: Record the probe result in the spec, and if practical add an integration case with a non-whole score just under 80 (for example a quiz whose question count gives 79.x%).

### 🟡 AC-7 "still opens it when published" after removal is not exercised, `tools/tests/test_pass_certificate_integration.py:330`
**Problem**: The removed-learner test opens the certificate as the owner while it is private (it was unpublished in the previous test). The published-after-removal case in AC-7 is not covered.
**Why it matters**: Small gap; the guest path is covered elsewhere, so the risk is low.
**Suggested fix**: Publish as admin, open as the removed owner (and as guest), then unpublish, inside this test.

## Nits
- ⚪ `docs/specs/0010-quiz-pass-rules-and-certificate.md:190`, follow-up "Update 0004 AC-8 and scope feature 9" is done in this change but still unticked.
- ⚪ `tools/tests/test_pass_certificate_integration.py:121-124`, asserts in the fixture's `finally` can mask the original test failure; consider reporting the leftovers without raising over an in-flight error.
- ⚪ `tools/tests/test_pass_certificate_integration.py:18`, imports private helpers (`_run_script`, `_site`, `_sql`) from another test module; a shared `conftest.py` or helper module would be cleaner.

## Strengths
- `_warn_if_stranded` is minimal, side effect free beyond one log line, uses `json.dumps` for safe quoting, logs no secret, and does one cheap `exists` lookup only for rows at 100%; the parametrized unit test covers all three branches (warn, under 100, certificate held) and asserts the exact line.
- The integration test drives the real LMS over HTTPS with per-user API keys, so the real permission checks apply, and it checks negative paths precisely (fourth attempt not stored, other student's rows untouched, student 403 on publish and delete, cleanup verified).
- The floor is a named exported constant beside the defaults, with boundary tests at -5, 0, 1, 79, 80, 100, 101.

## Test coverage
New logic is covered: the 80 floor (unit, boundaries both sides), the stranded warning (unit, three branches with the stubbed Frappe), and AC-1 to AC-7 live (integration marker). Gaps are the vacuous quiz-name assertion, the unproven rounding rule, and the published-after-removal case listed above.
