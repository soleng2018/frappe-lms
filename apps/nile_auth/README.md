# nile_auth

The one custom Frappe app. It holds the service user setup, the data model fixtures, and the group to
role mapping at login. The designs are [spec 0004](../../docs/specs/0004-data-model/index.md) (data model)
and [spec 0006](../../docs/specs/0006-group-to-role-mapping/index.md) (login).

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

- `nile_auth/constants.py`: roles, user types, site config key names, outcome words, and page texts.
- `nile_auth/groups.py`: `decide()`, the pure group classifier. No Frappe, tested in `tools/tests/test_groups.py`.
- `nile_auth/login.py`: `custom`, which replaces Frappe's OIDC callback (`hooks.py`
  `override_whitelisted_methods`), and `provision`.
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
- A repeated `nile_key` or `nile_group` is refused. Records with no key are fine (they are NULL).

## The login (spec 0009, on top of spec 0006)

At each Authentik login `custom` checks the `state` token, reads `nile_admin_group` and `nile_service_user` from
site config (written by `create-site`), gets the userinfo, and classifies its `groups` list against the titles of
the managed courses (LMS Courses that have a `nile_key`). Names are compared in code, case kept.

| Groups | Result |
|---|---|
| exactly one group equal to a managed course title | LMS Student, enrolled in that course only (no batch), other managed enrollments removed, lands on the course |
| `hol-admins` | Moderator, Course Creator, Desk User (Frappe then makes a System User). Follows the group at every login. |
| no course group, known learner (enabled, LMS Student) | results mode: enrollments in managed courses removed, everything else kept, lands on the profile |
| no course group, not a known learner | 403 page, admin roles removed, nothing else touched |
| two or more course groups | 403 "linked to more than one course" page, nothing changes |
| no `groups` list, empty group setting, or one title shared by two courses | setup fault page (500), nothing changes |

Courses stay unpublished, so Frappe's own rule "published, enrolled or instructor" hides every other course.
Only the admin roles, LMS Student (added, never removed) and `nile_groups` are changed, plus the enrollments above.
Administrator, Guest, the service user, the MCP user, any System Manager, and a user whose stored subject differs
from the login are refused. One log line per login on the Frappe logger `nile_auth`
(`sites/<site>/logs/nile_auth.log`) with email, outcome, mode and course group, never a token or code.

`nile_auth.cleanup.clear_batch_courses` lists (and with `dry_run=False` removes) the Batch Course rows the old
login put into batches that carry `nile_group`.

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
- A repeated `nile_key` or `nile_group` is refused. Records with no key are fine (they are NULL).

## The login (spec 0006)

At each Authentik login `custom` checks the `state` token, reads the three group settings from site config
( `nile_service_user`, all written
by `create-site`), gets the userinfo, and classifies its `groups` list.

| Groups | Result |
|---|---|
| `hol-admins` | Moderator, Course Creator, Desk User (Frappe then makes a System User). No System Manager. |
| `NileWorkshopNAdmin` (N from 1, no leading zero) | LMS Student, a Batch per group, a Batch Enrollment, an LMS Enrollment in every published course |
| both | both of the above |
| neither | 403 page, managed roles removed, nothing else touched |
| no `groups` list, or an empty group setting | setup fault page (500), nothing changes |

Only the four managed roles and the User field `nile_groups` are changed. Nothing is ever deleted. Administrator,
Guest, the service user, any System Manager, and a user whose stored subject differs from the login are refused.
One log line per login on the Frappe logger `nile_auth` (`sites/<site>/logs/nile_auth.log`), outcome words in
`constants.py`, never a token or code.

## What the live site showed for the login (pinned by `tools/tests/test_group_role_mapping_integration.py`)

- Overriding `frappe.integrations.oauth2_logins.custom` routes `/api/method/...custom/<provider>` to `nile_auth`.
- Frappe derives the user type from the roles: Desk User gives a System User, anything else a Website User.
- LMS adds LMS Student to every new user on insert, so the role reconcile runs after the insert.
- An LMS Enrollment made as Administrator with no batch queues no mail and no job, and skips LMS's unpublished course check.
- Frappe's own `update_oauth_user` step after ours keeps the roles and links the subject.
- The login takes one named database lock per person (`GET_LOCK`), first thing after an empty commit. Two logins of
  one person end in the same state with no error. A row lock on a User that does not exist yet would take a gap
  lock, and two different new learners then deadlocked on the insert, so the lock is not a row lock. Frappe's own
  User insert can still deadlock two new learners (the `__Auth` password row, the shared `username` index). The
  loser is rolled back whole and `provision` runs again, up to four times. No isolation level change is needed
  (pinned by `test_two_logins_of_one_person_at_once` and `test_two_first_logins_of_different_people_at_once`).
- A learner can read a course through LMS's permission functions only while enrolled; self enrollment in an
  unpublished course is refused. The same holds for the course list, the catalog API, a quiz of the other course,
  and a Program that holds it (pinned by `test_a_learner_in_one_course_cannot_reach_the_other`).
- The `backend` container has no `LMS_SERVICE_USER`; only `create-site` does, which is why it is written to site config.

## Not checked

- The sign in with a real Authentik user (feature 6).
- That a System User with Moderator and Course Creator opens the Desk in a browser.
