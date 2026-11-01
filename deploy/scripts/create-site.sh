#!/bin/bash
# One shot. Idempotent: a second run changes nothing except pending migrations.
# Secrets arrive as environment variables of this container (never as compose command text).
set -euo pipefail
cd /home/frappe/frappe-bench

SITE="$LMS_HOSTNAME"
CONFIG="sites/$SITE/site_config.json"
MARKER="sites/$SITE/.created"

if [ ! -f "$MARKER" ]; then
  echo "Creating site $SITE"
  # A run interrupted before the marker leaves a half built site; start clean.
  bench new-site --force \
    --mariadb-user-host-login-scope='%' \
    --db-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "$LMS_ADMIN_PASSWORD" \
    "$SITE"
  # Set before any app stores an encrypted value.
  bench --site "$SITE" set-config encryption_key "$LMS_ENCRYPTION_KEY"
  bench --site "$SITE" enable-scheduler
  touch "$MARKER"
else
  echo "Site $SITE exists"
  CURRENT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('encryption_key',''))" "$CONFIG")
  if [ "$CURRENT" != "$LMS_ENCRYPTION_KEY" ]; then
    echo "ERROR: LMS_ENCRYPTION_KEY differs from the key stored in $CONFIG." >&2
    echo "Restore the original .env value. Nothing was changed." >&2
    exit 1
  fi
fi

bench --site "$SITE" set-config host_name "https://$SITE"
bench --site "$SITE" set-config nile_admin_group "${AUTHENTIK_ADMIN_GROUP:-}"
bench --site "$SITE" set-config nile_student_group_prefix "${AUTHENTIK_STUDENT_GROUP_PREFIX:-}"
bench --site "$SITE" set-config nile_student_group_suffix "${AUTHENTIK_STUDENT_GROUP_SUFFIX:-}"

INSTALLED=$(bench --site "$SITE" list-apps | awk '{print $1}')
for APP in lms nile_auth; do
  if ! grep -qx "$APP" <<<"$INSTALLED"; then
    echo "Installing $APP"
    bench --site "$SITE" install-app "$APP"
  fi
done

bench --site "$SITE" migrate
bench --site "$SITE" execute nile_auth.setup.ensure_service_user
echo "create-site done"
