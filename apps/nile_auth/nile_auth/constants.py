"""The data model constants from spec 0004, in one place for the login hook (feature 7) to use."""

import datetime

# Roles and user types the login hook gives each kind of member.
STUDENT_USER_TYPE = "Website User"
STUDENT_ROLES = ("LMS Student",)
ADMIN_USER_TYPE = "System User"
# Desk User makes Frappe treat the account as a System User. The user type is never set by nile_auth.
ADMIN_ROLES = ("Moderator", "Course Creator", "Desk User")

# The only roles nile_auth adds or removes (spec 0006). Every other role is left alone.
MANAGED_ROLES = (*STUDENT_ROLES, *ADMIN_ROLES)

# The custom field that holds the exact Authentik group name on an LMS Batch. Batches are looked up
# only by this field, never by title or name.
BATCH_GROUP_FIELD = "nile_group"

# Values for the Batch fields LMS requires but that mean nothing for us. Dates are computed at login.
BATCH_END_YEARS = 10
BATCH_START_TIME = datetime.time(0, 0, 0)
BATCH_END_TIME = datetime.time(23, 59, 59)
BATCH_DESCRIPTION = "Students of {group}"
BATCH_PUBLISHED = 1
BATCH_ALLOW_SELF_ENROLLMENT = 0

# Spec 0006: the group to role mapping at login.
USER_GROUPS_FIELD = "nile_groups"
LOGGER_NAME = "nile_auth"

# Site config keys (written by create-site from .env).
CONF_ADMIN_GROUP = "nile_admin_group"
CONF_STUDENT_PREFIX = "nile_student_group_prefix"
CONF_STUDENT_SUFFIX = "nile_student_group_suffix"
CONF_SERVICE_USER = "nile_service_user"
CONF_MCP_USER = "nile_mcp_user"

# Outcome words for the one log line per login (AC-12).
OUTCOME_OK = "ok"
OUTCOME_NO_GROUP = "refused_no_group"
OUTCOME_PROTECTED = "refused_protected"
OUTCOME_IDENTITY = "refused_identity"
OUTCOME_DISABLED = "disabled"
OUTCOME_NO_EMAIL = "no_email"
OUTCOME_BAD_STATE = "bad_state"
OUTCOME_FAULT_CLAIM = "setup_fault_claim"
OUTCOME_FAULT_SETTINGS = "setup_fault_settings"
OUTCOME_ERROR = "error"

# Pages shown to a person. None of them names the rule that failed.
PAGE_REFUSED = ("Not allowed", "Your account is not in a workshop group, so you cannot use this site.", 403)
PAGE_PROTECTED = ("Not allowed", "This account cannot use this login.", 403)
PAGE_NO_EMAIL = ("Not allowed", "Your profile has no email address, so you cannot sign in.", 403)
PAGE_SETUP_FAULT = (
	"Sign in is not set up",
	"Sign in is not set up correctly. Tell the person who runs this site.",
	500,
)
PAGE_BAD_STATE = ("Invalid Request", "Your login attempt is invalid or has expired. Please try again.", 417)
PAGE_RETRY = ("Something went wrong", "We could not finish signing you in. Please try again.", 500)
