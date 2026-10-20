"""
The engine's own behaviour: matching, intent selection, the answer book.

These run without a request. Anything that needs the API lives in
`tests_api.py`, and the customer intents' wording lives in
`tests_customer.py`.
"""

from django.test import TestCase

from . import matching
from .intents.base import Intent, Reply
from .models import AssistantSettings, KnowledgeEntry, Message


class NormalisingTests(TestCase):

    def test_punctuation_becomes_a_word_break(self):
        self.assertEqual(
            matching.normalise('Booking/payment -- where?!'),
            'booking payment where',
        )

    def test_keywords_drop_stopwords_and_single_letters(self):
        self.assertEqual(
            matching.keywords('where is my booking'), {'booking'},
        )

    def test_rupee_sign_survives(self):
        """Prices are asked about in ₹, so it must not be stripped."""
        self.assertIn('₹500', matching.normalise('is it ₹500?'))


class ContainsTests(TestCase):

    def test_matches_whole_words_only(self):
        self.assertTrue(matching.contains('paid by card', 'card'))
        self.assertFalse(matching.contains('paid by card', 'car'))

    def test_tolerates_a_plural(self):
        self.assertTrue(matching.contains('show my bookings', 'booking'))
        self.assertTrue(matching.contains('show my booking', 'booking'))

    def test_multi_word_phrase_needs_the_words_adjacent(self):
        self.assertTrue(matching.contains('what is the price of this', 'price of'))
        self.assertFalse(matching.contains('price was fair of course', 'price of'))

    def test_an_empty_trigger_never_matches(self):
        self.assertFalse(matching.contains('anything at all', ''))


class TriggerScoreTests(TestCase):

    def test_a_tuple_trigger_needs_every_part(self):
        self.assertTrue(matching.trigger_score('cancel my booking', ('cancel', 'booking')))
        self.assertFalse(matching.trigger_score('cancel this', ('cancel', 'booking')))

    def test_a_longer_trigger_scores_higher(self):
        question = 'what is my booking status'
        self.assertGreater(
            matching.trigger_score(question, 'booking status'),
            matching.trigger_score(question, 'booking'),
        )


class IntentSelectionTests(TestCase):
    """
    The engine must pick the most specific intent, not the first one that
    matched -- that is what keeps "cancel my booking" out of booking_status.
    """

    def _pick(self, question, intents):
        from . import rules

        catalogue = tuple(
            Intent(name, triggers, lambda ctx: Reply(text=''))
            for name, triggers in intents
        )
        chosen = rules.select(question, catalogue)
        return chosen.name if chosen else None

    def test_the_more_specific_trigger_wins(self):
        picked = self._pick('can I cancel my booking', [
            ('booking_status', (('where', 'booking'), ('status', 'booking'))),
            ('cancel_booking', (('cancel', 'booking'),)),
        ])
        self.assertEqual(picked, 'cancel_booking')

    def test_nothing_matching_picks_nothing(self):
        self.assertIsNone(self._pick('tell me a joke', [
            ('cancel_booking', (('cancel', 'booking'),)),
        ]))

    def test_declaration_order_breaks_a_tie(self):
        picked = self._pick('booking', [
            ('first', ('booking',)),
            ('second', ('booking',)),
        ])
        self.assertEqual(picked, 'first')

    def test_the_real_catalogue_routes_the_obvious_questions(self):
        """A smoke test over the shipped triggers, not a made-up catalogue."""
        from . import rules
        from .intents import for_audience

        expected = {
            'where is my booking': 'booking_status',
            'show me my bookings': 'booking_list',
            'can I cancel my booking': 'cancel_booking',
            'I want to reschedule': 'reschedule_booking',
            'did my payment go through': 'payment_status',
            'I want a refund': 'refund',
            'how much is deep cleaning': 'price_query',
            'what services do you offer': 'service_list',
            'how many bids on my project': 'tender_status',
            'what is the confirmation fee': 'tender_fee',
            'let me talk to a human': 'talk_to_human',
            'who is coming to my house': 'vendor_details',
        }
        catalogue = for_audience('CUSTOMER')
        for question, intent_name in expected.items():
            with self.subTest(question=question):
                chosen = rules.select(question, catalogue)
                self.assertIsNotNone(chosen, f'nothing matched {question!r}')
                self.assertEqual(chosen.name, intent_name)


class AnswerBookTests(TestCase):

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        KnowledgeEntry.objects.all().delete()

    def _ask(self, question, audience='CUSTOMER'):
        from . import engine

        return engine.ask(question, audience=audience, user=None,
                          settings_row=self.settings)

    def test_a_matching_entry_is_quoted_verbatim(self):
        KnowledgeEntry.objects.create(
            question='Do you work on Sundays?',
            keywords='sunday,weekend,holiday',
            answer='Yes, Sundays are a normal working day for us.',
        )
        answer = self._ask('do you work on sunday')
        self.assertEqual(answer.text, 'Yes, Sundays are a normal working day for us.')
        self.assertTrue(answer.intent.startswith('knowledge:'))
        self.assertFalse(answer.escalate)

    def test_keywords_find_an_entry_the_question_does_not_name(self):
        KnowledgeEntry.objects.create(
            question='Do you work on Sundays?',
            keywords='weekend',
            answer='Yes, weekends are fine.',
        )
        self.assertEqual(self._ask('are you open at the weekend').text,
                         'Yes, weekends are fine.')

    def test_an_inactive_entry_is_never_given(self):
        """
        A draft policy must not reach a customer.

        The cancellation intent fires here -- so this also checks the policy
        handler's contract: with no entry to quote it refuses to answer and
        offers a human, rather than quoting the draft or improvising terms.
        """
        KnowledgeEntry.objects.create(
            question='What is the cancellation policy?',
            keywords='cancellation',
            answer='NOT WRITTEN YET.',
            is_active=False,
        )
        answer = self._ask('what is the cancellation policy')
        self.assertNotIn('NOT WRITTEN YET', answer.text)
        self.assertTrue(answer.escalate)

    def test_an_entry_for_the_other_audience_is_never_given(self):
        KnowledgeEntry.objects.create(
            question='When is my payout released?',
            keywords='payout',
            answer='Payouts go out on Fridays.',
            audience=KnowledgeEntry.Audience.VENDOR,
        )
        answer = self._ask('when is my payout released', audience='CUSTOMER')
        self.assertNotIn('Fridays', answer.text)

    def test_a_dead_end_offers_the_near_misses(self):
        KnowledgeEntry.objects.create(
            question='How do I change the address on my profile?',
            keywords='address,location,move',
            answer='Edit it on the profile screen.',
        )
        # Shares one keyword of three with the entry: relevant enough to
        # offer as a question, not enough to answer with.
        answer = self._ask('is my address visible to other people')
        self.assertEqual(answer.intent, Message.FALLBACK_INTENT)
        self.assertIn(
            'How do I change the address on my profile?', answer.suggestions,
        )
        self.assertTrue(answer.escalate)

    def test_a_dead_end_uses_the_admin_s_own_wording(self):
        self.settings.fallback_message = 'No idea, sorry.'
        self.settings.save()
        self.assertEqual(self._ask('xyzzy plugh').text, 'No idea, sorry.')


class SettingsTests(TestCase):

    def test_get_solo_always_returns_the_same_row(self):
        first = AssistantSettings.get_solo()
        self.assertEqual(AssistantSettings.get_solo().pk, first.pk)

    def test_claude_without_a_key_reads_back_as_the_rules_engine(self):
        row = AssistantSettings.get_solo()
        row.engine = AssistantSettings.Engine.CLAUDE
        row.save()
        self.assertEqual(row.effective_engine, AssistantSettings.Engine.RULES)
        self.assertTrue(row.is_awaiting_key)

    def test_claude_with_a_key_still_falls_back_while_unimplemented(self):
        """
        The Claude engine is designed for but not written. Until it is, a
        fully configured Claude setting must answer rather than crash.
        """
        from . import engine

        row = AssistantSettings.get_solo()
        row.engine = AssistantSettings.Engine.CLAUDE
        row.claude_api_key = 'sk-ant-not-a-real-key'
        row.save()

        self.assertEqual(row.effective_engine, AssistantSettings.Engine.CLAUDE)
        used, _callable = engine.resolve_engine(row)
        self.assertEqual(used, AssistantSettings.Engine.RULES)

    def test_each_audience_has_its_own_switch(self):
        row = AssistantSettings.get_solo()
        row.vendor_enabled = False
        row.save()
        self.assertTrue(row.enabled_for('CUSTOMER'))
        self.assertFalse(row.enabled_for('VENDOR'))
