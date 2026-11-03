# nile_auth

The one custom Frappe app. It holds the service user setup, the data model fixtures, and (later) the
group to role mapping at login. The design is in [spec 0004](../../docs/specs/0004-data-model/index.md).

## Verified LMS names (LMS v2.68.0, checked on the live site)

| Kind | Names |
|---|---|
| Roles | `LMS Student`, `Moderator`, `Course Creator`, `Batch Evaluator`, `System Manager` |
| Custom field `nile_key` (Data, unique) | LMS Course, Course Chapter, Course Lesson, LMS Quiz, LMS Question |
| Custom field `nile_group` (Data, unique) | LMS Batch |
| Course Lesson fields | `chapter`, `title`, `body`, `youtube`, `quiz_id`, `course` |
| LMS Quiz fields | `title`, `course`, `lesson`, `passing_percentage`, `max_attempts`, `total_marks` |
| LMS Quiz Submission | `quiz`, `member`, `score`, `score_out_of`, `percentage`, `passing_percentage` (all required) |
| Attempt limit | The submission after `max_attempts` is refused with `MaximumAttemptsExceededError` |

## Files

- `nile_auth/constants.py`: roles, user types, and batch defaults for the login hook.
- `nile_auth/fixtures/`: the custom fields and the Moderator delete permission on LMS Quiz Submission.
  Applied by `bench migrate`.

## What the live site showed (pinned by `tools/tests/test_data_model_integration.py`)

- **Quiz lessons are gated by the body, not by `quiz_id`.** LMS finds a lesson's quizzes from a
  `{{ Quiz("<quiz name>") }}` macro in `body` (or from `content` blocks). A quiz lesson with only
  `quiz_id` can be marked complete without passing. Video lessons show only when `body` has a
  `{{ YouTubeVideo("<id>") }}` macro (from reading the source, not run). The sync therefore writes both
  macros into `body` (spec 0004 AC-10), built by `lesson_body` in `tools/src/nile_tools/content.py`.
- A passing `submit_quiz` completes the quiz lesson by itself, when `quiz.lesson` and `quiz.course` are set.
- Video and lab lessons complete when the student marks them (`save_progress`).
- `create_certificate` works for a Website User with only LMS Student, no evaluator needed. It is refused
  under 100% progress. The certificate is created unpublished, and only its owner can read it.
- A student reads only their own Quiz Submission (LMS gives LMS Student `read` with `if_owner`), their own
  Enrollment, and no one else's progress or certificates. Once a doctype has any Custom DocPerm row, Frappe
  ignores its standard permissions, so the Quiz Submission fixture restates all five LMS rows and adds
  `delete` for Moderator.
- An LMS Batch with the spec values saves. Inserting a Batch Enrollment as Administrator creates the
  course enrollments. Run the login hook as Administrator: a Batch Enrollment by anyone else needs
  Moderator, Batch Evaluator, or self enrollment switched on.
- Adding a course to a batch later does not enroll its existing members, so `nile_auth` fills the gap at login.
- A repeated `nile_key` or `nile_group` is refused. Records with no key are fine (they are NULL).

## Not checked

That a System User with Moderator and Course Creator opens the Desk in a browser.
