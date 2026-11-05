"""Learner Progress: one row per learner and managed course (spec 0013)."""

from nile_auth.progress import STATUSES, filter_progress_rows
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
	{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 140},
	{"fieldname": "enrolled", "label": "Enrolled", "fieldtype": "Data", "width": 80},
	{"fieldname": "enabled", "label": "Enabled", "fieldtype": "Data", "width": 80},
	{"fieldname": "lessons_done", "label": "Lessons done", "fieldtype": "Int", "width": 100},
	{"fieldname": "lessons_total", "label": "Lessons total", "fieldtype": "Int", "width": 100},
	{"fieldname": "progress", "label": "Progress %", "fieldtype": "Percent", "width": 100},
	{"fieldname": "quizzes_passed", "label": "Quizzes passed", "fieldtype": "Int", "width": 110},
	{"fieldname": "quizzes_total", "label": "Quizzes total", "fieldtype": "Int", "width": 100},
	{"fieldname": "avg_best", "label": "Average best score", "fieldtype": "Percent", "width": 130},
	{"fieldname": "last_activity", "label": "Last activity", "fieldtype": "Datetime", "width": 160},
	{
		"fieldname": "certificate",
		"label": "Certificate",
		"fieldtype": "Link",
		"options": "LMS Certificate",
		"width": 160,
	},
	{"fieldname": "issue_date", "label": "Issue date", "fieldtype": "Date", "width": 100},
	{"fieldname": "published", "label": "Published", "fieldtype": "Data", "width": 90},
]


def execute(filters=None):
	"""Return the report columns and rows for the given filters."""
	filters = filters or {}
	progress_rows, _quiz_rows = load_rows()
	try:
		rows = filter_progress_rows(
			progress_rows,
			course=filters.get("course"),
			status=filters.get("status"),
			learner=filters.get("learner"),
			enrolled_only=bool(int(filters.get("enrolled_only") or 0)),
		)
	except ValueError as error:
		throw_bad_filter(error)
	return COLUMNS, rows
