# 0004. Model courses, quizzes, batches, and roles on native LMS records

**Date**: 2026-11-03
**Status**: Accepted
**Superseded in part**: by [0009](../0009-course-access-from-groups/index.md): AC-4 (what a login enrolls a learner in), the LMS Batch rows of the data model, and `published` 1 in the course creation values.

## Summary

The LMS already has records for courses, chapters, lessons, quizzes, attempts, progress, and certificates, and they already enforce most of your rules: a quiz lesson only counts when the student scores 80% or more, retakes stop at the limit, and a certificate is only issued at 100% progress. So this spec adds no new record types. It fixes how the content is shaped (one course, chapter 1 for concepts, one chapter per feature, a quiz after every video and after every lab guide), how students and admins are recorded (the LMS Student role and one course enrollment per learner, two LMS roles for admins, see spec 0009), and one small custom field (`nile_key`) so a re run of the content sync never makes duplicates. Slices 1 to 3 build on this without a rework. Updated 2026-11-03 after the live site checks: LMS only plays a video and only gates a quiz from a macro in the lesson `body`, so the sync writes `{{ YouTubeVideo("id") }}` and `{{ Quiz("name") }}` into the body, as well as `youtube` and `quiz_id`.

## Requirements

**User stories**:
- As a student, I want to watch each video, pass its quiz, do the lab, pass its quiz, and then request my certificate, so that I am certified for the hands on lab.
- As a hol-admin, I want to see every student, course, attempt, and certificate so that I can track progress and build the monthly report.
- As a hol-admin, I want to reset a student's attempts on one quiz so that a student locked out after three misses can try again.
- As the operator, I want a re run of the content sync to update records in place so that renaming a lesson never leaves a duplicate.

**Acceptance criteria**:
- **AC-1**: One LMS Course holds Chapter 1 (concept videos) and one chapter per feature. A chapter can hold any mix of video, lab guide, and quiz lessons (a lab need not have a video). Where a quiz follows a lesson, it is a quiz lesson of its own, and each quiz is linked both ways to its lesson (`lesson.quiz_id` names the quiz, and `quiz.lesson` and `quiz.course` name the lesson and course). The link is also written into the lesson body as a macro (AC-10), because LMS reads it from there.
- **AC-2**: Every quiz has `passing_percentage` 80 and `max_attempts` 3 unless its content file sets another value. A score under the pass mark does not complete the quiz lesson. A fourth attempt is refused.
- **AC-3**: Every record the sync creates (course, chapter, lesson, quiz, question) carries a unique `nile_key`. Running the sync twice creates nothing new. Changing a title in git updates the same record. A record whose `nile_key` is no longer in git is removed from the course outline (and unpublished), so progress can still reach 100.
- **AC-4**: Superseded by [0009](../0009-course-access-from-groups/index.md) AC-1 and AC-2. At login a learner with a course group is a Website User with the LMS Student role and one LMS Enrollment in that course, and a member of `hol-admins` is a System User with the Moderator and Course Creator roles.
- **AC-5**: The course has certification on and lesson order not enforced. A student with every lesson and quiz complete (progress 100) can request a certificate. A student with any quiz not yet passed has progress under 100 and is refused.
- **AC-6**: A hol-admin can read every Enrollment, Course Progress, Quiz Submission, Batch, Batch Enrollment, and Certificate record, and can delete one student's Quiz Submissions for one quiz to reset their attempts. LMS gives that delete only to System Manager, so `nile_auth` ships a permission fixture that gives Moderator delete on Quiz Submission, and restates the five LMS rows with it.
- **AC-7**: A student can read only their own enrollment, progress, and attempts. Certificates follow LMS's own rule (a published certificate is visible), which the integration test records.
- **AC-8**: Before anything is written, the content check names every problem at once: a quiz with no lesson, a quiz lesson with no quiz, an empty chapter, a repeated `nile_key`, a pass mark outside 80 to 100, an attempt limit under 1, a quiz with no questions (LMS would force its pass mark to 100), or an open ended question (it is never graded automatically, so the lesson could never complete), or a video lesson whose `youtube` value is not a plain video id.

- **AC-9**: Git is the only place content is authored. A check run (`sync --check`) changes nothing and lists every synced record whose fields differ from what git would write, and every LMS record in the course with no `nile_key`. A normal sync names each LMS edit it is about to overwrite before it does so.
- **AC-10**: The sync writes the body of every video and quiz lesson. A video lesson body is exactly `{{ YouTubeVideo("<id>") }}`, and `youtube` holds the same id. A quiz lesson body is exactly `{{ Quiz("<quiz name>") }}`, where the name is the name LMS gave the quiz, and `quiz_id` holds the same name. A lab lesson body is the markdown from git and has no macro. A student cannot complete a quiz lesson without passing its quiz, and the video plays. The check run (AC-9) reports a lesson whose body differs from the macro git implies, so a quiz lesson with an empty body or a stale quiz name is found and fixed.

## Decision

**Chosen option**: Option 1: native LMS records, one course, one chapter per feature.

Model the content and progress on the native LMS records exactly as set out under Feature design, add the `nile_key` custom field, and let `nile_auth` own batches, enrollments, and roles.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**:

Content, written by the sync (feature 8) through the REST API:

| Record | Fields we set | Key | Relationship |
|---|---|---|---|
| LMS Course | `title`, `short_introduction`, `description`, `published`=1, `status`=Approved, `enable_certification`=1, `enforce_lesson_completion`=0, `instructors`, `chapters` (the Chapter Reference rows) | `nile_key` (unique) | has many Course Chapter |
| Course Chapter | `title`, `course`, `lessons` (the Lesson Reference rows) | `nile_key` (unique) | one course, has many Course Lesson |
| Course Lesson, video | `title`, `chapter`, `youtube` (the video id), `body` (`{{ YouTubeVideo("<id>") }}`) | `nile_key` (unique) | one chapter |
| Course Lesson, lab guide | `title`, `chapter`, `body` (markdown from git) | `nile_key` (unique) | one chapter |
| Course Lesson, quiz | `title`, `chapter`, `quiz_id` (the quiz name), `body` (`{{ Quiz("<quiz name>") }}`) | `nile_key` (unique) | one chapter, one LMS Quiz |
| LMS Quiz | `title`, `course`, `lesson`, `passing_percentage`, `max_attempts`, `questions` | `nile_key` (unique) | one quiz lesson (1:1), many LMS Question |
| LMS Question | question text, type, options, correct answers, marks | `nile_key` (unique) | belongs to one quiz through a Quiz Question row |

Order and membership: LMS counts progress only for lessons listed in the course's chapter table (Chapter Reference) and in each chapter's lesson table (Lesson Reference). Setting `chapter` on a lesson is not enough. The sync writes both tables, and the row position (`idx`) is the order. `total_marks` and a lesson's `course` are filled by LMS, so the sync never sets them.

Lesson body: for a video or quiz lesson the body is derived, never authored. It is built by one pure function from the lesson and, for a quiz lesson, the quiz name LMS returned. The macro is the whole body (no extra text), so the compare in AC-9 is an exact string match. `youtube` and `quiz_id` stay set beside the macro, since LMS screens and the sync's own lookups read them. Macro text is `{{ YouTubeVideo("<id>") }}` and `{{ Quiz("<quiz name>") }}`, one space inside each brace pair, double quotes. The `content` field (Editor.js blocks) is not written. The live test showed the body macro is enough.

The usual course shape is: Chapter 1 holds concept videos, each followed by its quiz. Each feature chapter holds its videos and quizzes, then the lab guide and its quiz. No lesson type is required: a feature chapter may have no videos and start at the lab guide, or have a video with no lab. The content check only enforces structure (AC-8), never a fixed lesson pattern. A quiz that exists must be linked, and a chapter must hold at least one lesson.

People and progress:

| Record | Written by | Relationship |
|---|---|---|
| User | `nile_auth` at login | type Website User for students, System User for admins |
| LMS Batch | none written by the login (spec 0009) | Old batches stay in the LMS. The unique custom field `nile_group` on LMS Batch is unused. |
| LMS Batch Enrollment | `nile_auth` | User to Batch, one per student and group |
| LMS Enrollment | LMS, from the batch enrollment; `nile_auth` fills any gap at login | User to Course, holds `progress` |
| LMS Course Progress | LMS | one row per completed lesson and student |
| LMS Quiz Submission | LMS | one row per attempt, holds `percentage` and the `passing_percentage` in force at the time |
| LMS Certificate | LMS, on the student's own request | one per User and Course |

**State transitions** (one quiz lesson, for one student):
not started → attempted below the pass mark (attempts left) → passed (lesson complete) · attempted below the pass mark, attempts used up → locked → admin deletes the submissions → not started. Progress already earned for other lessons is untouched by a reset. A passed lesson stays complete.

**API surface** (everything goes through the standard Frappe REST resource API, with the service user's token, from the tools container; no new endpoints are added by this spec):

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/resource/<doctype>?filters=[["nile_key","=",key]]` | GET | doctype, `nile_key` | the record, or none | service user token | 403 missing role |
| `/api/resource/<doctype>` | POST | the fields in the content table | new record `name` | service user token | 409 duplicate, 417 validation |
| `/api/resource/<doctype>/<name>` | PUT | changed fields | updated record | service user token | 404, 417 validation |
| `/api/method/lms.lms.doctype.lms_certificate.lms_certificate.create_certificate` | POST | `course` | the certificate `name` | the student's own session | refused if not enrolled, certification off, or progress under 100 |
| `/api/resource/LMS Quiz Submission/<name>` | DELETE | submission `name` | none | hol-admin (Moderator, after the permission fixture) | 403 |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Sync creates or updates a record | `nile_key` | a stable id inside the content file (format in feature 11) |
| Sync creates a quiz | `passing_percentage` and `max_attempts` | the quiz's content file, else the defaults 80 and 3 written in the sync code as named constants |
| Sync creates a quiz lesson | `quiz_id`, `body`, `quiz.lesson`, `quiz.course` | the names returned when the quiz and lesson were created: create the quiz first (its `name` comes back), then the lesson with `quiz_id` and `body` = `{{ Quiz("<that name>") }}`, then set `lesson` and `course` on the quiz |
| Sync creates a video lesson | `youtube`, `body` | the video id in the content file (format in feature 11, the id only, not a URL). `body` = `{{ YouTubeVideo("<id>") }}` |
| Sync updates a quiz lesson | `body` | rebuilt from the quiz's current `name`, so a quiz recreated under a new name gets its lesson body rewritten in the same run |
| Sync creates a course | `enable_certification`=1, `enforce_lesson_completion`=0 | decided in this spec |
| Sync creates a course | `instructors` | the service user |
| Sync creates a course | `short_introduction`, `description` | the course content file (format in feature 11) |
| Sync creates a course | `published`, `status` | constants 1 and Approved, decided in this spec |
| Sync creates a quiz lesson | whether the quiz is locked for a student | derived: attempts used (count of that student's Quiz Submissions for the quiz) is at least `max_attempts`, and none has `percentage` at or above `passing_percentage` |
| Sync changes the outline | every student's stored progress | recomputed by the sync for each enrollment after any chapter, lesson, or quiz is added or removed (LMS only recomputes when a progress row is saved) |
| Sync finds a record not in git | what happens to it | removed from the Chapter Reference or Lesson Reference table and unpublished, never deleted |
| `nile_auth` creates a batch | nothing | superseded by spec 0009: the login creates no batch |
| `nile_auth` creates a batch | `start_date`, `end_date` | today, and today plus 10 years (the fields are required, and the values mean nothing for reports) |
| `nile_auth` creates a batch | `start_time`, `end_time`, `timezone` | `00:00:00`, `23:59:59`, and the site's system timezone |
| `nile_auth` creates a batch | `description`, `batch_details` | the text "Students of <group name>" |
| Certificate request | `template` (required) | the print format LMS names as its default, recorded by exact name after the first live check, until branding (feature 10) sets one |
| Certificate request | issue date, member name, course title | LMS fills them (today, the user, the course) |
| Manager views | course of a student | the student's LMS Enrollment, and the `nile_groups` field for the current course |
| Manager views | pass or fail of an attempt | `percentage` against the `passing_percentage` on the same Quiz Submission row |

**Key invariants**:
- `nile_key` is unique within each of its five records. The sync never matches on title.
- The login creates no batch (spec 0009), so no batch lookup rule applies.
- The sync never deletes a record that carries a `nile_key`. It removes it from the outline and unpublishes it.
- Content flows one way, from git to the LMS. An edit made inside the LMS to a synced record is replaced at the next sync, and is reported first. A record created only in the LMS has no `nile_key`, is left alone by the sync, and is listed by the check.
- Drift is found by comparing the fields git would write with the fields the LMS holds, so no hash or extra state is stored.
- Every quiz lesson has exactly one quiz, and every quiz has exactly one lesson and a course. A quiz without a lesson would be passable but never counted, so the certificate could never be reached.
- Quizzes are never shared between lessons.
- A quiz lesson's body always names its own quiz. A quiz lesson with `quiz_id` but no macro can be completed without passing, so the sync never writes one, and the check run reports one it finds.
- There is one course certificate per student and course (no batch level certificate).
- The sync only changes records that carry a `nile_key`. It never touches other LMS content.
- A Batch exists only for a group the student actually belongs to, and is named exactly as the group.

**Security model**:
- Students get the LMS Student role, a Website User account, and no Desk access. LMS limits them to their own enrollment, progress, attempts, and certificates.
- hol-admins get Moderator and Course Creator and a System User account (they need the Desk to reset attempts). They do not get System Manager, so they cannot change site settings or the Social Login Key.
- LMS gives only System Manager the right to delete a Quiz Submission. `nile_auth` adds a permission fixture (a Custom DocPerm row) giving Moderator delete on Quiz Submission. Frappe ignores the standard rows of a doctype once it has any Custom DocPerm row, so the fixture also restates the five LMS rows (System Manager, LMS Student with `if_owner`, Moderator, Course Creator, Batch Evaluator) unchanged. Moderator gains `delete` and nothing else changes.
- The service user keeps the roles set in spec 0001 (System Manager plus the roles content sync needs). Those LMS roles are Moderator and Course Creator, confirmed in this spec.
- The roles named here (LMS Student, Moderator, Course Creator, Batch Evaluator, System Manager) were read from the permission lists in LMS v2.68.0. Batch Evaluator is not granted to anyone.
- No regulated data beyond names and emails. No compliance scope applies.

**Configuration required**: none. Pass mark and attempt limit defaults are content rules, so they live in code constants and content files, never in `.env`.

**Critical test scenarios**:
- Happy path: a student passes every quiz, completes every lesson, requests the certificate, and receives it, verifies AC-5.
- Failure case: a student scores 79% on a quiz, the lesson stays incomplete, a third miss locks the quiz, the fourth attempt is refused, an admin deletes the submissions, and the student can try again, verifies AC-2 and AC-6.
- Failure case: the sync runs twice with a renamed lesson title and creates no duplicate, verifies AC-3.
- Failure case: the content check is given a quiz with no lesson and a repeated `nile_key`, and names both, verifies AC-8.
- Happy path: the body function returns exactly `{{ YouTubeVideo("abc") }}` for a video lesson and `{{ Quiz("<name>") }}` for a quiz lesson, verifies AC-10.
- Failure case: the compare is given a quiz lesson with `quiz_id` set and an empty body, and reports it, verifies AC-10 and AC-9.
- Failure case: the live test of a quiz lesson with only `quiz_id` completing without a pass stays in the suite as the reason the macro is needed, and a quiz lesson with the macro needs the pass, verifies AC-10 and AC-2.
- Auth and permission: a student requesting another student's attempts or enrollment gets nothing back, verifies AC-7. A hol-admin reads them all, verifies AC-6.
- Happy path: a first login with a course group creates the learner and one course enrollment, and a second login creates nothing new, verifies AC-4 (as replaced by spec 0009).

## Build plan

Tracer Bullet: land the thinnest real path first (a custom field and the content model, checked against the live site), then widen. Feature 5 must be up before the last task can run.

1. Add the `nile_key` custom field (Data, unique, read only in the UI) to LMS Course, Course Chapter, Course Lesson, LMS Quiz, and LMS Question, and the unique `nile_group` field to LMS Batch, as fixtures in `apps/nile_auth/`, applied by `bench migrate`, satisfies **AC-3**, **AC-4**
1a. Add the permission fixture that gives Moderator delete on LMS Quiz Submission, satisfies **AC-6**
2. Add the content model to `tools/src/nile_tools/`: frozen data classes for course, chapter, lesson (video, lab guide, quiz), and quiz, plus the named defaults 80 and 3, satisfies **AC-1**, **AC-2**
3. Add a pure content check over that model that returns every problem at once (quiz and lesson links, empty chapters, repeated keys, pass mark and attempt limits, quizzes with no questions, open ended questions), with unit tests, satisfies **AC-1**, **AC-2**, **AC-8**
2a. Add a pure `lesson_body` function to `tools/src/nile_tools/content.py` that returns the macro body for a video lesson, the quiz macro for a quiz lesson given the quiz name, and the markdown for a lab lesson, plus a check that a video `youtube` value is a plain video id (letters, digits, `-`, `_`, 11 characters), with unit tests, satisfies **AC-8**, **AC-10**
3a. Add a pure function in `tools/` that compares the records git would write with the records fetched from the LMS and returns the differences and the unmanaged records, with unit tests. Feature 8 wraps it in `sync --check` and in the pre overwrite warning, satisfies **AC-9**
4. Add the model constants to `apps/nile_auth/` (student roles, admin roles, user types, the batch default values) in one module, for feature 7 to use, satisfies **AC-4**
5. Add an `integration` test that runs on the live site once feature 5 is up. It checks that the four custom fields exist, the role names exist, the quiz and lesson fields named here exist, and a test quiz at 80% with 3 attempts behaves as AC-2 and AC-5 say, satisfies **AC-2**, **AC-5**, **AC-6**, **AC-7**
6. Record the verified LMS field and role names in `tools/AGENTS.md` and `apps/nile_auth/` docs so later features read one list, satisfies **AC-4**, **AC-6**

## Consequences

**Positive**:
- Pass rules, attempt limits, progress, and certificates are LMS behavior, so there is little custom code to test or break.
- The manager views and report can be built straight from LMS records.
- A new feature is a new chapter, with no change to the model.

**Negative / tradeoffs**:
- A student who misses a quiz three times is locked out until an admin resets them in the Desk. A `tools` reset command is left for later.
- Batches made before spec 0009 stay in the LMS, unused, with placeholder date values.
- The model depends on LMS record and field names. An LMS upgrade must re check the list under the integration test.
- Lesson order is free, so a student can take a lab before its video. The certificate still needs everything complete.
- A course added after students enrolled only reaches them at their next login (see Follow up).

**Neutral**:
- Certificates stay course level and use the LMS default template until branding.
- Videos count as complete when the student marks them, which is how LMS works.
- Quiz questions themselves (types, marks) are authored in the content format of feature 11.

## Follow-up

- [ ] Feature 7 designs the login hook on top of this: creating the Batch, the Batch Enrollment, and the gap filling LMS Enrollment, and what happens when a student leaves a group.
- [ ] Feature 8 builds `sync --check` and the warning before an overwrite on top of the compare function from task 3a. Two way sync (exporting LMS edits back into git) was considered and left out.
- [ ] Feature 8 adds each newly synced course to every existing Batch (Batch Course row). Verify whether LMS enrolls existing batch members on that change. If it does not, `nile_auth` fills the gap at next login, as AC-4 says.
- [ ] Feature 9 settles how an admin sees which students are locked out, and whether to build the attempt reset as a `tools` command.
- [ ] Feature 11 sets the content file format, including where `nile_key`, `passing_percentage`, and `max_attempts` live, and that a video is given by its id only.
- [ ] Feature 8 builds the order of writes AC-10 needs (quiz, then quiz lesson with the macro body, then the back link), and calls `lesson_body` from task 2a.
- [x] `apps/nile_auth/README.md` no longer says the spec needs updating.
- [x] Live site checks done (2026-11-03, ticked in `verify.md`): (1) `create_certificate` works for a Website User with LMS Student with the default template; (2) a quiz lesson with the macro cannot be completed without passing, and the macro in AC-10 is the fix for `mark_lesson_progress` completing a lesson that has only `quiz_id`, so no guard is needed in `nile_auth`; (3) a video lesson with `YouTubeVideo` in `body` plays in the student view; (7) video lessons complete on a mark, and the quiz lesson does not.
- [ ] Live site checks still open: (4) the Batch Course child record has no required field beyond `course`; (5) LMS creates course enrollments from a batch enrollment when `nile_auth` inserts it as another user, and the student sees them; (6) Moderator can delete a Quiz Submission after the fixture, and a System User with those roles opens the Desk.
- [ ] `percentage` on a Quiz Submission is a whole number. The manager views compute pass or fail with the same comparison LMS uses, and accept the rounding edge.
- [ ] Add the LMS field and role names to `tools/AGENTS.md` when task 6 is done (`/sync` owns the file).
- [ ] Update spec 0001's follow up: LMS role names are now confirmed.
