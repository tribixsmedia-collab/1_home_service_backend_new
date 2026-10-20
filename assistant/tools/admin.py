"""
The reports an admin may ask the assistant for.

This module is the one that does not look like the others, and the difference
is worth being explicit about.

A customer tool is safe because of *whose* rows it reads: the asker's own, and
no caller can name anyone else. None of that applies here. An admin asking
"how much did we take last month" is asking about everybody, so the question
is not whose data it is but whether this admin is allowed it -- and the answer
has to be the same one the dashboard gives. Every reader below therefore
carries `requires=`, naming the permission its equivalent page needs. An admin
with only `assistant.view` can ask what is pending; they cannot get revenue
out of the assistant that Reports would refuse them.

The second rule is that these are *named* reports with fixed parameters. There
is no reader here that takes a field name, a filter or a query. Even once the
Claude engine is wired up it will be choosing between these functions, never
composing a query of its own -- an LLM that can write an aggregate over the
production database is a different and much worse product than this one.

Everything is a count or a sum. Nothing returns a row, a name or a phone
number, so an aggregate cannot become a back door to a customer's details.
"""

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from . import tool

ADMIN = ['ADMIN']


def _since(days):
    """The cutoff for a "last N days" window, in the project's timezone."""
    return timezone.now() - timedelta(days=days)


def _window(days):
    """Days clamped to something a report can sensibly cover."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 7
    return max(1, min(days, 365))


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

@tool('report_bookings', audiences=ADMIN, requires='bookings.view')
def report_bookings(user, days=7):
    """Bookings in the last N days, broken down by status."""
    from bookings.models import Booking

    days = _window(days)
    period = Booking.objects.filter(created_at__gte=_since(days))

    by_status = {
        status: period.filter(status=status).count()
        for status, _label in Booking.Status.choices
    }
    return {
        'days': days,
        'total': period.count(),
        'by_status': by_status,
        'labels': dict(Booking.Status.choices),
        'unassigned_now': Booking.objects.filter(
            status=Booking.Status.PENDING,
        ).count(),
        'live_now': Booking.objects.filter(
            status__in=[Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS],
        ).count(),
    }


@tool('report_top_categories', audiences=ADMIN, requires='bookings.view')
def report_top_categories(user, days=30, limit=5):
    """The busiest categories in the last N days."""
    from bookings.models import Booking

    days = _window(days)
    rows = Booking.objects.filter(
        created_at__gte=_since(days),
    ).values('category__name').annotate(
        bookings=Count('id'),
    ).order_by('-bookings')[:max(1, min(int(limit or 5), 20))]

    return {
        'days': days,
        'rows': [
            {'name': row['category__name'] or 'Uncategorised',
             'bookings': row['bookings']}
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

@tool('report_revenue', audiences=ADMIN, requires='reports.view')
def report_revenue(user, days=30):
    """
    What was taken, held, released and refunded in the last N days.

    Behind `reports.view` rather than `payments.view`: this is the revenue
    figure, which is what the Reports page is gated on.
    """
    from payments.models import Payment

    days = _window(days)
    period = Payment.objects.filter(created_at__gte=_since(days))
    captured = period.filter(status=Payment.Status.CAPTURED)

    return {
        'days': days,
        'captured_total': captured.aggregate(t=Sum('amount'))['t'] or 0,
        'captured_count': captured.count(),
        'refunded_total': period.aggregate(t=Sum('amount_refunded'))['t'] or 0,
        'failed_count': period.filter(status=Payment.Status.FAILED).count(),
        # Held and released are platform-wide, not windowed: "how much are we
        # sitting on" is a question about now, not about a period.
        'held_total': Payment.objects.filter(
            status=Payment.Status.CAPTURED,
            payout_status=Payment.PayoutStatus.HELD,
        ).aggregate(t=Sum('amount'))['t'] or 0,
        'released_total': Payment.objects.filter(
            payout_status=Payment.PayoutStatus.RELEASED,
        ).aggregate(t=Sum('amount'))['t'] or 0,
    }


@tool('report_payouts', audiences=ADMIN, requires='payments.view')
def report_payouts(user):
    """Vendor payouts by state, and anything stuck."""
    from payments.models import Payout

    by_status = {
        status: Payout.objects.filter(status=status).count()
        for status, _label in Payout.Status.choices
    }
    stuck = Payout.objects.filter(status__in=Payout.RETRYABLE)

    return {
        'by_status': by_status,
        'labels': dict(Payout.Status.choices),
        'paid_total': Payout.objects.filter(
            status=Payout.Status.PROCESSED,
        ).aggregate(t=Sum('amount'))['t'] or 0,
        'stuck_count': stuck.count(),
        'stuck_total': stuck.aggregate(t=Sum('amount'))['t'] or 0,
    }


# ---------------------------------------------------------------------------
# Vendors and customers
# ---------------------------------------------------------------------------

@tool('report_vendors', audiences=ADMIN, requires='vendors.view')
def report_vendors(user):
    """Vendors by verification state and availability."""
    from vendors.models import Vendor

    vendors = Vendor.objects.all()
    return {
        'total': vendors.count(),
        'verified': vendors.filter(
            verification_status=Vendor.VerificationStatus.VERIFIED,
        ).count(),
        'pending': vendors.filter(
            verification_status=Vendor.VerificationStatus.PENDING,
        ).count(),
        'rejected': vendors.filter(
            verification_status=Vendor.VerificationStatus.REJECTED,
        ).count(),
        'available': vendors.filter(
            is_available=True, status=Vendor.AvailabilityStatus.AVAILABLE,
        ).count(),
        'pro': vendors.filter(is_pro=True).count(),
        # A verified vendor with no bank account cannot be paid, which is the
        # kind of thing nobody notices until a payout fails.
        'without_bank': vendors.filter(
            verification_status=Vendor.VerificationStatus.VERIFIED,
            bank_account__isnull=True,
        ).count(),
    }


@tool('report_customers', audiences=ADMIN, requires='customers.view')
def report_customers(user, days=30):
    """How many customers signed up in the last N days, and in total."""
    from customers.models import Customer

    days = _window(days)
    return {
        'days': days,
        'new': Customer.objects.filter(created_at__gte=_since(days)).count(),
        'total': Customer.objects.count(),
    }


# ---------------------------------------------------------------------------
# Tenders and subscriptions
# ---------------------------------------------------------------------------

@tool('report_tenders', audiences=ADMIN, requires='tenders.view')
def report_tenders(user):
    """Tenders by status, and how many are waiting on the admin."""
    from tenders.models import Tender, TenderBid

    tenders = Tender.objects.all()
    by_status = {
        status: tenders.filter(status=status).count()
        for status, _label in Tender.Status.choices
    }
    return {
        'by_status': by_status,
        'labels': dict(Tender.Status.choices),
        'awaiting_approval': by_status.get(Tender.Status.PENDING_APPROVAL, 0),
        'open_count': by_status.get(Tender.Status.OPEN, 0),
        'live_bids': TenderBid.objects.exclude(
            status=TenderBid.Status.WITHDRAWN,
        ).count(),
    }


@tool('report_subscriptions', audiences=ADMIN, requires='subscriptions.view')
def report_subscriptions(user):
    """Active vendor subscriptions by plan, and requests waiting."""
    from subscriptions.models import SubscriptionUpgradeRequest, VendorSubscription

    rows = VendorSubscription.objects.filter(
        status=VendorSubscription.Status.ACTIVE,
    ).values('plan__name').annotate(vendors=Count('id')).order_by('-vendors')

    return {
        'rows': [
            {'plan': row['plan__name'], 'vendors': row['vendors']}
            for row in rows
        ],
        'pending_requests': SubscriptionUpgradeRequest.objects.filter(
            status=SubscriptionUpgradeRequest.Status.PENDING,
        ).count(),
    }


# ---------------------------------------------------------------------------
# The one that answers "what should I be doing"
# ---------------------------------------------------------------------------

@tool('report_pending_actions', audiences=ADMIN)
def report_pending_actions(user):
    """
    Everything waiting on an admin right now.

    Deliberately ungated. Every number here is a count of work this
    dashboard's own pages already surface as a badge, and a to-do list is the
    one answer that is useless if half of it is hidden -- an admin who may
    not open Payments still benefits from knowing somebody needs to.
    """
    from bookings.models import Booking
    from payments.models import Payout
    from subscriptions.models import SubscriptionUpgradeRequest
    from support.models import SupportTicket
    from tenders.models import Tender
    from vendors.models import Vendor

    return {
        'unassigned_bookings': Booking.objects.filter(
            status=Booking.Status.PENDING,
        ).count(),
        'vendors_awaiting_verification': Vendor.objects.filter(
            verification_status=Vendor.VerificationStatus.PENDING,
        ).count(),
        'tenders_awaiting_approval': Tender.objects.filter(
            status=Tender.Status.PENDING_APPROVAL,
        ).count(),
        'open_tickets': SupportTicket.objects.filter(
            status__in=[SupportTicket.Status.OPEN,
                        SupportTicket.Status.IN_PROGRESS],
        ).count(),
        'tickets_awaiting_reply': SupportTicket.objects.filter(
            status__in=[SupportTicket.Status.OPEN,
                        SupportTicket.Status.IN_PROGRESS],
        ).exclude(
            messages__sender='ADMIN',
        ).distinct().count(),
        'failed_payouts': Payout.objects.filter(
            status__in=Payout.RETRYABLE,
        ).count(),
        'subscription_requests': SubscriptionUpgradeRequest.objects.filter(
            status=SubscriptionUpgradeRequest.Status.PENDING,
        ).count(),
        'unanswered_assistant_questions': _unanswered_assistant_count(),
    }


def _unanswered_assistant_count():
    """
    Questions the assistant could not answer, as a piece of admin work.

    It belongs in the to-do list: each one is a gap in the answer book, and
    the answer book is the only thing that fixes it.
    """
    from ..models import Conversation, Message

    return Conversation.objects.filter(
        messages__intent=Message.FALLBACK_INTENT,
    ).distinct().count()
