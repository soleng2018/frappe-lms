# Review, feat/data-model, 2026-11-03

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 14 files, branch vs main (plus uncommitted tests in `tools/tests/test_content.py` and a scope tick)
**Verdict**: Blocked

## Summary
The branch adds the spec 0004 data model: `nile_key` / `nile_group` custom field fixtures, a Moderator
delete permission fixture, the frozen content model with an every-problem-at-once check and the
`lesson_body` macro builder, a pure drift compare, and a strong live site integration suite. The tools
code is clean, typed, and well tested (303 unit tests pass, ruff and mypy clean). The headline problem
is the Custom DocPerm fixture: in Frappe a single Custom DocPerm row for a doctype replaces *all* of its
standard DocPerms, so the fixture silently strips System Manager, LMS Student (own read), Course Creator
and Batch Evaluator of every permission on LMS Quiz Submission. That breaks AC-7, and the README then
records the broken state as LMS behaviour.

## Blockers

### 🔴 One Custom DocPerm row wipes every standard permission on LMS Quiz Submission, `apps/nile_auth/nile_auth/fixtures/custom_docperm.json:2`
**Problem**: `frappe.permissions.get_valid_perms` (and `Meta` loading) uses only Custom DocPerm rows for
any doctype that has at least one. The LMS doctype ships DocPerms for System Manager (full), LMS Student
(read, `if_owner`), Moderator, Course Creator and Batch Evaluator (read). The fixture adds a single
Moderator row, so after `bench migrate` the only role with any permission on LMS Quiz Submission is
Moderator. Confirmed on the live site: `tabCustom DocPerm` holds exactly one row for `LMS Quiz Submission`.
**Why it matters**: AC-7 requires a student to read their own attempts; they now cannot. System Manager
(non Administrator), Course Creator and Batch Evaluator lose read too, which can break LMS screens and
reports that read submissions without `ignore_permissions`. The live test recorded
`AC7_s2_reads_own_submission` (`tools/tests/live_scripts/lms_behaviour.pyscript:135`) but no test asserts
it, and `apps/nile_auth/README.md:35` misattributes the result to LMS ("the doctype gives LMS Student no
read"), so the regression is documented as upstream behaviour.
**Suggested fix**: Either ship the full permission set for LMS Quiz Submission as Custom DocPerm rows
(copy every standard row, plus `delete` on the Moderator row), each with an explicit `nile-` name, or
avoid Custom DocPerm entirely and grant the delete another way (for example a `has_permission` hook in
`nile_auth`, or a whitelisted reset method that checks Moderator and deletes with `ignore_permissions`).
Add integration assertions that a student reads their own submission and System Manager keeps read and
delete, and correct the README line.

## Major

### 🟠 `compare` iterates `found` twice, so a generator gives an empty `unmanaged`, `tools/src/nile_tools/drift.py:50`
**Problem**: `found` is typed `Iterable[Record]`, consumed once to build `in_lms` and again at line 58
for the unmanaged records. A generator or iterator passed by the caller (natural for a streaming
LMS fetch in feature 8) yields nothing the second time, so `unmanaged` is silently `()`.
**Why it matters**: `sync --check` (AC-9) would report no hand made records when there are some, with no
error. Silent wrong output in a check command.
**Suggested fix**: Materialise `found` into a tuple at the top of `compare`, or type both parameters as
`Sequence[Record]`. Add a unit test passing a generator.

### 🟠 Integration test asserts a permission that holds trivially and omits the one AC-7 needs, `tools/tests/test_data_model_integration.py:185`
**Problem**: `student_delete is False` is true with or without the fixture, while the own submission read
recorded by the script is not asserted, and no assertion checks that roles other than Moderator keep
their standard access. This is why the blocker above went unnoticed.
**Suggested fix**: Assert `AC7_s2_reads_own_submission` is True, and that System Manager still has read
and delete on LMS Quiz Submission.

## Minor

### 🟡 `lesson_body` raises bare `ValueError`, `tools/src/nile_tools/content.py:116`
**Problem**: AGENTS.md asks for one consistent error type; the package already has `ConfigError`. A
content specific error (or reuse) would let the sync handle failures uniformly.
**Suggested fix**: Raise a named content error, or document that `ValueError` is the content module's type.

### 🟡 `lesson_body` trusts its inputs to be macro safe, `tools/src/nile_tools/content.py:113`
**Problem**: The video id and quiz name are interpolated into a Jinja macro inside double quotes.
The id is only validated by `check_course`, not here, so a caller that skips the check (or a quiz name
with a `"`) produces a broken or injected body.
**Suggested fix**: Validate the id with `_VIDEO_ID` inside `lesson_body` too, and refuse a quiz name
containing `"` or `}`.

### 🟡 `Record` is frozen but holds a mutable `Mapping`, `tools/src/nile_tools/drift.py:15`
**Problem**: The frozen dataclass generates `__hash__`, which raises `TypeError` on a dict field, and the
dict can still be mutated, against the immutable data rule.
**Suggested fix**: Wrap in `types.MappingProxyType` or store a tuple of pairs; or set `eq=True, unsafe_hash=False` deliberately and note it.

### 🟡 Duplicate keys in `found` collapse silently, `tools/src/nile_tools/drift.py:50`
**Problem**: If the LMS holds two records with one `(doctype, nile_key)` (possible before the unique index
exists, or across doctypes that share a table), the last wins and the other is never reported.
**Suggested fix**: Report duplicates, or document that the unique index makes them impossible.

## Nits
- ⚪ `tools/tests/test_data_model_integration.py:32`, the inline `BEHAVIOUR_SCRIPT` and the separate `.pyscript` file use two styles for the same job; move the inline one into `live_scripts/` too.
- ⚪ `tools/tests/test_data_model_integration.py:212`, the trailing comment forced an awkward wrapped assert; put the comment on its own line.
- ⚪ `apps/nile_auth/nile_auth/constants.py:1`, no `__all__`; fine for Frappe style, but a deliberate public set would match the project rule.

## Strengths
- `check_course` returns every problem at once with precise messages, and the unit tests cover each AC-8 rule, edges (1 and 100, 11 character ids), and blank keys.
- The live integration suite rolls back inside `bench console`, verifies nothing is left behind, and pins real LMS behaviour (quiz macro gating, attempt limits, certificate rules) with clear "if this fails, LMS changed" notes.
- Fixtures use explicit names so `bench migrate` re runs update rather than duplicate.

## Test coverage
Unit coverage of `content.py` and `drift.py` is thorough on behaviour (303 pass). Gaps: `compare` with a
generator input; `lesson_body` with an invalid id or unsafe quiz name. Integration: the permission
fixture's side effects on other roles and on a student's own submission read are not asserted.
