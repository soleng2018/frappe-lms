"""Fetch the plain lists the progress rules need, and run the access check (spec 0013)."""

import frappe
from frappe import _

from nile_auth.constants import CONF_MCP_USER, CONF_SERVICE_USER
from nile_auth.progress import DATASETS, assemble

__all__ = [
	"REPORT_ROLES",
	"excluded_users",
	"fetch",
	"load_rows",
	"require_report_access",
	"throw_bad_filter",
]

REPORT_ROLES = ("Moderator", "System Manager")


def require_report_access() -> None:
	"""Raise PermissionError unless the session user is a Moderator or System Manager."""
	frappe.only_for(REPORT_ROLES)


def excluded_users() -> list[str]:
	"""The service and MCP users from site config. A missing key excludes nothing."""
	return [u for u in (frappe.conf.get(CONF_SERVICE_USER), frappe.conf.get(CONF_MCP_USER)) if u]


def fetch(name: str) -> list[dict]:
	"""Run the one query behind a dataset name. Reads as the server, no per record permission check."""
	get = frappe.get_all
	if name == "courses":
		return get("LMS Course", filters={"nile_key": ["is", "set"]}, fields=["name", "title", "nile_key"])
	if name == "outline":
		return frappe.db.sql(
			"""
			select cr.parent as course, lr.lesson as lesson
			from `tabChapter Reference` cr
			join `tabLesson Reference` lr on lr.parent = cr.chapter and lr.parenttype = 'Course Chapter'
			where cr.parenttype = 'LMS Course'
			order by cr.parent, cr.idx, lr.idx
			""",
			as_dict=True,
		)
	if name == "enrollments":
		return get("LMS Enrollment", fields=["member", "course"], limit_page_length=0)
	if name == "progress":
		return get(
			"LMS Course Progress",
			fields=["member", "course", "lesson", "status", "modified"],
			limit_page_length=0,
		)
	if name == "quizzes":
		return get(
			"LMS Quiz",
			fields=["name", "title", "lesson", "max_attempts", "passing_percentage"],
			limit_page_length=0,
		)
	if name == "submissions":
		return get(
			"LMS Quiz Submission",
			fields=["member", "quiz", "percentage", "creation"],
			limit_page_length=0,
		)
	if name == "certificates":
		return get(
			"LMS Certificate",
			fields=["name", "member", "course", "issue_date", "published", "creation"],
			limit_page_length=0,
		)
	if name == "users":
		return get("User", fields=["name", "full_name", "enabled"], limit_page_length=0)
	raise ValueError(f"Unknown dataset {name}. Expected one of {', '.join(DATASETS)}")


def load_rows() -> tuple[list[dict], list[dict]]:
	"""Check access, then return all (progress rows, quiz rows) unfiltered."""
	require_report_access()
	return assemble(fetch, excluded_users())


def throw_bad_filter(error: ValueError) -> None:
	"""Turn a filter validation error into a Frappe validation message."""
	frappe.throw(_(str(error)), frappe.ValidationError)
