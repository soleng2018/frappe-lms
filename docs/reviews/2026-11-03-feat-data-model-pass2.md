# Review, feat/data-model, 2026-11-03 (pass 2)

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 14 files, branch vs main (plus uncommitted fixes)
**Verdict**: Approve with nits

## Summary
This pass checks the fixes for the first review's blocker and two majors. All three are fixed correctly.
The Custom DocPerm fixture now restates the five LMS rows for LMS Quiz Submission. I compared it field by
field with the `permissions` array in the running container's `lms_quiz_submission.json`, and the only
difference is `delete` on Moderator. `drift.compare` turns `found` into a tuple before it reads it, and
generator tests cover that. The integration test now pins every custom row, checks the total row count,
and asserts that a student reads their own submission and lists only their own. Unit tests (305), ruff
and mypy all pass. What remains is the four minors carried over from pass 1, plus one new minor about the
fixture drifting from upstream LMS.

## Minor

### 🟡 The restated LMS rows can silently fall behind an LMS upgrade, `apps/nile_auth/nile_auth/fixtures/custom_docperm.json:1`
**Problem**: Once Custom DocPerm rows exist, Frappe ignores the doctype's standard DocPerm. If a later LMS
tag changes or adds a standard row for LMS Quiz Submission, the fixture keeps hiding the change. The
integration test (`tools/tests/test_data_model_integration.py:171`) pins the fixture against itself, not
against `tabDocPerm`. It also checks only read, write, delete and if_owner, not
report/export/print/email/share/create.
**Suggested fix**: Add an integration assertion that every `tabDocPerm` row for LMS Quiz Submission equals
its `nile-` Custom DocPerm row on all flag columns, with Moderator `delete` as the only allowed difference.
That way an LMS pin bump fails loudly.

### 🟡 `lesson_body` raises bare `ValueError`, `tools/src/nile_tools/content.py:116` (carried over)
Still open from pass 1. Use one consistent content error type, or document that `ValueError` is it.

### 🟡 `lesson_body` trusts its inputs to be macro safe, `tools/src/nile_tools/content.py:113` (carried over)
Still open from pass 1. Validate the video id with `_VIDEO_ID` here too, and refuse a quiz name that contains `"` or `}`.

### 🟡 `Record` is frozen but holds a mutable `Mapping`, `tools/src/nile_tools/drift.py:15` (carried over)
Still open from pass 1.

### 🟡 Duplicate `(doctype, key)` in `found` collapse silently, `tools/src/nile_tools/drift.py:51` (carried over)
Still open from pass 1. Report the duplicates, or document why the unique index rules them out.

## Nits
- ⚪ `tools/tests/test_data_model_integration.py:250`: `len(...) == 1` would also pass if the one member value were another student's. Assert that it equals the s2 email (or that s1 is absent).
- ⚪ `docs/scope/scope.md:96`: the "Review it" box was ticked while the first review was Blocked. Tick it only once a review passes. This pass now justifies the tick.
- ⚪ Pass 1 nits about the inline `BEHAVIOUR_SCRIPT`, the wrapped assert comment, and `__all__` in `constants.py` are unchanged.

## Strengths
- The blocker fix is exact. The fixture matches upstream LMS v2.68.0 permissions flag for flag. The README and spec 0004 (AC-6 and the security model) now explain the Frappe rule that a single Custom DocPerm row replaces all standard rows, so the next reader will not repeat the mistake.
- The total row count check (`count(*) == 5`, not limited to `nile-%`) also catches a hand-added row in Role Permission Manager that would change access.
- The drift fix is minimal and its comment explains why. The generator tests cover both sides at once.
- The new content tests cover the video id edges (10 and 12 characters, illegal characters, all `-` and all `_`), blank keys at every level, and every bad video named at once.

## Test coverage
Every fix has a test. The generator input to `compare` has two unit tests. A student's own submission read
and list are asserted live, and the full permission row set is pinned. One gap remains: nothing ties the
fixture to the upstream standard rows (first minor). Unit tests (305), ruff and mypy are clean. I did not
re-run the integration suite (the author reports 25 passing on the live site with the fix deployed).
