# Verify: content sync · spec 0005 · updated 2026-11-03
_Steps derived from spec 0005 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

Run the live steps from the repo root with the stack up (`make up`). `make tools CMD=...` runs a command in the tools container. The throwaway course test `cd tools && uv run pytest -m integration tests/test_content_sync_integration.py` already walks AC-1, 2, 4, 5, 6 and 8 on the live site and deletes what it made. It leaves the real course alone. The steps below are the ones to run by hand against `content/course.yaml`.

## UI / manual
- [x] After `make tools CMD=sync`, open the course "Nile Workshop" in the LMS as a student test user → the course is published, shows two chapters, the video plays, the lab guide shows the markdown, and each quiz lesson opens its quiz   → AC-1, AC-4
- [x] In the Desk, open each synced quiz → its `lesson` and `course` are filled, the questions are listed with their marks, and the lesson body is `{{ Quiz("<that quiz's name>") }}`   → AC-4
- [x] In the Desk, edit the lab lesson body, then run `make tools CMD="sync --check"` → it lists that lesson body, exits 1, and the Desk body is still your edit   → AC-6
- [x] Run `make tools CMD=sync` after that edit → the output shows `LMS has '<your edit>...', git has '# Lab guide...'` and the Desk body is back to the git text   → AC-6
- [x] With a student who finished every lesson but one, remove that lesson (and its quiz) from `content/course.yaml`, then sync → the lesson and quiz are still in the Desk, not in the course outline, and the student's progress shows 100   → AC-5
- [x] In the Desk, create a lesson in the course with no `nile_key` and add it to a chapter, then run `make tools CMD="sync --check"` → it lists the lesson as unmanaged. Run `sync` → the output says `removed unmanaged row` and the lesson leaves the outline   → AC-5, AC-6

## Commands
- [x] `make tools CMD="sync --check"` on a site with no course → lists every course, chapter, question, quiz and lesson as `would create`, writes nothing, exit code 1   → AC-6
- [x] `make tools CMD=sync` on the empty site → creates the course, 2 chapters, 4 lessons, 2 quizzes and 2 questions, exit code 0   → AC-1
- [x] `make tools CMD=sync` again → prints `nothing to change` and `make tools CMD="sync --check"` exits 0   → AC-2
- [x] Change `title:` of one lesson in git and run `make tools CMD=sync` → output shows `updated Course Lesson <key>: title`, and the lesson count in the Desk is unchanged   → AC-2
- [x] Put `key: no` on a chapter, a number as a `youtube` id, a `body_file: ../x.md`, and a Choices question with one option → `make tools CMD=sync` prints every problem naming the file and key, writes nothing, exits 1   → AC-3
- [x] Give a `Choices` question five options, no correct option, an empty option, and a repeated option (one file, four questions) → each is named in one run   → AC-3
- [x] Set a wrong `LMS_API_SECRET` in `.env` and run `make tools CMD=sync` → output names the request URL, `HTTP 401`, the Frappe error type and message, with no traceback, no header and no secret, exit 1. Restore the secret   → AC-7
- [x] Create a Batch in the Desk (required fields only), run `make tools CMD=sync` → the batch has exactly one Batch Course row for the course. Run again → still one   → AC-8
- [x] Open the Batch in the Desk and save it with no change → saving works (the sync did not leave it in a state LMS rejects)   → AC-8

## Value sourcing
- [x] Every synced record has a `nile_key` equal to its `key` in the file: `bench mariadb` → `select nile_key from \`tabCourse Lesson\``, same for chapters, quizzes, questions, the course   → AC-1
- [x] The course instructor is the service user `LMS_SERVICE_USER`   → AC-1
- [x] Course `published`=1, `status`=Approved, `enable_certification`=1, `enforce_lesson_completion`=0   → AC-1
- [x] Chapter and lesson order in the outline matches the order in the file. Swap two lessons in git and sync → the outline order swaps   → AC-2, AC-4
- [x] Video lesson `youtube` is the id in the file and `body` is `{{ YouTubeVideo("<id>") }}`   → AC-4
- [x] Quiz lesson `quiz_id` is the name LMS gave the quiz. Give both quizzes the same title in git: one quiz is named `<slug>` and the other `<slug>-2`, and each lesson points to its own   → AC-4
- [x] Quiz `passing_percentage` and `max_attempts` are 80 and 3 when omitted from the file, and the file value when given   → AC-1
- [x] Question `option_1` to `option_4` and `is_correct_1` to `is_correct_4` follow the order and `correct` flags in the file, and `marks` on the quiz row follows the file (default 1)   → AC-1
- [x] A description or question with `&` in it syncs, then `sync --check` exits 0 (Frappe escapes it, the compare does not see a difference)   → AC-2
- [x] Progress: a student with progress rows for a detached lesson does not count them (set up in the Desk: an enrollment at 50, remove the lesson in git, sync, check the new value)   → AC-5

## Acceptance-criteria coverage
- AC-1 … covered by "sync on the empty site", the first two UI steps, and the Value sourcing steps · AC-2 … covered by "sync again", the title change and the `&` step · AC-3 … covered by the two file error steps · AC-4 … covered by the lesson body and quiz name steps · AC-5 … covered by the removal and progress steps · AC-6 … covered by the `--check` steps and the unmanaged step · AC-7 … covered by the wrong secret step · AC-8 … covered by the two batch steps
