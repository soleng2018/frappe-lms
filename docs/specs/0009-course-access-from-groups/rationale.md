# 0009. Rationale: give each learner only the course they booked

Build spec: see [index.md](index.md).

## Context

> ⚠️ Premise note: the spec uses a course title as the access key, and a title is editable, not unique in LMS (the course `name` is a slug of it, so two courses can share a title), and compared by the database without case. A rename silently stops access for new learners, and a duplicate title makes a group ambiguous. The safer frame is a separate fixed access name. The engineer chose the title, so the spec keeps it and adds guards: sync names every title change, refuses a duplicate and a title equal to the admin group, the login compares names in code with the case kept, a group that matches two courses refuses the login instead of guessing, and the reservation contract refuses a course group name that already exists in Authentik (a course titled like any other group would admit that group's members).

The LMS must certify learners for a hands on lab, and there will be several courses. A learner picks the course in the reservation app. That app then assigns the first free testbed of the matching type, and the Authentik group of that testbed is the only thing the LMS sees today. The learner never picks a group.

Spec 0006 turns membership of a testbed group into a student who is enrolled in every published course, through an LMS Batch that carries every published course. LMS decides who may read a course by one rule, written in `lms/lms/permissions.py` and repeated in `utils.get_course_details` and `get_lesson`: the course is published, or the user is enrolled, or the user is an instructor. Joining a batch enrolls the member in every course the batch holds, so a batch with all courses re grants all of them. A published course can also be entered by the learner through self enrollment.

The reservation app already has a worker that adds a learner to a group when a booking starts and removes them when it ends, and it guarantees one live booking per learner. Authentik is the one place that decides who may sign in. The learner must keep the certificate after the slot, and the operator wants Authentik, not Frappe, to revoke access. The pinned versions are LMS v2.68.0 and Frappe v16.54.0, and the `.env` parser rejects keys it does not know.

## Options considered

### Option 1: A course group named like the course, unpublished courses, direct enrollment (chosen)

The reservation app creates one Authentik group per course, named exactly like the course title. Frappe compares group names to managed course titles. One match enrolls the learner in that course and removes every other managed enrollment. No match leaves a known learner in results mode, with no enrollments. Courses stay unpublished, so LMS hides them from everyone not enrolled.

**Pros**:
- One signal, already carried by the `groups` claim, so no new claim mapping.
- LMS enforces the hiding itself; the only new rules are in the login.
- Fits the reservation worker's existing add and remove model and its one live booking rule.

**Cons**:
- The title becomes an access key (guarded, not eliminated).
- The reservation app must learn to create groups, which it forbids itself today.

### Option 2: A user attribute and a custom claim

The reservation app writes an attribute such as `hol_course` on the learner's Authentik user, and a scope mapping on the LMS provider emits it as a claim.

**Pros**:
- No extra group per course in Authentik.
- One value, no matching against titles.

**Cons**:
- A new scope mapping to maintain and attach to the provider, and the claim must be requested.
- The attribute must be cleared when the booking ends, and the course key is free text with nothing validating it at save time.
- Group membership is the thing the reservation worker already reconciles; an attribute is a second mechanism.

### Option 3: A map in Frappe from testbed group to course

Frappe keeps a table of testbed group to course. No change outside this repo.

**Pros**:
- Cheapest. No cross repository work.

**Cons**:
- It follows the testbed, not the booking. The reservation app lets an admin change a testbed's type while bookings stay as booked, so the map drifts from what the learner chose.
- One testbed can never host two courses.
- A second list of facts to keep in step with reservations.

### Option 4: A course group with a soft lock (published, self learning off)

Same signal as Option 1, but courses stay published with `disable_self_learning` on, so the catalog shows every course and its outline while the content stays locked to the enrolled.

**Pros**:
- Learners can see what other courses exist.
- No behavior change for the catalog.

**Cons**:
- The learner still sees titles, descriptions, and chapter outlines of courses they did not book, against the goal of being restricted to one course.
- Needs a second flag kept right on every course.

## Rationale

Option 1 fits the forces. The learner chooses a course at booking time, and only the reservation app knows that choice, so the signal has to start there (which rules out Option 3). LMS already hides an unpublished course from everyone not enrolled, at the data layer and in the APIs, so the lock needs no custom permission code. Option 4 leaves the other courses visible, and Option 2 adds a mechanism where groups already exist. The engineer's own description (a group created when a course is added, named like the course) is Option 1.

The engineer first asked whether the testbed group still matters. It does not for the course, and the spec ignores it, because the reservation app guarantees at most one course group per learner, so the course group alone says which course is live. Two alternatives for the state after the slot were weighed and dropped. A permanent group per course fails: with groups for two courses, Frappe could not tell which is live, until the engineer ruled out a second group by guaranteeing one at a time. Two groups per course (a permanent one and a live one) would let Authentik revoke per course, but it doubles what the reservation app must create and manage. Full access forever contradicts the wish to show only results and the certificate.

Results mode removes the LMS Enrollment, because LMS gives lessons only to enrolled learners and gives a learner their own certificate and submissions with no enrollment. That relaxes spec 0006's rule that enrollments are never deleted, for LMS Enrollment rows of managed courses only; progress, attempts, and certificates stay. Frappe cannot learn from the groups alone that a person once was a learner, so "known learner" is the LMS Student role, which `nile_auth` adds at the first live login and never removes. A stranger with no course group is still refused, so Frappe creates users only for people who booked.

Matching only managed courses (those with a `nile_key`) keeps grant and prune symmetric and follows the rule that scripts touch only what they created. It also removes the case of a hand made course sharing a title with a git course.

The READ COMMITTED setting of spec 0006 existed to make two first logins of one group agree on one batch. With no batch, the race that remains is one person logging in twice. Locking only that person's User row, as the first statement after a commit, serializes the two logins, and the first plain read after it opens the read view, so it sees what the other login committed. Locking course rows too would run every login on the site one at a time and block sync, so it is not done; LMS takes the course row lock itself when it inserts an enrollment. The build keeps the old setting until a two process test proves this, so a wrong guess costs a revert, not an outage. Two first logins of one new person have no row to lock and may collide on the insert, which is accepted.

Two matches refuse the login, even for an admin, because the engineer asked for a plain refusal when two courses show up. An admin locked out by a reservation bug still has `Administrator` and the service user.

## Cross check

On 2026-11-04 an independent read only pass on another model (Opus) checked the first draft. It found 14 points and all were applied: the role reconcile must touch only admin roles; the claim check and the two courses check come before the user checks; the landing rule must treat the generic `redirect_to` values as absent; lock only the User row; state the first login race; account for the Deleted Document rows; set progress on a new enrollment; probe for side effects of an enrollment insert and delete; name the dev site cleanup function; apply the retired key message on every path; state the log mode of an admin who is a known learner; refuse a title equal to the admin group and compare duplicates in code; correct the rollback claim; probe LMS Programs and the Portal Settings default role. It could not verify the LMS and Frappe claims because the source is not on the host, so they are probe tasks.

## Evidence

**LMS v2.68.0** (read from source at the pinned tag, `frappe/lms`):
- `lms/lms/permissions.py`: `can_access_course` is published, or author, or enrolled. `course_query_conditions` and the chapter rule apply the same test to lists. `course_lesson.has_permission` gives lessons to the enrolled, instructors, and preview lessons of a published course.
- `lms/lms/utils.py`: `get_lesson` comment says an unpublished course is readable by its authors and learners. `get_courses` with the `enrolled` filter is self scoped and includes drafts. `get_course_details` allows members.
- `lms/lms/doctype/lms_enrollment/lms_enrollment.py`: `validate_course_enrollment_eligibility` refuses an unpublished course and a `disable_self_learning` course for anyone who is not staff; `managed_by_caller` lets `Administrator` through.
- `lms/lms/doctype/lms_batch_enrollment/lms_batch_enrollment.py`: `validate_course_enrollment` enrolls the member in every Batch Course of the batch.
- `lms/lms/doctype/lms_certificate/lms_certificate.py`: a learner reads their own certificate, published or not; creating one needs an enrollment, not a published course.
- `lms/lms/permissions.py`: own Quiz and Assignment submissions and own progress rows are readable without an enrollment.
- `frontend/src/pages/ProfileCertificates.vue`: the profile page lists certificates through `get_user_certificates` and downloads the PDF.
- `lms_course.py`: the course `name` is `generate_slug(title)`, so titles are not unique.

**Reservations** (`soleng2018/reservations`):
- `db/migrations/0001_core.sql`: a testbed has one type; a booking keeps its own `testbed_type_id`; one live booking per user.
- `server/worker/reconcile.ts`: adds a learner to the testbed group while a confirmed booking is current and removes them after, and ends their Authentik sessions.
- `server/authentik/guard.ts` and `AGENTS.md`: the app never creates a group; writes go through a guard that allows only tagged learners and marked groups.
- `docs/specs/0010-availability-booking-rules/index.md`: the server assigns the first free testbed of the type in name order.

**nile-idp** (`soleng2018/nile-idp`):
- `scripts/nile_idp.py` and `docs/authentik-nile-saml-spec.md`: the `Nile: memberOf` mapping yields every group of the user; only the access group carries `hol_testbed_group` and `hol_testbed_domain`.

**This repository**:
- `apps/nile_auth/nile_auth/login.py`, `groups.py`, `constants.py`: the code this spec reworks.
- `tools/src/nile_tools/plan.py` (`_course_fields` sets `published` 1; `_batch_adds`) and `sync.py` (`AddToBatch`): the sync behavior that changes.
- `tools/src/nile_tools/config.py`: the strict parser reports an unknown key, which is why the two retired keys need their own message.
- `docs/specs/0008-idp-login/index.md` (untracked, Proposed, by another session): overlaps in AC-3, AC-10, AC-11, and the selftest.
