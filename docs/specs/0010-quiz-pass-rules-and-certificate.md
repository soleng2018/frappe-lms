# 0010. Pass every quiz at 80% or more, then request a shareable certificate

**Date**: 2026-11-04
**Status**: In Progress

## Summary

The LMS already enforces most of this: a quiz only counts at the pass mark, attempts stop at a limit, and a certificate is only given at 100% progress. So this spec adds almost no code. It fixes the numbers (pass at 80%, 3 attempts per quiz), says the student presses the LMS certificate button, and keeps the certificate private until a hol-admin publishes it at the student's request (a student cannot publish their own in this LMS). Publishing gives a public link that works as the LinkedIn credential address. A small log line also names any learner who loses their enrollment at 100% progress with no certificate. The one new rule is a floor: a content file may raise the pass mark but never set it under 80. The rest of the work is a live proof that every rule holds, and README steps for students and admins.

## Context

> Spec 0004 chose native LMS records and set the defaults (pass 80, 3 attempts, certificate at progress 100). Spec 0009 enrolls a learner in one course only, and removes that enrollment when the course group goes away. Scope feature 9 still owed the numbers and the certificate details.

The brief asks for a pass mark of 80% on each quiz, a limited number of retakes, and a downloadable certificate. Three facts shape the design, all read from the installed LMS (v2.68 code in the backend container):

- LMS has no overall score. Each quiz attempt stores its own percentage. Progress counts completed lessons only. A quiz lesson cannot complete without a pass (verified live, 0004 AC-10).
- The certificate button calls `create_certificate`, then opens the PDF download address. It needs an LMS Enrollment, certification on, and progress 100 (every lesson, not only quizzes). It stores no score. A new certificate has `published` 0, so only its owner can read it. The page `/certificate/<id>` redirects to the same PDF, but no student screen shows that address. The LMS Student role cannot write a certificate, so a student cannot change `published`; the Moderator role can. The quiz pass check uses the quiz's current `passing_percentage`, not the copy saved on the submission row. `percentage` is a whole number field.
- Spec 0009 removes a learner's enrollment when their course group goes away. A learner with no enrollment cannot request a certificate, but keeps one already issued.

## Requirements

**User stories**:
- As a student, I want to pass each quiz at 80% or more within 3 attempts, then press one button and get my certificate as a PDF, so that I am certified for the lab.
- As a student, I want to ask an admin to make my certificate public, so that I can add its link to LinkedIn.
- As a hol-admin, I want to publish one certificate on request in the Desk, so that its link opens for anyone.
- As a hol-admin, I want to find a student locked out of a quiz and reset their attempts in the Desk, so that they can try again.
- As the operator, I want the content check to refuse a pass mark under 80, so that a certificate always means 80% on every quiz.

**Acceptance criteria**:
- **AC-1**: Every quiz in the synced course has `passing_percentage` 80 or higher and `max_attempts` 3 unless its content file sets a different attempt limit. The content check refuses a quiz whose `passing_percentage` is under 80 or over 100, naming the quiz. It still refuses an attempt limit under 1 (0004 AC-8).
- **AC-2**: A student who scores 80% or more on a quiz completes its quiz lesson. A student who scores below 80% does not, and keeps any attempts left. After 3 attempts without a pass, a fourth is refused by the LMS.
- **AC-3**: A student enrolled in the course with progress 100 (every lesson and quiz complete) presses the LMS certificate button and receives a certificate with their name, the course title, and the issue date. A student with any lesson or quiz incomplete is refused by `create_certificate` with the LMS message "You have not completed the course yet." (the button is hidden below 100, so the test calls the method directly). There is no overall score and no other gate.
- **AC-4**: The certificate PDF opens for its owner at `https://<LMS_HOSTNAME>/certificate/<certificate name>`. The link is the PDF itself. The student finds the certificate name under Profile, Certificates (its download link holds the name), and the default print format is not empty.
- **AC-5**: A new certificate is private: a guest who opens the link gets no PDF. After a hol-admin ticks "Publish on Participant Page" on the certificate in the Desk, a guest gets the PDF. Unticking it makes it private again. A student cannot change the flag, and nothing in `nile_auth` or `tools` publishes a certificate. A private certificate gives a guest a permission failure (403).
- **AC-6**: A hol-admin (Moderator) can list Quiz Submissions in the Desk, filtered by quiz, and see a student's attempts with their percentages. They can delete one student's submissions for one quiz, and that student can then attempt it again. Passed lessons and other progress are untouched.
- **AC-7**: A learner whose course group has gone (results mode, spec 0009) still opens a certificate issued earlier, and still opens it when published. A learner with no enrollment and no certificate is refused with "You are not enrolled in this course." A learner with no enrollment who already holds a certificate gets the existing one back. A removed learner reaches old certificates under Profile, Certificates, since the course page is closed to them.
- **AC-8**: `README.md` tells a student how to request the certificate, publish it, and copy the link for LinkedIn. It tells an admin how to find and reset a locked out student. It states that the certificate must be requested while the learner is still in the course group. It tells a student to ask a hol-admin to publish, and tells the admin how.
- **AC-9**: When a login removes an enrollment (spec 0009 results mode) whose progress is 100 and whose learner holds no certificate for the course, `nile_auth` writes one warning line on the `nile_auth` logger with the email and the course, and no secret. Nothing else about the login changes.

## Options considered

### Option 1: Keep the LMS rules, add a floor and a live proof

Use LMS's own pass mark, attempt limit, progress rule, button and public toggle. Add only the 80 floor to the content check, a live integration test, and README steps.

**Pros**:
- Almost no custom code, so almost nothing to break on an LMS upgrade.
- Every rule is already enforced where students and admins use it.

**Cons**:
- A student must press the button while enrolled, and a missed window means a re entry into the course group.
- LinkedIn needs a manual publish step by an admin, because a student cannot publish.

### Option 2: Issue the certificate automatically on the last pass

A `nile_auth` hook on Quiz Submission creates the certificate when progress reaches 100.

**Pros**:
- The student never misses the window.
- Feature 15 (email on issue) hooks in at one point.

**Cons**:
- New code on a hot path and a new failure mode (hook fails, no certificate, no message).
- It bypasses LMS's own button and checks, which an upgrade can change.

### Option 3: Add an overall average gate

Require, for example, 90% averaged across quizzes, checked before issue.

**Pros**:
- Rewards high scorers.

**Cons**:
- Every student already scores 80% or more on each quiz, so the average adds a harder pass for little meaning.
- It needs custom code that replaces the LMS button, and a refusal message students would not expect.

## Decision

**Chosen option**: Option 1: keep the LMS rules, add a floor and a live proof.

The pass mark is 80 (floor), the attempt limit is 3 per quiz, the certificate is issued by the student's own button press at progress 100, stays private by default, and is made public by a hol-admin at the student's request through the LMS publish tick box in the Desk.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`)

## Rationale

The forces are a small team, a dev server, and rules that LMS already enforces (Context). Option 1 gets the full brief with one pure function change, and the proof that it works on the real site is the main deliverable. The attempt limit stays at 3 because it is already the tested default (0004), and a content file can still set another value for a special quiz. A floor of 80 is added because the brief says a certificate means 80% on every quiz, and 0004 let a content file set any pass mark from 1 to 100. The runner up was a warning only, which would let a mistaken file ship a weaker certificate.

Option 2 is the natural upgrade if students miss the window, and it can be added later without changing this spec. Option 3 was set aside because the answer to "is there an overall score" is no: LMS has none, and a per quiz 80% rule already makes any average at least 80%.

Publishing is an admin action on request because a student cannot write a certificate in this LMS, and an LMS published certificate lists the student by name on a public participants page. A small `nile_auth` method that lets the owner publish was the runner up, but it also needs a screen for the student to reach it. The cost is one admin step per LinkedIn request, written down in the README. The cleanup log line (AC-9) is the cheap guard against stranded learners. Issuing the certificate during the cleanup was the runner up, but it changes login code and bypasses the LMS button.

## Feature design

**Data model sketch**: no new records, fields or migrations. Records read or written: LMS Quiz (`passing_percentage`, `max_attempts`), LMS Quiz Submission (`percentage`, `passing_percentage` as held at the time), LMS Enrollment (`progress`), LMS Certificate (`member`, `course`, `template`, `issue_date`, `published`). All defined in spec 0004.

**State transitions** (one student and one quiz, as in 0004): not started → below the pass mark with attempts left → passed. Below the pass mark with attempts used up → locked → an admin deletes the submissions → not started. Certificate: not issued → issued and private (`published` 0) → published (`published` 1, a hol-admin's tick) → private again.

**API surface** (all LMS endpoints, none new):

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| the LMS quiz page (submit an attempt) | POST | quiz name, answers | percentage, pass or fail | the student's session | the insert past `max_attempts` raises `MaximumAttemptsExceededError` and the attempt is rolled back |
| `/api/method/lms.lms.doctype.lms_certificate.lms_certificate.create_certificate` | POST | `course` | certificate `name` and `template` | the student's session | "You are not enrolled in this course." (only if the learner has no certificate yet), certification off, "You have not completed the course yet." |
| `/certificate/<certificate name>` | GET | certificate name | redirect to the PDF | owner always, a guest only if `published` 1 | a permission failure (403) for a guest on a private certificate; a 500 if no print format exists or the id is unknown |
| `/app/lms-certificate/<name>` (Desk) | PUT | `published` | the saved certificate | Moderator, Course Creator, System Manager | 403 for a student |
| `/api/resource/LMS Quiz Submission/<name>` | DELETE | submission name | none | Moderator (fixture, 0004 AC-6) | 403 |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Content check | the pass mark floor | a named constant `MIN_PASSING_PERCENTAGE = 80` in `tools/src/nile_tools/content.py`, beside `DEFAULT_PASSING_PERCENTAGE` |
| Quiz attempt | the pass or fail of an attempt | `percentage` against the quiz's current `passing_percentage` (LMS uses the quiz value, not the copy on the row). Raising a pass mark later stops new passes from counting at the old mark; lessons already complete stay complete |
| Quiz attempt | whether a further attempt is allowed | the LMS counts that student's Quiz Submissions for the quiz after the insert and refuses any over `max_attempts`. The reply carries no attempts left value, so none is promised |
| Certificate request | `template` | LMS `get_default_certificate_template`: the default print format property setter, else the first print format of LMS Certificate. Branding (feature 10) sets the Nile format |
| Certificate request | name, course title, issue date | LMS fills them from the session user, the course, and today |
| README link | the public link | `https://<LMS_HOSTNAME>/certificate/<certificate name>`, where `LMS_HOSTNAME` is the existing key in `.env` and the name is the `name` parameter inside the download link under Profile, Certificates (an admin also sees it in the Desk list) |
| README LinkedIn steps | name, organization, issue date, credential id, credential URL | name: the course title; organization: Nile; issue date: the certificate's date; credential id: the certificate name; credential URL: the public link |
| Admin publish | which certificate | the Desk LMS Certificate list, filtered by `member` or `course` |
| Stranded learner log | email, course, progress, certificate held | the User being processed, the enrollment being removed (`progress`), and an LMS Certificate lookup by `member` and `course` |
| Admin reset | which student's rows | the Desk Quiz Submission list filtered by `quiz` and `member` |

**Key invariants**:
- No certificate is issued below progress 100, and no quiz lesson completes below its pass mark (LMS, verified in 0004).
- No synced quiz has a pass mark under 80.
- A certificate is never published by code in this repo. Only a hol-admin's tick sets `published`.
- A reset deletes Quiz Submissions only. It never changes Course Progress or a certificate.
- A certificate already issued is never revoked by a content change, a sync, or a login (0009 AC-10).

**Security model**:
- A student reads and requests only their own certificate, and reads only their own attempts (0004 AC-7). A guest reads a certificate only when it is published.
- A published certificate shows the student's name publicly: on the PDF, and on LMS's certified participants page. That is why publishing is an explicit admin action on request, never automatic.
- A hol-admin resets attempts through the Moderator delete fixture, and publishes a certificate through Moderator's own write right on LMS Certificate. No new role or permission is added. A student cannot write a certificate.
- Proctoring stays off. LMS Quiz Violation Log rows link to a Quiz Submission, and a linked row could block a reset.
- No regulated data beyond names and emails. No compliance scope applies.

**Configuration required**: none. The floor and the defaults are named constants in code, not `.env` keys.

**Critical test scenarios** (the live ones carry the `integration` marker):
- Happy path: a student passes every quiz at 80% or more, then requests the certificate and receives it with their name, course title and date, verifies **AC-2**, **AC-3**.
- Failure case: a quiz answered at 60% leaves the lesson incomplete with attempts left. Three misses lock the quiz and a fourth attempt is refused, verifies **AC-2**.
- Failure case: a student with one quiz unpassed (or any lesson incomplete) calls `create_certificate` directly and gets "You have not completed the course yet.". The test marks the non quiz lessons complete first through the same progress call the LMS uses, verifies **AC-3**.
- Failure case: a fourth attempt raises `MaximumAttemptsExceededError` and no fourth submission row exists, verifies **AC-2**.
- Happy path: the owner opens `/certificate/<id>` and gets a PDF, verifies **AC-4**.
- Auth/permission: a guest opens the link of a private certificate and gets no PDF. After a Moderator publishes it a guest gets the PDF. After unpublishing, a guest gets none. A student's attempt to set `published` is refused, verifies **AC-5**.
- Auth/permission: a Moderator deletes one student's submissions for one quiz, that student can attempt again, and other students' attempts and passed lessons are untouched, verifies **AC-6**.
- Edge case: a learner removed from the course group keeps and opens an earlier certificate and gets the same one back from `create_certificate`. A removed learner with no certificate is refused with the not enrolled message, verifies **AC-7**.
- Edge case: a login that removes an enrollment at progress 100 with no certificate writes the warning line with email and course, and removes nothing extra, verifies **AC-9**.
- Unit: the content check refuses `passing_percentage` 79 and 101, accepts 80 and 100, and names the quiz, verifies **AC-1**.

## Build plan

Tracer Bullet: prove the whole path on the live site first with the thinnest test, then lock it in as tests and docs. The code is the floor and one log line.

1. Probe the live site by hand with a throwaway course and student: the 80 boundary, the fourth attempt refusal, the certificate request, the link for a guest while private and while published, the Moderator reset, the Moderator publish, a student refused when setting `published`, and the not enrolled refusal. Probe a score of 79.5 to see whether it stores as 79 or 80 and write the real rounding rule into the README and this spec. Note the default print format name (it must not be empty) and any surprise in the PR description, satisfies **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-7**, **AC-8**
2. Raise the floor: add `MIN_PASSING_PERCENTAGE = 80` and change the quiz check in `tools/src/nile_tools/content.py` to refuse a pass mark under it or over 100, with unit tests for 79, 80, 100 and 101. Update the wording of 0004 AC-8 in the same change, satisfies **AC-1**
3. Add an `integration` test `tools/tests/test_pass_certificate_integration.py` that creates a throwaway course with an 80%, 3 attempt quiz and a throwaway student, and walks the happy path, the lock and the `MaximumAttemptsExceededError`, the refusal, the private and Moderator published link, the reset, and the removed enrollment case, then deletes what it made, satisfies **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-7**
4. Add the warning line in the `nile_auth` login cleanup for a learner whose enrollment is removed at progress 100 with no certificate, with a unit test in the existing stubbed Frappe tests, satisfies **AC-9**
5. Write the README sections (student: request, find the certificate under Profile, Certificates, ask for publishing, LinkedIn fields; admin: find and reset, publish; the request window note; the rounding rule), satisfies **AC-8**

## Consequences

**Positive**:
- Very little custom code, so little to break on an LMS upgrade.
- Every rule in the brief is proven by a live test, and the sharing path for LinkedIn needs no LMS change.
- Privacy by default: nobody is listed publicly until an admin publishes at the student's request.
- The log line (AC-9) finds stranded learners without changing who gets what.

**Negative / tradeoffs**:
- A learner must press the certificate button while still in the course group. If the group goes away first, they cannot request one (0009 removes the enrollment). The fix is to put them back in the group for a moment, and the AC-9 log line names who needs it. Option 2 would remove this and is the planned upgrade if it happens.
- A locked out student waits for an admin to reset them in the Desk. A `tools` reset command and a locked out report are left to feature 12.
- LinkedIn needs a student request to an admin, an admin publish, and then the student copies the link.
- `percentage` is a whole number field. A score such as 79.5 may be cut to 79 and fail, or rounded to 80. The live probe records which, and the README states it.
- Until branding (feature 10), the certificate uses LMS's default print format.

**Neutral**:
- A content file may set more than 3 attempts or a pass mark above 80 for a special quiz.
- Certificates stay course level, one per student and course.

## Follow-up

- [ ] Live check: a guest opens `/certificate/<id>` when `published` is 1. The code path allows it (the cross check read it), but it was not run as a guest. If it fails, this spec returns to `/architect`.
- [ ] Feature 15 (outbound email): the LMS already sends a certification email on issue when an outgoing account exists. Check that before building any second mail.
- [ ] Open question for later: a student publish control (a `nile_auth` method plus a link or page) if admins get too many requests.
- [ ] Live check (open from 0004): Moderator can delete a Quiz Submission after the fixture, and a System User with those roles opens the Desk.
- [ ] Feature 10 (branding) sets the certificate print format. Re check AC-4 and AC-5 after it lands.
- [ ] Feature 12 (manager progress view) decides whether to show locked out students and a reset command.
- [ ] If students miss the certificate window in practice, design Option 2 (issue on the last pass) as its own spec.
- [ ] Update 0004 AC-8 and scope feature 9 to say "80 or higher" when this spec is built.
