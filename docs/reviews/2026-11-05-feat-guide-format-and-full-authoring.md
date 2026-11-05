# Review, feat/guide-format-and-full-authoring, 2026-11-05

**Reviewed by**: claude-opus-5-5 (fresh reviewer context; author model not stated)
**Scope**: 37 files, branch vs main (committed since 3f4e215 plus uncommitted)
**Verdict**: Approve with nits

## Summary
The branch replaces the single `content/course.yaml` with `content/<course-key>/` folders. Lessons are now built from ordered text, video and quiz blocks. It adds an offline catalog check (`content check`), a scaffold (`content new`), image upload with hashed public names, per option explanations, and a many course `sync` that keeps each course isolated. It also adds a pre-commit hook. The code follows spec 0011 closely and is well tested (707 unit tests pass, ruff check and mypy are clean). Every problem is collected and reported at once, and the cross course and LMS side blocks behave as the spec says. I found no blockers or majors. The main issues are small: `content new` breaks AC-9 for numeric or boolean looking keys, the markdown scan refuses some common link forms, `held_elsewhere` does not cover questions, and `ruff format` fails on `sync.py`.

## Minor

### 🟡 `content new` writes an unquoted course key, so some keys fail `content check`, `tools/src/nile_tools/scaffold.py:245`
**Problem**: `key: {key}` is written without quotes. YAML reads `content new 2026` as an int, and `content new yes`, `no`, `on`, `off`, `true` or `null` as a bool or null. I reproduced it: `2026/course.yaml: key: must be text, found int 2026`, and the same for `yes`.
**Why it matters**: AC-9 says the output "passes `content check` with no edit". A numeric course key such as a year or `101` is a plausible choice. The scaffold accepts the key (it passes `_KEY_RULE`) and then writes a folder that fails at once.
**Suggested fix**: Quote the key with `json.dumps`, as the title already is. Add `2026` and `yes` to the scaffold test.

### 🟡 The markdown scan refuses a linked image and non http links, `tools/src/nile_tools/markdown.py:22,29`
**Problem**: `[![logo](../images/a.png)](https://x.org)` is a common way to make an image clickable. `_LINK` matches its inner part `[![logo](../images/a.png)` as a link to `../images/a.png`, so the check reports "a local link to '../images/a.png' is not supported" (reproduced). Separately, `mailto:`, `tel:` and `ftp:` links are counted as local and refused, because `_NOT_LOCAL` lists only `http:`, `https:`, `data:`, `/` and `#`. That follows spec AC-4 as written, but it is likely not what an author expects.
**Why it matters**: These are false refusals of valid content. They fail the commit hook, and the authoring guide offers no way around them.
**Suggested fix**: In `_LINK`, skip a match whose text starts with `!`, or drop link refs whose span lies inside an image ref. Treat any `scheme:` prefix as not local, and update AC-4 and `docs/authoring.md` to match.

### 🟡 `held_elsewhere` does not check question keys, `tools/src/nile_tools/plan.py:434-452`
**Problem**: Only chapters, lessons and quizzes are checked against another LMS course. A question can still be held elsewhere: its folder was removed from git but the course stays in the LMS (AC-7 lists such courses), or it was made by hand. In that case `read_state` finds the question by `nile_key`, and `plan_sync` overwrites its text and options and adds it to this course's quiz.
**Why it matters**: Another course's live quiz question changes without notice. AC-7 says "a record key that the LMS holds under a different course" should block the course.
**Suggested fix**: Block when a found question with a wanted key sits in a quiz whose `course` is not this course. The quiz rows are already read in `read_state`. Add a test next to `test_a_key_held_under_another_course_names_both`.

### 🟡 `ruff format --check` fails on `sync.py`, `tools/src/nile_tools/sync.py:313`
**Problem**: The `blocked = {...}` comprehension is not in ruff format. `make lint` and the pre-commit hook fail on the current tree.
**Suggested fix**: Run `make fmt` before committing.

### 🟡 The cover image is never cleared, and its write to the LMS is not unit tested, `tools/src/nile_tools/plan.py:157`
**Problem**: The course `image` field is added only when the cover's URL is known. If `image:` is removed from `course.yaml`, the LMS keeps the old cover with no difference reported. This is unlike `youtube` and `quiz_id`, which are cleared. The tests check that the cover is loaded (`test_the_cover_image`), but no unit test shows the uploaded URL being written to the course `image` field on create or update.
**Suggested fix**: Decide whether a removed cover should clear the field, and record that in the spec. Add a `test_sync_all` case for the cover, as there is for a guide image.

### 🟡 The spec's probe answers are unrecorded, `docs/specs/0011-guide-format-and-full-authoring/index.md:250`
**Problem**: Build task 1 is ticked, but the follow-up says no answers were recorded for the combined body, the public image, the `upload_file` behavior (whether the same bytes give the same URL, and whether Frappe keeps `file_name`) or the size limits. The image lookup by `file_name` depends on those answers.
**Why it matters**: The second run idempotency of image upload rests on Frappe behavior that only the live integration test proves. The fake LMS assumes it.
**Suggested fix**: Run the live two course integration test twice, then record the results in Follow-up before merge.

## Nits
- ⚪ `tools/src/nile_tools/sync.py:236`: in `--check`, a missing image is counted once, but AC-4 says it counts "as a difference for every lesson that uses it". The exit code is the same, only the count line differs.
- ⚪ `tools/src/nile_tools/contentfile.py:75`: `_Reader` is a mutable class. It is defensible as a problem collector, but AGENTS.md prefers functions.
- ⚪ `tools/src/nile_tools/scaffold.py:237`: `default_title` is public (no underscore) but not in `__all__`.
- ⚪ `tools/src/nile_tools/scaffold.py:294-298`: if a write fails after `mkdir`, a partial folder is left behind, though the docstring says "write nothing".
- ⚪ `tools/src/nile_tools/coursecheck.py`: an empty string course, chapter or lesson title (`title: ""`) is not refused, so the LMS rejects it at sync time instead.
- ⚪ `tools/src/nile_tools/contentfile.py:320`: a `text:` block can name any file, such as a `.yaml`. AC-2 says it must be a markdown file.
- ⚪ `docs/authoring.md:142-180`: the messages table leaves out the sync side block reasons (`refusing to sync: ... held by LMS course`, the title clash) and `a ... key is empty`.
- ⚪ `tools/AGENTS.md`: the new modules (`coursecheck`, `markdown`, `images`, `scaffold`) are not listed yet. `/sync` owns that file.

## Strengths
- Every problem is collected at once, with a precise `<where>` key path. The catalog and the `ready` and `blocked` split make the course isolation in `sync_all` simple and correct.
- The pure modules (`markdown`, `images`, `coursecheck`, `content.lesson_body`) are kept apart from I/O. Path traversal and symlink escape are handled by resolving against the course root.
- The tests cover the spec's critical scenarios: isolation under a 500 error, title and held elsewhere blocks, idempotent image upload, changed images, the `--check` upload rule, the scaffold passing the check, and explanation fields.

## Test coverage
Coverage is strong. 707 unit tests pass, and the new `test_sync_all.py`, `test_markdown.py`, `test_scaffold.py` and the reworked `test_contentfile.py` cover AC-1 to AC-9 and AC-11 at the unit level. Gaps: writing the cover image to the LMS, the linked image form and `mailto:` links, a numeric or boolean scaffold key, a question held by another course, and the exit code for a legacy stray file in `sync` (it is covered for `content check`).
