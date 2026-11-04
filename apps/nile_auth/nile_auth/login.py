"""Group to role mapping at login (spec 0006).

`custom` replaces Frappe's OIDC callback. It reads the groups from the userinfo, provisions the user
and the enrollments in one transaction, then hands over to Frappe's own `login_oauth_user`, which
commits. Any failure rolls everything back and shows a retry page.
"""

import json
import logging
from dataclasses import dataclass, field

import frappe
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils import add_years, today
from frappe.utils.oauth import (
	OAUTH_LOGIN_FLOW_CACHE_PREFIX,
	get_email,
	get_first_name,
	get_info_via_oauth,
	get_last_name,
	login_oauth_user,
)

from nile_auth import constants as c
from nile_auth.groups import KIND_NO_CLAIM, KIND_NO_GROUP, Decision, decide

__all__ = ["Outcome", "custom", "provision"]

PROTECTED_USERS = ("Administrator", "Guest")


@dataclass
class Outcome:
	"""What `provision` did, for the log line and the tests."""

	user: str = ""
	created: bool = False
	roles_added: list[str] = field(default_factory=list)
	roles_removed: list[str] = field(default_factory=list)
	batches_created: int = 0
	batch_courses_added: int = 0
	batch_enrollments_created: int = 0
	enrollments_created: int = 0


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
	_read_committed()
	seen = {"email": "none", "groups": ()}  # filled in as the flow learns them, for the log line
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
	frappe.db.sql("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")  # for later transactions
	_log(outcome, seen["email"], seen["groups"])


def _read_committed() -> None:
	"""Run this login's transaction at READ COMMITTED (`custom` puts the session level back).

	Under the default REPEATABLE READ, a login that loses a race for a new batch can never see the
	winner's committed row through LMS's own plain reads, and locking reads take gap locks that
	deadlock. Nothing is pending in a guest GET, so ending the transaction here loses nothing.
	"""
	frappe.db.sql(
		"SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
	)  # applies from the next transaction
	frappe.db.commit()  # Frappe starts the next transaction at once, now at READ COMMITTED


def _login(provider: str, code: str, state: str, seen: dict) -> str:
	"""Run steps 2 to 9 of the flow. Returns the outcome word, or raises Refused."""
	if not state or frappe.cache.get_value(f"{OAUTH_LOGIN_FLOW_CACHE_PREFIX}:{state}") is None:
		raise Refused(c.OUTCOME_BAD_STATE, c.PAGE_BAD_STATE)

	admin_group, prefix, suffix = (
		frappe.conf.get(key) for key in (c.CONF_ADMIN_GROUP, c.CONF_STUDENT_PREFIX, c.CONF_STUDENT_SUFFIX)
	)
	if not all((admin_group, prefix, suffix, frappe.conf.get(c.CONF_SERVICE_USER))):
		raise Refused(c.OUTCOME_FAULT_SETTINGS, c.PAGE_SETUP_FAULT)

	info = get_info_via_oauth(provider, code, decoder_compat)
	email = (get_email(info) or "").lower()
	if not email:
		raise Refused(c.OUTCOME_NO_EMAIL, c.PAGE_NO_EMAIL)
	seen["email"] = email

	decision = decide(info.get("groups"), admin_group, prefix, suffix)
	if decision.kind == KIND_NO_CLAIM:
		raise Refused(c.OUTCOME_FAULT_CLAIM, c.PAGE_SETUP_FAULT)
	seen["groups"] = decision.matched_groups

	existing = frappe.db.exists("User", email)
	if existing:
		_refuse_if_protected(existing, info, provider)
		if not frappe.db.get_value("User", existing, "enabled"):
			login_oauth_user(info, provider=provider, state=state)
			return c.OUTCOME_DISABLED

	if decision.kind == KIND_NO_GROUP:
		if existing:
			_strip_managed_roles(existing)
		raise Refused(c.OUTCOME_NO_GROUP, c.PAGE_REFUSED)

	try:
		frappe.set_user("Administrator")
		provision(info, decision, email)
	finally:
		frappe.set_user("Guest")
	login_oauth_user(info, provider=provider, state=state)
	return c.OUTCOME_OK


def _refuse_if_protected(name: str, info: dict, provider: str) -> None:
	service_user = (frappe.conf.get(c.CONF_SERVICE_USER) or "").lower()
	if (
		name in PROTECTED_USERS
		or name.lower() == service_user
		or frappe.db.exists("Has Role", {"parent": name, "parenttype": "User", "role": "System Manager"})
	):
		raise Refused(c.OUTCOME_PROTECTED, c.PAGE_PROTECTED)

	stored = frappe.db.get_value("User Social Login", {"parent": name, "provider": provider}, "userid")
	if stored:
		prop = frappe.db.get_value("Social Login Key", provider, "user_id_property") or "sub"
		if str(info.get(prop)) != str(stored):
			raise Refused(c.OUTCOME_IDENTITY, c.PAGE_PROTECTED)


def _strip_managed_roles(name: str) -> None:
	"""Take the managed roles from a user who is in no workshop group, and commit just that."""
	try:
		frappe.set_user("Administrator")
		user = frappe.get_doc("User", name)
		keep = [r for r in user.roles if r.role not in c.MANAGED_ROLES]
		if len(keep) != len(user.roles):
			user.set("roles", keep)
			user.set(c.USER_GROUPS_FIELD, "")
			user.flags.ignore_permissions = True
			user.save()
	finally:
		frappe.set_user("Guest")
	frappe.db.commit()


def provision(info: dict, decision: Decision, email: str | None = None) -> Outcome:
	"""Create or update the user and the enrollments for one member. Runs as Administrator, no commit."""
	email = (email or get_email(info)).lower()
	out = Outcome()
	user = _ensure_user(info, email, out)
	_reconcile_roles(user, decision, out)

	published = sorted(frappe.get_all("LMS Course", {"published": 1}, pluck="name"))
	batches = [_ensure_batch(group, published, out) for group in decision.workshop_groups]
	for batch in batches:
		_enroll_in_batch(batch, user.name, out)
	if batches:
		for course in published:
			_enroll_in_course(course, user.name, batches[0], out)
	return out


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


def _reconcile_roles(user, decision: Decision, out: Outcome) -> None:
	"""Set the managed roles to exactly the wanted ones and write nile_groups, in one save."""
	have = {r.role for r in user.roles}
	want = set(decision.desired_roles)
	out.roles_removed = sorted(have & set(c.MANAGED_ROLES) - want)
	out.roles_added = sorted(want - have)
	user.set("roles", [r for r in user.roles if r.role not in out.roles_removed])
	for role in out.roles_added:
		user.append("roles", {"role": role})
	user.set(c.USER_GROUPS_FIELD, "\n".join(decision.matched_groups))
	user.flags.ignore_permissions = True
	user.save()


def _ensure_batch(group: str, courses: list[str], out: Outcome) -> str:
	"""Find the batch by nile_group, create it if missing, top up its courses.

	A locking read of a row that does not exist yet takes a gap lock, and two first logins then
	deadlock on their inserts. So read plainly first, and use the locking read only on a row that
	exists (a record lock) or after a duplicate key error (the winner's row is then committed).
	"""
	name = frappe.db.get_value("LMS Batch", {c.BATCH_GROUP_FIELD: group}, "name")
	if name:
		frappe.db.get_value("LMS Batch", name, "name", for_update=True)
	else:
		frappe.db.savepoint("nile_batch")
		try:
			name = _new_batch(group, courses).name
			out.batches_created += 1
		except frappe.DuplicateEntryError, frappe.UniqueValidationError:
			frappe.db.rollback(save_point="nile_batch")
			name = _locked_batch(group)
			if not name:
				raise
		return name

	batch = frappe.get_doc("LMS Batch", name)
	have = {row.course for row in batch.courses}
	missing = [course for course in courses if course not in have]
	for course in missing:
		batch.append("courses", {"course": course})
	if missing:
		batch.flags.ignore_permissions = True
		batch.save()
		out.batch_courses_added += len(missing)
	return name


def _locked_batch(group: str) -> str | None:
	return frappe.db.get_value("LMS Batch", {c.BATCH_GROUP_FIELD: group}, "name", for_update=True)


def _new_batch(group: str, courses: list[str]):
	batch = frappe.get_doc(
		{
			"doctype": "LMS Batch",
			"title": group,
			c.BATCH_GROUP_FIELD: group,
			"start_date": today(),
			"end_date": add_years(today(), c.BATCH_END_YEARS),
			"start_time": c.BATCH_START_TIME,
			"end_time": c.BATCH_END_TIME,
			"timezone": frappe.utils.get_system_timezone(),
			"description": c.BATCH_DESCRIPTION.format(group=group),
			"batch_details": c.BATCH_DESCRIPTION.format(group=group),
			"published": c.BATCH_PUBLISHED,
			"allow_self_enrollment": c.BATCH_ALLOW_SELF_ENROLLMENT,
			"instructors": [{"instructor": frappe.conf.get(c.CONF_SERVICE_USER)}],
			"courses": [{"course": course} for course in courses],
		}
	)
	return batch.insert(ignore_permissions=True)


def _enroll_in_batch(batch: str, member: str, out: Outcome) -> None:
	if frappe.db.exists("LMS Batch Enrollment", {"batch": batch, "member": member}):
		return
	frappe.get_doc(
		{"doctype": "LMS Batch Enrollment", "batch": batch, "member": member, "confirmation_email_sent": 1}
	).insert(ignore_permissions=True)
	out.batch_enrollments_created += 1


def _enroll_in_course(course: str, member: str, batch: str, out: Outcome) -> None:
	frappe.db.get_value("LMS Course", course, "name", for_update=True)
	if frappe.db.exists("LMS Enrollment", {"course": course, "member": member}):
		return
	enrollment = frappe.get_doc(
		{"doctype": "LMS Enrollment", "course": course, "member": member, "enrollment_from_batch": batch}
	)
	enrollment.flags.via_batch_enrollment = True
	enrollment.insert(ignore_permissions=True)
	out.enrollments_created += 1


def _respond(page: tuple[str, str, int]) -> None:
	title, message, status = page
	frappe.respond_as_web_page(title, message, http_status_code=status, indicator_color="red")


def _log(outcome: str, email: str, groups: tuple[str, ...]) -> None:
	"""One line per login on the nile_auth logger. Never holds a token, code or the userinfo."""
	line = f"login email={json.dumps(email)} outcome={outcome} groups={json.dumps(list(groups))}"
	logger = frappe.logger(c.LOGGER_NAME)
	logger.setLevel(logging.INFO)  # frappe.logger starts at WARNING, and the ok line is info
	if outcome == c.OUTCOME_OK:
		logger.info(line)
	elif outcome in (c.OUTCOME_ERROR, c.OUTCOME_FAULT_CLAIM, c.OUTCOME_FAULT_SETTINGS):
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
