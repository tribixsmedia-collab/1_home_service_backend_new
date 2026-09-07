"""
The legal pages exist for people who are not signed in.

A Google Play reviewer opens the privacy policy and the data-deletion URL from
a signed-out browser. If either needs a login, or 500s because a setting is
absent, the listing is refused -- so the point of these tests is that the pages
render for an anonymous visitor on a server with nothing configured.
"""

from django.test import TestCase, override_settings
from django.urls import reverse


class PublicReachabilityTests(TestCase):
    """No authentication, on a bare configuration."""

    def test_every_legal_page_is_reachable_signed_out(self):
        for name in ('privacy_policy', 'terms_of_service', 'data_deletion'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_pages_render_with_no_company_details_configured(self):
        """
        The client will not have an address or support email on the day this
        first deploys. Missing details must degrade to a visible warning, not
        a template crash.
        """
        with override_settings(
            LEGAL_CONTACT_EMAIL='', LEGAL_ADDRESS='', LEGAL_LAST_UPDATED='',
            LEGAL_HAS_PLACEHOLDERS=True,
        ):
            body = self.client.get(reverse('privacy_policy')).content.decode()
        self.assertIn('not finished', body)

    def test_no_placeholder_warning_once_details_are_set(self):
        with override_settings(
            LEGAL_CONTACT_EMAIL='hello@example.com',
            LEGAL_ADDRESS='1 Example Street, Chennai',
            LEGAL_LAST_UPDATED='7 September 2026',
            LEGAL_HAS_PLACEHOLDERS=False,
        ):
            body = self.client.get(reverse('privacy_policy')).content.decode()
        self.assertNotIn('not finished', body)
        self.assertIn('hello@example.com', body)


class NoLeakedSourceTests(TestCase):
    """
    Template comments must not reach the reader.

    Django's {# #} is single-line only: written across several lines it prints
    its contents above the doctype. This shipped that way once -- an internal
    note about lawyers and Play reviewers rendered at the top of the live
    privacy policy.
    """

    def test_maintainer_notes_are_not_in_the_output(self):
        for name in ('privacy_policy', 'terms_of_service', 'data_deletion'):
            body = self.client.get(reverse(name)).content.decode()
            with self.subTest(page=name):
                self.assertNotIn('NOTE FOR WHOEVER MAINTAINS THIS', body)
                self.assertNotIn('reviewed by a lawyer', body)
                self.assertNotIn('Play reviewer', body)

    def test_document_starts_at_the_doctype(self):
        body = self.client.get(reverse('privacy_policy')).content.decode()
        self.assertTrue(
            body.lstrip().lower().startswith('<!doctype html>'),
            'Something is being emitted before the doctype: ' + body[:120],
        )


class PlayRequirementsTests(TestCase):
    """The specific things a store listing is checked against."""

    def test_privacy_policy_links_to_the_deletion_page(self):
        """Play wants the deletion route discoverable from the policy."""
        body = self.client.get(reverse('privacy_policy')).content.decode()
        self.assertIn(reverse('data_deletion'), body)

    def test_deletion_page_says_what_is_kept_and_for_how_long(self):
        """
        A deletion page that promises to erase everything would be untrue --
        booking and tax records are retained. Saying so is the requirement.
        """
        body = self.client.get(reverse('data_deletion')).content.decode().lower()
        self.assertIn('30 days', body)
        self.assertIn('tax', body)

    def test_policy_names_the_processors_that_receive_data(self):
        body = self.client.get(reverse('privacy_policy')).content.decode()
        for processor in ('Razorpay', 'Cloudinary', 'Firebase'):
            with self.subTest(processor=processor):
                self.assertIn(processor, body)


@override_settings(SECURE_SSL_REDIRECT=False)
class UrlShapeTests(TestCase):
    """The URLs go in a store listing and should not move afterwards."""

    def test_urls_are_the_expected_paths(self):
        self.assertEqual(reverse('privacy_policy'), '/privacy/')
        self.assertEqual(reverse('terms_of_service'), '/terms/')
        self.assertEqual(reverse('data_deletion'), '/data-deletion/')
