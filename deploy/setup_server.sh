#!/usr/bin/env bash
#
# First-time setup for a fresh Ubuntu 24.04 EC2 box in ap-south-1 (Mumbai).
# Run once, as a user with sudo:
#
#   sudo bash deploy/setup_server.sh
#
# It does NOT create the .env, request the TLS certificate, or start the app --
# those need values only you have. deploy/README.md picks up where this stops.
#
# The repository is private, so a read-only deploy key must already exist at
# /etc/homeservice/deploy_key before this runs. Generating it is the one step
# that cannot be scripted from here, because the public half has to be pasted
# into GitHub by hand. deploy/README.md section 5 walks through it.

set -euo pipefail

APP_DIR=/srv/homeservice
REPO=git@github.com:tribixsmedia-collab/1_home_service_backend_new.git
BRANCH=main
DEPLOY_KEY=/etc/homeservice/deploy_key

if [ "$EUID" -ne 0 ]; then
    echo "Run this with sudo." >&2
    exit 1
fi

# Fail here with something readable rather than letting the clone die on an
# SSH permission error thirty lines further down.
if [ ! -r "$DEPLOY_KEY" ]; then
    echo "No readable deploy key at $DEPLOY_KEY." >&2
    echo "Generate it and add the public half to the repository deploy keys" >&2
    echo "first -- deploy/README.md section 5." >&2
    exit 1
fi

# ssh refuses an unknown host when nobody is there to answer the prompt, and
# www-data has no ~/.ssh/known_hosts of its own, so GitHub goes in the system
# file. Compare the fingerprint against GitHub docs if this box matters.
if ! ssh-keygen -F github.com -f /etc/ssh/ssh_known_hosts >/dev/null 2>&1; then
    echo "==> Recording GitHub's SSH host key"
    # Not silenced: set -e would otherwise abort the whole script here with no
    # explanation at all if github.com could not be reached.
    if ! ssh-keyscan -t ed25519 github.com >> /etc/ssh/ssh_known_hosts; then
        echo "Could not reach github.com to fetch its host key." >&2
        exit 1
    fi
fi

# The clone below and every later deploy reach GitHub with this key and no
# other. IdentitiesOnly stops ssh offering whatever else it happens to find.
export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts"

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    postgresql-client \
    nginx git curl \
    certbot python3-certbot-nginx \
    unattended-upgrades

echo "==> Enabling automatic security updates"
# The box will be running unattended for months. Security patches should not
# wait for someone to remember.
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Fetching the code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH" --quiet
else
    mkdir -p "$APP_DIR"
    git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

# deploy.sh runs as www-data, which has no home directory and so no ~/.ssh to
# read a key from. Recording the command in the repo's own config is what lets
# its git fetch authenticate.
git -C "$APP_DIR" config core.sshCommand "$GIT_SSH_COMMAND"

echo "==> Building the virtualenv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> Creating the media and secrets directories"
# media/ holds vendor ID documents, which are the one thing on this box that
# exists nowhere else. See the backup section of deploy/README.md.
mkdir -p "$APP_DIR/media" "$APP_DIR/secrets"
chmod 750 "$APP_DIR/secrets"

echo "==> Setting ownership"
chown -R www-data:www-data "$APP_DIR"
chmod +x "$APP_DIR/deploy/deploy.sh"

echo "==> Installing the systemd units"
cp "$APP_DIR/deploy/gunicorn.socket"  /etc/systemd/system/homeservice.socket
cp "$APP_DIR/deploy/gunicorn.service" /etc/systemd/system/homeservice.service
systemctl daemon-reload
systemctl enable homeservice.socket

echo "==> Letting the deploy script restart the app without a password"
cat > /etc/sudoers.d/homeservice <<'SUDOERS'
www-data ALL=(root) NOPASSWD: /usr/bin/systemctl restart homeservice
SUDOERS
chmod 440 /etc/sudoers.d/homeservice

echo "==> Installing the nginx site"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/homeservice
ln -sf /etc/nginx/sites-available/homeservice /etc/nginx/sites-enabled/homeservice
rm -f /etc/nginx/sites-enabled/default

cat <<'NEXT'

==> Base system ready.

Still to do by hand, because each needs a value only you have:

  1. Put the real domain into /etc/nginx/sites-available/homeservice
     (replace api.example.com), then: sudo nginx -t && sudo systemctl reload nginx

  2. Create /srv/homeservice/.env from deploy/env.production.example
     sudo -u www-data nano /srv/homeservice/.env
     sudo chmod 600 /srv/homeservice/.env

  3. Get the HTTPS certificate:
     sudo certbot --nginx -d api.yourdomain.com

  4. Set up the database and start the app -- deploy/README.md, step 6 onward.

NEXT
