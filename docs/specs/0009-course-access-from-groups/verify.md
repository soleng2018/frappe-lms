# Verify: course access from groups · spec 0009 · updated 2026-11-04
_Steps derived from spec 0009 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] Sign in through the real Authentik as a throwaway student in a group named like a course → lands on `/lms/courses/<course>`, LMS Student, one enrollment, no batch → AC-1, AC-11 (proved by `idp selftest`, 2026-11-04)
- [x] Sign in as a user in no course group → 403 page, no Frappe user → AC-4 (proved by `idp selftest`, 2026-11-04)

## Commands
- [x] `uv run --directory tools pytest -m integration tests/test_group_role_mapping_integration.py` → 19 pass on the live site → AC-1 to AC-13, AC-15
- [x] `make tools CMD=sync` → "nothing to change", and the only course has `published` 0 → AC-12
- [x] A `.env` that still holds `AUTHENTIK_STUDENT_GROUP_PREFIX` → `ConfigError`: "is retired, delete this line" → AC-14
- [x] `bench --site <site> execute nile_auth.cleanup.clear_batch_courses` → 0 Batch Course rows → AC-10

## Probe findings (AC-13, from the live site)
- A learner live in course B cannot read course A through `can_access_course`, `can_access_lesson`, `chapter_has_permission`, the course row permission, the LMS catalog function `get_courses`, or a list of LMS Course, and cannot read or list a quiz of A.
- A self enrollment into A is refused (ValidationError).
- An LMS Program that holds A, with the learner as a member, gives no course or lesson access to A, and a self enrollment is still refused.
- A learner may not list LMS Course or LMS Quiz through `frappe.get_list` at all (PermissionError), so the REST list leaks nothing.
- An LMS Enrollment made as Administrator with no batch queues no mail and no job.

## Acceptance-criteria coverage
- AC-1 … integration `first`, `selftest` · AC-2 … `admin_*` · AC-3 … `results` · AC-4 … `nogroup_*` · AC-5 … unit tests · AC-6 … two course groups test · AC-7 … `faults` · AC-8 … protected accounts · AC-9 … the concurrent tests (one person, and two different new people) · AC-10 … no batch, mail or job test · AC-11 … deep link and default target tests · AC-12 … live `sync` · AC-13 … the course isolation test · AC-14 … retired key test · AC-15 … the log test
