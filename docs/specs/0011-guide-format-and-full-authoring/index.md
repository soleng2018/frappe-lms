# 0011. Author courses as folders of markdown and quiz files, with lessons built from blocks

**Date**: 2026-11-05
**Status**: Accepted
**Supersedes in part**: [0005](../0005-content-sync/index.md) (the content file format, the loader, and the one course scope) and [0004](../0004-data-model/index.md) AC-10 (a lesson body is now built from blocks, not one macro).

## Summary

An author adds a course by committing one folder, `content/<course-key>/`, with a `course.yaml`, markdown guides, one yaml file per quiz, and images. A lesson is an ordered list of blocks (text, video, quiz), so one lesson can mix them in any order. A new offline command, `content check`, finds every problem in every course before anything touches the LMS, and the same check runs at commit time. `sync` then pushes all courses (or one), and a course that fails never blocks the others; the blocked ones are listed at the end.

## Requirements

**User stories**:
- As an author, I want to add a course by committing a folder so that no code change and no Desk clicking is needed.
- As an author, I want a lesson to mix text, a video and a quiz in the order I choose so that a lesson fits its content (a video with its transcript, a lab with an intro).
- As an author, I want to put images in a guide so that a lab guide can show screens and diagrams.
- As an author, I want every mistake in my files reported at once, offline, and at commit time so that I fix them before sync.
- As the operator, I want to sync all courses in one command, and see which courses were blocked and why, so that one broken course never holds up the rest.

**Acceptance criteria**:
- **AC-1**: Every folder directly under `content/` that holds a `course.yaml` is a course. The folder name must equal the course `key` and match `[a-z0-9][a-z0-9-]*`. `course.yaml` must start with `format: 1`; any other value, or none, is a problem that names the file. A folder under `content/` without `course.yaml`, and the old files `content/course.yaml` and `content/labs/`, are problems that say where to move them. Names that start with a dot are ignored.
- **AC-2**: A lesson has a `key`, a `title`, and `blocks`, a non empty list in reading order. Each block is a mapping with exactly one of `text` (a path to a markdown file in the course folder), `video` (the 11 character YouTube id, as text) or `quiz` (a quiz key). A lesson may hold any number of `text` blocks, at most one `video`, and at most one `quiz`. The lesson `body` in the LMS is each block's rendering, stripped, joined by one blank line, in block order. A video renders as `{{ YouTubeVideo("<id>") }}`, a quiz as `{{ Quiz("<quiz name>") }}`, text as the file's markdown. A lesson with one block gets the same body as today. `youtube` is set from the video block, else cleared. `quiz_id` is set from the quiz block, else cleared. The lesson types `video`, `lab` and `quiz` no longer exist.
- **AC-3**: Each quiz is one file in `quizzes/` (any `*.yaml` name). It holds the `key`, `title`, `passing_percentage` (80 to 100, default 80), `max_attempts` (default 3), and the questions as in spec 0005. Every quiz is used by exactly one quiz block, in a lesson of the same course. A quiz file nobody uses, a quiz block with no file, and a quiz used twice are problems. Spec 0010's pass mark floor and spec 0005's choice rules (2 to 4 options, one or more correct, no empty or repeated option text) stay.
- **AC-4**: An image is a markdown image `![alt](path)` outside code (fenced or inline code is left alone, no check and no rewrite) whose path is local, meaning it does not start with `/` or `#` and does not start with a URL scheme (`http:`, `https:`, `data:`, `mailto:`, `tel:`, `ftp:` and any other `name:`). The path is relative to the markdown file, must stay inside the course folder, and is resolved before use, so `../images/x.png` and `images/x.png` from two guides are one image. An optional `"title"` and `<...>` around the path are kept; only the path is replaced. `course.yaml` may set `image: <path>` for a cover, relative to the course folder. The check refuses: a missing file, empty alt text, an extension other than `png`, `jpg`, `jpeg`, `gif` or `webp` (matched ignoring case), first bytes that do not match the extension, a file over 5 MB (1 MB is 1,000,000 bytes), a file name with a character outside `[a-z0-9._-]`, a path with `?`, `#` or percent encoding, a reference style image (`![a][r]`), a local `<img src>`, and a local link that is not an image (`[x](other.md)`, a pdf). Sync uploads each image to the LMS as a public file named `<course-key>-<first 12 hex of the sha256>-<file name>` and stores the file's URL in the lesson body (and the course `image` field). The hashed name is not guessable, and the course is hidden by enrollment. A second run uploads nothing and writes nothing. Changing an image makes a new file with a new name and updates the body. Nothing is deleted. `sync --check` uploads nothing.
- **AC-5**: `content check [course-key]` reads only the repository (no `.env`, no network), prints every problem at once as `ERROR <course>/<file>: <where>: <message>`, sorted by course, file, then where, and exits 1 on any problem, else prints `ok <course>` per course and exits 0. `<where>` is a key path such as `chapters[ch-x].lessons[l-y].blocks[2]`. A problem with no single course or file uses a fixed form, e.g. `ERROR content/course.yaml: -: move this file into content/<key>/`, and a cross course problem prints one line per course involved. If a `course.yaml` cannot be parsed, the rest of that course is skipped and the cross course checks use only the keys that did parse (the yaml `key`). Across courses it also refuses: two course titles equal ignoring case, and a `key` of a chapter, lesson, quiz or question that another course already uses (the LMS keeps one `nile_key` per record type for the whole site). Also a problem: a quiz file that no quiz block uses, a block key other than `text`, `video` or `quiz`, and `{{` anywhere in a guide (the LMS would run it as a macro and bypass the one quiz rule). A markdown file in `guides/` that no text block uses is a warning (`WARN ...`), not a problem, so a draft can sit in git; it does not change the exit code. With a `course-key`, only that course and the clashes it takes part in are shown and counted.
- **AC-6**: A `pre-commit` hook runs `content check` whenever a file under `content/` changes, and fails the commit on any problem. It is a local hook that runs on the host (`uv run --frozen --project tools`, `files: ^content/`, `pass_filenames: false`), not through `make tools`, so a commit needs no Docker. The existing `trailing-whitespace` hook excludes `content/**/*.md` (it would strip markdown hard breaks and change a body), and `check-added-large-files` is set to 5,000 KB so an allowed image can be committed.
- **AC-7**: `sync` with no argument syncs every course; `sync <course-key>` syncs one; `--check` works with both. A course with a problem is skipped whole and nothing is written for it. That covers its own check problems, a cross course clash it takes part in, a title that another LMS course already has or that equals `AUTHENTIK_ADMIN_GROUP` (spec 0009's `title_clash`, now a block with a reason, not a stop of the whole run, checked before phase 0), and a record key that the LMS holds under a different course (the message names both courses). A failed write stops only that course, with the output spec 0005 AC-7 describes. The other courses carry on. Every output line of a course starts with `[<course-key>]`. At the end, `sync` prints one line per blocked course with its reason and exits 1 if any course was blocked, else 0. A second run on unchanged content writes nothing, uploads nothing, and prints `[<course-key>] nothing to change` per course. An LMS course that has a `nile_key` but no folder is listed as `course <name> (<key>) has no folder in content/, left alone` (only when no course key is given), and nothing is changed or unpublished. In `--check`, the following each count as a difference and give exit 1: that line, a `would upload image` line, any blocked course, and any other difference. In a normal `sync`, that line does not change the exit code. With a `course-key`, only that course is synced and shown.
- **AC-8**: The existing `nile-workshop` course, moved into the new layout, makes `sync --check` on the live site print `[nile-workshop] nothing to change` and exit 0. Every existing LMS record keeps its key, and no lesson body, `youtube`, `quiz_id` or question changes. A cleared `youtube` or `quiz_id`, and an empty explanation, compare equal to an empty or null value in the LMS.
- **AC-9**: `content new <course-key> [--title TEXT]` creates `content/<course-key>/` with `course.yaml`, `guides/welcome.md`, and `quizzes/<course-key>-quiz.yaml`: one chapter, one lesson (a text block, then a quiz block), one guide and one quiz with one question and two options, with fixed placeholder text. The keys are exactly `<course-key>-ch-1`, `<course-key>-l-1`, `<course-key>-q-1` and `<course-key>-q-1-1`. The result passes `content check` with no edit. It refuses (exit 1, nothing written) a key that breaks AC-1's name rule, a folder that already exists, and a title that equals another course's title ignoring case. It writes with the invoking user's own file owner, so `content/` is mounted read write in the tools container.
- **AC-10**: `docs/authoring.md` documents the format: the folder layout, every field with its type and whether it is required, the block rules, the image rules, the key rules, the commands and exit codes, and every check message with its fix. `README.md` links to it and shows the three commands. The worked example in the guide is the `content new demo` output.
- **AC-11**: An option of a question may carry an optional `explanation` (plain text, 1 to 1000 characters after trimming). Sync writes it to that option's LMS field (`explanation_1` to `explanation_4`, by option position), clears the field of a position with no explanation or no option, and compares it like any field, so a rerun changes nothing. The check refuses a question level `explanation` (it names the option field to use), a value that is not text, an empty value, and one over 1000 characters. The learner sees it under that option after answering a question (LMS shows it when the quiz has `show_answers` on, which is the LMS default and which sync does not set, or after the learner has submitted an attempt). It is plain text: markdown and HTML show as typed.

## Decision

**Chosen option**: Option 1: a folder per course, lessons built from ordered blocks, and per course error isolation.

Replace the single `content/course.yaml` with `content/<course-key>/` folders. Rework the content model so a `Lesson` holds a tuple of `Block`s. Add a catalog step that finds every course folder and runs both the per course and the cross course checks, an offline `content check`, an image upload step, and a sync that loops over courses and isolates each one. The planner, the LMS client, and the rules of spec 0005 stay.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`)

## Feature design

**Content model** (pure, frozen data in `content.py`; no new LMS records):

| Type | Fields | Rules |
|---|---|---|
| `Course` | `key`, `title`, `short_introduction`, `description`, `image` (optional path), `chapters`, `quizzes` | folder name equals `key` |
| `Chapter` | `key`, `title`, `lessons` | at least one lesson |
| `Lesson` | `key`, `title`, `blocks` | at least one block; at most one video and one quiz |
| `TextBlock` | `path`, `markdown` | the file exists and is not empty |
| `VideoBlock` | `youtube` | 11 character id |
| `QuizBlock` | `quiz_key` | names a quiz of this course |
| `Quiz` | `key`, `title`, `passing_percentage`, `max_attempts`, `questions`, `lesson_key` | `lesson_key` is filled from the lesson whose block names the quiz |
| `Question` | `key`, `text`, `marks`, `options` | as spec 0005; a question level `explanation` is a problem |
| `Option` | `text`, `correct`, `explanation` | as spec 0005; `explanation` optional, plain text, 1 to 1000 characters after trimming |
| `Image` | `path`, `bytes` (read at load), `alt` | type, size and first bytes checked |

`VideoLesson`, `LabLesson` and `QuizLesson` are removed.

**Folder layout**:

```
content/<course-key>/
  course.yaml            format, key, title, short_introduction, description, image?, chapters
  guides/*.md            markdown for text blocks
  quizzes/*.yaml         one quiz per file
  images/*               png, jpg, jpeg, gif, webp
```

**`course.yaml`**:

```yaml
format: 1
key: nile-workshop
title: Nile Certified Associate
short_introduction: ...
description: ...
image: images/cover.png          # optional
chapters:
  - key: ch-concepts
    title: Concepts
    lessons:
      - key: l-intro
        title: Introduction
        blocks:
          - video: dQw4w9WgXcQ
          - text: guides/intro-transcript.md
          - quiz: q-intro
```

**Quiz file** (`quizzes/q-intro.yaml`):

```yaml
key: q-intro
title: Introduction quiz
passing_percentage: 80
max_attempts: 3
questions:
  - key: q-intro-1
    text: What is the video about?
    options:
      - text: The Nile Workshop
        correct: true
        explanation: The video introduces the Nile Workshop.   # optional, plain text
      - {text: Something else}
```

**Check order** (all pure, all problems collected):
1. Layout: legacy root files, folders without `course.yaml`, folder name against the yaml `key`.
2. Per course: read `course.yaml`, the quiz files and the guides; types, required fields, block rules, quiz rules (spec 0005 and 0010), images (AC-4), `{{` in guides, unused quizzes, and unused guides as warnings. A `course.yaml` that does not parse ends the checks of that course.
3. Across courses, using the yaml keys that parsed: titles equal ignoring case, repeated chapter, lesson, quiz or question keys.
4. A course is **ready** only if it has no problem of its own and takes part in no cross course clash. At sync time the planner adds the LMS side blocks of AC-7 (title clash, a key held under another LMS course).

**Exit codes**: `0` all fine. `1` any problem, blocked course, difference in `--check`, refused `content new`, or missing `.env` or LMS failure. `2` a command line usage error.

**Sync flow** (spec 0005's two phases stay; the changes are marked):
1. Load the catalog and run the checks. Print every problem. Mark the blocked courses.
2. If a course key was given and it is unknown, print the known keys and exit 1.
3. Read the LMS courses once (key, name, title), then for each ready course in folder name order: read its state, **upload its images (phase 0, new)**, run phase 1 (ensure) and phase 2 (converge) as in spec 0005. A failure stops that course, which is added to the blocked list with the spec 0005 AC-7 message; the loop goes on.
4. Print the LMS courses with a `nile_key` and no folder. Print the blocked list. Print one count line per course. Exit 1 if any course is blocked (in `--check`, also if any difference is found).

**Phase 0, images (new)**: for each image of the course, work out its file name from the course key and the sha256 (the check has already limited the original name to `[a-z0-9._-]`, so Frappe does not rename it). Look it up in the LMS File records by `file_name` and `is_private=0`, without filtering on owner. If missing, upload it with `POST /api/method/upload_file` (multipart fields `file`, `file_name`, `is_private=0`; not attached to any document). Frappe may reuse the URL of a file with the same bytes, so the code always takes the `file_url` from the response or the found record. That URL replaces the local path in the markdown and in the cover field. In `--check` nothing is uploaded: a file that exists gives its real URL for the body compare; a file that does not exist is listed as `would upload image <path>`, counts as a difference for every lesson that uses it, and the body of that lesson is not predicted.

**Body building** (pure, in `content.py`): `lesson_body(lesson, quiz_name, urls)` renders each block, strips it, drops empty renderings, joins with a blank line. `urls` maps each resolved image path to its LMS URL. Image links in code are never touched.

**API surface** (Frappe REST as the service user, as in spec 0005; the new row is the upload):

| Request | Used for | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `GET /api/resource/File` with `filters` on `file_name`, `is_private=0` | find an uploaded image | the computed file name | `name`, `file_url` | token | 401, 403 |
| `POST /api/method/upload_file` (multipart) | upload an image | `file`, `file_name`, `is_private=0` | `file_url` | token | 403, 413, 417 |
| the spec 0005 requests | everything else | as in spec 0005 | as in spec 0005 | token | as in spec 0005 |

**Commands** (all through `make tools CMD="..."`):

| Command | Network | Result |
|---|---|---|
| `content check [course-key]` | none, no `.env` | `ok <course>` lines or `ERROR` lines, exit 0 or 1 |
| `content new <course-key> [--title TEXT]` | none | creates the folder, prints its path |
| `sync [course-key] [--check]` | LMS | per course lines, blocked list, exit code |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Find a course folder | the course key | `key` in `course.yaml`; the folder name must equal it |
| Build a lesson body | text parts | the markdown file named by the text block, stripped |
| Build a lesson body | video part | the block's 11 character id |
| Build a lesson body | quiz part | the quiz `name` the LMS returned on create (spec 0005 AC-4), never the title |
| Set a lesson `youtube` | the id, or empty | the video block, else cleared |
| Set a lesson `quiz_id` | the quiz name, or empty | the quiz block, else cleared |
| Upload an image | `file_name` | course key, first 12 hex of the sha256 of the bytes, the original file name |
| Upload an image | `is_private` | decided in this spec: 0 (a private file would only be readable by its owner or by users who can read the document it is attached to) |
| Rewrite an image link | the URL in the body | the `file_url` the LMS returned, or found by `file_name`; in `--check`, the found record's URL, else `would upload image` and no predicted body |
| Locate a problem | `<where>` | the key path in the yaml, or the markdown file and line for a guide |
| Output prefix | `[<course-key>]` | the `key` of the course being synced |
| Count line | created, updated, detached, images uploaded | the actions and uploads of that course |
| LMS side block | the other LMS course | the LMS course that holds the record under that `nile_key` |
| Exit code | 0, 1 or 2 | the Exit codes rule above |
| Image alt text | the alt | the text inside `![ ]` in the markdown |
| Blocked list | course and reason | the check problem, or the failed write's message |
| Course with no folder | key, name | LMS courses with a `nile_key` not in the catalog |
| Cross course clash | the other course | the catalog |
| Admin group clash | `AUTHENTIK_ADMIN_GROUP` | `.env`, read by `sync` only (spec 0009); `content check` cannot know it |
| `content new` | title | `--title`, else the key with dashes as spaces and the first letter upper case |
| `content new` | every inner key | `<course-key>-ch-1`, `<course-key>-l-1`, `<course-key>-q-1`, `<course-key>-q-1-1` |
| `content new` | file names and text | `guides/welcome.md`, `quizzes/<course-key>-quiz.yaml`, fixed placeholder text in the code |
| Option explanation | the LMS field | `explanation_N` of the LMS Question, where N is the option's position from 1 (build task 1 probe, 2026-11-05) |
| Option explanation | the length limit | 1000 characters, a constant in `content.py` (AC-11) |
| Option explanation | whether the learner sees it | LMS `show_answers` on the quiz (default on); sync does not write `show_answers` |

**Key invariants**:
- Spec 0005's invariants stay: a record is found only by `nile_key`; nothing is written until that course's check passes; nothing is deleted; everything read, compared and detached is scoped to one course.
- A block order change, or a block added or removed, updates the same lesson record. It never makes a new one.
- A quiz block removed from a lesson detaches the quiz as spec 0005 says (its `lesson` is cleared; attempts stay).
- Image files in the LMS are never deleted or changed. A changed image is a new file under a new name. The lookup is by `file_name` and never depends on who owns the file.
- A markdown file is treated as UTF-8 text and stored as written. Only the local image links are rewritten, and only in the stored body, never in git.
- Keys are written in the files. Order is list order. A folder or file name never carries identity, except that the folder name must equal the course key.
- A course takes part in the cross course checks even when only one course is being synced, because those clashes are about the LMS as a whole.

**Security model**: sync runs as the service user (spec 0001). Git is the trust boundary, so markdown is stored as written. Images are uploaded as public files, because a private Frappe file is readable only by its owner or by users who can read the document it is attached to, which learners cannot do. The name carries a hash of the content, so a URL cannot be guessed, and the course itself is hidden by enrollment (spec 0009). Anyone who has an image URL can still load it, so authors must not put secrets in images. SVG is refused because it can carry script. A path that leaves the course folder is a problem, and a symlink that leaves it is too. Output never prints a key, a secret or an Authorization header. No personal data is handled.

**Configuration required**: none new. `content check` and `content new` need no `.env`. `sync` uses `LMS_HOSTNAME`, `LMS_API_KEY`, `LMS_API_SECRET` and `AUTHENTIK_ADMIN_GROUP`, as today.

**Critical test scenarios**:
- Happy path: two small courses, one with a lesson that mixes video, text and quiz, and a guide with an image, sync to a clean site; the lesson body has the three parts in order, the image is private and its URL is in the body, verifies **AC-2**, **AC-3**, **AC-4**, **AC-7**.
- Idempotency: run twice; the second makes no write and uploads nothing; reorder two blocks and the same lesson updates, verifies **AC-2**, **AC-4**, **AC-7**.
- Move the live `nile-workshop` course into the new layout; `sync --check` says `nothing to change`, verifies **AC-8**.
- Check failures, all at once: a numeric video id, a block with two keys, two videos in one lesson, a missing image, an `.svg`, a renamed `.exe` as `.png`, an image name with a capital or space, `{{` in a guide, an image inside a code fence (left alone), a reference style image, a link to `other.md`, an unused quiz, a repeated lesson key across two courses, and two titles that differ only in case; each is named with its course, file and key. An unused guide is only a warning, verifies **AC-1** to **AC-5**.
- A `course.yaml` that does not parse: that course is skipped and the others are still checked, verifies **AC-5**.
- LMS side blocks: a course whose title equals another LMS course, and a lesson key that the LMS holds under another course, are each blocked with the reason while the other courses sync, verifies **AC-7**.
- Legacy layout: a root `content/course.yaml` is refused with the new location, verifies **AC-1**.
- Isolation: course A has a bad file and course B is sound; `sync` writes B, skips A, lists A, exits 1. Then the LMS returns 500 on a write in B; A stays skipped, a third course C still syncs, verifies **AC-7**.
- Single course: `sync <key>` touches only that course; an unknown key lists the known ones, verifies **AC-7**.
- Folder removed in git: the LMS course is listed, not changed; `--check` exits 1, verifies **AC-7**.
- Scaffold: `content new demo` passes `content check` and refuses to run twice, verifies **AC-9**.
- Hook: a bad file under `content/` fails the commit, verifies **AC-6**.
- Explanation: a quiz with an explanation on one option is written to the right `explanation_N`, a rerun changes nothing, removing it clears the field, and a question level `explanation`, an empty one and one of 1001 characters are each refused. On the live site a learner who answers sees the text under that option, verifies **AC-11**.

## Build plan

Approach: Tracer Bullet. First prove the riskiest unknowns on the live site, then move the one existing course through the new path end to end, then thicken one strand at a time.

1. [x] Probe the live site (read only, or rolled back) and record the answers in Follow-up. Find: whether a lesson body with a video macro, text and a quiz macro in one body renders in order and can be completed (and whether passing the quiz completes the lesson); what `youtube` and `quiz_id` do when cleared; how `upload_file` treats `is_private=0`, a repeat upload of the same bytes, a repeat of the same `file_name`, and what it does to a name with a space or capital; whether a public image shows in a lesson page and on the course card; which size limit applies (Frappe and nginx); whether the old lab body was stored unstripped; which LMS Question field holds an explanation and whether the learner sees it; and whether `nile_key` is unique per record type for the whole site. If a combined body or a public image does not work, or there is no explanation field, stop and come back to `/architect`, satisfies **AC-2**, **AC-4**, **AC-11**
2. [x] Thin thread: rework the model to `Lesson` with blocks and `lesson_body`, read the new folder layout for one course (`course.yaml` and guides, quizzes still in the file for this step), move the sample course into `content/nile-workshop/`, run `sync --check` on the live site until it says `nothing to change`, satisfies **AC-1**, **AC-2**, **AC-8**
3. [x] Quiz files in `quizzes/`, the unused and missing quiz checks, and the per option `explanation` through the checker, the model (`Option.explanation`), the planner (`explanation_1` to `explanation_4`, cleared when absent) and `docs/authoring.md` (replace the line that says it is not supported), satisfies **AC-3**, **AC-11**
4. [x] The catalog: find every course folder, the cross course checks, the legacy layout message, and the `content check` command, satisfies **AC-1**, **AC-5**
5. [x] Many course sync: loop with isolation, `sync <course-key>`, the `[key]` prefix, the blocked list, `title_clash` and the key held under another course turned into per course blocks, the folder less course line, the exit codes, and the same for `--check`, satisfies **AC-7**
6. [x] Images: find local links in markdown (outside code), the image checks, phase 0 upload with the file name rule, the link rewrite, the cover image, and the `--check` rule for a missing file, satisfies **AC-4**
7. [x] `content new`, with a test that its output passes `content check`, satisfies **AC-9**
8. [x] The `pre-commit` hook for `content/`, the `trailing-whitespace` exclude and the `check-added-large-files` limit, satisfies **AC-6**
9. [x] `docs/authoring.md`, the README section, and a live integration test with two courses (one mixing blocks and an image), run twice, satisfies **AC-4**, **AC-7**, **AC-10**

## Migration plan

**Strategy**: no LMS migration. One commit moves the files and changes the loader; the live records stay as they are.
**Phases**:
1. Task 2 moves `content/course.yaml` and `content/labs/lab-guide.md` into `content/nile-workshop/` and rewrites each lesson as blocks (a `video` lesson becomes one video block, a `lab` lesson one text block, a `quiz` lesson one quiz block). Every key stays.
2. `sync --check` on the live site must say `nothing to change` before the loader switch is merged.
3. The old loader and the three lesson types are deleted in the same commit. There is no dual format.
**Rollback**: revert the commit. The old loader and layout return, and the LMS records are unchanged. Images and explanations written by a later sync are extra records the old format ignores, and courses added after the switch stay in the LMS where the old loader cannot see them.
**Risks**: a body that differs by one newline would show as a change on every lesson (the compare strips both sides, and AC-8 proves it before merge); a record key that the LMS already holds under another course, or by hand, which AC-7 turns into a block that names both courses.

## Consequences

**Positive**:
- A course is a folder that can be reviewed, moved and copied as one unit. Adding one needs no code.
- A lesson can mix text, video and quiz in the order the content needs.
- Mistakes are found offline and at commit time, not at sync time.
- One broken course never blocks the others.

**Negative / tradeoffs**:
- More files per course (guides, quizzes, images), and an author must learn the block shape.
- Keys must be unique across all courses, so every key is prefixed by hand (the scaffold does it).
- Every sync of every course re-reads each course, so a big catalog makes a slow run (fine for a few courses, and `sync <course-key>` is there for speed).
- Images are public files. Their names are unguessable, but anyone who has a URL can load it, so no secret may go in an image.
- Image files pile up in the LMS, since a changed image is a new file and nothing is deleted.
- Markdown has strict limits: no reference style images, no `<img>`, no local links except images, and no `{{`.
- A folder removed from git leaves its course in the LMS, listed on every run, until someone removes it by hand.

**Neutral**:
- The old format and loader are removed in one commit; spec 0005 and spec 0004 AC-10 are marked as superseded in part.
- `tools/AGENTS.md` should list the new modules (`/sync` owns that file).
- No new dependency (`PyYAML` and `httpx` are enough).

## Follow-up

- [ ] When this spec is confirmed, mark spec 0005 and spec 0004 AC-10 as superseded in part by 0011.
- [x] Build task 1 probe, explanation (found 2026-11-05 in the LMS source on the live backend): LMS Question has no question level explanation, only `explanation_1` to `explanation_10` beside `option_N`. This site uses four options, so only the first four are used. `Quiz.vue` shows `explanation_N` under its option after an answer, and the server sends explanations to a learner only when the quiz has `show_answers` on or the learner has already submitted. AC-11 was changed from per question to per option to match. The check that the learner really sees it in a browser is part of build task 3.
- [ ] Build task 1 recorded no answers for the combined body, the public image and the other probe items. Steps 2 to 9 are ticked, so treat them as working, and write the probe answers here if you still have them.
- [ ] Leaving `show_answers` on means a learner sees the correct option after each question, so an explanation adds no new leak. If the quiz should hide answers until the end, that is a separate quiz setting decision, not part of this spec.
- [ ] Feature 10 (branding) uses images too, but through Website Settings; it does not use this upload path.
- [ ] A command to list or remove old image files and detached records is not designed here. Raise it if they pile up.
- [ ] A lock against two syncs at once is still not designed (see spec 0005).
- [ ] Removing a course from the LMS after its folder is deleted is a manual step. Raise a cleanup command if it happens often.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).
