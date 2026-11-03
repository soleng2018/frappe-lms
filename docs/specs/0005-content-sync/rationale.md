# 0005 Rationale: Sync one course from git to the LMS with a planner that finds records by `nile_key`

## Context

Spec 0004 fixed the LMS records, the `nile_key` field, and the exact lesson body text. It left the sync itself to this feature. The sync must turn a file in git into a course, chapters, lessons, quizzes, and questions in the LMS, in an order that works (a quiz lesson needs its quiz first, the quiz needs its lesson back).

The forces: git is the only place content is authored, so the sync may overwrite LMS edits. The operator runs it by hand from the `tools` container, which already has the repo mounted and the service user's API key. The LMS is reached over HTTPS through Traefik and can fail midway. Students already hold progress, so a sync must never delete a record they have used.

## Options considered

### Option 1: A planner and a thin API client, keyed by `nile_key`

Load the file into the frozen content model, fetch the matching LMS records, compute a plan as plain data, then apply the plan. The plan is the same data `--check` prints.

**Pros**:
- The planner is a pure function, so most of the feature is unit tested with no network.
- `--check`, the overwrite warning, and the real run share one code path.
- Fits the functional style in `AGENTS.md`.

**Cons**:
- More modules than a single script.
- The plan has to describe the write order, which takes care.

### Option 2: One imperative script that calls the API as it reads the file

Walk the file and create or update each record on the spot.

**Pros**:
- Least code to start.

**Cons**:
- `--check` needs a second copy of the logic.
- Hard to test without a live site; a bug shows up as a half built course.

### Option 3: Frappe's own import tools (Data Import, fixtures, `bench` commands)

**Pros**:
- No client code.

**Cons**:
- Runs inside the Frappe containers, not through the API the brief asks for.
- Weak with child tables, write order, and the quiz back link, and gives no useful drift report.

## Rationale

Reasoning and options: the Context forces decide it. Git is the only author, so the code must be able to say what it would change before it changes it (Option 1 gives that for free, Option 2 does not). Students hold progress, so removals must be careful, and that is easy to unit test in a pure planner. The brief says the sync pushes through the API, which rules out Option 3. The runner up is Option 2 for a one off, but `--check` and the overwrite warning are required by spec 0004, so it would end up as Option 1 anyway.

Choices made on the way, with the runner up:
- File format: one YAML file plus lab markdown files (runner up: a folder with one file per record). One course is small, and feature 11 can change the format because the loader is the only reader.
- Questions: multiple choice only (runner up: also typed answers). Auto graded questions are all a quiz lesson needs to complete.
- LMS edits: warn and overwrite (runner up: stop unless `--force`). Git is the only place content is authored.
- Publish on create (runner up: leave a draft). Batches only enroll members in published courses.
- Failure: stop at the first error (runner up: collect all errors). Later records depend on earlier ones.
- Removals: detach and keep (runner up: delete). Deleting a quiz could lose attempts a manager still needs.
- HTTP retries: retry reads on a connection error or a 5xx, three times with a short wait; never retry a write (runner up: retry everything). A repeated write could duplicate, and a rerun is already safe.
- Concurrent runs: no lock (runner up: a lock file). The unique `nile_key` index makes the second run fail with a duplicate error, which AC-7 reports.
