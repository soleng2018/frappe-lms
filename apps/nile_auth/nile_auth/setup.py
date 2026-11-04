"""Site setup run by create-site. Reads its inputs from the container environment, never from arguments."""

import os
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

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
