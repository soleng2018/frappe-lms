# Review, feat/content-sync (second pass), 2026-11-03

**Reviewed by**: claude-opus-5-5 (second, independent pass; author on a different model)
**Scope**: 39 files, branch vs main (plus uncommitted changes)
**Verdict**: Changes requested

## Summary
The branch adds the spec 0005 content sync: a YAML loader, a pure two phase planner, a thin `httpx` LMS client, and `sync [--check]`, all tested against an in-memory fake LMS (403 unit tests pass, ruff and mypy clean). I reviewed the code on my own first and then compared with the first pass. The first pass's one Major is real. I reproduced it on its own: after a whole chapter is removed, its lessons are reported as detached on every later run. This pass adds two Minors the first pass missed. A lesson moved between chapters is reported as a `removed unmanaged row`. The fake LMS escapes `&` in plain text, which Frappe v16 does not do. I also checked the `&` normalisation claim against Frappe's source. The claim is only partly right, so the first pass's `_RICH` finding needs a different framing.

## Major

### 🟠 Lessons of a removed chapter are "detached" on every run, `tools/src/nile_tools/plan.py:403`
**Problem**: `_detached` builds `in_lessons` from the `lessons` table of every fetched chapter. That includes a chapter that is itself being detached, because `read_state` fetches chapters by `course` and a detached chapter keeps `course`. `plan_sync` rewrites the tables of git chapters only (`plan.py:346`). So the removed chapter keeps its rows, and its lessons count as "attached" forever. Reproduced on its own with the `test_sync` fixtures: drop `ch2` and `q2`, then sync three times. Runs 2 and 3 print `detached Course Lesson lab`, `detached Course Lesson lq`, `0 created, 0 updated, 2 detached`. `--check` exits 1 with `would detach ...` every time. Removing only one lesson from a chapter that stays (control case) settles to `nothing to change` as it should.
**Why it matters**: This breaks AC-2 (an unchanged rerun says `nothing to change`) and AC-6 (`--check` exits 0 on a clean state). Any gate built on `--check` stays red for good after a chapter is removed. `outline_changed` is also true on every run, so the enrollment and progress lists are read again each time.
**Suggested fix**: Count a lesson as attached only if it is in the table of a chapter that is still in the course outline after this sync. That means a chapter in git, or one listed in `found.course["chapters"]` and not being detached. Add a `test_sync` rerun test for removing a whole chapter.

## Minor

### 🟡 A lesson moved between chapters is reported as a "removed unmanaged row", `tools/src/nile_tools/plan.py:355`
**Problem**: `_dropped_rows(found_rows, rows, detached_names)` labels every row that leaves a chapter's table as unmanaged, unless that row is detached. A managed lesson that moved to another chapter is neither, so it is mislabelled. Reproduced: move `v` from `ch1` to `ch2`. Both `--check` and `sync` print `Course Chapter ch1: removed unmanaged row Cou-0008`, but `Cou-0008` is the keyed lesson `v`. The move itself applies correctly, and the rerun is clean.
**Why it matters**: Spec 0005 uses `removed unmanaged row` to warn that a Desk-made record was dropped. A false warning makes the operator look for lost content that does not exist, and it teaches them to ignore the real warning.
**Suggested fix**: Skip rows that belong to any keyed record (any name in `lessons` / `chapters`), not only detached ones. Only rows with no `nile_key` should get this note. `test_plan.py:214` can assert `notes == ()` for the move.

### 🟡 The `&` normalisation premise is only partly right, and the fake models it wrongly, `tools/src/nile_tools/plan.py:52`, `tools/tests/fake_lms.py:79`
**Problem**: I checked the claim against the Frappe v16 source in the running `backend` container (read only). `Document._sanitize_content` (`frappe/model/document.py` ~3322) skips any value with no `<` or `>`. `sanitize_html` returns the value unchanged unless `has_html_tags` matches `<[a-zA-Z][^>]*>`. I ran the pure function directly:
- `'A & B'` → `'A & B'`
- `'a < b & c'` → `'a < b & c'`
- `'<p>A & B</p>'` → `'<p>A &amp; B</p>'`
- `'Use <b>bold</b> & more'` → `'Use <b>bold</b> &amp; more'`

I found no escaping in the REST layer (`api/v1.py` `get_request_form_data`) or in the LMS controllers. So Frappe does **not** escape `&` in plain text. It escapes `&` (and rewrites or strips markup) only when the value holds an HTML tag, and this applies to every non-`Code` field, `title` and `option_N` included, not just the three in `_RICH`. `FakeLms` escapes `&` in `description` and `question` every time, so `test_sync.py:344` (`"A &amp; B"`) pins a behaviour the real site does not have. Spec 0005's probe note ("come back with `&` as `&amp;`") likely came from Desk-entered (Quill, `<p>`-wrapped) values.
**Verdict on the claim**: Not confirmed as stated. The normalise rule is still safe: `html.unescape` on both sides converges whether or not Frappe escaped. Plain titles like "Q&A" do not drift. The real gap is any authored value that holds a tag (a lab body with `<details>`, `<br>`, `<img ...>`, or a description with `<b>`). `nh3` can rewrite or strip such a tag, so it would drift on every run.
**Suggested fix**: Make the fake escape only when the value matches the tag pattern, and fix the comment at `plan.py:52` and the spec Follow-up note. Either have the loader refuse raw HTML tags in text fields, or run the git side through the same sanitiser rules (or compare after stripping tags). Add one integration case with a tag in a lab body.

### 🟡 Progress recompute is not resumable, `tools/src/nile_tools/sync.py:236` (confirms first pass)
The recompute runs only when this run changed the outline. If a run stops after the outline `PUT` and before `_recompute_progress`, the next run never fixes stored progress. This contradicts the Decision ("each run can stop anywhere and the next run finishes the job"). Run it on every normal sync, which costs two list calls and writes only rows that differ.

### 🟡 Lookup by `nile_key` is not scoped to the course, `tools/src/nile_tools/sync.py:66` (confirms first pass)
The `nile_key in [...]` lookups are site wide, so a keyed record in another course would be adopted and moved. This is latent with one course. Flag a mismatched `course` instead of adopting the record, or note it in the Follow-up for feature 11.

### 🟡 Content problems double report and lack the file prefix, `tools/src/nile_tools/contentfile.py:189` (confirms first pass)
A non-text key produces both `course.yaml: chapter: key must be text ...` and `chapter nile_key is empty`. Lines from `check_course` carry no `course.yaml:` prefix (AC-3: "names the file and the key"). Prefix them in `load_course`, and drop the derived empty-field lines when the reader already flagged that field.

## Nits
- ⚪ `tools/src/nile_tools/cli.py:112`, `_require` runs as a generator and stops at the first missing key, but AGENTS.md says to name every bad key at once (confirms first pass).
- ⚪ `tools/src/nile_tools/cli.py:115`, the `httpx.Client` is never closed (confirms first pass).
- ⚪ `tools/src/nile_tools/plan.py:247`, `payload` is public and used by `sync.py` but missing from `__all__` (confirms first pass).
- ⚪ `tools/src/nile_tools/plan.py:338`, `_by_key(found.lessons|chapters|quizzes)` is rebuilt inside loops (confirms first pass).
- ⚪ `tools/src/nile_tools/contentfile.py:70`, a missing field reads `found NoneType None` (confirms first pass).
- ⚪ `tools/tests/fake_lms.py:43`, a third quiz with the same title reuses `<slug>-2` and overwrites the second; `counter_writes` is set outside `__init__` (confirms first pass).
- ⚪ `tools/src/nile_tools/contentfile.py:37`, `_Reader` is a small mutable class (confirms first pass; acceptable).
- ⚪ `tools/src/nile_tools/plan.py:288`, `wanted` in `_question_plan` serves only as a None sentinel, and the rows are rebuilt from `marks` (new). Use the result directly or say so in the name.
- ⚪ `tools/src/nile_tools/sync.py:56`, every run (including `--check`) does a `GET` for each LMS Batch before it knows the course exists (new). This is fine at this scale, but a `fields=["name","courses.course"]` list or a lazy fetch would avoid an N+1 once there are many batches.

## Strengths
- The planner is pure and testable, and `Ref` resolution makes the create order explicit. Every LMS name comes from a create response, never from a title.
- The client is careful: reads retry, writes never do, a duplicate `nile_key` is recovered by key, and errors name the record, URL, status, `exc_type` and message without the header or secret.
- The sync tests drive behaviour through a realistic fake (write order, rerun, mid-run failure and resume, batches, progress) rather than through mocks. The control cases I ran (single lesson removal, lesson move) converge on the next run.

## Test coverage
Strong: 403 unit tests pass, and ruff and mypy are clean. The integration test carries `pytestmark = pytest.mark.integration`. Gaps:
- No rerun test after removing a whole chapter. It would have caught the Major.
- No assertion that a lesson move adds no `removed unmanaged row` note.
- No test that progress is fixed on a run after an interrupted outline write.
- `FakeLms` escapes `&` in plain text, which Frappe does not do, so the escaping tests prove the normaliser against the wrong input. No test covers a value with an HTML tag, which is the case that can actually drift.
