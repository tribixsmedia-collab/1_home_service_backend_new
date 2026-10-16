# Shipping an update

How to get a code change from your laptop onto the live site.

There are two separate things to deploy and they work completely differently:

| What | Lives where | How it ships |
|------|-------------|--------------|
| **Backend** (Django API + dashboard) | `/srv/homeservice` on the server | server pulls from GitHub |
| **Web app** (customer_app, Flutter web) | `/srv/homeservice-web` on the server | you build on your laptop and upload |

The backend pulls. The web app is pushed. Mixing those up is the usual cause of
"I deployed but nothing changed".

Both live on the same EC2 box, `13.200.180.192`, in Mumbai.

| Address | Serves |
|---------|--------|
| `https://13-200-180-192.sslip.io` | API + admin dashboard |
| `https://web.13-200-180-192.sslip.io` | customer web app |

Connect with:

```bash
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192
```

Leave with `exit`.

---

## Part 1 — Backend (Django)

### 1. Change and test on your laptop

```bash
cd "C:\Users\root\Desktop\claude\Make My House\home_service_backend"
python manage.py test
```

Do not skip the tests. The server runs `manage.py check --deploy` before it
restarts, but that only catches settings and import errors, not broken logic.

### 2. Commit and push to `main`

The server deploys from `main`. A change sitting on `development` will never
reach it.

```bash
git add -A
git commit -m "Describe what changed"
git push origin main
```

### 3. Check whether you are about to run a migration

This decides whether the deploy is reversible.

```bash
git diff --name-only origin/main~1..origin/main | grep migration
```

Nothing listed means the deploy is safe to roll back by checking out the old
commit. If migrations *are* listed, read **Migrations** below before going on.

### 4. Deploy

```bash
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "sudo -u www-data /srv/homeservice/deploy/deploy.sh"
```

That one script does everything, in this order:

1. fetches `main` and hard-resets the checkout to it
2. installs any new dependencies
3. runs `manage.py check --deploy`
4. applies migrations
5. collects static files
6. restarts the service
7. confirms it came back up

It stops at the first failure. A bad migration therefore leaves the **previous
version still serving** rather than a half-updated one, which is the behaviour
you want at 11pm.

Success ends with:

```
==> Live on <commit>
```

### 5. Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://13-200-180-192.sslip.io/privacy/
curl -s https://13-200-180-192.sslip.io/api/services/categories/
```

A `200` and some JSON means it is alive. Then open the dashboard and click
through whatever you actually changed.

---

## Part 2 — Web app (customer_app)

The API address is **compiled into** the build. There is no runtime setting, so
a build points at whatever host it was built against, for ever.

### 1. Change and test on your laptop

```bash
cd "C:\Users\root\Desktop\claude\Make My House\home service project\customer_app"
flutter test
```

### 2. Build

This is a bash script, so use **Git Bash**, not PowerShell:

```bash
./build_web.sh
```

It builds against `https://13-200-180-192.sslip.io/api` by default, copies
`.htaccess` in by hand (Flutter silently skips dotfiles), and packages
everything as `homeservice-web.tar.gz`.

To build against a different backend — a real domain, once you have one:

```bash
API_BASE_URL=https://api.yourdomain.com/api ./build_web.sh
```

The script refuses anything that is not `https`. A page served over https
cannot call a plain-http API; browsers block it as mixed content, and the app
loads and then does nothing.

### 3. Upload

```bash
scp -i C:/keys/homeservice-key.pem homeservice-web.tar.gz ubuntu@13.200.180.192:/tmp/
```

About 16MB, so give it a minute.

### 4. Install

```bash
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "sudo rm -rf /srv/homeservice-web/* && sudo tar -xzf /tmp/homeservice-web.tar.gz -C /srv/homeservice-web && sudo chown -R www-data:www-data /srv/homeservice-web && rm /tmp/homeservice-web.tar.gz && echo DONE"
```

The `rm -rf` matters: extracting over the top leaves orphaned files from the
previous build behind, and stale JavaScript can get served alongside new HTML.

**No nginx restart is needed.** These are static files; nginx picks them up
immediately.

### 5. Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://web.13-200-180-192.sslip.io/
curl -s https://web.13-200-180-192.sslip.io/version.json
```

Then open the site and **hard-refresh** — `Ctrl+Shift+R`, or `Ctrl+F5`.

`index.html`, `version.json` and `flutter_service_worker.js` are served
`no-store`, so a normal visitor does get the new version. But your own browser
may be holding a service worker from the previous build. If the site looks
unchanged, open DevTools → Application → Service Workers → Unregister, then
reload.

---

## Changing settings (`.env`)

`.env` holds the secrets and is **not in Git**, deliberately. It lives only on
the server, and `deploy.sh` never touches it.

Back it up before every edit:

```bash
sudo cp -a /srv/homeservice/.env /srv/homeservice/.env.bak.$(date +%Y%m%d-%H%M%S)
```

Then edit and restart. For a single value, one line is less error-prone than an
editor:

```bash
sudo sed -i 's|^SETTING_NAME=.*|SETTING_NAME=new_value|' /srv/homeservice/.env
sudo systemctl restart homeservice.service
```

**Django reads `.env` once, at startup.** Edit it and walk away and the app
keeps running with the old value — which looks exactly like the edit not
working. The restart is not optional.

Confirm what Django actually ended up with:

```bash
cd /srv/homeservice && sudo -u www-data ./venv/bin/python manage.py shell -c "from django.conf import settings; print(settings.SETTING_NAME)"
```

Check the value, not the file. A line can be present and empty, and `grep` will
happily show you a setting that Django reads as blank.

---

## Migrations

A migration that only adds things is safe. One that drops or renames a column
destroys data, and rolling the code back will not bring it back.

Before deploying one:

```bash
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "cd /srv/homeservice && sudo -u www-data ./venv/bin/python manage.py showmigrations --plan | grep '\[ \]'"
```

For anything destructive, snapshot the database first — RDS console →
`homeservice-db` → Actions → Take snapshot. The free plan keeps only 1 day of
automatic backups, so do not rely on those.

---

## Rolling back

### Backend

Find the commit that worked and put the server on it:

```bash
cd /srv/homeservice
git log --oneline -10
sudo -u www-data git -c safe.directory=/srv/homeservice reset --hard <commit>
sudo systemctl restart homeservice.service
```

This does **not** undo a migration. If the bad deploy migrated the database,
you need the snapshot.

Then fix `main` properly, because the next `deploy.sh` will pull it straight
back.

### Web app

There is no automatic history. Keep the last known-good `homeservice-web.tar.gz`
on your laptop and re-upload it with the Part 2 steps.

Worth doing: rename each one, `homeservice-web-2026-10-14.tar.gz`, and keep a
few.

---

## When something breaks

```bash
sudo journalctl -u homeservice -n 100 --no-pager       # the app's own log
sudo tail -50 /var/log/nginx/homeservice.error.log     # API host
sudo tail -50 /var/log/nginx/homeservice-web.error.log # web app host
systemctl is-active homeservice.service nginx
```

**The service is called `homeservice`, not `gunicorn`.** Checking
`gunicorn.service` reports "inactive" and looks exactly like an outage when
nothing is wrong at all.

| Symptom | Usual cause |
|---------|-------------|
| 502 Bad Gateway | app not running — the journal says why, usually a bad `.env` value |
| Web app 404s on refresh or a shared link | `try_files` missing from `nginx-web.conf` |
| Site looks unchanged after deploy | your service worker — hard-refresh, then unregister it |
| API calls blocked in the browser console | web origin missing from `CORS_ALLOWED_ORIGINS` |
| Everything redirects forever | nginx not passing `X-Forwarded-Proto` |

---

## Two rules worth keeping

**Never edit code directly on the server.** `deploy.sh` runs `git reset --hard`,
so anything you changed there is destroyed without warning on the next deploy.
Change it on your laptop, push, deploy.

**Deploy the backend before the web app** when a change spans both. The API
tolerates an old web app calling it; an old API being called by a new web app
breaks for whoever is mid-session.

---

## Connecting a real domain name

Everything currently runs on `sslip.io` addresses. This replaces them with a
real domain. `rniservices.com` is the example — substitute your own.

**Add the new names, do not replace the old ones.** Every step below keeps the
`sslip.io` addresses working alongside the new domain, because installed apps
and the current web build still point at the old address and would break the
moment it vanished. Retire the old names only once everything is rebuilt.

### 1. Buy the domain

Route 53 (~$14/yr plus $0.50/month for the zone) or any registrar — GoDaddy,
Namecheap, BigRock, Hostinger. You do **not** need Route 53; an outside
registrar works identically and is usually cheaper.

### 2. Point the DNS at the server

Three **A records** at your registrar:

| Type | Name | Value | Becomes |
|------|------|-------|---------|
| A | `@` | `13.200.180.192` | rniservices.com — the website |
| A | `www` | `13.200.180.192` | www.rniservices.com — the website |
| A | `api` | `13.200.180.192` | api.rniservices.com — the backend |

Default TTL. The API needs its own name because the Django dashboard owns `/`
on that host; the website cannot share it without hiding the dashboard.

**Never release the Elastic IP.** All three records point at it.

### 3. Wait, then check it resolved

```bash
nslookup api.rniservices.com
nslookup www.rniservices.com
```

Each must answer `13.200.180.192`. The certificate step fails otherwise, so do
not continue until they do.

### 4. Add the names to nginx

```bash
sudo nano /etc/nginx/sites-available/homeservice
```

Both `server_name` lines (one for https, one for the http redirect) become:

```
server_name 13-200-180-192.sslip.io api.rniservices.com;
```

Then the web app's file:

```bash
sudo nano /etc/nginx/sites-available/homeservice-web
```

Both of its `server_name` lines become:

```
server_name web.13-200-180-192.sslip.io rniservices.com www.rniservices.com;
```

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If `nginx -t` fails, fix it **before** reloading — a reload with a broken
config takes both sites down.

### 5. Get HTTPS certificates

`--expand` adds the new names to the existing certificate instead of creating a
second one, so the old address keeps its HTTPS:

```bash
sudo certbot --nginx --expand -d 13-200-180-192.sslip.io -d api.rniservices.com
```

```bash
sudo certbot --nginx --expand -d web.13-200-180-192.sslip.io -d rniservices.com -d www.rniservices.com
```

Certbot edits the nginx files and reloads. Renewal stays automatic.

### 6. Tell Django the new addresses

```bash
sudo cp -a /srv/homeservice/.env /srv/homeservice/.env.bak.$(date +%Y%m%d-%H%M%S)
sudo nano /srv/homeservice/.env
```

Keep the old values, add the new ones. Each must be one line, no spaces around
the commas:

```
ALLOWED_HOSTS=13-200-180-192.sslip.io,api.rniservices.com
CSRF_TRUSTED_ORIGINS=https://13-200-180-192.sslip.io,https://api.rniservices.com
CORS_ALLOWED_ORIGINS=https://13-200-180-192.sslip.io,https://web.13-200-180-192.sslip.io,https://rniservices.com,https://www.rniservices.com
```

```bash
sudo systemctl restart homeservice.service
```

**Miss the CORS line and the site loads but does nothing** — pages appear, every
API call is blocked, and nothing says so except the browser console.

### 7. Rebuild the web app

The API address is compiled in, so the live build still calls the old host.

```bash
API_BASE_URL=https://api.rniservices.com/api ./build_web.sh
```

Run it from `customer_app` in Git Bash, then deploy as in Part 2.

### 8. Rebuild the Android apps

```bash
flutter build appbundle --release --dart-define=API_BASE_URL=https://api.rniservices.com/api
```

**Do this before publishing to the Play Store.** Once customers have installed
the app the address inside it cannot be changed.

### 9. Verify

```bash
curl -s -o /dev/null -w "api %{http_code}\n" https://api.rniservices.com/privacy/
curl -s -o /dev/null -w "web %{http_code}\n" https://rniservices.com/
curl -s -o /dev/null -w "old %{http_code}\n" https://13-200-180-192.sslip.io/privacy/
```

All three should answer `200`. The last matters as much as the rest: it confirms
nothing already installed has broken.

---

## Cheat sheet

```bash
# Backend: push then deploy
git push origin main
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "sudo -u www-data /srv/homeservice/deploy/deploy.sh"

# Web app: build, upload, install  (Git Bash)
cd "C:\Users\root\Desktop\claude\Make My House\home service project\customer_app"
./build_web.sh
scp -i C:/keys/homeservice-key.pem homeservice-web.tar.gz ubuntu@13.200.180.192:/tmp/
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "sudo rm -rf /srv/homeservice-web/* && sudo tar -xzf /tmp/homeservice-web.tar.gz -C /srv/homeservice-web && sudo chown -R www-data:www-data /srv/homeservice-web && rm /tmp/homeservice-web.tar.gz && echo DONE"

# Is it alive?
curl -s -o /dev/null -w "api %{http_code}\n" https://13-200-180-192.sslip.io/privacy/
curl -s -o /dev/null -w "web %{http_code}\n" https://web.13-200-180-192.sslip.io/

# What went wrong?
ssh -i C:/keys/homeservice-key.pem ubuntu@13.200.180.192 "sudo journalctl -u homeservice -n 60 --no-pager"
```
