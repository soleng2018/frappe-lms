"""Course access from groups at login (spec 0009, building on spec 0006).

`custom` replaces Frappe's OIDC callback. It reads the groups from the userinfo, finds the one course
group, provisions the user and the one enrollment in one transaction, then hands over to Frappe's own
`login_oauth_user`, which commits. Any failure rolls everything back and shows a retry page.
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field

import frappe
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils import get_url
from frappe.utils.oauth import (
	OAUTH_LOGIN_FLOW_CACHE_PREFIX,
	get_email,
	get_first_name,
	get_info_via_oauth,
	get_last_name,
	login_oauth_user,
)
from lms.lms.utils import get_course_progress

from nile_auth import constants as c
from nile_auth.groups import (
	KIND_ADMIN_ONLY,
	KIND_BAD_COURSE,
	KIND_LIVE,
	KIND_NO_GROUP,
	KIND_RESULTS,
	KIND_TWO_COURSES,
	Decision,
	claim_fault,
	decide,
	landing_path,
	mode,
)

__all__ = ["Outcome", "custom", "provision"]

PROTECTED_USERS = ("Administrator", "Guest")
LOCK_WAIT_SECONDS = 30
DEADLOCK_TRIES = 4


@dataclass
class Outcome:
	"""What `provision` did, for the tests."""

	user: str = ""
	created: bool = False
	roles_added: list[str] = field(default_factory=list)
	roles_removed: list[str] = field(default_factory=list)
	enrollments_created: int = 0
	enrollments_removed: list[str] = field(default_factory=list)


class Refused(Exception):
	"""Raised inside the flow to end it with a page and a log outcome."""

	def __init__(self, outcome: str, page: tuple[str, str, int]):
		super().__init__(outcome)
		self.outcome = outcome
		self.page = page


@frappe.whitelist(allow_guest=True)
def custom(code: str, state: str):
	"""Callback for /api/method/frappe.integrations.oauth2_logins.custom/<provider>, with groups."""
	# Switching user later clears the request data, so capture everything now.
	path = frappe.request.path[1:].split("/")
	if not (len(path) == 4 and path[3] and frappe.db.exists("Social Login Key", path[3])):
		return
	provider = path[3]
	seen = {"email": "none", "mode": "none", "group": "", "lock": ""}  # filled in as the flow learns
	try:
		outcome = _login(provider, code, state, seen)
	except Refused as refusal:
		_respond(refusal.page)
		outcome = refusal.outcome
	except Exception:
		frappe.db.rollback()
		frappe.set_user("Guest")
		_log_fault(code, state)
		_respond(c.PAGE_RETRY)
		outcome = c.OUTCOME_ERROR
	finally:
		_drop_lock(seen["lock"])
	_log(outcome, seen)


def _login(provider: str, code: str, state: str, seen: dict) -> str:
	"""Run steps 2 to 10 of the flow. Returns the outcome word, or raises Refused."""
	kept = frappe.cache.get_value(f"{OAUTH_LOGIN_FLOW_CACHE_PREFIX}:{state}") if state else None
	if kept is None:
		raise Refused(c.OUTCOME_BAD_STATE, c.PAGE_BAD_STATE)

	admin_group = frappe.conf.get(c.CONF_ADMIN_GROUP)
	if not (admin_group and frappe.conf.get(c.CONF_SERVICE_USER)):
		raise Refused(c.OUTCOME_FAULT_SETTINGS, c.PAGE_SETUP_FAULT)

	info = get_info_via_oauth(provider, code, decoder_compat)
	email = (get_email(info) or "").lower()
	if not email:
		raise Refused(c.OUTCOME_NO_EMAIL, c.PAGE_NO_EMAIL)
	seen["email"] = email

	groups = info.get("groups")
	if claim_fault(groups, admin_group):
		raise Refused(c.OUTCOME_FAULT_CLAIM, c.PAGE_SETUP_FAULT)

	# The empty commit ends the read view of this request. The named lock that follows touches no
	# table, so it opens no new read view: it serializes two logins of one person, and every plain
	# read after it sees what the other login committed. A row lock on a User that does not exist yet
	# would take a gap lock, and two different new learners would deadlock on the insert.
	frappe.db.commit()
	seen["lock"] = _take_lock(email)

	managed = frappe.get_all("LMS Course", filters={"nile_key": ["is", "set"]}, fields=["name", "title"])
	courses = [(row.name, row.title) for row in managed]
	# Look the user up by name and by the email field: Administrator and Guest are named by word,
	# not by email, so an Authentik account that carries their email must still meet the protected check.
	existing = frappe.db.exists("User", email) or frappe.db.get_value("User", {"email": email}, "name")
	known = bool(existing) and _is_known_learner(existing)
	decision = decide(groups, admin_group, courses, known)
	seen["mode"] = mode(decision)
	seen["group"] = decision.course_group
	if decision.kind == KIND_TWO_COURSES:
		raise Refused(c.OUTCOME_TWO_COURSES, c.PAGE_TWO_COURSES)
	if decision.kind == KIND_BAD_COURSE:
		raise Refused(c.OUTCOME_FAULT_COURSE, c.PAGE_SETUP_FAULT)

	if existing:
		_refuse_if_protected(existing, info, provider)
		if not frappe.db.get_value("User", existing, "enabled"):
			login_oauth_user(info, provider=provider, state=state)
			return c.OUTCOME_DISABLED

	if decision.kind == KIND_NO_GROUP:
		if existing:
			_strip_admin_roles(existing)
		raise Refused(c.OUTCOME_NO_GROUP, c.PAGE_REFUSED)

	out = _provision_retrying(info, decision, email, [name for name, _title in courses])
	login_oauth_user(info, provider=provider, state=state)  # consumes the state, sets a redirect
	if frappe.local.response.get("type") != "redirect" or frappe.session.user != out.user:
		return c.OUTCOME_BAD_STATE  # the state was gone: Frappe showed its 417 page, nobody signed in
	try:
		_land(decision, out.user, kept)
	except Exception:
		_log_fault(code, state)  # the person is signed in; keep Frappe's own redirect
	return c.OUTCOME_OK


def _provision_retrying(info: dict, decision: Decision, email: str, managed: list[str]) -> Outcome:
	"""Run `provision` as Administrator; if the database picks it as a deadlock victim, start over.

	Frappe's own User insert (the __Auth password row, the username index) can deadlock with the insert
	of another new learner. The loser is rolled back whole, so running it again is safe.
	"""
	for attempt in range(1, DEADLOCK_TRIES + 1):
		try:
			frappe.set_user("Administrator")
			return provision(info, decision, email, managed)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == DEADLOCK_TRIES:
				raise
			time.sleep(random.uniform(0.05, 0.4) * attempt)
		finally:
			frappe.set_user("Guest")
	raise AssertionError("unreachable")


def _take_lock(email: str) -> str:
	"""Take the named database lock of one person's login, or raise after the wait."""
	name = "nile_login:" + hashlib.sha1(email.encode()).hexdigest()
	if frappe.db.sql("select get_lock(%s, %s)", (name, LOCK_WAIT_SECONDS))[0][0] != 1:
		raise TimeoutError("the login lock of this person was not free in time")
	return name


def _drop_lock(name: str) -> None:
	"""Release the named lock; a failure here must not hide the login's own result."""
	if name:
		try:
			frappe.db.sql("select release_lock(%s)", (name,))
		except Exception:
			pass


def _is_known_learner(email: str) -> bool:
	"""An existing, enabled user who holds the LMS Student role."""
	return bool(
		frappe.db.get_value("User", email, "enabled")
		and frappe.db.exists("Has Role", {"parent": email, "parenttype": "User", "role": c.STUDENT_ROLES[0]})
	)


def _land(decision: Decision, email: str, kept: str) -> None:
	"""Change the redirect that Frappe's login left, to the place AC-11 names."""
	response = frappe.local.response
	if response.get("type") != "redirect" or frappe.session.user != email:
		return
	username = frappe.db.get_value("User", email, "username")
	response["location"] = get_url(landing_path(decision, username, kept))


def _refuse_if_protected(name: str, info: dict, provider: str) -> None:
	# The MCP user is optional here: a site without the setting still accepts logins.
	service_user = (frappe.conf.get(c.CONF_SERVICE_USER) or "").lower()
	mcp_user = (frappe.conf.get(c.CONF_MCP_USER) or "").lower()
	if (
		name in PROTECTED_USERS
		or name.lower() == service_user
		or (mcp_user and name.lower() == mcp_user)
		or frappe.db.exists("Has Role", {"parent": name, "parenttype": "User", "role": "System Manager"})
	):
		raise Refused(c.OUTCOME_PROTECTED, c.PAGE_PROTECTED)

	stored = frappe.db.get_value("User Social Login", {"parent": name, "provider": provider}, "userid")
	if stored:
		prop = frappe.db.get_value("Social Login Key", provider, "user_id_property") or "sub"
		if str(info.get(prop)) != str(stored):
			raise Refused(c.OUTCOME_IDENTITY, c.PAGE_PROTECTED)


def _strip_admin_roles(name: str) -> None:
	"""Take the admin roles from a user who is in no course group and no admin group, and commit."""
	try:
		frappe.set_user("Administrator")
		user = frappe.get_doc("User", name)
		keep = [r for r in user.roles if r.role not in c.ADMIN_ROLES]
		if len(keep) != len(user.roles):
			user.set("roles", keep)
			user.set(c.USER_GROUPS_FIELD, "")
			user.flags.ignore_permissions = True
			user.save()
	finally:
		frappe.set_user("Guest")
	frappe.db.commit()


def provision(
	info: dict, decision: Decision, email: str | None = None, managed: list[str] | None = None
) -> Outcome:
	"""Create or update the user and the one enrollment. Runs as Administrator, no commit."""
	email = (email or get_email(info)).lower()
	out = Outcome()
	user = _ensure_user(info, email, out)
	# LMS adds LMS Student when it inserts a user; an admin with no course group must not keep it.
	_reconcile_roles(user, decision, out, drop_student=out.created and decision.kind == KIND_ADMIN_ONLY)

	have = frappe.get_all(
		"LMS Enrollment",
		filters={"member": user.name, "course": ["in", managed or _managed_courses()]},
		fields=["name", "course", "progress"],
	)
	if decision.kind == KIND_LIVE:
		if not any(row.course == decision.course for row in have):
			_enroll(decision.course, user.name, out)
	if decision.kind in (KIND_LIVE, KIND_RESULTS, KIND_ADMIN_ONLY):
		for row in have:
			if row.course != decision.course:
				_warn_if_stranded(user.name, row)
				frappe.delete_doc("LMS Enrollment", row.name, ignore_permissions=True)
				out.enrollments_removed.append(row.course)
	return out


def _warn_if_stranded(member: str, row) -> None:
	"""Spec 0010 AC-9: name a learner who loses an enrollment at 100% progress with no certificate."""
	if (row.progress or 0) < 100:
		return
	if frappe.db.exists("LMS Certificate", {"member": member, "course": row.course}):
		return
	frappe.logger(c.LOGGER_NAME).warning(
		f"stranded learner email={json.dumps(member)} course={json.dumps(row.course)} "
		"progress=100 certificate=none"
	)


def _managed_courses() -> list[str]:
	return frappe.get_all("LMS Course", filters={"nile_key": ["is", "set"]}, pluck="name") or [""]


def _ensure_user(info: dict, email: str, out: Outcome):
	out.user = email
	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	user = frappe.new_doc("User")
	user.update(
		{
			"email": email,
			"first_name": get_first_name(info) or email.split("@")[0],
			"last_name": get_last_name(info),
			"enabled": 1,
			"new_password": frappe.generate_hash(),
			"user_type": c.STUDENT_USER_TYPE,
			"send_welcome_email": 0,
		}
	)
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)  # LMS adds LMS Student here, so the reconcile comes after
	out.created = True
	return user


def _reconcile_roles(user, decision: Decision, out: Outcome, drop_student: bool = False) -> None:
	"""Set the admin roles, add LMS Student for a live login, and write nile_groups, in one save."""
	have = {r.role for r in user.roles}
	want = set(decision.desired_roles)
	gone = (have & set(c.ADMIN_ROLES)) - want
	if drop_student:
		gone |= have & set(c.STUDENT_ROLES)
	out.roles_removed = sorted(gone)
	out.roles_added = sorted(want - have)
	user.set("roles", [r for r in user.roles if r.role not in gone])
	for role in out.roles_added:
		user.append("roles", {"role": role})
	user.set(c.USER_GROUPS_FIELD, "\n".join(decision.matched_groups))
	user.flags.ignore_permissions = True
	user.save()


def _enroll(course: str, member: str, out: Outcome) -> None:
	"""Enroll directly, with no batch. The progress comes from the learner's own lesson rows."""
	frappe.get_doc(
		{
			"doctype": "LMS Enrollment",
			"course": course,
			"member": member,
			"progress": get_course_progress(course, member),
		}
	).insert(ignore_permissions=True)
	out.enrollments_created += 1


def _respond(page: tuple[str, str, int]) -> None:
	title, message, status = page
	frappe.respond_as_web_page(title, message, http_status_code=status, indicator_color="red")


def _log(outcome: str, seen: dict) -> None:
	"""One line per login on the nile_auth logger. Never holds a token, code or the userinfo."""
	line = (
		f"login email={json.dumps(seen['email'])} outcome={outcome} mode={seen['mode']} "
		f"course_group={json.dumps(seen['group'])}"
	)
	logger = frappe.logger(c.LOGGER_NAME)
	if logger.level != logging.INFO:
		logger.setLevel(logging.INFO)  # frappe.logger starts at WARNING, and the ok line is info
	if outcome == c.OUTCOME_OK:
		logger.info(line)
	elif outcome in (
		c.OUTCOME_ERROR,
		c.OUTCOME_FAULT_CLAIM,
		c.OUTCOME_FAULT_SETTINGS,
		c.OUTCOME_FAULT_COURSE,
	):
		logger.error(line)
	else:
		logger.warning(line)


def _log_fault(code: str, state: str) -> None:
	"""Write the traceback to the Error Log, with the code and state scrubbed out of it."""
	text = frappe.get_traceback(with_context=False)
	for secret in (code, state):
		if secret:
			text = text.replace(secret, "***")
	frappe.log_error(title="nile_auth login failed", message=text)
	frappe.db.commit()
