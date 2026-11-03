# nile_auth

The one custom Frappe app. It holds the service user setup, the data model fixtures, and (later) the
group to role mapping at login. The design is in [spec 0004](../../docs/specs/0004-data-model.md).

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

## Not yet verified on the live site

The certificate request, progress at 100, and a student's view of their own records (AC-5, AC-7), plus
the other open checks in the spec's Follow-up.
