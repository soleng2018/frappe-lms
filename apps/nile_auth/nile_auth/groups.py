"""Classify the Authentik groups of one login into a decision (spec 0009). Pure: no Frappe, no I/O."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from nile_auth.constants import ADMIN_ROLES, STUDENT_ROLES

__all__ = ["Decision", "claim_fault", "decide", "landing_path", "mode", "safe_return_path"]

LANDING_PATH = "/lms"  # where everyone without a better place lands after a sign in
# Login pages put these in redirect_to nearly always, so they count as "no deep link" (AC-11).
DEFAULT_TARGETS = ("/", "/me", "/app", "/lms", "/lms/courses")

KIND_LIVE = "live"
KIND_RESULTS = "results"
KIND_ADMIN_ONLY = "admin_only"
KIND_NO_GROUP = "no_group"
KIND_TWO_COURSES = "two_courses"
KIND_NO_CLAIM = "no_claim"
KIND_BAD_COURSE = "bad_course"

FAULT_CLAIM = "claim"
FAULT_SETTINGS = "settings"


@dataclass(frozen=True)
class Decision:
	"""What one login's groups mean."""

	kind: str  # live, results, admin_only, no_group, two_courses, no_claim or bad_course
	reason: str = ""  # for no_claim: "claim" (bad groups value) or "settings" (empty admin group)
	course: str = ""  # the LMS Course name, for live
	course_group: str = ""
	matched_groups: tuple[str, ...] = ()  # course group, then the admin group
	is_admin: bool = False
	desired_roles: tuple[str, ...] = ()


def claim_fault(groups: Any, admin_group: Any) -> str | None:
	"""Return "settings", "claim", or None when the admin group setting and the groups value are usable."""
	if not isinstance(admin_group, str) or not admin_group:
		return FAULT_SETTINGS
	if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
		return FAULT_CLAIM
	return None


def decide(
	groups: Any,
	admin_group: Any,
	courses: list[tuple[str, str]],
	known_learner: bool,
) -> Decision:
	"""Classify a userinfo groups value against the managed courses `(name, title)`. Never raises."""
	fault = claim_fault(groups, admin_group)
	if fault:
		return Decision(KIND_NO_CLAIM, reason=fault)

	titles = {title for _, title in courses}
	course_groups = sorted({g for g in groups if g != admin_group and g in titles})
	is_admin = admin_group in groups
	admin_roles = ADMIN_ROLES if is_admin else ()
	admin_match = (admin_group,) if is_admin else ()

	if len(course_groups) > 1:
		return Decision(KIND_TWO_COURSES, is_admin=is_admin)
	if course_groups:
		group = course_groups[0]
		names = [name for name, title in courses if title == group]
		if len(names) > 1:
			return Decision(KIND_BAD_COURSE, course_group=group, is_admin=is_admin)
		return Decision(
			KIND_LIVE,
			course=names[0],
			course_group=group,
			matched_groups=(group, *admin_match),
			is_admin=is_admin,
			desired_roles=(*admin_roles, *STUDENT_ROLES),
		)
	if known_learner:
		kind = KIND_RESULTS
	elif is_admin:
		kind = KIND_ADMIN_ONLY
	else:
		return Decision(KIND_NO_GROUP)
	return Decision(kind, matched_groups=admin_match, is_admin=is_admin, desired_roles=admin_roles)


def mode(decision: Decision) -> str:
	"""The mode word for the log line: live, results, admin or none (AC-15)."""
	return {KIND_LIVE: "live", KIND_RESULTS: "results", KIND_ADMIN_ONLY: "admin"}.get(decision.kind, "none")


def safe_return_path(value: Any) -> str | None:
	"""Return `value` if it is a path on this site, else None (spec 0008 AC-10)."""
	if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
		return None
	if any(ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in value):
		return None
	if value[1:4].lower() in ("%2f", "%5c"):
		return None
	return value


def landing_path(decision: Decision, username: str | None, redirect_to: Any = None) -> str:
	"""Where a person lands: a real deep link, else their course or profile, else `/lms` (AC-11)."""
	link = safe_return_path(redirect_to)
	if link and (link.rstrip("/") or "/") not in DEFAULT_TARGETS:
		return link
	if decision.is_admin:
		return LANDING_PATH
	if decision.kind == KIND_LIVE and decision.course:
		return f"/lms/courses/{quote(decision.course, safe='')}"
	if decision.kind == KIND_RESULTS and username:
		return f"/lms/user/{quote(username, safe='')}"
	return LANDING_PATH
