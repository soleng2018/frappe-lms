#!/bin/bash
# One shot. Idempotent: a second run changes nothing except pending migrations.
# Secrets arrive as environment variables of this container (never as compose command text).
set -euo pipefail
cd /home/frappe/frappe-bench

SITE="${LMS_HOSTNAME:?LMS_HOSTNAME is blank}"
# Refuse before anything is written, so the site settings below stay as they were (spec 0007, AC-5).
# Compared without regard to case, as Frappe and MariaDB treat user ids.
MCP="${LMS_MCP_USER:-}" SVC="${LMS_SERVICE_USER:-}"
if [ -n "$MCP" ] && [ "${MCP,,}" = "${SVC,,}" ]; then
  echo "ERROR: LMS_MCP_USER must differ from LMS_SERVICE_USER. Nothing was changed." >&2
  exit 1
fi
CONFIG="sites/$SITE/site_config.json"
# PENDING exists from the start of a first creation until all setup below has finished. A leftover
# one means a first run was interrupted, so the site is ours and incomplete. MARKER records a
# finished setup. A site with neither (made before these markers) is never dropped.
PENDING="sites/.creating-$SITE"
MARKER="sites/$SITE/.created"

if [ -f "$PENDING" ]; then
  echo "A previous run was interrupted while creating $SITE. Dropping the partial site."
  ARCHIVE="$(mktemp -d)"
  # The root password is on this command line too (accepted exposure, see below).
  if ! bench drop-site "$SITE" --force --no-backup --archived-sites-path "$ARCHIVE" \
    --db-root-password "$DB_ROOT_PASSWORD"; then
    echo "WARNING: drop-site failed. A database and user for $SITE may be left behind in the db" >&2
    echo "service. Check with 'show databases' and drop them by hand if you see an orphan." >&2
  fi
  # The archive holds the site config, which includes passwords.
  rm -rf "$ARCHIVE" "sites/$SITE" "$PENDING"
fi

if [ ! -d "sites/$SITE" ]; then
  echo "Creating site $SITE"
  touch "$PENDING"
  # Accepted exposure: the DB root and admin passwords are visible in this container's process
  # list while new-site runs. Frappe only reads them from arguments or from config files.
  bench new-site \
    --mariadb-user-host-login-scope='%' \
    --db-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "$LMS_ADMIN_PASSWORD" \
    "$SITE"
  # Set before any app stores an encrypted value. Read from the environment, not from arguments.
  python3 - "$CONFIG" <<'PY'
import json
import os
import sys

path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
config["encryption_key"] = os.environ["LMS_ENCRYPTION_KEY"]
with open(path + ".tmp", "w") as f:
    json.dump(config, f, indent=1)
os.replace(path + ".tmp", path)
PY
  bench --site "$SITE" enable-scheduler
else
  echo "Site $SITE exists"
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: sites/$SITE has no site_config.json and no interrupted run is recorded." >&2
    echo "Remove the folder by hand (and its database) if it is a leftover. Nothing was changed." >&2
    exit 1
  fi
  CURRENT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('encryption_key',''))" "$CONFIG")
  if [ "$CURRENT" != "$LMS_ENCRYPTION_KEY" ]; then
    echo "ERROR: LMS_ENCRYPTION_KEY differs from the key stored in $CONFIG." >&2
    echo "Restore the original .env value. Nothing was changed." >&2
    exit 1
  fi
fi

bench --site "$SITE" set-config host_name "https://$SITE"
bench --site "$SITE" set-config nile_admin_group "${AUTHENTIK_ADMIN_GROUP:-}"
bench --site "$SITE" set-config nile_service_user "${LMS_SERVICE_USER:-}"
bench --site "$SITE" set-config nile_mcp_user "${LMS_MCP_USER:-}"

INSTALLED=$(bench --site "$SITE" list-apps | awk '{print $1}')
for APP in lms nile_auth; do
  if ! grep -qx "$APP" <<<"$INSTALLED"; then
    echo "Installing $APP"
    bench --site "$SITE" install-app "$APP"
  fi
done

bench --site "$SITE" migrate
bench --site "$SITE" execute nile_auth.setup.ensure_service_user
bench --site "$SITE" execute nile_auth.setup.ensure_timezone
bench --site "$SITE" execute nile_auth.setup.ensure_mcp_user
# Spec 0012: the Nile certificate and the app identity, set on every run (each is rerun safe).
bench --site "$SITE" execute nile_auth.setup.ensure_certificate_format
bench --site "$SITE" execute nile_auth.setup.ensure_site_identity
touch "$MARKER"
rm -f "$PENDING"
echo "create-site done"
