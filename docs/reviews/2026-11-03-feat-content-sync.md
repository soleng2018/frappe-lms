# Review, feat/content-sync, 2026-11-03

**Reviewed by**: claude-opus-5-5 (author on a different model)
**Scope**: 39 files, branch vs main (plus uncommitted changes)
**Verdict**: Changes requested

## Summary
The branch adds the spec 0005 content sync: a YAML loader with all-at-once problem reporting, a pure two-phase planner (`plan_creates` then `plan_sync`), a thin `httpx` LMS client with read retries and duplicate-key recovery, and the `sync [--check]` command, backed by an in-memory fake LMS and a live integration test. The design follows the spec closely and the code is clean and well tested (403 unit tests pass). One real idempotency bug: when a whole chapter is removed from git, its lessons are reported as detached on every later run, so `sync` never says `nothing to change` and `sync --check` exits 1 forever. A few smaller gaps follow.

## Major

### 🟠 Lessons of a removed chapter are "detached" on every run, `tools/src/nile_tools/plan.py:403`
**Problem**: `_detached` counts a lesson as attached when its name appears in the `lessons` table of *any* fetched chapter, including a chapter that was itself detached. `plan_sync` only rewrites the tables of chapters still in git (`plan.py:346`), so the detached chapter's table keeps its rows and those lessons stay "attached" forever. Reproduced with the unit test fake: remove `ch2` from `course()`, run sync three times. Run 2 prints `detached Course Lesson lab`, `detached Course Lesson lq`, `0 created, 0 updated, 2 detached`. `--check` then exits 1 with `would detach ...` on every run.
**Why it matters**: Breaks AC-2 (an unchanged rerun must say `nothing to change`) and AC-6 (`--check` on a clean state must exit 0). `outline_changed` also returns true every run, so progress is recomputed on every sync. Any CI or operator use of `--check` as a gate fails permanently after a chapter is removed.
**Suggested fix**: Build `in_lessons` only from the chapters that are still in the course outline (the rows of `found.course["chapters"]` minus chapters being detached), or treat a lesson as detached only when it is in the table of a chapter git keeps. Add a `test_sync` rerun test for whole-chapter removal next to `test_a_rerun_after_a_removal_has_nothing_left_to_detach`.

## Minor

### 🟡 Progress recompute is not resumable, `tools/src/nile_tools/sync.py:236`
**Problem**: Progress is recomputed only when `outline_changed(creates, actions)` is true for *this* run. If a run writes the outline and then fails (or is interrupted) before `_recompute_progress`, the next run sees no outline change and never fixes stored progress.
**Why it matters**: The spec says each run can stop anywhere and the next run finishes the job (Decision; AC-5). A student who had already completed every remaining lesson keeps a stale `progress` below 100 until some later outline change.
**Suggested fix**: Always run the recompute in a normal sync (it is two list calls and writes only rows that differ), or compare stored progress as part of the plan.

### 🟡 Lookup by `nile_key` is not scoped to the course, `tools/src/nile_tools/sync.py:66`
**Problem**: `read_state` merges chapters, lessons and quizzes found by `course` with those found by `nile_key in [...]` across the whole site. A record with a matching key in another course is pulled in, and `plan_sync` then rewrites its `course`/`chapter` link to this course.
**Why it matters**: The Key invariants say a second course (feature 11) is never touched. Today there is one course, so this is latent, but reusing a key in a second course would silently move its records rather than fail.
**Suggested fix**: Keep the key lookup (it is needed for quizzes, which are created without `course`), but report a keyed record whose `course` is set to a different course as a problem instead of adopting it. At minimum note this in spec 0005's Follow-up for feature 11.

### 🟡 Only three fields are normalised, `tools/src/nile_tools/plan.py:53`
**Problem**: `_RICH` covers `description`, `question` and `body`. Titles, `short_introduction` and `option_1..4` are compared raw. The build task 1 probe only established escaping for `description` and `question`. If Frappe's `sanitize_html` also escapes `&` in these fields (I am not certain it does for every field type), any title or option with `&` would show as drift and be rewritten on every run.
**Why it matters**: A perpetual update would break AC-2 for an ordinary title like "Q&A".
**Suggested fix**: Add a title and an option containing `&` (and `<`) to the integration test content. If either comes back escaped, normalise every text field the sync writes.

### 🟡 Content problems mix file-named and unnamed lines, and double-report, `tools/src/nile_tools/contentfile.py:189`
**Problem**: The uncommitted change runs `check_course` even when the reader already found problems. That fixes the hiding problem the new tests target, but a non-text value now yields two lines: `course.yaml: chapter: key must be text, found bool False` and `chapter nile_key is empty`. A numeric video id also yields a second `youtube is ''` line. `check_course` lines also lack the `course.yaml:` prefix that AC-3 asks for ("A bad file names the file and the key").
**Why it matters**: The output is noisy and the derived line points at an empty key rather than the real cause. Not wrong, but harder to act on.
**Suggested fix**: Prefix `check_course` output with the file name in `load_course`. Suppress the derived duplicates, either by having the reader return a sentinel the check skips or by dropping the empty-key and empty-youtube lines when the reader already flagged that field.

## Nits
- ⚪ `tools/src/nile_tools/cli.py:111`, the `_require` generator stops at the first missing key; AGENTS.md asks to name every bad key at once (same pattern as `whoami`).
- ⚪ `tools/src/nile_tools/cli.py:115`, the `httpx.Client` from `lms.connect` is never closed; use it as a context manager or close it in a `finally`.
- ⚪ `tools/src/nile_tools/plan.py:247`, `payload` is used by `sync.py` but is missing from `__all__`.
- ⚪ `tools/src/nile_tools/plan.py:338`, `_by_key(found.lessons)` / `_by_key(found.chapters)` / `_by_key(found.quizzes)` are rebuilt inside loops; build them once.
- ⚪ `tools/src/nile_tools/contentfile.py:70`, a missing field reads `found NoneType None`; "is missing" would read better.
- ⚪ `tools/tests/fake_lms.py:43`, a third quiz with the same title gets `<slug>-2` again and silently overwrites the second quiz in the store. Number the suffix the way LMS does, so a future test does not pass or fail for the wrong reason. Also `counter_writes` is set outside `__init__` (line 73).
- ⚪ `tools/src/nile_tools/contentfile.py:37`, `_Reader` is a small mutable class; acceptable since it is local to one load, but a function returning `(value, problems)` would match the functional style rule more closely.

## Strengths
- The planner is pure and two-phase exactly as the spec describes. Every name comes from a create response, and `Ref` resolution makes the dependency order explicit and testable.
- The LMS client is careful: reads retry, writes are never retried, a duplicate `nile_key` is recovered by fetching by key, and errors name the record, URL, status, `exc_type` and decoded message without headers or secrets.
- `FakeLms` models Frappe's escaping, child-table stripping in list responses, quiz slug naming and duplicate errors. The sync tests use it to check behaviour (write order, idempotency, failure and resume, batches, progress), not mocks.

## Test coverage
Strong overall: loader edge cases (YAML booleans and numbers, path escape, non-UTF-8, every choice-question rule), planner diffs and detaches, sync end-to-end against the fake (create, rerun, rename, LMS edit, check mode, removal, progress, batches, mid-run failure and resume), client error decoding with `MockTransport`, and a live `integration` test. Gaps: no rerun test after removing a whole chapter (it would have caught the Major); no test that progress gets fixed on a run after an interrupted outline write; no test for text fields other than `description`/`question` carrying `&`.
