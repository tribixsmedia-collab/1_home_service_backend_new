"""
The vendor intents, against real rows.

Two things get the most attention here. `why_no_jobs` is the diagnostic the
whole vendor side is worth building for, so each switch that can block
assignment gets its own test. And the scoping tests check the two leaks that
would matter most: one vendor reading another's payout or bid, and a customer's
address being handed out on a job that is not live.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment, Payout
from services.models import Service, ServiceCategory
from tenders.models import Tender, TenderBid, TenderSettings
from vendors.bank_models import VendorBankAccount
from vendors.models import Vendor, VendorServiceRegion

from . import engine
from .models import AssistantSettings, KnowledgeEntry
from .tools import ToolBox, ToolDenied


class VendorIntentTests(TestCase):

    def setUp(self):
        self.settings = AssistantSettings.get_solo()

        user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR,
            first_name='Ravi', last_name='Kumar',
        )
        self.vendor = Vendor.objects.create(
            user=user,
            verification_status=Vendor.VerificationStatus.VERIFIED,
        )
        self.user = user

        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.vendor.categories.add(self.category)

        customer_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER,
            first_name='Asha', last_name='Nair', phone_number='9000011111',
        )
        self.customer = Customer.objects.create(user=customer_user)

    def ask(self, question):
        return engine.ask(
            question, audience='VENDOR', user=self.user,
            settings_row=self.settings,
        )

    def job(self, **kwargs):
        defaults = {
            'customer': self.customer,
            'category': self.category,
            'vendor': self.vendor,
            'preferred_date': timezone.localdate(),
            'preferred_time': time(11, 0),
            'amount': Decimal('1800.00'),
            'status': Booking.Status.ASSIGNED,
            'address_text': '12 Marine Drive, Kochi',
            'address_state': 'Kerala',
            'address_district': 'Ernakulam',
            'customer_phone': '9000011111',
        }
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    # ------------------------------------------------------------- the jobs
    def test_no_jobs_points_at_the_diagnostic(self):
        answer = self.ask('show me my jobs')
        self.assertEqual(answer.intent, 'job_list')
        self.assertIn('no jobs yet', answer.text)
        self.assertIn('Why am I not getting jobs?', answer.suggestions)

    def test_job_list_counts_today_separately(self):
        self.job()
        self.job(preferred_date=timezone.localdate() + timedelta(days=3))
        answer = self.ask('my jobs')
        self.assertIn('1 job scheduled today', answer.text)
        self.assertIn('2 live', answer.text)

    def test_job_details_give_the_customer_contact_on_a_live_job(self):
        booking = self.job(status=Booking.Status.IN_PROGRESS)
        answer = self.ask('what is the customer address')
        self.assertEqual(answer.intent, 'job_details')
        self.assertIn(f"#{booking.id}", answer.text)
        self.assertIn('Asha Nair', answer.text)
        self.assertIn('9000011111', answer.text)
        self.assertIn('12 Marine Drive, Kochi', answer.text)

    def test_an_assigned_job_is_told_about_the_arrival_photo(self):
        self.job(status=Booking.Status.ASSIGNED)
        answer = self.ask('where is my current job')
        self.assertIn('arrival photo', answer.text)

    def test_in_progress_beats_merely_assigned(self):
        self.job(status=Booking.Status.ASSIGNED,
                 preferred_date=timezone.localdate() - timedelta(days=1))
        started = self.job(status=Booking.Status.IN_PROGRESS)
        answer = self.ask('customer phone number')
        self.assertIn(f"#{started.id}", answer.text)

    def test_a_job_can_be_asked_about_by_number(self):
        booking = self.job(status=Booking.Status.COMPLETED)
        answer = self.ask(f'job details for {booking.id}')
        self.assertIn(f"#{booking.id}", answer.text)

    # ------------------------------------------------------- why no jobs
    def test_an_unverified_vendor_is_told_that_first(self):
        self.vendor.verification_status = Vendor.VerificationStatus.PENDING
        self.vendor.save()
        answer = self.ask('why am I not getting any jobs')
        self.assertEqual(answer.intent, 'why_no_jobs')
        self.assertIn('Pending Review', answer.text)
        self.assertIn('no documents uploaded', answer.text)
        self.assertTrue(answer.escalate)

    def test_a_rejected_vendor_is_told_plainly(self):
        self.vendor.verification_status = Vendor.VerificationStatus.REJECTED
        self.vendor.save()
        answer = self.ask('why no work')
        self.assertIn('rejected at verification', answer.text)

    def test_being_offline_is_reported(self):
        self.vendor.status = Vendor.AvailabilityStatus.OFFLINE
        self.vendor.save()
        answer = self.ask('why am I not getting jobs')
        self.assertIn('Offline', answer.text)

    def test_being_marked_unavailable_is_reported(self):
        self.vendor.is_available = False
        self.vendor.save()
        answer = self.ask('why am I not getting jobs')
        self.assertIn('switched to unavailable', answer.text)

    def test_covering_nothing_is_reported(self):
        self.vendor.categories.clear()
        answer = self.ask('why am I not getting jobs')
        self.assertIn('No services or categories', answer.text)

    def test_no_regions_is_explained_as_everywhere_not_as_a_fault(self):
        """
        Empty coverage means every state. An empty list looks like a problem
        and is the opposite of one, so the answer has to say so.
        """
        answer = self.ask('why am I not getting jobs')
        self.assertIn('no area limits', answer.text)
        self.assertNotIn('stopping jobs', answer.text)

    def test_named_regions_are_listed_back(self):
        VendorServiceRegion.objects.create(
            vendor=self.vendor, state='Kerala', district='Ernakulam',
        )
        answer = self.ask('why am I not getting jobs')
        self.assertIn('Kerala', answer.text)
        self.assertIn('Ernakulam', answer.text)

    def test_a_healthy_account_is_not_given_an_invented_reason(self):
        answer = self.ask('why am I not getting jobs')
        self.assertIn('looks fine for assignment', answer.text)
        self.assertIn('nothing on your side left to fix', answer.text)

    # ------------------------------------------------------- verification
    def test_verification_status_reads_back(self):
        answer = self.ask('is my account verified')
        self.assertEqual(answer.intent, 'verification_status')
        self.assertIn('Verified', answer.text)
        self.assertFalse(answer.escalate)

    # -------------------------------------------------------- availability
    def test_availability_states_the_current_setting(self):
        answer = self.ask('how do I go offline')
        self.assertEqual(answer.intent, 'availability')
        self.assertIn('Available', answer.text)
        self.assertIn('profile screen', answer.text)

    # --------------------------------------------------------------- money
    def _paid_job(self, **kwargs):
        booking = self.job(status=Booking.Status.COMPLETED, **kwargs)
        payment = Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id=f'order_vendor_{booking.id}',
            amount=booking.amount,
        )
        payment.mark_captured(payment_id=f'pay_vendor_{booking.id}', method='upi')
        return booking, payment

    def test_nothing_earned_yet_says_so(self):
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ravi Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
        )
        answer = self.ask('when will I be paid')
        self.assertEqual(answer.intent, 'payout_status')
        self.assertIn('Nothing has been paid out', answer.text)

    def test_missing_bank_details_lead_the_answer(self):
        answer = self.ask('when will I get my money')
        self.assertIn('no bank account on file', answer.text)
        self.assertTrue(answer.escalate)

    def test_held_money_is_explained_as_held(self):
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ravi Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
        )
        self._paid_job()
        answer = self.ask('payout status')
        self.assertIn('₹1,800', answer.text)
        self.assertIn('being held by the platform', answer.text)

    def test_a_processed_payout_is_reported_with_its_utr(self):
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ravi Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
        )
        _booking, payment = self._paid_job()
        Payout.objects.create(
            payment=payment, vendor=self.vendor, amount=payment.amount,
            idempotency_key='idem_vendor_1',
            status=Payout.Status.PROCESSED, utr='UTR12345',
            processed_at=timezone.now(),
        )
        answer = self.ask('my earnings')
        self.assertIn('₹1,800 has been paid out', answer.text)
        self.assertIn('UTR12345', answer.text)

    def test_a_failed_payout_offers_a_human(self):
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ravi Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
        )
        _booking, payment = self._paid_job()
        Payout.objects.create(
            payment=payment, vendor=self.vendor, amount=payment.amount,
            idempotency_key='idem_vendor_2',
            status=Payout.Status.FAILED,
            failure_reason='Beneficiary account closed',
        )
        answer = self.ask('money not received')
        self.assertIn('Beneficiary account closed', answer.text)
        self.assertTrue(answer.escalate)

    def test_bank_state_never_reads_out_the_account_number(self):
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ravi Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
            bank_name='State Bank of India',
        )
        answer = self.ask('is my bank account verified')
        self.assertEqual(answer.intent, 'bank_state')
        self.assertIn('State Bank of India', answer.text)
        self.assertNotIn('123456789012', answer.text)
        self.assertIn("can't show the account number", answer.text)

    def test_bank_state_with_nothing_on_file(self):
        answer = self.ask('how do I add my bank account')
        self.assertIn('no bank account on file', answer.text)

    # -------------------------------------------------------------- tenders
    def _tender(self, **kwargs):
        defaults = {
            'customer': self.customer,
            'title': 'Bathroom redo',
            'category': self.category,
            'description': 'Retile and replumb',
            'expected_budget': Decimal('60000.00'),
            'bid_deadline': timezone.localdate() + timedelta(days=10),
            'status': Tender.Status.OPEN,
            'address_state': 'Kerala',
            'address_district': 'Ernakulam',
        }
        defaults.update(kwargs)
        return Tender.objects.create(**defaults)

    def test_no_bids_offers_what_is_open(self):
        self._tender()
        answer = self.ask('my bids')
        self.assertEqual(answer.intent, 'my_bids')
        self.assertIn("haven't bid on anything yet", answer.text)
        self.assertIn('Bathroom redo', answer.text)

    def test_a_selected_bid_is_not_reported_as_won(self):
        tender = self._tender(status=Tender.Status.PENDING_CONFIRMATION)
        TenderBid.objects.create(
            tender=tender, vendor=self.vendor, amount=Decimal('55000'),
            work_plan='Three weeks', timeline_days=21,
            status=TenderBid.Status.SELECTED,
        )
        answer = self.ask('did I win my bid')
        self.assertIn('not confirmed yet', answer.text)
        self.assertIn('confirmation fee', answer.text)
        self.assertNotIn('you have won', answer.text.lower())

    def test_open_tenders_exclude_ones_already_bid_on(self):
        bid_on = self._tender(title='Already bid')
        TenderBid.objects.create(
            tender=bid_on, vendor=self.vendor, amount=Decimal('50000'),
            work_plan='x', timeline_days=10,
        )
        self._tender(title='Still open')

        answer = self.ask('any new projects')
        self.assertEqual(answer.intent, 'open_tenders')
        self.assertIn('Still open', answer.text)
        self.assertNotIn('Already bid', answer.text)

    def test_open_tenders_respect_where_the_vendor_works(self):
        VendorServiceRegion.objects.create(vendor=self.vendor, state='Kerala')
        self._tender(title='In Kerala', address_state='Kerala')
        self._tender(title='In Gujarat', address_state='Gujarat',
                     address_district='Surat')

        answer = self.ask('any open projects')
        self.assertIn('In Kerala', answer.text)
        self.assertNotIn('In Gujarat', answer.text)

    def test_the_fee_is_explained_as_not_coming_out_of_the_bid(self):
        fee_settings = TenderSettings.get_solo()
        fee_settings.confirmation_fee_percent = Decimal('10.00')
        fee_settings.save()

        answer = self.ask('is any commission deducted from my bid')
        self.assertEqual(answer.intent, 'bid_fee')
        self.assertIn('Nothing is deducted', answer.text)
        self.assertIn('10%', answer.text)
        self.assertIn('customer pays us', answer.text)

    # --------------------------------------------------------- subscription
    def test_no_plan_says_so_and_does_not_invent_a_checkout(self):
        answer = self.ask('what is my plan')
        self.assertEqual(answer.intent, 'subscription')
        self.assertIn('not on a plan', answer.text)
        self.assertIn('granted by an admin', answer.text)
        self.assertIn('nothing to pay', answer.text)

    def test_an_active_plan_reports_the_days_left(self):
        from subscriptions.models import SubscriptionPlan, VendorSubscription

        plan = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('999.00'),
        )
        VendorSubscription.objects.create(
            vendor=self.vendor, plan=plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=29),
            status=VendorSubscription.Status.ACTIVE,
        )
        answer = self.ask('my subscription status')
        self.assertIn('Gold', answer.text)
        self.assertIn('30 days left', answer.text)

    # ----------------------------------------------------------------- audit
    def test_the_diagnostic_records_everything_it_read(self):
        answer = self.ask('why am I not getting jobs')
        read = [call['name'] for call in answer.tool_calls]
        self.assertIn('vendor_profile', read)
        self.assertIn('vendor_job_counts', read)


class VendorScopingTests(TestCase):
    """One vendor must not be able to read another's jobs, money or bids."""

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        self.category = ServiceCategory.objects.create(name='Plumbing')

        ravi_user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR)
        self.ravi = Vendor.objects.create(
            user=ravi_user,
            verification_status=Vendor.VerificationStatus.VERIFIED,
        )
        self.ravi_user = ravi_user

        sunil_user = User.objects.create_user(
            username='sunil', password='pw', role=User.Role.VENDOR)
        self.sunil = Vendor.objects.create(
            user=sunil_user,
            verification_status=Vendor.VerificationStatus.VERIFIED,
        )

        customer_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER,
            first_name='Asha', phone_number='9000011111')
        self.customer = Customer.objects.create(user=customer_user)

        self.sunils_job = Booking.objects.create(
            customer=self.customer, category=self.category, vendor=self.sunil,
            preferred_date=timezone.localdate(), preferred_time=time(9, 0),
            amount=Decimal('7000.00'), status=Booking.Status.IN_PROGRESS,
            address_text='99 Secret Lane', customer_phone='9000011111',
        )

    def ask_as_ravi(self, question):
        return engine.ask(question, audience='VENDOR', user=self.ravi_user,
                          settings_row=self.settings)

    def test_another_vendors_job_is_not_found_by_number(self):
        answer = self.ask_as_ravi(f'job details for {self.sunils_job.id}')
        self.assertIn('not assigned to you', answer.text)
        self.assertNotIn('99 Secret Lane', answer.text)
        self.assertNotIn('9000011111', answer.text)

    def test_another_vendors_job_does_not_leak_through_the_live_job(self):
        answer = self.ask_as_ravi('what is the customer address')
        self.assertIn('no job in progress', answer.text)
        self.assertNotIn('Secret Lane', answer.text)

    def test_another_vendors_payout_is_not_counted(self):
        payment = Payment.objects.create(
            booking=self.sunils_job, customer=self.customer,
            razorpay_order_id='order_scope_1', amount=Decimal('7000.00'),
        )
        payment.mark_captured(payment_id='pay_scope_1', method='upi')
        Payout.objects.create(
            payment=payment, vendor=self.sunil, amount=payment.amount,
            idempotency_key='idem_scope_1', status=Payout.Status.PROCESSED,
            utr='UTRSECRET',
        )
        answer = self.ask_as_ravi('my earnings')
        self.assertNotIn('7,000', answer.text)
        self.assertNotIn('UTRSECRET', answer.text)

    def test_another_vendors_bid_is_not_listed(self):
        tender = Tender.objects.create(
            customer=self.customer, title='Big job', category=self.category,
            description='x', expected_budget=Decimal('100000'),
            status=Tender.Status.OPEN,
        )
        TenderBid.objects.create(
            tender=tender, vendor=self.sunil, amount=Decimal('88888'),
            work_plan='x', timeline_days=10,
        )
        answer = self.ask_as_ravi('my bids')
        self.assertNotIn('88,888', answer.text)

    def test_a_vendor_tool_refuses_a_customer_conversation(self):
        box = ToolBox(audience='CUSTOMER', user=self.ravi_user)
        with self.assertRaises(ToolDenied):
            box.call('vendor_payouts')

    def test_a_customer_tool_refuses_a_vendor_conversation(self):
        box = ToolBox(audience='VENDOR', user=self.ravi_user)
        with self.assertRaises(ToolDenied):
            box.call('customer_bookings')

    def test_the_shared_fee_tool_serves_both(self):
        """Platform settings are the same fact whoever asks."""
        for audience in ('CUSTOMER', 'VENDOR'):
            with self.subTest(audience=audience):
                box = ToolBox(audience=audience, user=self.ravi_user)
                self.assertIn('percent', box.call('tender_fee_terms'))


class VendorAnswerBookTests(TestCase):
    """Where the vendor catalogue stops, the answer book takes over."""

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        KnowledgeEntry.objects.all().delete()

        user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=user)
        self.user = user

    def ask(self, question):
        return engine.ask(question, audience='VENDOR', user=self.user,
                          settings_row=self.settings)

    def test_an_unmatched_question_falls_to_the_vendor_answer_book(self):
        KnowledgeEntry.objects.create(
            question='What should I wear on a job?',
            keywords='uniform,dress,clothes,wear',
            answer='Wear the RNI t-shirt and carry your ID.',
            audience=KnowledgeEntry.Audience.VENDOR,
        )
        self.assertIn('RNI t-shirt', self.ask('what uniform do I wear').text)

    def test_a_customer_only_answer_is_never_given_to_a_vendor(self):
        KnowledgeEntry.objects.create(
            question='How do I book a service?',
            keywords='book,booking,order',
            answer='Pick a category on the home screen.',
            audience=KnowledgeEntry.Audience.CUSTOMER,
        )
        self.assertNotIn('home screen', self.ask('how do I book').text)
