"""
The customer intents, against real rows.

These are the tests that matter most: an answer about somebody's booking is
the only kind of answer a bot can get wrong in a way that costs money. So
each one asserts the fact in the reply, not just that a reply came back --
and the scoping tests at the bottom assert what the assistant must *not* say.
"""

from datetime import time
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment
from services.models import Service, ServiceCategory
from services.pricing import PricingType
from tenders.models import Tender, TenderBid, TenderSettings
from vendors.models import Vendor

from . import engine
from .models import AssistantSettings, KnowledgeEntry
from .tools import ToolBox, ToolDenied


class CustomerIntentTests(TestCase):

    def setUp(self):
        self.settings = AssistantSettings.get_solo()

        user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER,
            first_name='Asha', last_name='Nair',
        )
        self.customer = Customer.objects.create(user=user)
        self.user = user

        vendor_user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR,
            first_name='Ravi', last_name='Kumar', phone_number='9876500000',
        )
        self.vendor = Vendor.objects.create(user=vendor_user)

        self.category = ServiceCategory.objects.create(name='Plumbing')

    def ask(self, question):
        return engine.ask(
            question, audience='CUSTOMER', user=self.user,
            settings_row=self.settings,
        )

    def booking(self, **kwargs):
        defaults = {
            'customer': self.customer,
            'category': self.category,
            'preferred_date': '2026-11-02',
            'preferred_time': time(10, 30),
            'amount': Decimal('2500.00'),
        }
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    # ------------------------------------------------------------- bookings
    def test_no_bookings_says_so_without_inventing_one(self):
        answer = self.ask('where is my booking')
        self.assertEqual(answer.intent, 'booking_status')
        self.assertIn("don't have any bookings", answer.text)

    def test_pending_booking_explains_it_is_waiting_for_a_vendor(self):
        booking = self.booking(status=Booking.Status.PENDING)
        answer = self.ask('where is my booking')
        self.assertIn(f"#{booking.id}", answer.text)
        self.assertIn('Pending Assignment', answer.text)
        self.assertIn('matching you with a vendor', answer.text)

    def test_assigned_booking_names_the_vendor_and_the_slot(self):
        self.booking(status=Booking.Status.ASSIGNED, vendor=self.vendor)
        answer = self.ask('where is my booking')
        self.assertIn('Ravi Kumar', answer.text)
        self.assertIn('02 Nov 2026', answer.text)
        self.assertIn('10:30 AM', answer.text)

    def test_the_live_booking_is_preferred_over_the_newest(self):
        """
        Two open bookings: the one being worked on is the one being asked
        about, even though the other was created later.
        """
        in_progress = self.booking(
            status=Booking.Status.IN_PROGRESS, vendor=self.vendor,
        )
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask('where is my booking')
        self.assertIn(f"#{in_progress.id}", answer.text)

    def test_a_booking_can_be_asked_about_by_number(self):
        old = self.booking(status=Booking.Status.COMPLETED)
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask(f'what is the status of booking {old.id}')
        self.assertIn(f"#{old.id}", answer.text)
        self.assertIn('Completed', answer.text)

    def test_an_unknown_booking_number_is_not_quietly_swapped(self):
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask('status of booking 99999')
        self.assertIn("can't find booking #99999", answer.text)

    def test_booking_list_lists_them(self):
        first = self.booking(status=Booking.Status.COMPLETED)
        second = self.booking(status=Booking.Status.PENDING)
        answer = self.ask('show me my bookings')
        self.assertEqual(answer.intent, 'booking_list')
        self.assertIn(f"#{first.id}", answer.text)
        self.assertIn(f"#{second.id}", answer.text)

    def test_unpaid_amount_is_mentioned(self):
        self.booking(status=Booking.Status.ASSIGNED, vendor=self.vendor,
                     payment_status=Booking.PaymentStatus.UNPAID)
        answer = self.ask('where is my booking')
        self.assertIn('₹2,500', answer.text)

    # --------------------------------------------------------------- vendor
    def test_vendor_details_gives_the_name_and_number(self):
        self.booking(status=Booking.Status.ASSIGNED, vendor=self.vendor)
        answer = self.ask('who is coming to my house')
        self.assertEqual(answer.intent, 'vendor_details')
        self.assertIn('Ravi Kumar', answer.text)
        self.assertIn('9876500000', answer.text)

    def test_vendor_details_before_assignment_says_nobody_yet(self):
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask('who is coming')
        self.assertIn('No vendor is assigned yet', answer.text)

    # ---------------------------------------------------------------- money
    def test_captured_payment_mentions_the_hold(self):
        booking = self.booking(status=Booking.Status.ASSIGNED, vendor=self.vendor)
        payment = Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id='order_assistant_1', amount=Decimal('2500.00'),
        )
        payment.mark_captured(payment_id='pay_assistant_1', method='upi')

        answer = self.ask('did my payment go through')
        self.assertEqual(answer.intent, 'payment_status')
        self.assertIn('₹2,500', answer.text)
        self.assertIn('holding it', answer.text)
        self.assertFalse(answer.escalate)

    def test_a_failed_payment_says_nothing_was_charged_and_offers_a_human(self):
        booking = self.booking()
        Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id='order_assistant_2', amount=Decimal('900.00'),
            status=Payment.Status.FAILED, failure_reason='Insufficient funds',
        )
        answer = self.ask('my payment failed')
        self.assertIn('Nothing was charged', answer.text)
        self.assertIn('Insufficient funds', answer.text)
        self.assertTrue(answer.escalate)

    def test_an_abandoned_checkout_is_not_reported_as_a_charge(self):
        booking = self.booking()
        Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id='order_assistant_3', amount=Decimal('400.00'),
            status=Payment.Status.ATTEMPTED,
        )
        answer = self.ask('was money deducted')
        self.assertIn("wasn't completed", answer.text)
        self.assertIn('nothing was charged', answer.text)

    def test_refund_without_a_written_policy_refuses_to_guess(self):
        KnowledgeEntry.objects.all().delete()
        answer = self.ask('I want a refund')
        self.assertEqual(answer.intent, 'refund')
        self.assertIn("don't want to guess", answer.text)
        self.assertTrue(answer.escalate)

    def test_refund_quotes_the_written_policy_when_there_is_one(self):
        KnowledgeEntry.objects.all().delete()
        KnowledgeEntry.objects.create(
            question='How long does a refund take?',
            keywords='refund,money back',
            answer='Refunds are processed within 3 working days.',
        )
        answer = self.ask('I want a refund')
        self.assertIn('within 3 working days', answer.text)

    # -------------------------------------------------------------- catalogue
    def test_price_query_reads_the_live_catalogue(self):
        Service.objects.create(
            category=self.category, name='Deep Cleaning',
            price=Decimal('15.00'), pricing_type=PricingType.PER_SQ_FT,
        )
        answer = self.ask('how much is deep cleaning')
        self.assertEqual(answer.intent, 'price_query')
        self.assertIn('Deep Cleaning', answer.text)
        # The rate, written the way the app's service card writes it.
        self.assertIn('₹15 / sq ft', answer.text)

    def test_price_query_for_something_unlisted_does_not_invent_a_price(self):
        answer = self.ask('how much is a swimming pool')
        self.assertIn("couldn't find that service", answer.text)
        self.assertTrue(answer.escalate)

    def test_a_quote_only_service_says_price_on_request(self):
        Service.objects.create(
            category=self.category, name='Full Home Renovation',
            price=Decimal('0'), pricing_type=PricingType.CUSTOM_QUOTE,
        )
        answer = self.ask('cost of full home renovation')
        self.assertIn('Price on request', answer.text)

    def test_service_list_names_the_active_categories(self):
        ServiceCategory.objects.create(name='Carpentry')
        ServiceCategory.objects.create(name='Retired', is_active=False)
        answer = self.ask('what services do you offer')
        self.assertIn('Plumbing', answer.text)
        self.assertIn('Carpentry', answer.text)
        self.assertNotIn('Retired', answer.text)

    # --------------------------------------------------------------- tenders
    def _tender(self, **kwargs):
        defaults = {
            'customer': self.customer,
            'title': 'Bathroom redo',
            'category': self.category,
            'description': 'Retile and replumb',
            'expected_budget': Decimal('50000.00'),
            'bid_deadline': '2026-12-01',
            'status': Tender.Status.OPEN,
        }
        defaults.update(kwargs)
        return Tender.objects.create(**defaults)

    def test_tender_status_counts_the_live_bids(self):
        tender = self._tender()
        TenderBid.objects.create(
            tender=tender, vendor=self.vendor, amount=Decimal('40000'),
            work_plan='Two weeks', timeline_days=14,
        )
        answer = self.ask('how many bids on my project')
        self.assertEqual(answer.intent, 'tender_status')
        self.assertIn('1 bid', answer.text)

    def test_a_withdrawn_bid_is_not_counted(self):
        tender = self._tender()
        TenderBid.objects.create(
            tender=tender, vendor=self.vendor, amount=Decimal('40000'),
            work_plan='Two weeks', timeline_days=14,
            status=TenderBid.Status.WITHDRAWN,
        )
        answer = self.ask('any bids on my project')
        self.assertIn('0 bids', answer.text)

    def test_the_confirmation_fee_is_quoted_at_the_live_percentage(self):
        fee_settings = TenderSettings.get_solo()
        fee_settings.confirmation_fee_percent = Decimal('7.50')
        fee_settings.save()

        answer = self.ask('what is the confirmation fee')
        self.assertEqual(answer.intent, 'tender_fee')
        self.assertIn('7.5%', answer.text)
        self.assertIn('held', answer.text)

    def test_a_switched_off_fee_is_not_quoted(self):
        fee_settings = TenderSettings.get_solo()
        fee_settings.is_confirmation_fee_active = False
        fee_settings.save()

        answer = self.ask('why do I pay a fee for a bid')
        self.assertIn('no confirmation fee at the moment', answer.text)

    # -------------------------------------------------------------- handover
    def test_asking_for_a_person_offers_the_handover(self):
        answer = self.ask('let me talk to a human')
        self.assertEqual(answer.intent, 'talk_to_human')
        self.assertTrue(answer.escalate)

    # ----------------------------------------------------------------- audit
    def test_every_answer_records_what_it_read(self):
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask('where is my booking')
        self.assertIn(
            'customer_active_booking',
            [call['name'] for call in answer.tool_calls],
        )

    def test_the_rules_engine_costs_nothing(self):
        answer = self.ask('where is my booking')
        self.assertEqual(answer.tokens_used, 0)
        self.assertEqual(answer.engine, 'RULES')


class ScopingTests(TestCase):
    """
    What the assistant must never say.

    One customer asking about their booking must not be able to reach
    another's, and a customer intent must not be able to reach a vendor tool
    even by naming it.
    """

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        self.category = ServiceCategory.objects.create(name='Plumbing')

        asha_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER)
        self.asha = Customer.objects.create(user=asha_user)
        self.asha_user = asha_user

        bala_user = User.objects.create_user(
            username='bala', password='pw', role=User.Role.CUSTOMER)
        self.bala = Customer.objects.create(user=bala_user)

        self.balas_booking = Booking.objects.create(
            customer=self.bala, category=self.category,
            preferred_date='2026-11-02', preferred_time=time(9, 0),
            amount=Decimal('5000.00'), status=Booking.Status.IN_PROGRESS,
        )

    def ask_as_asha(self, question):
        return engine.ask(question, audience='CUSTOMER', user=self.asha_user,
                          settings_row=self.settings)

    def test_another_customers_booking_is_not_found_by_number(self):
        answer = self.ask_as_asha(
            f'status of booking {self.balas_booking.id}'
        )
        self.assertIn("can't find booking", answer.text)
        self.assertNotIn('5,000', answer.text)

    def test_another_customers_booking_is_not_found_by_accident(self):
        answer = self.ask_as_asha('where is my booking')
        self.assertIn("don't have any bookings", answer.text)

    def test_a_tool_refuses_an_audience_it_is_not_registered_for(self):
        box = ToolBox(audience='VENDOR', user=self.asha_user)
        with self.assertRaises(ToolDenied):
            box.call('customer_bookings')

    def test_the_customer_toolbox_exposes_only_customer_tools(self):
        box = ToolBox(audience='CUSTOMER', user=self.asha_user)
        self.assertIn('customer_bookings', box.available())
        # Nothing registered for another audience leaks in.
        for name in box.available():
            from .tools import REGISTRY
            self.assertIn('CUSTOMER', REGISTRY[name].audiences)

    def test_the_tool_log_keeps_no_model_instances(self):
        """
        The audit log is read by a human in the dashboard, so it holds
        scalars -- never a repr that might carry somebody's phone number.
        """
        import json

        answer = self.ask_as_asha('how much is cleaning')
        json.dumps(answer.tool_calls)  # raises if anything unserialisable got in
