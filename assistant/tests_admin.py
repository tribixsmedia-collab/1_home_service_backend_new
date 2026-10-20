"""
The admin reports, and the permission gating that makes them safe.

The gating tests are the important half. Admin reports read the whole
platform, so "whose rows are these" cannot protect anything -- the only thing
standing between an admin with `assistant.view` and the revenue figure is the
`requires=` on each report. If these tests pass, the assistant is not a way
around the role somebody was given.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment
from services.models import ServiceCategory
from tenders.models import Tender
from vendors.models import Vendor

from . import engine
from .models import AssistantSettings
from .tools import REGISTRY, ToolBox, ToolDenied

ALL_PERMISSIONS = frozenset({
    'bookings.view', 'payments.view', 'reports.view', 'vendors.view',
    'customers.view', 'tenders.view', 'subscriptions.view',
})


class AdminReportTests(TestCase):

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        self.admin = User.objects.create_user(
            username='boss', password='pw', role=User.Role.ADMIN)

        self.category = ServiceCategory.objects.create(name='Plumbing')

        customer_user = User.objects.create_user(
            username='asha', password='pw', role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=customer_user)

        vendor_user = User.objects.create_user(
            username='ravi', password='pw', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(
            user=vendor_user,
            verification_status=Vendor.VerificationStatus.VERIFIED,
        )

    def ask(self, question, permissions=ALL_PERMISSIONS):
        return engine.ask(
            question, audience='ADMIN', user=self.admin,
            settings_row=self.settings, permissions=permissions,
        )

    def booking(self, **kwargs):
        defaults = {
            'customer': self.customer,
            'category': self.category,
            'preferred_date': timezone.localdate(),
            'preferred_time': time(10, 0),
            'amount': Decimal('2000.00'),
            'status': Booking.Status.PENDING,
        }
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    # ------------------------------------------------------------- bookings
    def test_booking_counts_are_reported_by_status(self):
        self.booking(status=Booking.Status.PENDING)
        self.booking(status=Booking.Status.COMPLETED, vendor=self.vendor)
        answer = self.ask('how many bookings this week')

        self.assertEqual(answer.intent, 'bookings_report')
        self.assertIn('2 bookings created in the last 7 days', answer.text)
        self.assertIn('1 pending assignment', answer.text)
        self.assertIn('1 waiting to be assigned', answer.text)

    def test_a_named_window_is_honoured(self):
        answer = self.ask('how many bookings today')
        self.assertIn('today', answer.text)

    def test_a_number_of_days_beats_a_phrase(self):
        answer = self.ask('booking count for the last 14 days')
        self.assertIn('the last 14 days', answer.text)

    def test_an_absurd_window_is_clamped(self):
        """Clamped to a year, which reads back as "the last year"."""
        answer = self.ask('booking count for the last 99999 days')
        self.assertIn('the last year', answer.text)
        self.assertNotIn('99999', answer.text)

    def test_the_busiest_categories_are_ranked(self):
        other = ServiceCategory.objects.create(name='Electrical')
        self.booking()
        self.booking()
        self.booking(category=other)

        answer = self.ask('which are the busiest categories')
        self.assertEqual(answer.intent, 'top_categories')
        self.assertIn('Plumbing — 2', answer.text)
        self.assertIn('Electrical — 1', answer.text)

    # --------------------------------------------------------------- money
    def test_revenue_reports_taken_and_held(self):
        booking = self.booking(status=Booking.Status.COMPLETED, vendor=self.vendor)
        payment = Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id='order_admin_1', amount=Decimal('2000.00'),
        )
        payment.mark_captured(payment_id='pay_admin_1', method='upi')

        answer = self.ask('what is our revenue this month')
        self.assertEqual(answer.intent, 'revenue_report')
        self.assertIn('₹2,000 taken', answer.text)
        self.assertIn('Held by the platform right now: ₹2,000', answer.text)

    def test_payouts_report_counts_what_is_stuck(self):
        from payments.models import Payout

        booking = self.booking(status=Booking.Status.COMPLETED, vendor=self.vendor)
        payment = Payment.objects.create(
            booking=booking, customer=self.customer,
            razorpay_order_id='order_admin_2', amount=Decimal('2000.00'),
        )
        payment.mark_captured(payment_id='pay_admin_2', method='upi')
        Payout.objects.create(
            payment=payment, vendor=self.vendor, amount=payment.amount,
            idempotency_key='idem_admin_1', status=Payout.Status.FAILED,
            failure_reason='Account closed',
        )

        answer = self.ask('any failed payouts')
        self.assertEqual(answer.intent, 'payouts_report')
        self.assertIn('1 payouts failed and can be retried', answer.text)

    # -------------------------------------------------------------- vendors
    def test_vendor_report_flags_verified_vendors_with_no_bank_account(self):
        answer = self.ask('how many vendors do we have')
        self.assertEqual(answer.intent, 'vendors_report')
        self.assertIn('1 vendors: 1 verified', answer.text)
        self.assertIn('no bank account', answer.text)

    def test_customer_report_counts_signups(self):
        answer = self.ask('how many new customers this month')
        self.assertEqual(answer.intent, 'customers_report')
        self.assertIn('1 new customers', answer.text)

    # -------------------------------------------------------------- tenders
    def test_tender_report_flags_what_is_awaiting_approval(self):
        Tender.objects.create(
            customer=self.customer, title='Kitchen', category=self.category,
            description='x', expected_budget=Decimal('50000'),
            status=Tender.Status.PENDING_APPROVAL,
        )
        answer = self.ask('tender summary')
        self.assertEqual(answer.intent, 'tenders_report')
        self.assertIn('1 are waiting for an admin to approve', answer.text)

    def test_subscription_report_with_nobody_on_a_plan(self):
        answer = self.ask('subscription report')
        self.assertEqual(answer.intent, 'subscriptions_report')
        self.assertIn('No vendor is on an active plan', answer.text)

    # --------------------------------------------------------- the to-do list
    def test_pending_actions_lists_only_what_is_outstanding(self):
        self.booking(status=Booking.Status.PENDING)
        Vendor.objects.create(
            user=User.objects.create_user(
                username='new-vendor', password='pw', role=User.Role.VENDOR),
            verification_status=Vendor.VerificationStatus.PENDING,
        )

        answer = self.ask('what needs my attention')
        self.assertEqual(answer.intent, 'pending_actions')
        self.assertIn('1 booking waiting to be assigned', answer.text)
        self.assertIn('1 vendor awaiting verification', answer.text)
        # Nothing is said about the queues that are empty.
        self.assertNotIn('payouts', answer.text)

    def test_an_empty_queue_says_so(self):
        answer = self.ask('is anything waiting on me')
        self.assertIn('Nothing is waiting on an admin', answer.text)

    def test_pending_actions_works_without_any_report_permission(self):
        """
        The to-do list is ungated on purpose: every number in it is work this
        dashboard already badges, and a half-hidden to-do list is useless.
        """
        self.booking(status=Booking.Status.PENDING)
        answer = self.ask('what needs my attention', permissions=frozenset())
        self.assertIn('1 booking waiting to be assigned', answer.text)

    # ----------------------------------------------------- what it will not do
    def test_being_asked_to_act_is_refused_plainly(self):
        booking = self.booking()
        answer = self.ask(f'assign booking {booking.id} to a vendor')
        self.assertEqual(answer.intent, 'cannot_act')
        self.assertIn("can't assign", answer.text)
        # And it must not have quietly answered with a count instead.
        self.assertNotIn('bookings created', answer.text)

    def test_no_report_takes_a_field_or_filter_from_the_text(self):
        """
        Every admin report is a named function with at most a day count.

        Guarded as a test because it is the property that keeps this safe
        once the Claude engine picks the report instead of a regex: an engine
        that can only choose between these cannot compose a query.
        """
        allowed = {'days', 'limit'}
        for name, spec in REGISTRY.items():
            if 'ADMIN' not in spec.audiences:
                continue
            import inspect

            params = set(inspect.signature(spec.func).parameters) - {'user'}
            with self.subTest(tool=name):
                self.assertTrue(
                    params <= allowed,
                    f'{name} takes {sorted(params - allowed)}, which is more '
                    'than a window',
                )

    def test_what_it_can_do_lists_only_the_permitted_reports(self):
        answer = self.ask('what can you do', permissions=frozenset({'bookings.view'}))
        self.assertEqual(answer.intent, 'what_can_you_do')
        self.assertIn('booking counts by status', answer.text)
        self.assertNotIn('revenue, refunds', answer.text)


class AdminPermissionTests(TestCase):
    """
    A report must refuse an admin the dashboard would refuse.

    This is the escalation hole the `requires=` on each admin tool exists to
    close, so each one gets a test.
    """

    def setUp(self):
        self.settings = AssistantSettings.get_solo()
        self.admin = User.objects.create_user(
            username='desk', password='pw', role=User.Role.ADMIN)

    def ask(self, question, permissions=frozenset()):
        return engine.ask(
            question, audience='ADMIN', user=self.admin,
            settings_row=self.settings, permissions=permissions,
        )

    def test_revenue_is_refused_without_reports_view(self):
        answer = self.ask('what is our revenue this month')
        self.assertIn("don't have access to revenue figures", answer.text)
        self.assertIn('reports.view', answer.text)
        # And no figure leaked into the refusal.
        self.assertNotIn('₹', answer.text)

    def test_revenue_is_allowed_with_reports_view(self):
        answer = self.ask('revenue this month',
                          permissions=frozenset({'reports.view'}))
        self.assertIn('taken across', answer.text)

    def test_each_report_names_the_permission_it_needs(self):
        cases = {
            'how many bookings this week': 'bookings.view',
            'what is our revenue': 'reports.view',
            'any failed payouts': 'payments.view',
            'how many vendors': 'vendors.view',
            'how many new customers': 'customers.view',
            'tender summary': 'tenders.view',
            'subscription report': 'subscriptions.view',
            'busiest categories': 'bookings.view',
        }
        for question, permission in cases.items():
            with self.subTest(question=question):
                answer = self.ask(question)
                self.assertIn("don't have access", answer.text)
                self.assertIn(permission, answer.text)

    def test_holding_one_permission_does_not_open_the_others(self):
        answer = self.ask('any failed payouts',
                          permissions=frozenset({'bookings.view'}))
        self.assertIn('payments.view', answer.text)

    def test_the_toolbox_refuses_a_gated_report_outright(self):
        box = ToolBox(audience='ADMIN', user=self.admin, permissions=frozenset())
        with self.assertRaises(ToolDenied):
            box.call('report_revenue')

    def test_the_toolbox_allows_it_once_the_permission_is_held(self):
        box = ToolBox(
            audience='ADMIN', user=self.admin,
            permissions=frozenset({'reports.view'}),
        )
        self.assertIn('captured_total', box.call('report_revenue'))

    def test_available_reflects_the_permissions_held(self):
        box = ToolBox(
            audience='ADMIN', user=self.admin,
            permissions=frozenset({'vendors.view'}),
        )
        available = box.available()
        self.assertIn('report_vendors', available)
        self.assertIn('report_pending_actions', available)
        self.assertNotIn('report_revenue', available)

    def test_an_admin_cannot_reach_a_customer_tool(self):
        box = ToolBox(
            audience='ADMIN', user=self.admin, permissions=ALL_PERMISSIONS,
        )
        with self.assertRaises(ToolDenied):
            box.call('customer_bookings')

    def test_a_customer_cannot_reach_an_admin_report(self):
        """
        Belt and braces: a customer conversation carries no permissions, but
        the audience check refuses the report before that even matters.
        """
        box = ToolBox(
            audience='CUSTOMER', user=self.admin, permissions=ALL_PERMISSIONS,
        )
        with self.assertRaises(ToolDenied):
            box.call('report_revenue')

    def test_every_admin_report_except_the_todo_list_is_gated(self):
        ungated = {
            name for name, spec in REGISTRY.items()
            if 'ADMIN' in spec.audiences and not spec.requires
        }
        self.assertEqual(ungated, {'report_pending_actions'})
