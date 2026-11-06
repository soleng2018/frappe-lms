"""The Monthly Report rules (spec 0014). Pure: no Frappe, no I/O.

It shares the row set, the outline and the quiz rules with `progress.py`, so the numbers match the
Learner Progress report. Every rule is judged as of the end of the chosen month (the cutoff).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from nile_auth.progress import (
	DATASETS,
	LESSON_COMPLETE,
	STATE_LOCKED,
	STATE_PASSED,
	Fetch,
	attempt_score,
	counted_quizzes,
	excluded_set,
	group,
	lower_sort,
	matches_learner,
	newest_certificate,
	outline_by_course,
	quiz_state,
	round_half_up,
	row_keys,
)

__all__ = [
	"DATASETS",
	"OUTCOME_NOT_PASSED",
	"OUTCOME_PASSED",
	"RESULTS",
	"RESULT_BEHIND",
	"RESULT_DONE",
	"BadFilter",
	"Window",
	"as_of",
	"build_rows",
	"filter_rows",
	"monthly_rows",
	"parse_month",
	"totals",
]


class BadFilter(ValueError):
	"""A filter value the report cannot use (a bad month or result)."""


RESULT_DONE = "Done"
RESULT_BEHIND = "Behind"
RESULTS = (RESULT_DONE, RESULT_BEHIND)
OUTCOME_PASSED = "Passed"
OUTCOME_NOT_PASSED = "Not passed"

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SETTLED = (STATE_PASSED, STATE_LOCKED)


@dataclass(frozen=True)
class Window:
	"""A month as a half open range: `start` is in, `next_start` (the cutoff) is out."""

	start: date
	next_start: date

	@property
	def first(self) -> datetime:
		"""Midnight at the start of the month."""
		return datetime.combine(self.start, time.min)

	@property
	def cut(self) -> datetime:
		"""Midnight at the start of the next month. A datetime before this is by month end."""
		return datetime.combine(self.next_start, time.min)


def _month_after(day: date) -> date:
	return date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)


def parse_month(value: str | None, today: date) -> Window:
	"""Turn `YYYY-MM` into a window. Blank is the last full month; a bad or future month raises ValueError."""
	text = (value or "").strip()
	this_month = today.replace(day=1)
	if not text:
		start = (this_month - timedelta(days=1)).replace(day=1)
		return Window(start, this_month)
	if not _MONTH.match(text):
		raise BadFilter("Month must look like 2026-10 (year, a dash, month 01 to 12)")
	start = date(int(text[:4]), int(text[5:]), 1)
	if start > this_month:
		raise BadFilter("Month cannot be after the current month")
	return Window(start, _month_after(start))


def _dt(value: Any) -> datetime:
	"""A date or datetime as a datetime. An empty value is the earliest possible time."""
	if value is None:
		return datetime.min
	if isinstance(value, datetime):
		return value
	return datetime.combine(value, time.min)


def _day(value: Any) -> date | None:
	if value is None:
		return None
	return value.date() if isinstance(value, datetime) else value


def _first_certificate_day(cert: dict[str, Any]) -> date:
	"""The earlier of a certificate's creation day and issue date, for the row cutoff."""
	days = [d for d in (_day(cert.get("creation")), _day(cert.get("issue_date"))) if d]
	return min(days, default=date.min)


def as_of(data: dict[str, list[dict[str, Any]]], window: Window) -> dict[str, list[dict[str, Any]]]:
	"""Keep only the records that let a learner have a row by month end (spec 0014 AC-3)."""
	return {
		"enrollments": [e for e in data["enrollments"] if _dt(e.get("creation")) < window.cut],
		"progress": [p for p in data["progress"] if _dt(p.get("creation")) < window.cut],
		"certificates": [c for c in data["certificates"] if _first_certificate_day(c) < window.next_start],
	}


def _replay(attempts: list[dict[str, Any]], allowed: int, pass_mark: int) -> tuple[str, datetime | None]:
	"""Return the final quiz state and when the attempt that first settled it (Passed or Locked) was made."""
	best: int | None = None
	settled_at: datetime | None = None
	for used, attempt in enumerate(attempts, 1):
		score = attempt_score(attempt)
		best = score if best is None else max(best, score)
		if settled_at is None and quiz_state(best, used, allowed, pass_mark) in _SETTLED:
			settled_at = _dt(attempt.get("creation"))
	return quiz_state(best, len(attempts), allowed, pass_mark), settled_at


def _yes(flag: bool) -> str:
	return "Yes" if flag else "No"


def _row(
	window: Window,
	member: str,
	course: str,
	user: dict[str, Any],
	info: dict[str, Any],
	lessons: list[str],
	quizzes: list[dict[str, Any]],
	progress: list[dict[str, Any]],
	certificates: list[dict[str, Any]],
	submissions: dict[tuple, list[dict[str, Any]]],
	enrolled: bool,
) -> dict[str, Any]:
	in_outline = set(lessons)
	quiz_lessons = {q["lesson"] for q in quizzes}
	plain = [lesson for lesson in lessons if lesson not in quiz_lessons]

	# Lessons: the first Complete row before the cutoff.
	complete_at: dict[str, datetime] = {}
	for row in progress:
		lesson = row["lesson"]
		if row["status"] != LESSON_COMPLETE or lesson not in in_outline:
			continue
		created = _dt(row.get("creation"))
		if created >= window.cut:
			continue
		complete_at[lesson] = min(created, complete_at.get(lesson, created))
	# A lesson counts in the month of its earliest Complete row, so a duplicate row never counts twice.
	completed_in_month = {lesson for lesson, at in complete_at.items() if at >= window.first}

	# Quizzes: replay the attempts made before the cutoff.
	states: list[str] = []
	settled_times: list[datetime | None] = []
	attempts = score_sum = first_passed = 0
	for quiz in quizzes:
		tried = sorted(
			(a for a in submissions.get((member, quiz["name"]), []) if _dt(a.get("creation")) < window.cut),
			key=lambda a: _dt(a.get("creation")),
		)
		allowed, pass_mark = quiz["max_attempts"] or 0, quiz["passing_percentage"] or 0
		state, settled_at = _replay(tried, allowed, pass_mark)
		states.append(state)
		settled_times.append(settled_at)
		in_month = [a for a in tried if _dt(a.get("creation")) >= window.first]
		attempts += len(in_month)
		score_sum += sum(attempt_score(a) for a in in_month)
		first_pass = next((a for a in tried if attempt_score(a) >= pass_mark), None)
		if first_pass is not None and _dt(first_pass.get("creation")) >= window.first:
			first_passed += 1

	# Certificates: held means an issue date before the cutoff, published or not.
	issued = [(c, _day(c.get("issue_date"))) for c in certificates]
	dated = [(c, d) for c, d in issued if d is not None and d < window.next_start]
	held = [c for c, _d in dated]
	issue_days = [d for _c, d in dated]
	cert = newest_certificate(held)

	finished = (
		len(lessons) >= 1
		and all(lesson in complete_at for lesson in plain)
		and all(state in _SETTLED for state in states)
	)
	finish_times = [complete_at[lesson] for lesson in plain if lesson in complete_at] + [
		t for t in settled_times if t is not None
	]
	finish_day = max(finish_times, default=None) if finished else None
	candidates = [d for d in [finish_day.date() if finish_day else None, *issue_days] if d is not None]
	is_done = bool(held) or finished
	done_day = min(candidates, default=None) if is_done else None
	locked = sum(state == STATE_LOCKED for state in states)

	outcome = None
	if is_done:
		outcome = OUTCOME_NOT_PASSED if (not held and locked) else OUTCOME_PASSED

	return {
		"learner": member,
		"full_name": user["full_name"],
		"course": info["title"],
		"course_name": course,
		"result": RESULT_DONE if is_done else RESULT_BEHIND,
		"outcome": outcome,
		"done_date": done_day,
		"completed_this_month": _yes(done_day is not None and window.start <= done_day < window.next_start),
		"lessons_completed": len(completed_in_month),
		"quizzes_first_passed": first_passed,
		"attempts": attempts,
		"avg_attempt_score": round_half_up(score_sum, attempts) if attempts else None,
		"attempt_score_sum": score_sum,
		"certificate_issued": _yes(any(window.start <= d < window.next_start for d in issue_days)),
		"lessons_done": len(complete_at),
		"lessons_left": len(lessons) - len(complete_at),
		"locked_quizzes": locked,
		"certificate": cert["name"] if cert else None,
		"enrolled": _yes(enrolled),
		"enabled": _yes(bool(user["enabled"])),
	}


def build_rows(
	data: dict[str, list[dict[str, Any]]], excluded_users: Iterable[str], window: Window
) -> list[dict[str, Any]]:
	"""Build every Monthly Report row for the window, unfiltered and ordered."""
	courses = {c["name"]: c for c in data["courses"] if c.get("nile_key")}
	users = {u["name"]: u for u in data["users"]}
	outline = outline_by_course([r for r in data["outline"] if r["course"] in courses])
	quizzes = counted_quizzes(data["quizzes"], outline)
	keys = row_keys(as_of(data, window), courses, users, excluded_set(excluded_users))

	enrolled = {(e["member"], e["course"]) for e in data["enrollments"]}
	progress = group(data["progress"], "member", "course")
	certificates = group(data["certificates"], "member", "course")
	submissions = group(data["submissions"], "member", "quiz")

	rows = [
		_row(
			window,
			member,
			course,
			users[member],
			courses[course],
			outline.get(course, []),
			quizzes.get(course, []),
			progress.get((member, course), []),
			certificates.get((member, course), []),
			submissions,
			(member, course) in enrolled,
		)
		for member, course in keys
	]
	rows.sort(key=lambda r: (r["course"].lower(), lower_sort(r), r["learner"], r["course_name"]))
	return rows


def _check_result(result: str | None) -> None:
	if result and result not in RESULTS:
		raise BadFilter(f"Result must be one of: {', '.join(RESULTS)}")


def filter_rows(
	rows: list[dict[str, Any]],
	course: str | None = None,
	result: str | None = None,
	learner: str | None = None,
	enrolled_only: bool = False,
) -> list[dict[str, Any]]:
	"""Apply the Monthly Report filters with AND. A result outside Done and Behind raises ValueError."""
	_check_result(result)
	return [
		r
		for r in rows
		if (not course or r["course_name"] == course)
		and (not result or r["result"] == result)
		and matches_learner(r, learner)
		and (not enrolled_only or r["enrolled"] == "Yes")
	]


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
	"""The five totals over the shown rows. The score is the mean of every attempt, not of row means."""
	attempts = sum(r["attempts"] for r in rows)
	return {
		"done": sum(r["result"] == RESULT_DONE for r in rows),
		"behind": sum(r["result"] == RESULT_BEHIND for r in rows),
		"certified": sum(r["certificate_issued"] == "Yes" for r in rows),
		"attempts": attempts,
		"avg_attempt_score": round_half_up(sum(r["attempt_score_sum"] for r in rows), attempts)
		if attempts
		else 0,
	}


def monthly_rows(
	fetch: Fetch,
	excluded_users: Iterable[str],
	today: date,
	month: str | None = None,
	course: str | None = None,
	result: str | None = None,
	learner: str | None = None,
	enrolled_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
	"""Validate the filters, fetch the 8 lists once, and return the filtered rows and their totals."""
	window = parse_month(month, today)
	_check_result(result)
	data = {name: fetch(name) for name in DATASETS}
	rows = filter_rows(build_rows(data, excluded_users, window), course, result, learner, enrolled_only)
	return rows, totals(rows)
