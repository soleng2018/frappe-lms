"""Site setup run by create-site. Reads its inputs from the container environment, never from arguments."""

import os
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from nile_auth.branding import ICON_URL, IMAGE_FILES, PRINT_FORMAT_NAME, SITE_IDENTITY, changed_values
from nile_auth.mcp_user import MCP_ROLES, mcp_user_problems

# Roles the content sync needs (names confirmed against LMS v2.68.0 in spec 0004).
LMS_ROLES = ("LMS Student", "Course Creator", "Moderator", "Batch Evaluator")


def ensure_timezone():
	"""Set the System Settings timezone from LMS_TIMEZONE (rerun safe). Without it Frappe uses Asia/Kolkata."""
	name = os.environ["LMS_TIMEZONE"]
	try:
		ZoneInfo(name)
	except ZoneInfoNotFoundError, ValueError:
		# See ensure_service_user: exit directly, because raising hides the message.
		sys.exit(f"ERROR: LMS_TIMEZONE '{name}' is not a known timezone. Nothing was changed.")
	if frappe.db.get_single_value("System Settings", "time_zone") == name:
		print(f"Timezone already {name}")
		return
	frappe.db.set_single_value("System Settings", "time_zone", name)
	frappe.db.commit()
	print(f"Timezone set to {name}")


def ensure_service_user():
	user_id = os.environ["LMS_SERVICE_USER"]
	api_key = os.environ["LMS_API_KEY"]
	api_secret = os.environ["LMS_API_SECRET"]

	if frappe.db.exists("User", user_id):
		user = frappe.get_doc("User", user_id)
		if user.api_key != api_key or user.get_password("api_secret") != api_secret:
			# bench execute re-evaluates the path as code after any Exception and hides the real
			# message behind a NameError, so exit directly instead of raising.
			sys.exit(
				f"ERROR: Service user {user_id} already has a different API key or secret than the "
				".env file. Nothing was changed. Restore the original .env values."
			)
		print(f"Service user {user_id} already set up")
		return

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": user_id,
			"first_name": "Nile Tools",
			"user_type": "System User",
			"send_welcome_email": 0,
			"enabled": 1,
		}
	)
	user.append("roles", {"role": "System Manager"})
	for role in LMS_ROLES:
		if frappe.db.exists("Role", role):
			user.append("roles", {"role": role})
	user.api_key = api_key
	user.api_secret = api_secret
	user.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"Created service user {user_id}")


def _mcp_stop(user_id: str, problems: list[str]):
	"""Exit with every problem found on the MCP user (see ensure_service_user for why sys.exit)."""
	sys.exit(f"ERROR: MCP user {user_id}: " + "; ".join(problems) + ". Nothing was changed further.")


def _mcp_problems(user_type: str, roles: set[str]) -> list[str]:
	missing = [r for r in MCP_ROLES if not frappe.db.exists("Role", r)]
	return mcp_user_problems(user_type, roles, missing)


def ensure_mcp_user():
	"""Create the MCP user, or make its key and secret match .env (rotation). Rerun safe."""
	user_id = os.environ["LMS_MCP_USER"]
	api_key = os.environ["LMS_MCP_API_KEY"]
	api_secret = os.environ["LMS_MCP_API_SECRET"]

	if user_id.lower() == os.environ.get("LMS_SERVICE_USER", "").lower():
		sys.exit("ERROR: LMS_MCP_USER must differ from LMS_SERVICE_USER. Nothing was changed.")

	if frappe.db.exists("User", user_id):
		user = frappe.get_doc("User", user_id)
		problems = _mcp_problems(user.user_type, {r.role for r in user.roles})
		if problems:
			_mcp_stop(user_id, problems)
		if user.api_key == api_key and user.get_password("api_secret", raise_exception=False) == api_secret:
			print(f"MCP user {user_id} already set up")
			return
		user.api_key = api_key
		user.api_secret = api_secret
		user.flags.ignore_permissions = True
		user.save()
		frappe.db.commit()
		print(f"MCP user {user_id} key and secret updated from .env")
		return

	problems = _mcp_problems("System User", {"Desk User"})
	if problems:
		_mcp_stop(user_id, problems)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": user_id,
			"first_name": "Nile MCP",
			"user_type": "System User",
			"send_welcome_email": 0,
			"enabled": 1,
		}
	)
	for role in MCP_ROLES:
		user.append("roles", {"role": role})
	user.api_key = api_key
	user.api_secret = api_secret
	user.insert(ignore_permissions=True)
	user.reload()
	problems = _mcp_problems(user.user_type, {r.role for r in user.roles})
	if problems:
		frappe.db.rollback()
		_mcp_stop(user_id, problems)
	frappe.db.commit()
	print(f"Created MCP user {user_id}")


def _read_app_file(*parts: str) -> str:
	"""Read a text file shipped in the app, or exit naming the path (see ensure_service_user for why)."""
	path = frappe.get_app_path("nile_auth", *parts)
	try:
		with open(path, encoding="utf-8") as f:
			return f.read()
	except OSError:
		sys.exit(f"ERROR: the file {path} is missing. Nothing was changed.")


def ensure_certificate_format():
	"""Spec 0012 AC-6: create or update the Print Format from the shipped files and make it the default.

	Reads each current value and writes only a difference, so a second run changes nothing.
	"""
	html = _read_app_file("templates", "certificate.html")
	css = _read_app_file("templates", "certificate.css")
	try:
		frappe.get_jenv().from_string(html)
	except Exception as e:
		sys.exit(f"ERROR: templates/certificate.html does not parse: {e}. Nothing was changed.")

	wanted = {
		"doc_type": "LMS Certificate",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"pdf_generator": "wkhtmltopdf",
		"standard": "No",
		"disabled": 0,
		"margin_top": 0,
		"margin_bottom": 0,
		"margin_left": 0,
		"margin_right": 0,
		"html": html,
		"css": css,
	}
	updated = []
	if frappe.db.exists("Print Format", PRINT_FORMAT_NAME):
		doc = frappe.get_doc("Print Format", PRINT_FORMAT_NAME)
		diff = changed_values(doc.as_dict(), wanted)
		if diff:
			doc.update(diff)
			doc.flags.ignore_permissions = True
			doc.save()
			updated.append("Print Format")
	else:
		doc = frappe.get_doc({"doctype": "Print Format", "name": PRINT_FORMAT_NAME, **wanted})
		doc.insert(ignore_permissions=True)
		updated.append("Print Format")

	# The Property Setter LMS reads (get_default_certificate_template). Not make_property_setter, which
	# deletes and inserts every time.
	filters = {"doc_type": "LMS Certificate", "property": "default_print_format"}
	setter = frappe.db.get_value("Property Setter", filters, ["name", "value"], as_dict=True)
	if not setter:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				**filters,
				"doctype_or_field": "DocType",
				"property_type": "Data",
				"value": PRINT_FORMAT_NAME,
			}
		).insert(ignore_permissions=True)
		updated.append("default")
	elif setter.value != PRINT_FORMAT_NAME:
		frappe.db.set_value("Property Setter", setter.name, "value", PRINT_FORMAT_NAME)
		updated.append("default")

	if not updated:
		print(f"Print Format {PRINT_FORMAT_NAME} unchanged")
		return
	frappe.clear_cache(doctype="LMS Certificate")
	frappe.db.commit()
	print(f"Print Format {PRINT_FORMAT_NAME} updated ({', '.join(updated)})")


def _ensure_icon_file_record():
	"""Create the one File record the LMS sidebar needs for the shield; return True if it inserted.

	The sidebar draws banner_image only when a File row has that file_url (get_branding looks it up).
	The file lives in the app's public folder, so Frappe's path checks refuse it. copy_from_existing_file
	skips the blob handling and ignore_validate skips the path check (probed in spec 0012, rationale.md).
	Deleting the row never touches the file on disk.
	"""
	if frappe.db.exists("File", {"file_url": ICON_URL}):
		return False
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": os.path.basename(ICON_URL), "file_url": ICON_URL, "is_private": 0}
	)
	doc.flags.copy_from_existing_file = True
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	return True


def ensure_site_identity():
	"""Spec 0012 AC-5: set the app name, logos and favicon in Website Settings, plus the shield File record.

	Touches only those four fields and that one File record. A second run changes nothing.
	"""
	for file_name in IMAGE_FILES:
		path = frappe.get_app_path("nile_auth", "public", "images", file_name)
		if not os.path.isfile(path):
			sys.exit(f"ERROR: the brand file {path} is missing from the image. Nothing was changed.")

	current = {key: frappe.db.get_single_value("Website Settings", key) for key in SITE_IDENTITY}
	diff = changed_values(current, SITE_IDENTITY)
	updated = list(diff)
	for key, value in diff.items():
		frappe.db.set_single_value("Website Settings", key, value)
	if _ensure_icon_file_record():
		updated.append("shield File record")
	if not updated:
		print("Site identity unchanged")
		return
	frappe.clear_cache()
	frappe.db.commit()
	print(f"Site identity updated ({', '.join(updated)})")
