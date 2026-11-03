"""The data model constants from spec 0004, in one place for the login hook (feature 7) to use."""

import datetime

# Roles and user types the login hook gives each kind of member.
STUDENT_USER_TYPE = "Website User"
STUDENT_ROLES = ("LMS Student",)
ADMIN_USER_TYPE = "System User"
ADMIN_ROLES = ("Moderator", "Course Creator")

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
