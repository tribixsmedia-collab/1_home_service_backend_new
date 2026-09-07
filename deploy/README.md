# Putting the backend on AWS

This is the whole job, start to finish, for one EC2 server and one RDS
database in Mumbai. Follow it top to bottom the first time.

Everything here is done once. Afterwards, shipping new code is a single
command — see [Deploying an update](#deploying-an-update) at the end.

**Region: `ap-south-1` (Mumbai), for every resource.** Indian customers get a
fast app, and payment data stays in the country. Picking a US region by
accident is both slower and a compliance problem, and moving afterwards means
rebuilding everything.

---

## What you are building

| Piece | AWS service | Rough cost |
|---|---|---|
| The server the app runs on | EC2 `t3.small` | ~₹1,300/month |
| The database | RDS PostgreSQL `db.t4g.micro` | ~₹1,300/month |
| Disk for the server | 30 GB gp3 | ~₹230/month |
| The domain's DNS | Route 53 | ~₹45/month |
| HTTPS certificate | Let's Encrypt (on the box) | free |
| Sending email | SES | ~free at this volume |

Roughly **₹2,900/month**, plus 18% GST, billed in dollars.

A brand-new AWS account gets 12 months free on the small sizes. Note the date
it ends — the bill appears suddenly in month 13.

> Photos and video stay on Cloudinary rather than S3. Cloudinary shrinks and
> re-encodes images as it delivers them, which S3 does not do on its own, and
> it is already built and tested. Nothing here depends on that choice.

---

## 1. Create the database first

RDS takes about ten minutes to become available, so start it before the server
and it will be ready when you need it.

In the RDS console → **Create database**:

- **Standard create**, engine **PostgreSQL**
- Template **Free tier** if the account is new, otherwise **Dev/Test**
- Instance: `db.t4g.micro`
- Storage: 20 GB gp3, **storage autoscaling on**
- **Public access: No** ← important, and awkward to change later
- Initial database name: `homeservice_db`
- Master username: `homeservice`
- Master password: generate a long one and put it somewhere safe now
- **Automated backups: 7 days**

Leave it building and move on.

## 2. Create the server

EC2 → **Launch instance**:

- Ubuntu Server 24.04 LTS, architecture x86_64
- Type `t3.small`
- Create a new key pair, download the `.pem`, and keep it — it is the only way
  in, and AWS will not give you another copy
- Storage: 30 GB gp3
- Security group — allow only:
  - SSH (22) from **your own IP**, not from anywhere
  - HTTP (80) from anywhere
  - HTTPS (443) from anywhere

## 3. Let the server reach the database

This is the step people miss, and the symptom is a deploy that hangs with no
error.

1. EC2 → your instance → copy its **security group id** (`sg-…`)
2. RDS → your database → **Connectivity & security** → its security group
3. **Edit inbound rules** → Add rule:
   - Type **PostgreSQL**, Port 5432
   - Source: **the EC2 security group id from step 1**

Type the security group id, not an IP address. The server's IP changes when
it restarts; the group id never does.

## 4. Point the domain at the server

Give the instance an **Elastic IP** first (EC2 → Elastic IPs → Allocate, then
Associate with the instance). Without one, the address changes on every
restart and the domain silently stops working.

Then in Route 53, on your hosted zone, add an **A record**:

| Name | Type | Value |
|---|---|---|
| `api` | A | the Elastic IP |

DNS takes a few minutes. Check with `ping api.yourdomain.com` before going on
— certbot in step 7 will fail if the name does not yet resolve.

## 5. Set the server up

SSH in and run the setup script:

```bash
ssh -i your-key.pem ubuntu@api.yourdomain.com

git clone https://github.com/tribixsmedia-collab/1_home_service_backend_new.git /tmp/hs
sudo bash /tmp/hs/deploy/setup_server.sh
```

That installs Python, nginx, certbot and Postgres client tools, clones the
code to `/srv/homeservice`, builds the virtualenv, and installs the service
files. It deliberately stops short of starting anything.

## 6. Write the settings file

```bash
sudo -u www-data cp /srv/homeservice/deploy/env.production.example /srv/homeservice/.env
sudo -u www-data nano /srv/homeservice/.env
sudo chmod 600 /srv/homeservice/.env
```

Every line is commented in that file. The four you cannot skip:

- `SECRET_KEY` — generate a fresh one, do not reuse the development value:
  ```bash
  /srv/homeservice/venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```
- `ALLOWED_HOSTS` — `api.yourdomain.com`
- `DB_HOST` / `DB_PASSWORD` — from the RDS instance in step 1
- `DEBUG=False`

The rest are integration keys. Leave any of them blank and that integration
quietly falls back — no SMS goes out, no push arrives, photos go to local
disk. Nothing crashes. Fill them in as the client sends them.

## 7. Put the domain into nginx, and get HTTPS

```bash
sudo nano /etc/nginx/sites-available/homeservice   # replace api.example.com
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d api.yourdomain.com
```

Certbot edits the nginx file to add the certificate and the redirect from
http to https, and installs a timer that renews it automatically. The
certificate is free and renews itself; there is nothing to buy and nothing to
diary.

## 8. Start it

```bash
cd /srv/homeservice
sudo -u www-data venv/bin/python manage.py migrate
sudo -u www-data venv/bin/python manage.py collectstatic --noinput
sudo -u www-data venv/bin/python manage.py createsuperuser

sudo systemctl enable --now homeservice.socket homeservice
sudo systemctl status homeservice
```

Open `https://api.yourdomain.com/` — the admin dashboard login should appear,
over HTTPS, with no certificate warning.

## 9. Check what is actually switched on

Two checks. The first is Django’s own, on settings:

```bash
cd /srv/homeservice
sudo -u www-data venv/bin/python manage.py check --deploy
```

This should print **no warnings**. Any that appear are real in production —
unlike on a development machine, where they are expected.

The second calls each outside service and reports what is genuinely working:

```bash
sudo -u www-data venv/bin/python manage.py check_integrations
```

Every integration degrades rather than crashes when its keys are missing, which
is why a half-configured server looks perfectly healthy. This is what tells
them apart:

- **LIVE** — a real call to the service succeeded
- **FALLBACK** — deliberately not configured; it names what happens instead
- **BROKEN** — configured, but the service refused us. Usually a wrong key

With `DEBUG=False` it also treats fallbacks that would break real customers —
login codes printing to a terminal, payments refusing — as problems, and exits
non-zero. That makes it the natural last line of `deploy.sh` once the client's
keys are in. Add `--offline` to skip the network calls.

## 10. Point the apps at the server

In both Flutter apps, `lib/config.dart` holds the backend address. Change it
to `https://api.yourdomain.com` and rebuild. Until this is done the apps still
talk to whatever machine they were built against.

---

## Two things that will bite later

### Vendor ID documents live only on this server

Everything else survives the server being destroyed: the database is in RDS
with its own backups, and photos are on Cloudinary. Vendor government-ID
scans, address proofs and trade certificates are **only** on this box's disk,
at `/srv/homeservice/media/vendor_documents/`.

They are kept there on purpose — a Cloudinary link authorises nobody, and
these are people's identity documents. The trade-off is that they are the one
thing you have to back up yourself.

Turn on **EBS snapshots** for the instance's volume: EC2 → Elastic Block Store
→ Lifecycle Manager → daily, keep 7. Five minutes, and it is the difference
between a bad afternoon and telling every vendor to re-upload their ID.

nginx is configured to refuse these files outright at `/media/vendor_documents/`.
They are reachable only through the dashboard, only by an admin holding the
`vendors.view` permission. Do not "fix" that block in `deploy/nginx.conf` —
removing it publishes every vendor's ID to anyone who can guess a filename.

### Email will not send to real customers at first

AWS SES starts every account in **sandbox mode**, where it delivers only to
addresses you have personally verified. Customer login codes go out by email,
so this blocks real sign-ups.

Raise the production-access request in the SES console on day one. It usually
clears in about 24 hours, but it is a queue, not a button.

---

## Deploying an update

Once, on your own machine, push to `main`. Then on the server:

```bash
sudo -u www-data /srv/homeservice/deploy/deploy.sh
```

It fetches `main`, installs dependencies, checks the app starts, migrates,
collects static files and restarts. It stops at the first failure, so a bad
migration leaves the previous version still serving rather than a half-updated
one.

## When something is wrong

```bash
sudo journalctl -u homeservice -n 100 --no-pager   # the app's own log
sudo tail -50 /var/log/nginx/homeservice.error.log # nginx's
sudo systemctl status homeservice
```

**502 Bad Gateway** — the app is not running. The journal will say why; a bad
`.env` value is the usual cause.

**Everything redirects forever** — nginx is not passing `X-Forwarded-Proto`.
Check that line is present in the `location /` block.

**Uploads fail at a certain size** — `client_max_body_size` in the nginx file.

**Blank page where a vendor document should be** — `MEDIA_X_ACCEL_REDIRECT=True`
in `.env` but the `/protected-media/` block missing from nginx. Set it to
`False` and the app serves the file itself, more slowly but correctly.
