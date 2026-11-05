"""Quiz Scores: one row per learner and quiz (spec 0013)."""

from nile_auth.progress import filter_quiz_rows
from nile_auth.progress_data import load_rows, throw_bad_filter

COLUMNS = [
	{"fieldname": "learner", "label": "Learner", "fieldtype": "Link", "options": "User", "width": 200},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "course", "label": "Course", "fieldtype": "Data", "width": 200},
	{
		"fieldname": "course_name",
		"label": "Course ID",
		"fieldtype": "Link",
		"options": "LMS Course",
		"hidden": 1,
	},
	{"fieldname": "quiz", "label": "Quiz", "fieldtype": "Link", "options": "LMS Quiz", "width": 220},
	{"fieldname": "best_score", "label": "Best score", "fieldtype": "Percent", "width": 100},
	{"fieldname": "attempts_used", "label": "Attempts used", "fieldtype": "Int", "width": 110},
	{"fieldname": "attempts_allowed", "label": "Attempts allowed", "fieldtype": "Data", "width": 120},
	{"fieldname": "pass_mark", "label": "Pass mark", "fieldtype": "Percent", "width": 90},
	{"fieldname": "state", "label": "State", "fieldtype": "Data", "width": 110},
	{"fieldname": "last_attempt", "label": "Last attempt", "fieldtype": "Datetime", "width": 160},
]


def execute(filters=None):
	"""Return the report columns and rows for the given filters."""
	filters = filters or {}
	_progress_rows, quiz_rows = load_rows()
	try:
		rows = filter_quiz_rows(
			quiz_rows,
			course=filters.get("course"),
			state=filters.get("state"),
			learner=filters.get("learner"),
		)
	except ValueError as error:
		throw_bad_filter(error)
	return COLUMNS, rows
