"""Monthly Report: one row per learner and managed course, judged at the end of a month (spec 0014)."""

import frappe
from frappe import _
from frappe.utils import getdate

from nile_auth.monthly import monthly_rows
from nile_auth.progress_data import excluded_users, fetch, require_report_access, throw_bad_filter

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
	{"fieldname": "result", "label": "Result", "fieldtype": "Data", "width": 90},
	{"fieldname": "outcome", "label": "Outcome", "fieldtype": "Data", "width": 100},
	{"fieldname": "done_date", "label": "Done date", "fieldtype": "Date", "width": 100},
	{"fieldname": "completed_this_month", "label": "Completed this month", "fieldtype": "Data", "width": 90},
	{
		"fieldname": "lessons_completed",
		"label": "Lessons completed in month",
		"fieldtype": "Int",
		"width": 100,
	},
	{
		"fieldname": "quizzes_first_passed",
		"label": "Quizzes first passed in month",
		"fieldtype": "Int",
		"width": 110,
	},
	{"fieldname": "attempts", "label": "Attempts in month", "fieldtype": "Int", "width": 100},
	{
		"fieldname": "avg_attempt_score",
		"label": "Average attempt score in month",
		"fieldtype": "Percent",
		"width": 130,
	},
	{
		"fieldname": "certificate_issued",
		"label": "Certificate issued in month",
		"fieldtype": "Data",
		"width": 100,
	},
	{"fieldname": "lessons_done", "label": "Lessons done", "fieldtype": "Int", "width": 100},
	{"fieldname": "lessons_left", "label": "Lessons left", "fieldtype": "Int", "width": 100},
	{"fieldname": "locked_quizzes", "label": "Locked quizzes", "fieldtype": "Int", "width": 100},
	{
		"fieldname": "certificate",
		"label": "Certificate",
		"fieldtype": "Link",
		"options": "LMS Certificate",
		"width": 160,
	},
	{"fieldname": "enrolled", "label": "Enrolled now", "fieldtype": "Data", "width": 90},
	{"fieldname": "enabled", "label": "Enabled now", "fieldtype": "Data", "width": 90},
	{"fieldname": "attempt_score_sum", "label": "Attempt score sum", "fieldtype": "Int", "hidden": 1},
]


def summary(totals: dict[str, int]) -> list[dict]:
	"""The five tiles shown above the table."""
	return [
		{"value": totals["done"], "label": _("Done"), "datatype": "Int", "indicator": "Green"},
		{"value": totals["behind"], "label": _("Behind"), "datatype": "Int", "indicator": "Orange"},
		{"value": totals["certified"], "label": _("Certified this month"), "datatype": "Int"},
		{"value": totals["attempts"], "label": _("Attempts this month"), "datatype": "Int"},
		{"value": totals["avg_attempt_score"], "label": _("Average attempt score"), "datatype": "Percent"},
	]


def execute(filters=None):
	"""Return the report columns, rows and totals for the given filters."""
	filters = filters or {}
	require_report_access()
	try:
		rows, totals = monthly_rows(
			fetch,
			excluded_users(),
			getdate(),
			month=filters.get("month"),
			course=filters.get("course"),
			result=filters.get("result"),
			learner=filters.get("learner"),
			enrolled_only=bool(int(filters.get("enrolled_only") or 0)),
		)
	except ValueError as error:
		throw_bad_filter(error)
	return COLUMNS, rows, None, None, summary(totals)
