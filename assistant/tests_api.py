"""
The three endpoints the apps call, and the handover into support.

The audience tests are the important ones here: the API decides who is asking
from the signed-in user's role, so a customer cannot ask as a vendor by
putting it in the body.
"""

from datetime import time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from services.models import ServiceCategory
from support.models import SupportTicket
from vendors.models import Vendor

from .models import AssistantSettings, Conversation, KnowledgeEntry, Message


class AssistantApiTests(TestCase):

    def setUp(self):
        self.settings = AssistantSettings.get_solo()

        user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER,
            first_name='Asha',
        )
        self.customer = Customer.objects.create(user=user)
        self.user = user

        self.client = APIClient()
        self.client.force_authenticate(user=user)

        self.category = ServiceCategory.objects.create(name='Plumbing')

    # -------------------------------------------------------------- session
    def test_session_returns_the_greeting_and_an_empty_chat(self):
        response = self.client.get(reverse('assistant-session'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['enabled'])
        self.assertEqual(response.data['greeting'], self.settings.greeting)
        self.assertEqual(response.data['conversation']['messages'], [])
        self.assertTrue(response.data['suggestions'])

    def test_session_says_disabled_rather_than_failing(self):
        self.settings.customer_enabled = False
        self.settings.save()
        response = self.client.get(reverse('assistant-session'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['enabled'])
        self.assertNotIn('conversation', response.data)

    def test_session_reuses_the_running_chat(self):
        first = self.client.get(reverse('assistant-session')).data
        second = self.client.get(reverse('assistant-session')).data
        self.assertEqual(first['conversation']['id'], second['conversation']['id'])

    def test_signing_out_locks_the_endpoints(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(reverse('assistant-session')).status_code, 401)
        self.assertEqual(
            self.client.post(reverse('assistant-ask'), {'question': 'hi'}).status_code,
            401,
        )

    # ------------------------------------------------------------------ ask
    def test_asking_stores_both_turns(self):
        Booking.objects.create(
            customer=self.customer, category=self.category,
            preferred_date='2026-11-02', preferred_time=time(10, 0),
            amount=Decimal('900.00'), status=Booking.Status.PENDING,
        )
        response = self.client.post(
            reverse('assistant-ask'), {'question': 'where is my booking'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('Pending Assignment', response.data['message']['text'])
        self.assertTrue(response.data['message']['is_bot'])

        conversation = Conversation.objects.get(id=response.data['conversation_id'])
        roles = list(conversation.messages.values_list('role', flat=True))
        self.assertEqual(roles, [Message.Role.USER, Message.Role.BOT])

    def test_the_stored_answer_keeps_its_audit_trail(self):
        self.client.post(reverse('assistant-ask'), {'question': 'my bookings'})
        reply = Message.objects.filter(role=Message.Role.BOT).last()
        self.assertEqual(reply.intent, 'booking_list')
        self.assertEqual(reply.engine, 'RULES')
        self.assertEqual(reply.tool_names, ['customer_bookings'])
        self.assertEqual(reply.tokens_used, 0)

    def test_an_empty_question_is_refused(self):
        response = self.client.post(reverse('assistant-ask'), {'question': '   '})
        self.assertEqual(response.status_code, 400)

    def test_the_audience_comes_from_the_role_not_the_body(self):
        """
        A customer claiming to be a vendor is still answered as a customer.

        The tell is the intent that fired: "my bookings" is a customer
        trigger, and the vendor catalogue has no equivalent, so a body-driven
        audience would have fallen through to the answer book instead.
        """
        response = self.client.post(reverse('assistant-ask'), {
            'question': 'show me my bookings',
            'audience': 'VENDOR',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Message.objects.filter(role=Message.Role.BOT).last().intent,
            'booking_list',
        )
        self.assertEqual(
            Conversation.objects.get().audience, Conversation.Audience.CUSTOMER,
        )

    def test_asking_while_switched_off_is_refused(self):
        self.settings.customer_enabled = False
        self.settings.save()
        response = self.client.post(reverse('assistant-ask'), {'question': 'hi'})
        self.assertEqual(response.status_code, 403)

    def test_the_daily_limit_stops_the_engine_being_called(self):
        self.settings.daily_message_limit = 2
        self.settings.save()

        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    reverse('assistant-ask'), {'question': 'hello'},
                ).status_code,
                200,
            )

        response = self.client.post(reverse('assistant-ask'), {'question': 'hello'})
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.data['limit_reached'])
        # The refused question is not stored, so it cannot push tomorrow's
        # count up either.
        self.assertEqual(Message.objects.filter(role=Message.Role.USER).count(), 2)

    def test_a_zero_limit_means_no_limit(self):
        self.settings.daily_message_limit = 0
        self.settings.save()
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    reverse('assistant-ask'), {'question': 'hello'},
                ).status_code,
                200,
            )

    def test_one_persons_questions_do_not_count_against_another(self):
        self.settings.daily_message_limit = 1
        self.settings.save()
        self.client.post(reverse('assistant-ask'), {'question': 'hello'})

        other_user = User.objects.create_user(
            username='bala', password='pw', role=User.Role.CUSTOMER)
        Customer.objects.create(user=other_user)
        other = APIClient()
        other.force_authenticate(user=other_user)

        self.assertEqual(
            other.post(reverse('assistant-ask'), {'question': 'hello'}).status_code,
            200,
        )

    # ------------------------------------------------------------- handover
    def test_escalating_opens_a_ticket_carrying_the_transcript(self):
        self.client.post(reverse('assistant-ask'), {'question': 'I want a refund'})

        response = self.client.post(reverse('assistant-escalate'))
        self.assertEqual(response.status_code, 201)

        ticket = SupportTicket.objects.get(id=response.data['ticket_id'])
        self.assertEqual(ticket.customer, self.customer)
        self.assertEqual(ticket.raised_by, SupportTicket.RaisedBy.CUSTOMER)
        # Routed by what the assistant was last asked about.
        self.assertEqual(ticket.category, SupportTicket.Category.PAYMENT)
        # Subject is the person's own words.
        self.assertEqual(ticket.subject, 'I want a refund')

        transcript = ticket.messages.get().message
        self.assertIn('Me: I want a refund', transcript)
        self.assertIn('Assistant:', transcript)

    def test_escalating_twice_does_not_open_two_tickets(self):
        self.client.post(reverse('assistant-ask'), {'question': 'help me'})

        first = self.client.post(reverse('assistant-escalate'))
        second = self.client.post(reverse('assistant-escalate'))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['ticket_id'], second.data['ticket_id'])
        self.assertEqual(SupportTicket.objects.count(), 1)
        self.assertIn('Already with', second.data['message'])

    def test_escalating_an_empty_chat_is_refused(self):
        response = self.client.post(reverse('assistant-escalate'))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SupportTicket.objects.exists())

    def test_a_handed_over_chat_is_closed_and_a_fresh_one_starts(self):
        self.client.post(reverse('assistant-ask'), {'question': 'help me'})
        self.client.post(reverse('assistant-escalate'))

        response = self.client.post(reverse('assistant-ask'), {'question': 'hello'})
        self.assertEqual(Conversation.objects.count(), 2)

        fresh = Conversation.objects.get(id=response.data['conversation_id'])
        self.assertFalse(fresh.is_escalated)
        # The support agent's copy is not appended to after they got it.
        self.assertEqual(fresh.messages.count(), 2)

    def test_an_account_with_no_profile_is_refused_cleanly(self):
        """
        Shouldn't happen, but must not be a 500 when it does.

        Signing up creates the customer profile; a hand-made account can
        reach the endpoint without one.
        """
        stray = User.objects.create_user(
            username='stray', password='pw', role=User.Role.CUSTOMER)
        client = APIClient()
        client.force_authenticate(user=stray)

        self.assertEqual(client.get(reverse('assistant-session')).status_code, 403)
        self.assertEqual(
            client.post(reverse('assistant-ask'), {'question': 'hi'}).status_code,
            403,
        )

    def test_an_unanswered_question_is_counted_for_the_dashboard(self):
        KnowledgeEntry.objects.all().delete()
        self.client.post(
            reverse('assistant-ask'), {'question': 'do you also sell cement'},
        )
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.unanswered_count, 1)


class VendorAudienceTests(TestCase):
    """
    A vendor is served as a vendor end to end.

    The vendor intents themselves are tested in `tests_vendor.py`. What is
    checked here is the plumbing: the conversation is filed under VENDOR, the
    answer book splits by audience, and a handover raises a vendor ticket.
    """

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        KnowledgeEntry.objects.all().delete()

        user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=user)

        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_a_vendor_gets_a_vendor_conversation(self):
        self.client.post(reverse('assistant-ask'), {'question': 'hello'})
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.audience, Conversation.Audience.VENDOR)
        self.assertEqual(conversation.vendor, self.vendor)
        self.assertIsNone(conversation.customer)

    def test_a_vendor_is_answered_from_the_vendor_answer_book(self):
        KnowledgeEntry.objects.create(
            question='What should I wear on a job?',
            keywords='uniform,dress,clothes,wear',
            answer='Wear the RNI t-shirt and carry your ID.',
            audience=KnowledgeEntry.Audience.VENDOR,
        )
        response = self.client.post(
            reverse('assistant-ask'), {'question': 'what uniform do I wear'},
        )
        self.assertIn('RNI t-shirt', response.data['message']['text'])

    def test_a_vendor_is_not_given_a_customer_only_answer(self):
        KnowledgeEntry.objects.create(
            question='How do I book a service?',
            keywords='book,booking',
            answer='Pick a category on the home screen.',
            audience=KnowledgeEntry.Audience.CUSTOMER,
        )
        response = self.client.post(
            reverse('assistant-ask'), {'question': 'how do I book a service'},
        )
        self.assertNotIn('home screen', response.data['message']['text'])

    def test_a_vendor_handover_raises_a_vendor_ticket(self):
        self.client.post(reverse('assistant-ask'), {'question': 'I need help'})
        ticket_id = self.client.post(reverse('assistant-escalate')).data['ticket_id']

        ticket = SupportTicket.objects.get(id=ticket_id)
        self.assertEqual(ticket.vendor, self.vendor)
        self.assertIsNone(ticket.customer)
        self.assertEqual(ticket.raised_by, SupportTicket.RaisedBy.VENDOR)
        # VENDOR is a customer's category ("vendor issue"); a vendor's own
        # ticket must not land in it.
        self.assertIn(ticket.category, SupportTicket.VENDOR_CATEGORIES)
