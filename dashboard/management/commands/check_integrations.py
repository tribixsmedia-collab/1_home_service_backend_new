"""
What is actually switched on, and what is quietly pretending.

Every outside service in this project degrades rather than crashes when its
keys are missing: no Cloudinary means local disk, no SMS means the code prints
to the terminal, no Razorpay means checkout refuses politely. That is the right
behaviour, and it is also why a half-configured server looks perfectly healthy
from the outside. This command is the answer to "is it really on?".

    python manage.py check_integrations
    python manage.py check_integrations --offline    # no network calls
    python manage.py check_integrations --production # judge as if DEBUG=False

Three states, and the difference between the last two is the point:

  LIVE      configured, and a real call to the service succeeded
  FALLBACK  deliberately not configured; what happens instead is named
  BROKEN    configured, but the service refused us -- a wrong key, usually

A fallback is fine on a laptop and often fatal in production: nobody can sign
in if the OTP is printing to a terminal. So with DEBUG=False, fallbacks that
would break real users are reported as problems and the command exits non-zero,
which makes it usable as the last step of a deploy.
"""

import socket
from dataclasses import dataclass, field

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

LIVE = 'LIVE'
FALLBACK = 'FALLBACK'
BROKEN = 'BROKEN'
SKIPPED = 'SKIPPED'


@dataclass
class Result:
    name: str
    state: str
    detail: str = ''
    # What happens instead, when this is a FALLBACK.
    instead: str = ''
    # True when a FALLBACK here means real users cannot use the app.
    fatal_in_production: bool = False
    notes: list = field(default_factory=list)


def _probe(fn, offline, unchecked='not checked (--offline)'):
    """Run a live check, or say plainly that it was not run."""
    if offline:
        return None, unchecked
    try:
        return True, fn()
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'[:160]


# ---------------------------------------------------------------- the checks

def check_database(offline):
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        engine = settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1]
        host = settings.DATABASES['default'].get('HOST') or 'local socket'
        return Result('Database', LIVE, f'{engine} at {host}')
    except Exception as exc:
        return Result('Database', BROKEN, f'{type(exc).__name__}: {exc}'[:160])


def check_cloudinary(offline):
    if not settings.USE_CLOUDINARY:
        return Result(
            'Cloudinary', FALLBACK,
            'no credentials',
            instead='images and video are stored on this server\'s own disk',
        )

    ok, detail = _probe(lambda: _cloudinary_ping(), offline)
    if ok is None:
        return Result('Cloudinary', LIVE, f'cloud "{settings.CLOUDINARY_CLOUD_NAME}", {detail}')
    if not ok:
        return Result('Cloudinary', BROKEN, detail)
    return Result('Cloudinary', LIVE, detail)


def _cloudinary_ping():
    import cloudinary
    import cloudinary.api
    usage = cloudinary.api.usage(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )
    plan = usage.get('plan', '?')
    credits = (usage.get('credits') or {})
    used, limit = credits.get('usage'), credits.get('limit')
    extra = f', {used}/{limit} credits' if limit else ''
    return f'cloud "{settings.CLOUDINARY_CLOUD_NAME}", {plan} plan{extra}'


def check_push(offline):
    from notifications import push

    if not push._enabled():
        return Result(
            'Push notifications (FCM)', FALLBACK,
            'FCM_ENABLED off, or no project id / credentials file',
            instead='alerts are still recorded in-app, but no phone receives one',
        )

    problem = push._preflight_error()
    if problem:
        return Result('Push notifications (FCM)', BROKEN, problem[:160])

    ok, detail = _probe(
        lambda: f'project "{settings.FCM_PROJECT_ID}", token obtained'
        if push._access_token() else 'no token',
        offline,
    )
    if ok is None:
        return Result('Push notifications (FCM)', LIVE,
                      f'project "{settings.FCM_PROJECT_ID}", {detail}')
    if not ok:
        return Result('Push notifications (FCM)', BROKEN, detail)

    res = Result('Push notifications (FCM)', LIVE, detail)
    res.notes.append(
        'A token is only delivered if the app that registered it belongs to '
        'this same Firebase project.'
    )
    return res


def check_razorpay(offline):
    from payments import gateway

    if not gateway.is_configured():
        return Result(
            'Razorpay (payments)', FALLBACK,
            'no key id / secret',
            instead='checkout refuses with "online payment is not set up yet"',
            fatal_in_production=True,
        )

    key = settings.RAZORPAY_KEY_ID
    mode = 'LIVE keys' if key.startswith('rzp_live') else 'TEST keys'

    ok, detail = _probe(lambda: _razorpay_ping(), offline)
    res = Result('Razorpay (payments)', LIVE if ok is not False else BROKEN,
                 f'{mode}, {detail}')
    if ok is not False and mode == 'TEST keys':
        res.notes.append('Test keys move no real money. Live keys start rzp_live_.')
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        res.notes.append(
            'RAZORPAY_WEBHOOK_SECRET is empty, so webhook deliveries cannot be '
            'verified and a payment confirmed only by webhook will be ignored.'
        )
    return res


def _razorpay_ping():
    from payments import gateway
    # Listing one payment is the cheapest authenticated read; it proves the
    # key pair is accepted without creating anything.
    gateway.get_client().payment.all({'count': 1})
    return 'credentials accepted'


def check_payouts(offline):
    from payments import payoutx

    if not payoutx.is_enabled():
        return Result(
            'RazorpayX (vendor payouts)', FALLBACK,
            'not configured',
            instead='payouts are made by hand and the reference typed into the '
                    'dashboard, which is the intended way to start',
        )
    return Result('RazorpayX (vendor payouts)', LIVE,
                  f'account {settings.RAZORPAYX_ACCOUNT_NUMBER[:6]}..., '
                  f'mode {settings.RAZORPAYX_PAYOUT_MODE}')


def check_sms(offline):
    backend = getattr(settings, 'SMS_BACKEND', 'console')

    if backend == 'console':
        return Result(
            'SMS (login codes)', FALLBACK,
            'SMS_BACKEND=console',
            instead='the code is printed to the server terminal and sent to nobody',
            fatal_in_production=True,
        )

    keys = {
        'fast2sms': ('FAST2SMS_API_KEY',),
        'msg91': ('MSG91_AUTH_KEY', 'MSG91_SENDER_ID'),
        'twilio': ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'),
    }.get(backend)

    if keys is None:
        return Result('SMS (login codes)', BROKEN,
                      f'SMS_BACKEND="{backend}" is not one of console, '
                      f'fast2sms, msg91, twilio')

    missing = [k for k in keys if not getattr(settings, k, '')]
    if missing:
        return Result('SMS (login codes)', BROKEN,
                      f'{backend}, but {", ".join(missing)} is empty')

    res = Result('SMS (login codes)', LIVE, f'{backend}, credentials present')
    res.notes.append(
        'Not probed: every provider bills per message, so the only real test '
        'is requesting an OTP on a phone you hold.'
    )
    return res


def check_email(offline):
    backend = settings.EMAIL_BACKEND.rsplit('.', 1)[-1]

    if 'console' in settings.EMAIL_BACKEND.lower():
        return Result(
            'Email (login codes, receipts)', FALLBACK,
            'console backend',
            instead='mail is printed to the server terminal',
            fatal_in_production=True,
        )

    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        return Result('Email (login codes, receipts)', BROKEN,
                      f'{backend} with no EMAIL_HOST_USER / PASSWORD')

    host, port = settings.EMAIL_HOST, settings.EMAIL_PORT
    ok, detail = _probe(lambda: _smtp_reachable(host, port), offline)
    if ok is None:
        return Result('Email (login codes, receipts)', LIVE, f'{host}:{port}, {detail}')
    if not ok:
        return Result('Email (login codes, receipts)', BROKEN, f'{host}:{port} -- {detail}')

    res = Result('Email (login codes, receipts)', LIVE, f'{host}:{port} reachable')
    if 'amazonaws' in host:
        res.notes.append(
            'SES starts in sandbox mode and delivers only to verified '
            'addresses. Reachable does not mean customers receive mail.'
        )
    return res


def _smtp_reachable(host, port):
    with socket.create_connection((host, int(port)), timeout=8):
        return 'port open'


def check_maps(offline):
    from maps.models import MapSettings

    try:
        row = MapSettings.objects.first()
    except Exception as exc:
        return Result('Maps', BROKEN, f'could not read settings: {exc}'[:120])

    # Compared against the model's own enum rather than a lowercase literal.
    # The stored value is "GOOGLE"; a string comparison against "google" reads
    # as FALLBACK however the dashboard is set, which is how this first shipped
    # -- it printed 'provider "GOOGLE"' and called it the free map in the same
    # line.
    provider = getattr(row, 'provider', None) or MapSettings.Provider.FREE

    if provider == MapSettings.Provider.GOOGLE:
        if not getattr(row, 'google_api_key', ''):
            return Result(
                'Maps', BROKEN,
                'the dashboard selects Google, but no API key is saved',
                instead='maps and address lookup fail until a key is entered, '
                        'or the provider is set back to the free map',
            )
        return Result('Maps', LIVE, 'Google maps and geocoding')

    return Result(
        'Maps', FALLBACK, f'provider "{provider}"',
        instead='the free map is used -- it works, needs no card, and is not a '
                'missing key. Switch in the dashboard if ever wanted',
    )


def check_legal(offline):
    if settings.LEGAL_HAS_PLACEHOLDERS:
        return Result(
            'Legal pages', BROKEN,
            'contact email, address or date is blank',
            instead='the pages show a "not finished" banner',
            fatal_in_production=True,
        )
    return Result('Legal pages', LIVE,
                  f'/privacy/, /terms/, /data-deletion/ -- {settings.LEGAL_CONTACT_EMAIL}')


CHECKS = [
    check_database, check_cloudinary, check_push, check_razorpay,
    check_payouts, check_sms, check_email, check_maps, check_legal,
]


class Command(BaseCommand):
    help = 'Report which outside services are live, and which are falling back.'

    def add_arguments(self, parser):
        parser.add_argument('--offline', action='store_true',
                            help='Skip every network call; report configuration only.')
        parser.add_argument('--production', action='store_true',
                            help='Judge as if DEBUG=False, whatever this server '
                                 'is set to. Use to check a deploy before it goes live.')

    def handle(self, *args, **options):
        offline = options['offline']
        strict = options['production'] or not settings.DEBUG

        results = []
        for check in CHECKS:
            try:
                results.append(check(offline))
            except Exception as exc:
                results.append(Result(
                    check.__name__.replace('check_', '').title(), BROKEN,
                    f'the check itself failed: {type(exc).__name__}: {exc}'[:160]))

        width = max(len(r.name) for r in results) + 2
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Outside services' + ('  [judged as production]' if strict else '')
        ))
        self.stdout.write('')

        problems = 0
        for r in results:
            fatal = r.state == BROKEN or (strict and r.state == FALLBACK
                                          and r.fatal_in_production)
            if fatal:
                problems += 1

            style = (self.style.ERROR if fatal
                     else self.style.SUCCESS if r.state == LIVE
                     else self.style.WARNING)
            label = 'PROBLEM' if fatal and r.state == FALLBACK else r.state
            self.stdout.write(
                f'  {r.name.ljust(width)}{style(label.ljust(9))} {r.detail}'
            )
            if r.instead:
                self.stdout.write(f'  {"".ljust(width)}{"".ljust(9)} -> {r.instead}')
            for note in r.notes:
                self.stdout.write(f'  {"".ljust(width)}{"".ljust(9)} - {note}')

        self.stdout.write('')
        live = sum(1 for r in results if r.state == LIVE)
        self.stdout.write(f'  {live} live, {len(results) - live} not -- {problems} need attention')

        if problems:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                'Something above would fail for a real user.'
                if strict else
                'Something configured is not working.'
            ))
            # Non-zero so this can end a deploy script.
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS('  Nothing needs attention.'))
