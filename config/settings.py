from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
import os
import sys

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# Read first, because it decides how strict everything below is allowed to
# be. Defaulting to False means a server that never received a .env fails
# closed: with debug on, any error page prints the database password, the
# API keys and the full source paths to whoever triggered it.
DEBUG = config('DEBUG', default=False, cast=bool)

# No usable default on purpose. A key committed to source is a key anyone who
# can read the repository can use to forge a signed-in session. Local
# development gets a throwaway; production supplies a real one or refuses to
# start, which is far better than starting insecurely and looking fine.
SECRET_KEY = config('SECRET_KEY', default='')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-local-development-only-never-deploy'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY is not set. Generate one by running: python -c '
            '"from django.core.management.utils import get_random_secret_key; '
            'print(get_random_secret_key())" -- then add it to the .env file '
            'on this server.'
        )

# Comma-separated bare hostnames -- no brackets, no quotes. This is split as
# plain text, so ALLOWED_HOSTS=["*"] does not mean "any host", it creates one
# host literally named '["*"]' and every real request is then rejected.
ALLOWED_HOSTS = [
    h.strip() for h in config('ALLOWED_HOSTS', default='').split(',') if h.strip()
]
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
    else:
        raise ImproperlyConfigured(
            "ALLOWED_HOSTS is not set. Add this server's domain to its .env, "
            "e.g. ALLOWED_HOSTS=api.example.com,example.com"
        )

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    # Media (images/video) is served from Cloudinary's CDN, not from this
    # server. Listed after staticfiles because only media is delegated --
    # static files stay with whitenoise.
    'cloudinary',
    'cloudinary_storage',

    # our apps
    'accounts',
    'vendors',
    'customers',
    'services',
    'bookings',
    'payments',
    'promotions',
    'home_sections',
    'curations',
    'service_forms',
    'legal',
    'reviews',
    'discounts',
    'dashboard',
    'support',
    'notifications',
    'referrals',
    'branding',
    'tenders',
    'subscriptions',
    'maps',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
     'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# --- CORS: which websites may call this API from a browser ---
# Only the web build is affected. The Android and iOS apps are not browsers,
# send no Origin header, and are not subject to CORS at all -- so tightening
# this cannot break them. Left open, any site on the internet could make
# authenticated calls using a logged-in visitor's browser.
CORS_ALLOWED_ORIGINS = [
    o.strip().rstrip('/')
    for o in config('CORS_ALLOWED_ORIGINS', default='').split(',')
    if o.strip()
]
CORS_ALLOW_ALL_ORIGINS = config('CORS_ALLOW_ALL_ORIGINS', default=DEBUG, cast=bool)

if not DEBUG and not CORS_ALLOW_ALL_ORIGINS and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        'CORS_ALLOWED_ORIGINS is empty, so the customer web view would be '
        'blocked from calling this API. Set it in .env, e.g. '
        'CORS_ALLOWED_ORIGINS=https://example.com,https://www.example.com'
    )

# Separate from CORS and just as necessary. The dashboard posts forms over
# https from behind nginx; Django checks the Origin header of every POST
# against this list, so without the domain here each admin save fails with a
# CSRF error. Entries must include the scheme.
CSRF_TRUSTED_ORIGINS = [
    o.strip().rstrip('/')
    for o in config('CSRF_TRUSTED_ORIGINS', default='').split(',')
    if o.strip()
]

# --- Custom user model (defined in accounts app) ---
AUTH_USER_MODEL = 'accounts.User'

# --- Django REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
}
# --- OTP / SMS settings ---
# SMS_BACKEND: 'console' (free, dev only, prints OTP to terminal) or
# 'fast2sms' / 'msg91' / 'twilio' for real SMS. See accounts/sms.py.

# ---------- Dashboard sign-in security ----------
# Sessions are only used by the admin dashboard and Django's own admin site;
# the mobile apps authenticate with JWTs and are unaffected by any of this.

# A signed-in dashboard session lasts a working day, then asks again.
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=12 * 60 * 60, cast=int)
SESSION_SAVE_EVERY_REQUEST = True  # the day is measured from last activity

# Behind a proxy (Render, nginx) every request arrives from the load balancer,
# so the per-IP part of the lockout would see one address for the whole world
# and lock everyone out at once. The header is client-supplied and therefore
# spoofable, which only lets an attacker dodge the IP counter -- never the
# per-username one. Set to False when the app is exposed directly.
ADMIN_LOGIN_TRUST_PROXY_HEADER = config(
    'ADMIN_LOGIN_TRUST_PROXY_HEADER', default=True, cast=bool
)

# Cookies carrying a signed-in session must not travel in the clear. Off in
# DEBUG so local development over plain http still works.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ---------- HTTPS ----------
# nginx terminates TLS and forwards to gunicorn over plain http, so without
# this Django believes every request arrived insecurely: it refuses to set the
# secure cookies above (nobody can sign in to the dashboard) and, with the
# redirect below on, bounces the browser to https forever. nginx must actually
# send the header -- proxy_set_header X-Forwarded-Proto $scheme.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)

# HSTS tells a browser to refuse plain http for this domain for this many
# seconds, and it cannot be withdrawn early: a browser that once saw a
# one-year header honours it for a year even after the header stops. So it
# starts at 0 and is raised deliberately once https is proven on the real
# domain -- 300, then 86400, then 31536000.
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    'SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)

SMS_BACKEND = config('SMS_BACKEND', default='console')
OTP_EXPIRY_MINUTES = config('OTP_EXPIRY_MINUTES', default=5, cast=int)
OTP_RESEND_COOLDOWN_SECONDS = config('OTP_RESEND_COOLDOWN_SECONDS', default=60, cast=int)

FAST2SMS_API_KEY = config('FAST2SMS_API_KEY', default='')
MSG91_AUTH_KEY = config('MSG91_AUTH_KEY', default='')
MSG91_SENDER_ID = config('MSG91_SENDER_ID', default='')
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER = config('TWILIO_FROM_NUMBER', default='')

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Puts the signed-in dashboard user and their permission set
                # into every template, so the sidebar can hide what a role
                # cannot open.
                'dashboard.context_processors.admin_user',
                # Which map the dashboard's map pages should draw, and the
                # Google key when Google is the one chosen.
                'dashboard.context_processors.map_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='homeservice_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Database

# Read through decouple, not os.environ: decouple checks real environment
# variables first (how Render supplies this) and falls back to the .env file
# (how local dev supplies it). os.environ alone can't see .env, which silently
# yields an unconfigured dummy backend.
# DATABASE_URL = config('DATABASE_URL', default='')

# if not DATABASE_URL:
#     raise ImproperlyConfigured(
#         "DATABASE_URL is not set. Add it to your .env file for local "
#         "development, or to the environment on the server."
#     )

# DATABASES = {
#     "default": dj_database_url.config(
#         default=DATABASE_URL,
#         conn_max_age=600,
#         # Managed Postgres requires SSL; a local sqlite:// URL rejects the flag.
#         ssl_require=DATABASE_URL.startswith("postgres"),
#     )
# }

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

# USE_TZ is on, so every datetime is stored in the database in UTC whatever
# this says -- changing it converts how times are read and displayed, not what
# is stored, and needs no migration. It does change what "today" means in
# every dashboard filter and report, which is why it belongs before real
# bookings exist rather than after.
TIME_ZONE = config('TIME_ZONE', default='Asia/Kolkata')

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

# STATIC_URL = 'static/'
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (vendor documents, job-start photos)
# Kept for the local-disk fallback below, and because config/urls.py serves
# MEDIA_URL while DEBUG is on.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Vendor ID documents are served by dashboard.views.vendor_document_view, which
# checks the admin's permission first. On nginx the view can hand the file over
# via X-Accel-Redirect so Python never streams the bytes; the prefix below must
# match the `internal` location in deploy/nginx.conf.
#
# Default off. Turning it on without that nginx block gives a blank response;
# leaving it off merely means Django reads the file itself. Slower, never wrong.
MEDIA_X_ACCEL_REDIRECT = config('MEDIA_X_ACCEL_REDIRECT', default=False, cast=bool)
MEDIA_X_ACCEL_PREFIX = config('MEDIA_X_ACCEL_PREFIX', default='/protected-media/')


# ---------- Public legal pages ----------
# Company details for /privacy/, /terms/ and /data-deletion/. Kept in
# configuration rather than the templates so the client's real address and
# support address are set once at deploy time, not by editing and redeploying.
#
# Google Play checks the privacy policy URL, and its account-deletion policy
# requires a public page describing how to request deletion.
LEGAL_COMPANY_NAME = config('LEGAL_COMPANY_NAME', default='RNI Services')
LEGAL_CONTACT_EMAIL = config('LEGAL_CONTACT_EMAIL', default='')
LEGAL_CONTACT_PHONE = config('LEGAL_CONTACT_PHONE', default='')
LEGAL_ADDRESS = config('LEGAL_ADDRESS', default='')
LEGAL_LAST_UPDATED = config('LEGAL_LAST_UPDATED', default='')

# A policy that still says "[your email]" is worse than no policy: Play reads
# it, and a customer exercising a data right has nowhere to write. The pages
# render a visible banner while anything is unset, so this cannot be missed by
# a reviewer or by us.
LEGAL_HAS_PLACEHOLDERS = not all([
    LEGAL_CONTACT_EMAIL, LEGAL_ADDRESS, LEGAL_LAST_UPDATED,
])

# ---------- Cloudinary (image & video CDN) ----------
# Uploads go to Cloudinary instead of this server's disk, and are delivered
# from a CDN. That removes two problems at once: Python is no longer the thing
# streaming a 100 MB video to a phone, and an admin who uploads a 2 MB PNG as a
# category icon no longer ships 2 MB to every user -- it is re-encoded on
# delivery instead (see config/storages.py).
CLOUDINARY_CLOUD_NAME = config('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY = config('CLOUDINARY_API_KEY', default='')
CLOUDINARY_API_SECRET = config('CLOUDINARY_API_SECRET', default='')

# The test suite uploads real files in several places. Pointed at Cloudinary
# those uploads would cross the network on every run -- slow, flaky offline,
# and each run would leave test junk in the live account and burn credits.
# Tests therefore always use local disk, whatever .env says.
_RUNNING_TESTS = 'test' in sys.argv

# Empty cloud name = not configured yet. Falling back to local disk rather
# than erroring keeps offline work and a fresh clone runnable.
USE_CLOUDINARY = bool(
    CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET
) and not _RUNNING_TESTS

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
    'API_KEY': CLOUDINARY_API_KEY,
    'API_SECRET': CLOUDINARY_API_SECRET,
    # Tags every upload made by this project, so orphaned files can be found
    # and cleaned up later without touching anything uploaded by hand.
    'MEDIA_TAG': 'home_service_media',
}

# Images are the default because they are the overwhelming majority of fields.
# Video and vendor documents opt out per field, via FileField(storage=...) --
# Cloudinary cannot serve a video that was uploaded as an image.
if USE_CLOUDINARY:
    _DEFAULT_FILE_STORAGE = 'config.storages.OptimizedImageCloudinaryStorage'
else:
    _DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Django 5.1 removed DEFAULT_FILE_STORAGE and STATICFILES_STORAGE; both are now
# keys in STORAGES. The old STATICFILES_STORAGE line that used to live here was
# being silently ignored, so whitenoise's compression was never actually on.
# Manifest storage is only safe once collectstatic has written the manifest,
# which is a deploy step -- under DEBUG there is none, so it stays off there.
STORAGES = {
    'default': {
        'BACKEND': _DEFAULT_FILE_STORAGE,
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------- Email / OTP delivery ----------
# The backend used to be hard-coded to 'console', which only prints the OTP
# to the server's terminal. Nobody reads a terminal on a VPS, so every login
# silently became impossible the moment this was deployed. It now follows
# DEBUG: printed while developing, actually sent in production.
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default=(
        'django.core.mail.backends.console.EmailBackend'
        if DEBUG
        else 'django.core.mail.backends.smtp.EmailBackend'
    ),
)

EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)

# python-decouple does not strip trailing '# comments' from a .env value, so
# `EMAIL_HOST_USER = me@gmail.com  # my address` is read complete with the
# comment and every send fails on an unparseable sender. Trimmed here so a
# stray comment costs nothing.
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='').split('#')[0].strip()
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='').split('#')[0].strip()

EMAIL_TIMEOUT = 10

DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# Failing at startup beats discovering it when the first customer cannot log
# in: SMTP selected with no credentials cannot deliver a single OTP.
if EMAIL_BACKEND.endswith('smtp.EmailBackend') and not (
    EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
):
    raise ImproperlyConfigured(
        'EMAIL_BACKEND is set to SMTP but EMAIL_HOST_USER / '
        'EMAIL_HOST_PASSWORD are missing from .env, so no OTP email could be '
        'sent and nobody would be able to sign in.'
    )


# ---------- Firebase Cloud Messaging ----------
# The project id belongs in configuration, not in source: moving to the
# company Firebase account should be a .env change on the server, not a code
# change that has to be committed, reviewed and redeployed.
FCM_ENABLED = config('FCM_ENABLED', default=True, cast=bool)
FCM_PROJECT_ID = config('FCM_PROJECT_ID', default='')

# A private key. It is deliberately absent from Git (see .gitignore) and has
# to be copied onto each server by hand. notifications/push.py checks the file
# exists before every send and records a readable reason if it does not, so a
# missing file degrades to "no push" rather than crashing a request.
FCM_CREDENTIALS_FILE = config(
    'FCM_CREDENTIALS_FILE',
    default=str(BASE_DIR / 'secrets' / 'fcm-service-account.json'),
)




# ---------- Razorpay ----------
# Money is captured into the platform's own Razorpay account, not the vendor's.
# That capture IS the hold: nothing reaches a vendor until a payout is made
# separately, so a booking can be refunded in full while work is disputed.
RAZORPAY_KEY_ID = config('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = config('RAZORPAY_KEY_SECRET', default='')

# Set in the Razorpay dashboard when creating the webhook. Without it the
# webhook endpoint refuses every delivery rather than trusting unsigned calls.
RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')

RAZORPAY_CURRENCY = config('RAZORPAY_CURRENCY', default='INR')

# Live keys are 'rzp_live_*'. Anything else is a sandbox that cannot move real
# money, which the dashboard shows so nobody mistakes test takings for revenue.
RAZORPAY_IS_LIVE = RAZORPAY_KEY_ID.startswith('rzp_live_')

# ---------- RazorpayX (payouts) ----------
# A separate product from the payment gateway above, with its own dashboard,
# its own credentials, and a virtual account that money is paid out FROM.
# Sharing the gateway keys works on some accounts, hence the fallback.
# `or` rather than a config default: an empty value in .env is how someone
# says "I have not set this up", and that must still fall back.
RAZORPAYX_KEY_ID = config('RAZORPAYX_KEY_ID', default='') or RAZORPAY_KEY_ID
RAZORPAYX_KEY_SECRET = (
    config('RAZORPAYX_KEY_SECRET', default='') or RAZORPAY_KEY_SECRET
)

# The RazorpayX virtual account payouts are debited from. Found on the X
# dashboard under Account Details. Nothing can be paid out without it, which
# is why it alone decides whether the feature is on.
RAZORPAYX_ACCOUNT_NUMBER = config('RAZORPAYX_ACCOUNT_NUMBER', default='')

# IMPS settles in minutes and is capped around 5 lakh; NEFT is the fallback
# for larger amounts. Both are chosen per payout, this is just the default.
RAZORPAYX_PAYOUT_MODE = config('RAZORPAYX_PAYOUT_MODE', default='IMPS')

# Rupees. Above this a payout goes NEFT instead of IMPS.
RAZORPAYX_IMPS_LIMIT = config('RAZORPAYX_IMPS_LIMIT', default=200000, cast=int)

# Off until an account number is configured, so nothing about the existing
# release flow changes until someone deliberately turns this on.
RAZORPAYX_ENABLED = bool(RAZORPAYX_ACCOUNT_NUMBER)

# Penny-drop validation costs a small fee per check. On by default because
# paying the wrong account costs considerably more.
RAZORPAYX_VALIDATE_ACCOUNTS = config(
    'RAZORPAYX_VALIDATE_ACCOUNTS', default=True, cast=bool
)

# How close the bank's registered name must be to what the vendor typed
# before the account is auto-verified. Below this an admin looks at it.
RAZORPAYX_NAME_MATCH_THRESHOLD = config(
    'RAZORPAYX_NAME_MATCH_THRESHOLD', default=0.85, cast=float
)
