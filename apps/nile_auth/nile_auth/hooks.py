app_name = "nile_auth"
app_title = "Nile Auth"
app_publisher = "Nile"
app_description = "Group to role mapping and service user setup for the Nile LMS"
app_email = "noreply@example.com"
app_license = "mit"
required_apps = ["lms"]

# Applied by `bench migrate`. Names are explicit so a re run updates the rows instead of adding more.
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Nile Auth"]]},
	{"dt": "Custom DocPerm", "filters": [["name", "like", "nile-%"]]},
]

# Spec 0006: our callback replaces Frappe's for every custom Social Login Key.
override_whitelisted_methods = {
	"frappe.integrations.oauth2_logins.custom": "nile_auth.login.custom",
}
