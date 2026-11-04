# Verify: data model · spec 0004 · updated 2026-11-03
_Steps derived from spec 0004 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

Run the live steps from `tools/` with the stack up (`make up`). Steps marked **needs feature 7** or **needs feature 8** cannot run until that feature exists. `/check verify` reports them as blocked, not passed.

## UI / manual
- [x] Open the Desk as a `hol-admins` test user, open one student's Quiz Submissions for a quiz, delete them → the delete works and the student can attempt the quiz again   → AC-2, AC-6
- [x] As a student test user, open the course in the LMS, play a video lesson whose body is `{{ YouTubeVideo("<id>") }}` → the video plays   → AC-10
- [x] As a student test user, open a quiz lesson with the `{{ Quiz("<name>") }}` body and try to mark it complete without passing → the lesson stays incomplete   → AC-10, AC-2
- [x] As a student test user with every lesson and quiz done, press the certificate button → the certificate is issued; with one quiz unpassed → it is refused   → AC-5
- [ ] **Needs feature 7 as changed by spec 0009:** log in with a course group for the first time → a Website User with LMS Student and an LMS Enrollment in that course only exist; log in again → nothing new is created   → AC-4
- [x] **Needs feature 7:** log in as a `hol-admins` member → a System User with Moderator and Course Creator and no System Manager   → AC-4
- [x] **Needs feature 7:** two first logins for the same group at the same moment → exactly one batch exists   → AC-4

## Commands
- [x] `cd tools && uv run pytest tests/test_data_model_integration.py -m integration` → all pass on the live site   → AC-1, AC-2, AC-5, AC-6, AC-7
- [x] `cd tools && uv run pytest tests/test_content.py tests/test_drift.py` → all pass   → AC-8, AC-9, AC-10
- [x] Check the live schema: the unique `nile_key` field exists on LMS Course, Course Chapter, Course Lesson, LMS Quiz, LMS Question, and the unique `nile_group` field on LMS Batch → all six present   → AC-3, AC-4
- [x] Content check given a quiz with no lesson and a repeated `nile_key` → both problems named in one run, nothing written   → AC-8
- [x] Content check given a pass mark of 0 or 101, an attempt limit of 0, a quiz with no questions, an open ended question, and a `youtube` value that is a URL → every one named in the same run   → AC-8
- [x] `lesson_body` for a video with id `abc` → exactly `{{ YouTubeVideo("abc") }}`; for a quiz named `Q1` → exactly `{{ Quiz("Q1") }}`; for a lab → the markdown, no macro   → AC-10
- [x] Compare given a quiz lesson with `quiz_id` set and an empty body → reported as drift; given a stale quiz name in the macro → reported; given an LMS record with no `nile_key` → listed as unmanaged   → AC-9, AC-10
- [x] **Needs feature 8:** `sync` twice on the same content → the second run creates nothing   → AC-3
- [x] **Needs feature 8:** rename a lesson title in git and run `sync` → the same record is updated, no duplicate   → AC-3
- [x] **Needs feature 8:** remove a lesson from git and run `sync` → it leaves the course outline, is unpublished, is not deleted, and a student's progress can still reach 100   → AC-3
- [x] **Needs feature 8:** `sync --check` after editing a synced lesson in the LMS → changes nothing, lists that lesson, and lists any LMS record with no `nile_key`; a normal `sync` names the edit before it overwrites it   → AC-9
- [x] **Needs feature 8:** `sync` on a new quiz lesson → quiz is created first, then the lesson with `quiz_id` and the macro body, then `quiz.lesson` and `quiz.course` are set   → AC-10, AC-1

## Value sourcing
- [x] Quiz created without a pass mark or attempt limit in its content file → `passing_percentage` 80 and `max_attempts` 3 (the named constants); with values in the file → those values are used   → AC-2
- [x] Quiz `nile_key` and course `nile_key`: change the title only → the key and record name stay the same   → AC-3
- [x] Quiz lesson body after a quiz is recreated under a new name → the body is rebuilt from the new name in the same run (**needs feature 8**)   → AC-10
- [x] Batch created with the spec values: `start_date` today, `end_date` today plus 10 years, `00:00:00` to `23:59:59`, the site timezone, `allow_self_enrollment` 0, `published` 1 → the batch saves and enrolls its members in every published course. Vary the site timezone and check `timezone` follows it   → AC-4
- [x] Locked quiz: 3 submissions under 80% for one student → the fourth is refused; one submission at or above the pass mark → not locked   → AC-2
- [x] Certificate template: with the LMS default template → the request succeeds and fills the date, member, and course title   → AC-5
- [x] Manager view pass or fail: a Quiz Submission is read as pass or fail from its own `percentage` against its own `passing_percentage` → changing the quiz's pass mark later does not change an old attempt   → AC-6

## Acceptance-criteria coverage
- AC-1 covered by the schema fields step and the integration run, plus the sync ordering step (feature 8)
- AC-2 covered by the integration run, the locked quiz step, the defaults step, and the Desk reset step
- AC-3 covered by the `nile_key` schema step; the rest needs feature 8 (sync twice, rename, removal)
- AC-4 covered by the `nile_group` schema step and the batch values step; the login steps need feature 7
- AC-5 covered by the integration run and the certificate steps
- AC-6 covered by the integration run, the Desk reset step, and the manager view step
- AC-7 covered by the integration run (a student sees only their own records)
- AC-8 covered by the two content check steps
- AC-9 covered by the compare step; `sync --check` needs feature 8
- AC-10 covered by the `lesson_body` step, the compare step, the integration run, and the video and quiz lesson steps
