# 0004 Rationale: Model courses, quizzes, batches, and roles on native LMS records

## Context

The brief asks students to watch videos, follow a lab guide, pass a quiz after each at 80% or higher, and then get a certificate. Managers track progress and want a monthly report. Content lives in git and is pushed to Frappe by a script (scope features 8 and 11). Students and admins come from Authentik groups: a group named like a course for a student, and `hol-admins` for an admin (scope feature 7, spec 0009).

Four later features read or write the same records: the content sync (8), the login hook that maps groups to roles (7), the quiz and certificate rules (9), and the progress view and report (12, 13). If each invented its own shape for a course, an attempt, or an enrollment, they would clash. This spec is the single place that says which LMS record holds what, who writes it, and which role may touch it.

The course is larger than the scope first assumed. Chapter 1 holds a set of core concept videos (what Nile is, how the service is offered), each followed by its own quiz. After that, every feature gets its own chapter with small feature videos and quizzes, then a feature lab and a lab quiz. New features are added over time, so adding a feature must mean adding a chapter and nothing more.

The LMS records and rules named below were read from the pinned release (v2.68.0) source, not recalled. Spec 0001 had listed the role names as unverified, and this spec confirms them.

The first version of this spec had the sync set only `youtube` on a video lesson and only `quiz_id` on a quiz lesson. The live site test (`tools/tests/test_data_model_integration.py`) showed that is not enough. LMS finds a lesson's quiz from a `{{ Quiz("<quiz name>") }}` macro in `body`, so a quiz lesson with only `quiz_id` completes without a pass, and a video shows from a `{{ YouTubeVideo("<id>") }}` macro in `body`. A quiz lesson with the macro needs the pass, as AC-2 and AC-5 require.

## Options considered

### Option 1: Native LMS records, one course, one chapter per feature, one batch per group

Use LMS Course, Course Chapter, Course Lesson, LMS Quiz, LMS Quiz Submission, LMS Enrollment, LMS Course Progress, LMS Batch, and LMS Certificate as they are. Quizzes are lessons. Batches are no longer used by the login (spec 0009). A custom field `nile_key` on four records gives the sync a stable match.

**Pros**:
- The pass rule, the attempt limit, progress, and certificate checks already work and are maintained upstream.
- The manager views and the report read records LMS already fills.
- Adding a feature is adding a chapter.

**Cons**:
- We depend on LMS internals staying put across upgrades (pinned tag, checked when the pin moves).
- A student who burns three attempts is stuck until an admin resets them.
- Batches need required fields (dates, times, instructors) that mean nothing for us.

### Option 2: Custom records for attempts, progress, and certificates

Build our own doctypes for pass rules and certificates and use LMS only to show content.

**Pros**:
- Full control of the pass and retake rules.

**Cons**:
- Duplicates what LMS already does, and the LMS screens would not show our data.
- More code to keep working with each Frappe upgrade.

### Option 3: One course per feature, with a certificate each

Each feature becomes its own course with its own certificate.

**Pros**:
- Smaller courses, and a certificate per feature.

**Cons**:
- The brief asks for one certificate after the whole path, and LMS has no certificate that spans courses.
- Enrollment and reporting multiply with every feature.

## Rationale

The forces are a small team, a dev server, and a rule set (80% pass, limited retakes, certificate at completion) that LMS already implements. Reusing it keeps the custom code to one small app and means the LMS screens, and the report in slice 3, show real data without translation. Option 2 buys control we do not need and pays for it on every upgrade. Option 3 fails the brief, which asks for one certificate.

Two choices were made for you where expertise settled them. Course level certification (not batch level) keeps one certificate per student and course, and it matches LMS's own self service button. Batches are created by `nile_auth` at first login, because the group number N is open ended and cannot be listed in advance.

A weak spot to accept knowingly: a quiz lesson is only marked complete by a pass, so the three attempt limit can lock a student out. The reset is a manual admin step for now (the scope asks for a limit, and this keeps it real).
