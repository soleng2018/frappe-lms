# 0005. Sync one course from git to the LMS with a planner that finds records by `nile_key`

**Date**: 2026-11-03
**Status**: Accepted
**Superseded in part**: by [0009](../0009-course-access-from-groups/index.md): the course is now created and kept unpublished (AC-1), and AC-8 (every batch gets the course) no longer applies.

## Summary

You write the course once in git, as one `content/course.yaml` plus a markdown file per lab guide. The `sync` command reads it, checks it, works out what the LMS needs (create, update, or detach), and then makes those changes through the LMS API. Every record is found by its `nile_key`, so running it twice changes nothing and renaming a title updates the same record. `sync --check` shows what would change without changing anything. This is the thin version for one course. The full authoring format comes with feature 11.

## Requirements

**User stories**:
- As the operator, I want to run one command that builds the course in the LMS from git so that I never click through the Desk to author content.
- As the operator, I want to run the command again after editing git and have the same records updated so that nothing is duplicated.
- As the operator, I want a dry run that lists what differs so that I can see an LMS edit before it is overwritten.

**Acceptance criteria**:
- **AC-1**: `sync` creates the course from `content/course.yaml` in the LMS: the course, its chapters, and every video, lab guide, and quiz lesson, with each quiz and its multiple choice questions. Every record carries its `nile_key`. The course is created published, with certification on and lesson order not enforced, as spec 0004 sets.
- **AC-2**: Running `sync` a second time on unchanged content makes no write and says so. Changing a title in git updates the same record; no duplicate appears.
- **AC-3**: The content check runs first. If the file cannot be read or any problem is found, the command prints every problem at once, writes nothing, and exits 1. A bad file names the file and the key. The loader requires text (not a number or true/false) for `key`, `title`, `youtube`, and question and option text, and rejects a `body_file` that is missing or points outside `content/`. A `Choices` question with fewer than two options, more than four, no correct option, or empty or repeated option text is a problem.
- **AC-4**: Lesson bodies follow spec 0004 AC-10 exactly. For a new quiz lesson, the quiz exists before the lesson gets its `quiz_id` and its `{{ Quiz("<quiz name>") }}` body, and the back link (`quiz.lesson` and `quiz.course`) is written last. A lesson never holds a quiz name that does not exist, and the name always comes from the LMS create response, never from the title. A video lesson body is `{{ YouTubeVideo("<id>") }}` and a lab lesson body is the markdown from git.
- **AC-5**: A lesson or chapter removed from git leaves the course outline and is unpublished where the record has such a field, but is not deleted. A quiz or question removed from git is detached and kept, and the output names it. Detach rules are in Key invariants. After any outline change, stored progress is made correct again (Sync flow step 7), so a student's progress can still reach 100 and never counts a detached lesson.
- **AC-6**: `sync --check` changes nothing. It lists every record git would create, every record it would detach, every record that differs from what git would write, and every LMS record in the course with no `nile_key`, and exits 1 if it lists anything, else 0. A normal `sync` prints each field it is about to overwrite as `LMS has X, git has Y` (long values such as lab bodies cut to one line), then overwrites it and carries on.
- **AC-7**: On the first failed write, `sync` stops, exits 1, and prints the record, the request URL, the HTTP status, Frappe's `exc_type`, and the decoded message, followed by the action lines already printed as what was done. It never prints a traceback, a header, or a secret. Running it again continues, because records are found by `nile_key`. A create that fails with a duplicate `nile_key` error is treated as "fetch it by key and continue", which covers a request that timed out after the server saved it.
- **AC-8**: After the course exists, `sync` makes sure every existing LMS Batch has one Batch Course row for it. A second run adds none.

## Decision

**Chosen option**: Option 1: a planner and a thin API client.

Add `content/course.yaml` as the source, a loader, a pure planner, a small `httpx` client for the LMS, and the `sync` and `sync --check` commands in `nile_tools`. No new config keys and no new dependencies. The run has two phases, ensure then converge: first create whatever is missing with only its required fields, then re-read and update everything else once every LMS name is known. Each run can stop anywhere and the next run finishes the job.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`)

## Feature design

**Data model sketch**: no new records and no new fields. It uses the records and `nile_key` fields from spec 0004. The model in `content.py` grows by two things: `Question` gains `options` (a tuple of `Option(text, correct)`, at most 4) and `Course` gains `short_introduction` and `description`. In the LMS, a question stores `question`, `type`, `option_1` to `option_4`, and `is_correct_1` to `is_correct_4` (LMS works out `multiple` itself). `marks` lives on the quiz's question row, not on the question.

**Content file** (`content/course.yaml`; lab bodies in `content/labs/<name>.md`):

```yaml
key: nile-workshop
title: Nile Workshop
short_introduction: ...
description: ...
chapters:
  - key: ch-concepts
    title: Concepts
    lessons:
      - {key: l-intro, type: video, title: Intro, youtube: dQw4w9WgXcQ}
      - {key: l-intro-quiz, type: quiz, title: Intro quiz, quiz: q-intro}
      - {key: l-lab1, type: lab, title: Lab 1, body_file: labs/lab1.md}
quizzes:
  - key: q-intro
    title: Intro quiz
    passing_percentage: 80   # optional, default 80
    max_attempts: 3          # optional, default 3
    questions:
      - key: q-intro-1
        text: ...
        options: [{text: A, correct: true}, {text: B}]
```

The loader uses `yaml.safe_load`, reads `body_file` relative to `content/`, and builds the frozen `Course`. `quiz.lesson_key` is filled from the lesson that names the quiz.

**Sync flow**:
1. Load the file, then `check_course`. Any problem: print all, exit 1, no network write.
2. Fetch the LMS records, scoped to this course: the course by `nile_key`; its chapters, lessons, and quizzes by `course`; the questions of those quizzes (a question has no `course` field, so it follows its quiz); the records in the course with no `nile_key` (the unmanaged ones); and every LMS Batch with its Batch Course rows.
3. Phase 1, ensure: create each missing record in dependency order with only its required fields: course, chapters, questions, quizzes (with their question rows, since the rows link to questions that must exist first), then lessons. Every LMS `name` comes from the create response, never from the title (LMS names a quiz from its title, so a second quiz with the same title gets a suffixed name).
4. Phase 2, converge: re-fetch, then the pure `plan_sync(course, found, batches)` returns an ordered tuple of actions now that every name is known: `Update(differences)` for fields, lesson bodies (via `lesson_body`), `quiz_id`, `quiz.lesson` and `quiz.course`, the outline tables and quiz question rows; `Detach`; `AddToBatch`; and the unmanaged list. A quiz lesson's `quiz_id`, `body`, and the quiz's `lesson` and `course` are all compared fields, so a run that stopped halfway finishes on the next run. Differences come from `drift.compare` on normalised values (below).
5. [x] `--check`: print the phase 1 creates that would happen, then the phase 2 differences, detaches, and unmanaged records for the records that exist. Exit 1 if there is any.
6. [x] Normal run: print each field being overwritten, then apply phase 1 and phase 2 in order.
7. [x] If the outline changed, make stored progress correct for the course's enrollments (build task 1 finds how LMS recomputes it; if it does not, set `progress` to completed lessons still in the outline over lessons in the outline, as a whole number).

**Compare rules**: a child table is compared as a tuple of linked names in row order (`chapters`, `lessons`, quiz `questions` with their `marks`, `instructors`), never as raw rows with `name`, `idx`, and `modified`. Rich text fields (`question`, `description`, lesson `body`) go through one pure normalise function on both sides (strip, unescape what Frappe escapes) so a round trip is equal; build task 1 settles its exact rules. A record that does not exist yet is a create, never drift.

**Write order inside phase 1**: course → chapters → questions → quizzes → lessons in file order (a video or lab lesson with its body and `youtube`; a quiz lesson with only its required fields). Phase 2 then sets the quiz lesson's `quiz_id` and macro body, the back link, and the two outline tables in file order. The outline tables are sent whole on every `PUT`. Moving a lesson to another chapter updates its `chapter` and rewrites both chapters' tables.

**API surface** (Frappe REST, as the service user; the host is `LMS_HOSTNAME`, the header is `Authorization: token <LMS_API_KEY>:<LMS_API_SECRET>`):

| Request | Used for | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `GET /api/resource/<DocType>` with `fields`, `filters`, `limit_page_length=0` | read the current records | doctype, filters on `nile_key` or `course` | list of records | token | 401, 403, 5xx |
| `GET /api/resource/<DocType>/<name>` | read child rows (outline, questions, batch courses) | name | one record | token | 404 |
| `POST /api/resource/<DocType>` | create | the fields in spec 0004 | the new record with its `name` | token | 409 or 417 duplicate `nile_key`, 403 |
| `PUT /api/resource/<DocType>/<name>` | update, set the back link, set outline rows, detach, add Batch Course row | changed fields only; a child table is sent whole, so for the outline send every row, and for Batch Course `GET` the batch first and send its existing rows (with `name`) plus the new one | the record | token | 404, 403, 417 |

**Value sourcing**:

| Action | Value produced | Source |
|---|---|---|
| Create or update any record | `nile_key` | the `key` in `course.yaml` |
| Create course | `title`, `short_introduction`, `description` | `course.yaml` |
| Create course | `published`=1, `status`=Approved, `enable_certification`=1, `enforce_lesson_completion`=0 | spec 0004 Feature design |
| Create course | `instructors` | `LMS_SERVICE_USER` from `.env` (the only user the tools know); confirmed or corrected by build task 1 |
| Create chapter or lesson | `title`, order | `course.yaml`, order of the lists |
| Video lesson | `youtube`, `body` | `youtube` id in the file; body from `lesson_body` |
| Lab lesson | `body` | the markdown file named by `body_file` |
| Quiz lesson | `quiz_id`, `body` | the quiz `name` LMS returned on create; body from `lesson_body` |
| Create quiz | `passing_percentage`, `max_attempts` | the file, else the named defaults 80 and 3 |
| Create quiz | `lesson`, `course` | the lesson's `name` after it is created; the course `name` |
| Create question | `question`, `type`, `option_1` to `option_4`, `is_correct_1` to `is_correct_4` | the file; option order is file order; type is `Choices` |
| Quiz question row | `marks` | the file; defaults to 1 |
| Recompute progress | `progress` per enrollment | LMS Course Progress rows for lessons still in the outline, over the lessons in the outline (only if LMS does not do it, per build task 1) |
| Error output | status, `exc_type`, message | the HTTP response and Frappe's error body, decoded |
| Add to batch | Batch Course row | every LMS Batch read in step 2; the course `name` |
| Detach | what to detach | records fetched in step 2 (scoped to this course) whose `nile_key` is not in the file |

**Key invariants**:
- A record is found only by `nile_key`, never by title.
- Nothing is written until the whole content check passes.
- Nothing is ever deleted. Detach means, per record type:
  - lesson or chapter: its row is removed from the outline table, and `published` is set to 0 only if build task 1 finds the field there
  - quiz: `lesson` is cleared and `course` is kept, so attempts stay attributable
  - question: its row is removed from the quiz
  - the old course after a key change: `published` is set to 0
- Rewriting an outline table also drops any row for a record made in the LMS with no `nile_key`; each one is printed as `removed unmanaged row`.
- Everything read, compared, and detached is scoped to this course, so a second course (feature 11) is never touched. Questions follow their quiz.
- Rich text compares through one normalise function, so an unchanged field never causes a write.
- Changing a quiz's `nile_key` makes a new quiz and detaches the old one. The lesson body then points to the new quiz, and students retake it, because their attempts stay on the old quiz.
- A video or quiz lesson body is always the macro from `lesson_body`, never authored.
- Changing a `nile_key` in git is a remove plus a create. Spec text warns about this.

**Security model**: the command runs as the service user from spec 0001, with the key and secret from `.env`. A 403 names the record type and URL. Lab markdown comes from git and is stored as the lesson body as is; the repo is the trust boundary. Output never includes the key, the secret, or the Authorization header, and failures print the URL without credentials. No personal data is handled.

**Configuration required**: none new. Uses `LMS_HOSTNAME`, `LMS_API_KEY`, `LMS_API_SECRET`, `LMS_SERVICE_USER`. The content path is fixed at `content/course.yaml` under the repo root, which the `tools` container already mounts.

**Output** (plain lines, for people): one line per change (`created Course Lesson l-intro`, `updated LMS Quiz q-intro: title`, `detached Course Lesson l-old`), then a one line count. Nothing changed prints `nothing to change`.

**Critical test scenarios**:
- Happy path: a clean site and a small valid file produce the course, chapters, lessons, quiz, and questions with bodies as spec 0004 says, verifies **AC-1**, **AC-4**.
- Idempotency: run twice, the second makes no write; rename a lesson title, the same record updates, verifies **AC-2**.
- Failure case: a file with a quiz that has no lesson and a repeated `nile_key` names both and writes nothing, verifies **AC-3**.
- Failure case: a removed lesson leaves the outline and is not deleted; a removed question stays in the LMS, verifies **AC-5**.
- Check mode: edit a lesson in the LMS, `--check` lists it and exits 1 and changes nothing; a lesson added in git is listed as a create and exits 1; clean state exits 0; a record made in the LMS with no key is listed as unmanaged, verifies **AC-6**
- Removal and progress: remove a lesson in git, sync, and a student who finished the rest reaches progress 100 and does not count the detached lesson, verifies **AC-5**
- File errors: a numeric video id, `no` as a key, or a `body_file` outside `content/` is named with its file and key, verifies **AC-3**.
- Failure case: the LMS returns 500 on the third write; the command stops, names the record, and a rerun finishes, verifies **AC-7**.
- Batches: with two batches, both get one Batch Course row; a second run adds none, verifies **AC-8**.

## Build plan

Approach: Tracer Bullet. Prove one thin create path end to end on the live site first, then thicken it one strand at a time.

1. [x] Probe the live site (read only, or rolled back) and record the answers in this spec's Follow-up. Find: the required fields for LMS Course (including `image`, `published_on`, and whether `instructors` is enforced), Course Chapter, Course Lesson, LMS Quiz, LMS Question, and Batch Course; how outline rows are written; which record types have a `published` field; how a quiz is named when two share a title; whether a round trip changes rich text (`question`, `description`, lesson `body`) and what the normalise function must do; how LMS recomputes `progress` after an outline change and whether it counts progress rows of detached lessons; what LMS does for members when a course is added to a batch; and whether LMS Batch `validate` rejects a re-save of a batch made in the UI, satisfies **AC-1**, **AC-2**, **AC-5**, **AC-8**
2. [x] Extend the content model (`Question.options` with at most 4, `Course.short_introduction` and `description`), add the `Option` type, and extend `check_course` for choice questions (fewer than two or more than four options, no correct option, empty or repeated option text), with unit tests, satisfies **AC-1**, **AC-3**
3. [x] Add the loader `contentfile.py` (`yaml.safe_load`; text required for `key`, `title`, `youtube`, question and option text; `body_file` must exist and stay inside `content/`; errors naming the file and key) and a small sample `content/course.yaml` with a video, a lab guide, and a quiz for each, with unit tests, satisfies **AC-1**, **AC-3**
4. [x] Add the LMS client `lms.py` with `httpx`: list, get, create, update, token header, read retries, a duplicate create treated as "fetch by key", errors that print status, `exc_type`, and the decoded message with the URL and never a traceback, header, or secret, with `httpx.MockTransport` unit tests, satisfies **AC-7**
5. [x] Thin thread: phase 1 and phase 2 for course, chapter, and a video lesson only, the `sync` command in `cli.py`, and a live run, satisfies **AC-1**
6. [x] Thicken the create path: questions and quizzes, lab lessons, quiz lessons (`quiz_id`, macro body, back link), and the outline tables, satisfies **AC-1**, **AC-4**
7. [x] Thicken to update: course scoped fetch, the normalised compare (child tables as ordered name tuples, rich text through one function), `Update` actions, the `LMS has X, git has Y` warning, and `nothing to change` on a rerun. Include a test for moving a lesson between chapters and for a run that stopped halfway, satisfies **AC-2**, **AC-4**, **AC-6**
8. [x] Add removals as in Key invariants, the `removed unmanaged row` lines, and the progress recompute step, satisfies **AC-5**
9. [x] Add batches: read each LMS Batch, send its existing Batch Course rows plus the missing one, satisfies **AC-8**
10. [x] Add `sync --check` with creates, detaches, differences, the unmanaged list, and exit codes, satisfies **AC-6**
11. [x] Add an `integration` test that runs sync twice on the live site and checks the invariants, then update `README.md` with the command and the content folder, satisfies **AC-2**, **AC-4**, **AC-5**, **AC-8**

## Consequences

**Positive**:
- Content has one author path, reviewable in git, with a dry run.
- Most of the logic is pure and unit tested.
- A failed run is safe to repeat.

**Negative / tradeoffs**:
- LMS edits are overwritten on every sync; only the warning protects an editor who forgot.
- Detached records pile up in the LMS over time, since nothing is deleted.
- Changing a `nile_key` looks like a removal plus a new record, and the old one is detached, not renamed.
- The thin file format will change in feature 11, so the loader and sample will be reworked.
- With no lock, two syncs at once can fail one of them with a duplicate error.
- The two phase run makes more requests than a single pass (a re-read between phases), which is fine for one course.
- Changing a quiz's `nile_key` makes students retake it, since their attempts stay on the old quiz.
- Rewriting an outline drops lessons or chapters someone added in the Desk without a `nile_key`, and says so.

**Neutral**:
- Adds `PyYAML` use to `tools/` (already a stack dependency) and a `content/` folder.
- `tools/AGENTS.md` should list the new modules (`/sync` owns that file).

## Follow-up

### Probe answers (build task 1, live site, rolled back, 2026-11-03)

- Required fields: LMS Course `title`, `short_introduction`, `description`, `instructors` (LMS fills it with the creating user, so the service user is the instructor with no extra field; `image` and `published_on` are not required). Course Chapter `title`, `course`. Course Lesson `title`, `chapter` (`course` is filled from the chapter). LMS Quiz `title`, `passing_percentage`, `total_marks` (LMS computes it from the question rows). LMS Question has none. Quiz Question row `question`, `marks`. Batch Course `course` (also `title`, `evaluator`, both optional).
- Outline rows are not added when a chapter or lesson is created. `Course.chapters` and `Course Chapter.lessons` stay empty until the sync writes them whole.
- `published` exists on LMS Course and LMS Batch only. Course Chapter and Course Lesson have none, so detaching those is only removing the outline row.
- Names: chapter and lesson `{####} {title}`, question `QTS-YYYY-#####`, quiz a slug of the title (a second quiz with the same title becomes `<slug>-2`), course a slug of the title.
- Rich text: `description` and `question` come back with `&` as `&amp;`. Lesson `body` macros come back unchanged. The normalise rule is `html.unescape(value).strip()` on both sides.
- A duplicate `nile_key` raises `UniqueValidationError` with `for key 'nile_key'` in the message.
- A quiz with no questions can be created (the check still refuses it).
- Progress: LMS does not recompute the stored `LMS Enrollment.progress` when the outline changes. LMS computes it with `get_course_progress`: completed rows for lessons still in the outline, over lessons in the outline, capped at 100, rounded to the site float precision (3 places by default). That function already ignores detached lessons. The sync recomputes with the same formula, so the value is not a whole number as step 7 guessed.
- Batches: the site has none yet. `LMS Batch.validate` lets Moderator and System Manager add any course, and the service user has both. Adding a course to a batch later does not enroll existing members (pinned in spec 0004's integration test). A re save of a batch made in the UI is checked in the build task 11 integration test.
- Not decided by the spec: the old course after a `nile_key` change cannot be found by key, and must not be found by title, so it is not unpublished. Raise with `/architect` if wanted.

- [ ] Build task 1 answers the open LMS questions from spec 0004 (item 4: Batch Course child fields; item 5: whether LMS enrolls existing members when a course is added to a batch). Update spec 0004's Follow-up when it does.
- [ ] Build task 1 may show the plan needs a change (for example, no `published` field to unset, or LMS counting progress rows of detached lessons). If it does, come back to `/architect` before building on a wrong assumption.
- [ ] Feature 11 replaces the thin file format and may add question types. The loader is the only reader to change.
- [ ] Feature 7 designs the login hook that fills any gap when LMS does not enroll existing batch members.
- [ ] A cleanup command for detached records is not designed here. Raise it if they pile up.
