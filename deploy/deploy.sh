#!/usr/bin/env bash
#
# Ship the current main branch to this server.
#
#   sudo -u www-data /srv/homeservice/deploy/deploy.sh
#
# Safe to run repeatedly. It stops at the first failure rather than restarting
# a half-updated app, so a broken migration leaves the old code serving.

set -euo pipefail

APP_DIR=/srv/homeservice
VENV="$APP_DIR/venv"
BRANCH="${DEPLOY_BRANCH:-main}"

cd "$APP_DIR"

echo "==> Fetching $BRANCH"
git fetch --quiet origin "$BRANCH"

OLD_REV=$(git rev-parse --short HEAD)
git reset --hard "origin/$BRANCH" --quiet
NEW_REV=$(git rev-parse --short HEAD)

if [ "$OLD_REV" = "$NEW_REV" ]; then
    echo "    already at $NEW_REV"
else
    echo "    $OLD_REV -> $NEW_REV"
fi

echo "==> Installing dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt

echo "==> Checking the app can start"
# Runs before migrate on purpose: a settings or import error should stop the
# deploy while the database is still untouched.
"$VENV/bin/python" manage.py check --deploy

echo "==> Applying database migrations"
"$VENV/bin/python" manage.py migrate --noinput

echo "==> Collecting static files"
"$VENV/bin/python" manage.py collectstatic --noinput

echo "==> Restarting"
# Needs passwordless sudo for exactly this command; see deploy/README.md.
sudo systemctl restart homeservice

sleep 2
if systemctl is-active --quiet homeservice; then
    echo "==> Live on $NEW_REV"
else
    echo "!!! homeservice did not come back up. Recent log:" >&2
    journalctl -u homeservice -n 40 --no-pager >&2
    exit 1
fi
