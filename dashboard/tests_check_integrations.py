"""
The point of check_integrations is the difference between "not configured"
and "configured but not working". These tests are about that distinction, and
about the escalation that happens once DEBUG is off -- an OTP printing to a
terminal is fine on a laptop and means nobody can sign in on a server.

Almost everything runs with --offline: a test suite must not call Cloudinary,
Firebase or Razorpay. The two maps tests that need probing on mock Google and
blank every other service first, so the suite still touches no network.
"""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from maps.models import MapSettings


def run(offline=True, **opts):
    """Returns (output, exit_code). The command exits non-zero on a problem."""
    out = StringIO()
    code = 0
    try:
        call_command('check_integrations', offline=offline, stdout=out, **opts)
    except SystemExit as exc:
        code = exc.code
    return out.getvalue(), code


# settings_test inherits the developer's real .env, so a check running with
# offline=False would call Cloudinary and open an SMTP socket for real. Only
# the maps tests need probing on; these leave every other service with nothing
# to reach, so the suite still touches no network.
NO_OTHER_NETWORK = override_settings(
    USE_CLOUDINARY=False,
    CLOUDINARY_CLOUD_NAME='', CLOUDINARY_API_KEY='', CLOUDINARY_API_SECRET='',
    RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='',
    RAZORPAYX_KEY_ID='', RAZORPAYX_KEY_SECRET='', RAZORPAYX_ACCOUNT_NUMBER='',
    FCM_ENABLED=False,
    SMS_BACKEND='console',
    EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
)


class StateClassificationTests(TestCase):
    """Absent, working, and broken must not look the same."""

    @override_settings(SMS_BACKEND='console')
    def test_console_sms_is_a_fallback_and_says_what_happens_instead(self):
        out, _ = run()
        self.assertIn('SMS (login codes)', out)
        self.assertIn('FALLBACK', out)
        self.assertIn('sent to nobody', out)

    @override_settings(SMS_BACKEND='fast2sms', FAST2SMS_API_KEY='')
    def test_a_named_provider_with_no_key_is_broken_not_a_fallback(self):
        """
        Asking for real SMS and leaving the key blank is a mistake, not a
        choice -- it must not be reported the same way as choosing console.
        """
        out, code = run()
        self.assertIn('BROKEN', out)
        self.assertIn('FAST2SMS_API_KEY', out)
        self.assertEqual(code, 1)

    @override_settings(SMS_BACKEND='nonsense')
    def test_an_unknown_sms_backend_is_reported_rather_than_ignored(self):
        out, code = run()
        self.assertIn('BROKEN', out)
        self.assertEqual(code, 1)

    @override_settings(LEGAL_HAS_PLACEHOLDERS=True)
    def test_unfinished_legal_pages_are_broken(self):
        out, code = run()
        self.assertIn('Legal pages', out)
        self.assertIn('BROKEN', out)
        self.assertEqual(code, 1)


class MapsProviderTests(TestCase):
    """
    The provider is stored as "GOOGLE"; comparing it to "google" reported the
    free map however the dashboard was set. That shipped once.
    """

    def test_google_selected_without_a_key_is_broken(self):
        MapSettings.objects.create(
            provider=MapSettings.Provider.GOOGLE, google_api_key='',
        )
        out, code = run()
        self.assertIn('BROKEN', out)
        self.assertIn('no API key', out)
        self.assertEqual(code, 1)

    def test_google_selected_with_a_key_is_live(self):
        """Offline, a saved key is as far as the check can go."""
        MapSettings.objects.create(
            provider=MapSettings.Provider.GOOGLE, google_api_key='AIza-test',
        )
        out, _ = run()
        self.assertRegex(out, r'Maps\s+LIVE')
        self.assertIn('not checked', out)

    @NO_OTHER_NETWORK
    def test_a_key_google_refuses_is_broken_not_live(self):
        """
        A saved key is not an accepted key. Google refuses one whose project
        has no billing, or with the APIs switched off, and refuses it at
        request time -- nothing about the stored value shows it.

        This shipped reporting LIVE on presence alone, while every map in the
        customer app was quietly drawing the free basemap. Nothing looked
        broken, which is the whole reason this command exists.
        """
        MapSettings.objects.create(
            provider=MapSettings.Provider.GOOGLE, google_api_key='AIza-refused',
        )
        refusal = [
            {'name': 'Map Tiles API', 'ok': False, 'detail': 'blocked'},
            {'name': 'Geocoding API', 'ok': False, 'detail': 'not authorized'},
        ]
        with mock.patch('maps.google.check_key', return_value=refusal):
            out, code = run(offline=False)

        self.assertIn('BROKEN', out)
        self.assertIn('not authorized', out)
        self.assertEqual(code, 1)

    @NO_OTHER_NETWORK
    @override_settings(DEBUG=True)
    def test_a_key_google_accepts_is_live(self):
        # DEBUG=True so the other services, left unconfigured above, stay
        # tolerated fallbacks. Otherwise the exit code would be 1 for reasons
        # that have nothing to do with maps.
        MapSettings.objects.create(
            provider=MapSettings.Provider.GOOGLE, google_api_key='AIza-good',
        )
        accepted = [
            {'name': 'Map Tiles API', 'ok': True, 'detail': 'fine'},
            {'name': 'Geocoding API', 'ok': True, 'detail': 'fine'},
        ]
        with mock.patch('maps.google.check_key', return_value=accepted):
            out, code = run(offline=False)

        self.assertRegex(out, r'Maps\s+LIVE')
        self.assertIn('key accepted', out)
        self.assertEqual(code, 0)

    def test_free_map_is_a_fallback_that_is_not_a_problem(self):
        MapSettings.objects.create(provider=MapSettings.Provider.FREE)
        out, _ = run()
        self.assertRegex(out, r'Maps\s+FALLBACK')
        self.assertIn('needs no card', out)


@override_settings(
    SMS_BACKEND='console',
    EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
)
class ProductionEscalationTests(TestCase):
    """A dev fallback is a production outage."""

    @override_settings(DEBUG=True)
    def test_fallbacks_are_tolerated_off_production(self):
        """
        DEBUG=True stands in for a developer's laptop. Django forces DEBUG off
        during tests, so without this override the command judges strictly --
        which is correct behaviour for a server and wrong for this assertion.
        """
        _, code = run()
        self.assertEqual(code, 0, 'console SMS must not fail a dev check')

    def test_the_same_fallbacks_fail_in_production(self):
        out, code = run(production=True)
        self.assertEqual(code, 1)
        self.assertIn('PROBLEM', out)
        self.assertIn('would fail for a real user', out)

    def test_a_harmless_fallback_does_not_fail_production(self):
        """
        Manual vendor payouts are the intended way to start, so RazorpayX
        being off must never be escalated -- only things that stop a real
        customer using the app.
        """
        out, _ = run(production=True)
        payout_line = next(
            line for line in out.splitlines() if 'RazorpayX' in line
        )
        self.assertIn('FALLBACK', payout_line)
        self.assertNotIn('PROBLEM', payout_line)


class OutputTests(TestCase):
    def test_output_is_ascii_only(self):
        """
        Printed on a Windows console (cp1252) and on the Linux server. An
        arrow or a middle dot crashes the first with UnicodeEncodeError, which
        is how this first failed.
        """
        out, _ = run()
        out.encode('ascii')  # raises if anything non-ASCII crept back in

    def test_every_service_appears(self):
        out, _ = run()
        for name in ('Database', 'Cloudinary', 'Push notifications',
                     'Razorpay', 'SMS', 'Email', 'Maps', 'Legal pages'):
            with self.subTest(service=name):
                self.assertIn(name, out)

    def test_offline_reports_that_it_did_not_probe(self):
        out, _ = run()
        self.assertIn('--offline', out)
