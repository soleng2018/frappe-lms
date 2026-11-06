"""The progress and quiz rules of the manager reports (spec 0013). Pure: no Frappe, no I/O.

The reports and the monthly report (feature 13) call these functions, so their numbers match.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

__all__ = [
	"DATASETS",
	"QUIZ_STATES",
	"STATUSES",
	"assemble",
	"filter_progress_rows",
	"filter_quiz_rows",
	"progress_percent",
	"quiz_state",
	"round_half_up",
	"status_for",
]

STATUS_NOT_STARTED = "Not started"
STATUS_IN_PROGRESS = "In progress"
STATUS_READY = "Ready for certificate"
STATUS_CERTIFIED = "Certified"
STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_READY, STATUS_CERTIFIED)

STATE_NOT_ATTEMPTED = "Not attempted"
STATE_IN_PROGRESS = "In progress"
STATE_PASSED = "Passed"
STATE_LOCKED = "Locked"
QUIZ_STATES = (STATE_NOT_ATTEMPTED, STATE_IN_PROGRESS, STATE_PASSED, STATE_LOCKED)

UNLIMITED = "Unlimited"
LESSON_COMPLETE = "Complete"

# The fixed set of lists the assembly asks for. One fetch call each, whatever the number of learners.
# `outline` rows come ordered by course, chapter position, then lesson position.
DATASETS = (
	"courses",  # name, title, nile_key (managed courses only)
	"outline",  # course, lesson
	"enrollments",  # member, course
	"progress",  # member, course, lesson, status, modified
	"quizzes",  # name, title, lesson, max_attempts, passing_percentage
	"submissions",  # member, quiz, percentage, creation
	"certificates",  # name, member, course, issue_date, published, creation
	"users",  # name, full_name, enabled
)

Fetch = Callable[[str], list[dict[str, Any]]]


def round_half_up(numerator: int, denominator: int) -> int:
	"""Round a non negative fraction to a whole number, halves up (72.5 gives 73)."""
	return (2 * numerator + denominator) // (2 * denominator)


def progress_percent(done: int, total: int) -> int:
	"""Lessons done as a whole percent, rounded down, so 100 means every lesson is done."""
	if total <= 0:
		return 0
	return min(100, done * 100 // total)


def status_for(certified: bool, done: int, total: int) -> str:
	"""Return the first matching status: Certified, Ready for certificate, In progress, Not started."""
	if certified:
		return STATUS_CERTIFIED
	if total > 0 and done == total:
		return STATUS_READY
	if done >= 1:
		return STATUS_IN_PROGRESS
	return STATUS_NOT_STARTED


def quiz_state(best: int | None, used: int, allowed: int, pass_mark: int) -> str:
	"""Return Passed, Locked, In progress or Not attempted. An allowed count of 0 means unlimited."""
	if used >= 1 and best is not None and best >= pass_mark:
		return STATE_PASSED
	if allowed > 0 and used >= allowed:
		return STATE_LOCKED
	if used >= 1:
		return STATE_IN_PROGRESS
	return STATE_NOT_ATTEMPTED


def _latest(values: Iterable[Any]) -> Any:
	present = [v for v in values if v is not None]
	return max(present) if present else None


def _outline_by_course(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
	"""Distinct lessons per course, in outline order (a lesson referenced twice counts once)."""
	out: dict[str, list[str]] = defaultdict(list)
	for r in rows:
		if r["lesson"] not in out[r["course"]]:
			out[r["course"]].append(r["lesson"])
	return out


def _group(rows: list[dict[str, Any]], *keys: str) -> dict[tuple, list[dict[str, Any]]]:
	out: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
	for r in rows:
		out[tuple(r[k] for k in keys)].append(r)
	return out


def _newest_certificate(certs: list[dict[str, Any]]) -> dict[str, Any] | None:
	if not certs:
		return None
	return max(certs, key=lambda c: (c.get("issue_date") or "", c.get("creation") or ""))


def _lower_sort(row: dict[str, Any]) -> str:
	return (row["full_name"] or row["learner"]).lower()


def assemble(
	fetch: Fetch, excluded_users: Iterable[str] = ()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	"""Build every Learner Progress row and every Quiz Scores row, unfiltered and ordered."""
	data = {name: fetch(name) for name in DATASETS}
	excluded = {u for u in excluded_users if u} | {"Administrator"}
	courses = {c["name"]: c for c in data["courses"] if c.get("nile_key")}
	users = {u["name"]: u for u in data["users"]}
	outline = _outline_by_course([r for r in data["outline"] if r["course"] in courses])

	quizzes_by_course: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for course, lessons in outline.items():
		by_lesson = _group(data["quizzes"], "lesson")
		for lesson in lessons:
			quizzes_by_course[course].extend(by_lesson.get((lesson,), []))

	enrolled = {(e["member"], e["course"]) for e in data["enrollments"]}
	progress = _group(data["progress"], "member", "course")
	certs = _group(data["certificates"], "member", "course")
	subs = _group(data["submissions"], "member", "quiz")

	keys = {k for k in [*enrolled, *progress, *certs] if k[1] in courses and k[0] in users}
	keys = {k for k in keys if k[0] not in excluded}

	progress_rows: list[dict[str, Any]] = []
	quiz_rows: list[dict[str, Any]] = []
	for member, course in keys:
		user, info = users[member], courses[course]
		lessons = outline.get(course, [])
		in_outline = set(lessons)
		prog = progress.get((member, course), [])
		done = len(
			{p["lesson"] for p in prog if p["status"] == LESSON_COMPLETE and p["lesson"] in in_outline}
		)
		cert_list = certs.get((member, course), [])
		cert = _newest_certificate(cert_list)

		passed, attempted_bests, sub_times = 0, [], []
		for q in quizzes_by_course.get(course, []):
			attempts = subs.get((member, q["name"]), [])
			best = max((a["percentage"] or 0 for a in attempts), default=None)
			pass_mark = q["passing_percentage"] or 0
			allowed = q["max_attempts"] or 0
			last = _latest(a["creation"] for a in attempts)
			sub_times.append(last)
			if best is not None:
				attempted_bests.append(best)
			state = quiz_state(best, len(attempts), allowed, pass_mark)
			passed += state == STATE_PASSED
			quiz_rows.append(
				{
					"learner": member,
					"full_name": user["full_name"],
					"course": info["title"],
					"course_name": course,
					"quiz": q["name"],
					"quiz_title": q["title"],
					"best_score": best,
					"attempts_used": len(attempts),
					"attempts_allowed": allowed or UNLIMITED,
					"pass_mark": pass_mark,
					"state": state,
					"last_attempt": last,
				}
			)

		avg = round_half_up(sum(attempted_bests), len(attempted_bests)) if attempted_bests else None
		progress_rows.append(
			{
				"learner": member,
				"full_name": user["full_name"],
				"course": info["title"],
				"course_name": course,
				"status": status_for(bool(cert_list), done, len(lessons)),
				"enrolled": "Yes" if (member, course) in enrolled else "No",
				"enabled": "Yes" if user["enabled"] else "No",
				"lessons_done": done,
				"lessons_total": len(lessons),
				"progress": progress_percent(done, len(lessons)),
				"quizzes_passed": passed,
				"quizzes_total": len(quizzes_by_course.get(course, [])),
				"avg_best": avg,
				"last_activity": _latest([*(p["modified"] for p in prog), *sub_times]),
				"certificate": cert["name"] if cert else None,
				"issue_date": cert["issue_date"] if cert else None,
				"published": ("Yes" if cert["published"] else "No") if cert else None,
			}
		)

	progress_rows.sort(key=lambda r: (r["course"].lower(), _lower_sort(r), r["learner"]))
	position = {(course, q["name"]): i for course, qs in quizzes_by_course.items() for i, q in enumerate(qs)}
	quiz_rows.sort(
		key=lambda r: (
			r["course"].lower(),
			_lower_sort(r),
			r["learner"],
			position[(r["course_name"], r["quiz"])],
		)
	)
	return progress_rows, quiz_rows


def _check(value: str | None, allowed: tuple[str, ...], label: str) -> None:
	if value and value not in allowed:
		raise ValueError(f"{label} must be one of: {', '.join(allowed)}")


def _matches_learner(row: dict[str, Any], learner: str | None) -> bool:
	if not learner:
		return True
	needle = learner.strip().lower()
	return needle in (row["full_name"] or "").lower() or needle in row["learner"].lower()


def filter_progress_rows(
	rows: list[dict[str, Any]],
	course: str | None = None,
	status: str | None = None,
	learner: str | None = None,
	enrolled_only: bool = False,
) -> list[dict[str, Any]]:
	"""Apply the Learner Progress filters with AND. A status outside the list raises ValueError."""
	_check(status, STATUSES, "Status")
	return [
		r
		for r in rows
		if (not course or r["course_name"] == course)
		and (not status or r["status"] == status)
		and _matches_learner(r, learner)
		and (not enrolled_only or r["enrolled"] == "Yes")
	]


def filter_quiz_rows(
	rows: list[dict[str, Any]],
	course: str | None = None,
	state: str | None = None,
	learner: str | None = None,
) -> list[dict[str, Any]]:
	"""Apply the Quiz Scores filters with AND. A state outside the list raises ValueError."""
	_check(state, QUIZ_STATES, "State")
	return [
		r
		for r in rows
		if (not course or r["course_name"] == course)
		and (not state or r["state"] == state)
		and _matches_learner(r, learner)
	]
