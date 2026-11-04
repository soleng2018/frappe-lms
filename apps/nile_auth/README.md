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

- `nile_auth/constants.py`: roles, user types, batch defaults, site config key names, outcome words, and page texts.
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
- Adding a course to a batch later does not enroll its existing members, so `nile_auth` fills the gap at login.
- A repeated `nile_key` or `nile_group` is refused. Records with no key are fine (they are NULL).

## The login (spec 0006)

At each Authentik login `custom` checks the `state` token, reads the three group settings from site config
(`nile_admin_group`, `nile_student_group_prefix`, `nile_student_group_suffix`, plus `nile_service_user`, all written
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
- `confirmation_email_sent = 1` on the Batch Enrollment queues no mail. LMS Settings has batch notifications off.
- Frappe's own `update_oauth_user` step after ours keeps the roles and links the subject.
- **A locking read of a batch that does not exist yet deadlocks two simultaneous first logins** (gap locks), and
  under MariaDB's default REPEATABLE READ the losing login cannot see the winner's row through LMS's own reads
  (Batch Enrollment link check). So `custom` runs its transaction at READ COMMITTED (`SET SESSION`, then a commit
  of the empty transaction, and puts the level back at the end), reads the batch plainly first, and locks only a row
  that exists or after a duplicate key error. Spec 0006 was updated to say this on 2026-11-03.
- Course top up reaches only the groups in the current login. Batches of groups a student has left are not changed.
- The `backend` container has no `LMS_SERVICE_USER`; only `create-site` does, which is why it is written to site config.

## Not checked

- The sign in with a real Authentik user (feature 6).
- That a System User with Moderator and Course Creator opens the Desk in a browser.
