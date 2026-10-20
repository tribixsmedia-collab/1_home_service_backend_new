"""
The dashboard's assistant pages.

Three things worth a test here: the pages render, the two permissions really
split reading from writing, and the answer-book form saves the whole entry --
these forms post every field, so a half-posted form must not be able to blank
the rest of a live answer by accident.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assistant.models import (
    AssistantSettings, Conversation, KnowledgeEntry, Message,
)
from bookings.models import Booking
from customers.models import Customer
from services.models import ServiceCategory

from .testing import sign_in


class AssistantDashboardTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username='boss', password='pw', role=User.Role.ADMIN)
        sign_in(self.client, self.admin)

        customer_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER,
            first_name='Asha', last_name='Nair')
        self.customer = Customer.objects.create(user=customer_user)

        self.chat = Conversation.objects.create(
            audience=Conversation.Audience.CUSTOMER, customer=self.customer,
        )
        Message.objects.create(
            conversation=self.chat, role=Message.Role.USER,
            text='do you also sell cement',
        )
        Message.objects.create(
            conversation=self.chat, role=Message.Role.BOT,
            text="I'm not sure about that one.",
            intent=Message.FALLBACK_INTENT, engine='RULES',
        )

    # ------------------------------------------------------------- the list
    def test_the_chat_list_renders_with_the_unanswered_count(self):
        response = self.client.get(reverse('assistant_conversations'))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('Asha Nair', html)
        self.assertIn('1 unanswered', html)
        self.assertIn(
            reverse('assistant_conversation_detail', args=[self.chat.id]), html,
        )

    def test_the_unanswered_filter_narrows_to_the_failures(self):
        quiet = Conversation.objects.create(
            audience=Conversation.Audience.CUSTOMER, customer=self.customer,
        )
        Message.objects.create(
            conversation=quiet, role=Message.Role.BOT,
            text='Your booking is on its way.', intent='booking_status',
        )

        response = self.client.get(
            reverse('assistant_conversations'), {'state': 'unanswered'},
        )
        listed = [chat.id for chat in response.context['page_obj']]
        self.assertIn(self.chat.id, listed)
        self.assertNotIn(quiet.id, listed)

    def test_the_list_can_be_searched_by_what_was_asked(self):
        response = self.client.get(
            reverse('assistant_conversations'), {'q': 'cement'},
        )
        self.assertIn(self.chat.id, [c.id for c in response.context['page_obj']])

        response = self.client.get(
            reverse('assistant_conversations'), {'q': 'scaffolding'},
        )
        self.assertEqual(list(response.context['page_obj']), [])

    # ----------------------------------------------------------- transcript
    def test_the_transcript_shows_the_audit_trail(self):
        Message.objects.create(
            conversation=self.chat, role=Message.Role.BOT,
            text='Booking #3 is assigned.', intent='booking_status',
            engine='RULES', tool_calls=[{'name': 'customer_active_booking', 'args': {}}],
        )
        response = self.client.get(
            reverse('assistant_conversation_detail', args=[self.chat.id]),
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('do you also sell cement', html)
        self.assertIn('booking_status', html)
        self.assertIn('customer_active_booking', html)

    def test_the_transcript_links_the_answers_it_quoted(self):
        entry = KnowledgeEntry.objects.create(
            question='Do you work on Sundays?', answer='Yes we do.',
        )
        Message.objects.create(
            conversation=self.chat, role=Message.Role.BOT,
            text='Yes we do.', intent=f'knowledge:{entry.id}', engine='RULES',
        )
        response = self.client.get(
            reverse('assistant_conversation_detail', args=[self.chat.id]),
        )
        self.assertIn(entry, response.context['quoted_entries'])
        self.assertIn(
            reverse('assistant_knowledge_edit', args=[entry.id]),
            response.content.decode(),
        )

    # ---------------------------------------------------------- answer book
    def test_the_answer_book_lists_the_seeded_entries(self):
        response = self.client.get(reverse('assistant_knowledge_list'))
        self.assertEqual(response.status_code, 200)
        # Shipped by the seed migration, and switched on.
        self.assertIn('How do I book a service?', response.content.decode())

    def test_the_seeded_policy_drafts_ship_switched_off(self):
        """
        A migration must not author the business's cancellation terms.

        They ship off, so the assistant refuses the question until somebody
        writes the real wording.
        """
        draft = KnowledgeEntry.objects.get(
            question='What is your cancellation policy?',
        )
        self.assertFalse(draft.is_active)
        self.assertIn('NOT WRITTEN YET', draft.answer)

    def test_adding_an_answer(self):
        response = self.client.post(reverse('assistant_knowledge_add'), {
            'question': 'Do you work on Sundays?',
            'answer': 'Yes, Sundays are a normal working day.',
            'keywords': 'sunday, weekend',
            'audience': 'ALL',
            'sort_order': '10',
            'is_active': 'on',
        })
        self.assertRedirects(response, reverse('assistant_knowledge_list'))

        entry = KnowledgeEntry.objects.get(question='Do you work on Sundays?')
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.keyword_list, ['sunday', 'weekend'])

    def test_an_answer_with_no_text_is_refused(self):
        response = self.client.post(reverse('assistant_knowledge_add'), {
            'question': 'Do you work on Sundays?',
            'answer': '   ',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            KnowledgeEntry.objects.filter(
                question='Do you work on Sundays?',
            ).exists()
        )

    def test_editing_saves_the_whole_entry(self):
        entry = KnowledgeEntry.objects.create(
            question='Old question', answer='Old answer',
            keywords='old', sort_order=5, is_active=True,
        )
        self.client.post(reverse('assistant_knowledge_edit', args=[entry.id]), {
            'question': 'New question',
            'answer': 'New answer',
            'keywords': 'new, newer',
            'audience': 'CUSTOMER',
            'sort_order': '20',
            # is_active left out, which is what an unchecked box posts.
        })
        entry.refresh_from_db()
        self.assertEqual(entry.question, 'New question')
        self.assertEqual(entry.answer, 'New answer')
        self.assertEqual(entry.keywords, 'new, newer')
        self.assertEqual(entry.audience, 'CUSTOMER')
        self.assertEqual(entry.sort_order, 20)
        self.assertFalse(entry.is_active)

    def test_toggling_switches_an_answer_off_and_on(self):
        entry = KnowledgeEntry.objects.create(
            question='Q', answer='A', is_active=True,
        )
        self.client.post(reverse('assistant_knowledge_toggle', args=[entry.id]))
        entry.refresh_from_db()
        self.assertFalse(entry.is_active)

        self.client.post(reverse('assistant_knowledge_toggle', args=[entry.id]))
        entry.refresh_from_db()
        self.assertTrue(entry.is_active)

    def test_deleting_an_answer(self):
        entry = KnowledgeEntry.objects.create(question='Q', answer='A')
        self.client.post(reverse('assistant_knowledge_delete', args=[entry.id]))
        self.assertFalse(KnowledgeEntry.objects.filter(id=entry.id).exists())

    # --------------------------------------------------------------- settings
    def test_settings_render_and_save(self):
        response = self.client.post(reverse('assistant_settings'), {
            'engine': 'RULES',
            'customer_enabled': 'on',
            'daily_message_limit': '25',
            'monthly_token_cap': '0',
            'claude_model': 'claude-haiku-5-5',
            'greeting': 'Hello there.',
            'fallback_message': 'No idea.',
        })
        self.assertRedirects(response, reverse('assistant_settings'))

        settings_row = AssistantSettings.get_solo()
        self.assertTrue(settings_row.customer_enabled)
        # Unchecked boxes are absent from the POST, which means off.
        self.assertFalse(settings_row.vendor_enabled)
        self.assertFalse(settings_row.admin_enabled)
        self.assertEqual(settings_row.daily_message_limit, 25)
        self.assertEqual(settings_row.greeting, 'Hello there.')

    def test_a_nonsense_limit_falls_back_rather_than_crashing(self):
        self.client.post(reverse('assistant_settings'), {
            'engine': 'RULES',
            'daily_message_limit': 'lots',
            'monthly_token_cap': '-5',
            'greeting': 'Hi',
            'fallback_message': 'No',
        })
        settings_row = AssistantSettings.get_solo()
        self.assertEqual(settings_row.daily_message_limit, 50)
        self.assertEqual(settings_row.monthly_token_cap, 0)

    def test_choosing_claude_warns_that_it_is_not_built(self):
        response = self.client.post(reverse('assistant_settings'), {
            'engine': 'CLAUDE',
            'claude_api_key': 'sk-ant-whatever',
            'greeting': 'Hi',
            'fallback_message': 'No',
        }, follow=True)
        self.assertContains(response, 'not built yet')

    def test_choosing_claude_without_a_key_says_so(self):
        response = self.client.post(reverse('assistant_settings'), {
            'engine': 'CLAUDE',
            'claude_api_key': '',
            'greeting': 'Hi',
            'fallback_message': 'No',
        }, follow=True)
        self.assertContains(response, 'needs an API key')


class AssistantPermissionTests(TestCase):
    """`assistant.view` reads, `assistant.manage` writes, and not the reverse."""

    def setUp(self):
        self.reader = User.objects.create_user(
            username='reader', password='pw', role=User.Role.ADMIN)
        self.entry = KnowledgeEntry.objects.create(
            question='Q', answer='A', is_active=True,
        )

    def sign_in_with(self, *codes):
        sign_in(self.client, self.reader, permissions=list(codes))

    def test_a_reader_can_open_the_chats(self):
        self.sign_in_with('assistant.view')
        self.assertEqual(
            self.client.get(reverse('assistant_conversations')).status_code, 200,
        )

    def test_a_reader_cannot_edit_the_answer_book(self):
        self.sign_in_with('assistant.view')
        response = self.client.post(
            reverse('assistant_knowledge_edit', args=[self.entry.id]),
            {'question': 'Hijacked', 'answer': 'Hijacked'},
        )
        self.assertEqual(response.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.question, 'Q')

    def test_a_reader_cannot_switch_an_answer_off(self):
        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_knowledge_toggle', args=[self.entry.id]))
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_active)

    def test_a_reader_may_see_the_settings_but_not_change_them(self):
        self.sign_in_with('assistant.view')
        self.assertEqual(
            self.client.get(reverse('assistant_settings')).status_code, 200,
        )

        self.client.post(reverse('assistant_settings'), {
            'engine': 'RULES', 'greeting': 'Hijacked', 'fallback_message': 'x',
        })
        self.assertNotEqual(AssistantSettings.get_solo().greeting, 'Hijacked')

    def test_somebody_with_neither_permission_is_refused(self):
        self.sign_in_with('bookings.view')
        self.assertEqual(
            self.client.get(reverse('assistant_conversations')).status_code, 403,
        )

    def test_a_manager_can_write(self):
        self.sign_in_with('assistant.view', 'assistant.manage')
        self.client.post(reverse('assistant_knowledge_toggle', args=[self.entry.id]))
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_active)


class AssistantAdminChatTests(TestCase):
    """
    The dashboard's own "Ask the assistant" page.

    The test that matters is the last one: asking must not get a figure past
    the role the person was given.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username='desk', password='pw', role=User.Role.ADMIN)

        customer_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=customer_user)
        self.category = ServiceCategory.objects.create(name='Plumbing')

    def sign_in_with(self, *codes):
        sign_in(self.client, self.admin, permissions=list(codes) or None)

    def booking(self, **kwargs):
        from datetime import time
        from decimal import Decimal

        defaults = {
            'customer': self.customer,
            'category': self.category,
            'preferred_date': '2026-11-02',
            'preferred_time': time(10, 0),
            'amount': Decimal('2000.00'),
            'status': Booking.Status.PENDING,
        }
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    def test_the_page_renders_with_the_starters(self):
        self.sign_in_with('assistant.view')
        response = self.client.get(reverse('assistant_admin_chat'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'What needs my attention?')

    def test_asking_stores_both_turns_against_the_admin(self):
        self.sign_in_with('assistant.view', 'bookings.view')
        self.booking()

        response = self.client.post(reverse('assistant_admin_chat'), {
            'question': 'how many bookings this week',
        })
        self.assertRedirects(response, reverse('assistant_admin_chat'))

        chat = Conversation.objects.get()
        self.assertEqual(chat.audience, Conversation.Audience.ADMIN)
        self.assertEqual(chat.admin_user, self.admin)
        self.assertIsNone(chat.customer)

        reply = chat.messages.filter(role=Message.Role.BOT).get()
        self.assertEqual(reply.intent, 'bookings_report')
        self.assertIn('1 bookings created', reply.text)

    def test_an_empty_question_is_refused(self):
        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_admin_chat'), {'question': '  '})
        self.assertFalse(Message.objects.exists())

    def test_the_transcript_shows_on_the_page(self):
        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what needs my attention',
        })
        response = self.client.get(reverse('assistant_admin_chat'))
        self.assertContains(response, 'what needs my attention')

    def test_asking_while_switched_off_is_refused(self):
        settings_row = AssistantSettings.get_solo()
        settings_row.admin_enabled = False
        settings_row.save()

        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what needs my attention',
        })
        self.assertFalse(Message.objects.exists())

    def test_somebody_without_assistant_view_cannot_open_it(self):
        self.sign_in_with('bookings.view')
        self.assertEqual(
            self.client.get(reverse('assistant_admin_chat')).status_code, 403,
        )

    def test_asking_cannot_get_past_the_role(self):
        """
        The escalation hole this page could have been.

        `assistant.view` lets somebody ask. It must not let them read a
        revenue figure that Reports itself would refuse them.
        """
        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what is our revenue this month',
        })
        reply = Message.objects.filter(role=Message.Role.BOT).get()
        self.assertIn("don't have access to revenue figures", reply.text)
        self.assertIn('reports.view', reply.text)
        self.assertNotIn('₹', reply.text)

    def test_the_same_question_answers_once_the_role_has_it(self):
        self.sign_in_with('assistant.view', 'reports.view')
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what is our revenue this month',
        })
        reply = Message.objects.filter(role=Message.Role.BOT).get()
        self.assertIn('taken across', reply.text)

    def test_a_super_admin_gets_everything(self):
        sign_in(self.client, self.admin)  # no permissions = super admin
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what is our revenue this month',
        })
        reply = Message.objects.filter(role=Message.Role.BOT).get()
        self.assertIn('taken across', reply.text)

    def test_an_admin_chat_appears_in_the_chat_list(self):
        self.sign_in_with('assistant.view')
        self.client.post(reverse('assistant_admin_chat'), {
            'question': 'what needs my attention',
        })
        response = self.client.get(reverse('assistant_conversations'))
        self.assertContains(response, 'Admin')
