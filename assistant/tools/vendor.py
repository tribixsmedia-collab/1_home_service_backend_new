"""
What the assistant may read on behalf of a vendor.

Same contract as the customer tools: the asking user comes in, the profile is
found here through `user.vendor_profile`, and no caller gets to name a vendor.
That is what stops one vendor asking about another's bid or payout.

Two things are deliberately left out of what comes back:

  The customer's phone number and address appear only on a job that is
  actually assigned to this vendor, and only while it is live. A finished job
  does not need to hand the address back out, and an unassigned one was never
  theirs to see.

  Bank details are reported as a state -- on file, validated, missing -- never
  as digits. "Is my account set up" is the question vendors ask; the number
  itself is on their own bank screen and has no business in a chat transcript
  the support team can read.
"""

from django.db.models import Sum

from . import tool

VENDOR = ['VENDOR']


def _profile(user):
    """The caller's vendor profile, or None if they somehow have none."""
    return getattr(user, 'vendor_profile', None)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _job_dict(booking, *, with_contact=False):
    """
    One assigned booking as the vendor's job.

    `with_contact` is only ever set for a live job of theirs -- see the module
    docstring.
    """
    job = {
        'id': booking.id,
        'status': booking.status,
        'status_display': booking.get_status_display(),
        'category': booking.category.name if booking.category_id else '',
        'subcategory': booking.subcategory.name if booking.subcategory_id else '',
        'preferred_date': booking.preferred_date,
        'preferred_time': booking.preferred_time,
        'amount': booking.amount,
        'payment_status': booking.payment_status,
        'payment_status_display': booking.get_payment_status_display(),
        'notes': booking.notes,
        'area': ', '.join(
            part for part in (booking.address_district, booking.address_state)
            if part
        ),
        'assigned_at': booking.assigned_at,
        'completed_at': booking.completed_at,
        'services': [
            line.get('name', '') for line in (booking.services_json or [])
            if isinstance(line, dict)
        ],
        'has_started_photo': hasattr(booking, 'start_photo'),
    }
    if with_contact:
        job['customer_name'] = (
            booking.customer.user.get_full_name() or booking.customer.user.username
        )
        job['customer_phone'] = booking.customer_phone or (
            getattr(booking.customer.user, 'phone_number', '') or ''
        )
        job['address'] = booking.address_text
    return job


def _own_jobs(user):
    profile = _profile(user)
    if profile is None:
        return None
    from bookings.models import Booking

    return Booking.objects.filter(vendor=profile).select_related(
        'category', 'subcategory', 'customer__user',
    )


@tool('vendor_jobs', audiences=VENDOR)
def vendor_jobs(user, limit=5):
    """The caller's most recent jobs."""
    jobs = _own_jobs(user)
    if jobs is None:
        return []
    return [
        _job_dict(booking)
        for booking in jobs.order_by('-created_at')[:limit]
    ]


@tool('vendor_active_job', audiences=VENDOR)
def vendor_active_job(user):
    """
    The job the caller is on right now, with the customer's contact details.

    In progress beats merely assigned: with two open jobs, the one they have
    already started is the one "where is this job" means.
    """
    jobs = _own_jobs(user)
    if jobs is None:
        return None
    from bookings.models import Booking

    for status in (Booking.Status.IN_PROGRESS, Booking.Status.ASSIGNED):
        booking = jobs.filter(status=status).order_by('preferred_date').first()
        if booking:
            return _job_dict(booking, with_contact=True)
    return None


@tool('vendor_job', audiences=VENDOR)
def vendor_job(user, booking_id=None):
    """One job of the caller's -- the named one, or the latest."""
    jobs = _own_jobs(user)
    if jobs is None:
        return None
    if booking_id is not None:
        # Filtered rather than fetched by id: another vendor's job reads back
        # as "no such job", which is all the caller may know about it.
        booking = jobs.filter(id=booking_id).first()
    else:
        booking = jobs.order_by('-created_at').first()
    if booking is None:
        return None

    from bookings.models import Booking

    live = booking.status in (Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS)
    return _job_dict(booking, with_contact=live)


@tool('vendor_job_counts', audiences=VENDOR)
def vendor_job_counts(user):
    """How many jobs the caller has, by the states that matter."""
    jobs = _own_jobs(user)
    if jobs is None:
        return {'live': 0, 'completed': 0, 'total': 0, 'today': 0}

    from django.utils import timezone

    from bookings.models import Booking

    return {
        'live': jobs.filter(
            status__in=[Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS],
        ).count(),
        'completed': jobs.filter(status=Booking.Status.COMPLETED).count(),
        'total': jobs.count(),
        'today': jobs.filter(
            preferred_date=timezone.localdate(),
            status__in=[Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS],
        ).count(),
    }


# ---------------------------------------------------------------------------
# The profile, and why work may not be arriving
# ---------------------------------------------------------------------------

@tool('vendor_profile', audiences=VENDOR)
def vendor_profile(user):
    """
    Everything about the caller's own standing on the platform.

    This is what the "why am I not getting jobs" answer is built from, so it
    carries every switch that can stop a vendor being picked: verification,
    availability, what they cover and where.
    """
    profile = _profile(user)
    if profile is None:
        return None

    return {
        'name': profile.display_name,
        'verification_status': profile.verification_status,
        'verification_display': profile.get_verification_status_display(),
        'is_verified': (
            profile.verification_status == profile.VerificationStatus.VERIFIED
        ),
        'is_available': profile.is_available,
        'status': profile.status,
        'status_display': profile.get_status_display(),
        'is_pro': profile.is_pro,
        # Empty means every state -- see vendors/models.py. The handler has to
        # say that out loud, because "no regions" reads as "no coverage".
        'region_labels': profile.service_region_labels,
        'coverage_labels': profile.coverage_labels,
        'location': profile.location_label,
        'document_count': profile.documents.count(),
        'average_rating': profile.average_rating,
        'total_reviews': profile.total_reviews,
    }


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

@tool('vendor_payouts', audiences=VENDOR)
def vendor_payouts(user, limit=5):
    """The caller's recent payouts, newest first."""
    profile = _profile(user)
    if profile is None:
        return []
    from payments.models import Payout

    payouts = Payout.objects.filter(vendor=profile).select_related(
        'payment__booking',
    ).order_by('-created_at')[:limit]

    return [
        {
            'id': payout.id,
            'booking_id': getattr(payout.payment, 'booking_id', None),
            'amount': payout.amount,
            'status': payout.status,
            'status_display': payout.get_status_display(),
            'mode': payout.mode,
            'utr': payout.utr,
            'failure_reason': payout.failure_reason,
            'created_at': payout.created_at,
            'processed_at': payout.processed_at,
        }
        for payout in payouts
    ]


@tool('vendor_earnings', audiences=VENDOR)
def vendor_earnings(user):
    """
    What the caller has been paid, and what is still being held.

    Held money is the customer's payment on a job of theirs that the platform
    has not released yet. The vendor receives the whole payment -- nothing is
    deducted -- so the held figure is the payment amount, not a share of it.
    """
    profile = _profile(user)
    if profile is None:
        return {'paid_out': 0, 'held': 0, 'in_flight': 0}
    from payments.models import Payment, Payout

    paid_out = Payout.objects.filter(
        vendor=profile, status=Payout.Status.PROCESSED,
    ).aggregate(total=Sum('amount'))['total'] or 0

    in_flight = Payout.objects.filter(
        vendor=profile,
        status__in=[Payout.Status.QUEUED, Payout.Status.PROCESSING],
    ).aggregate(total=Sum('amount'))['total'] or 0

    held = Payment.objects.filter(
        booking__vendor=profile,
        status=Payment.Status.CAPTURED,
        payout_status=Payment.PayoutStatus.HELD,
    ).aggregate(total=Sum('amount'))['total'] or 0

    return {'paid_out': paid_out, 'held': held, 'in_flight': in_flight}


@tool('vendor_bank_state', audiences=VENDOR)
def vendor_bank_state(user):
    """
    Whether the caller's payout details are on file and validated.

    A state, never the digits: see the module docstring.
    """
    profile = _profile(user)
    if profile is None:
        return {'on_file': False}

    account = getattr(profile, 'bank_account', None)
    if account is None:
        return {'on_file': False}

    return {
        'on_file': True,
        'bank_name': account.bank_name,
        'validation_status': account.validation_status,
        'validation_display': account.get_validation_status_display(),
        'has_upi': bool(account.upi_id),
    }


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------

@tool('vendor_bids', audiences=VENDOR)
def vendor_bids(user, limit=5):
    """The caller's own bids, and where each one stands."""
    profile = _profile(user)
    if profile is None:
        return []
    from tenders.models import TenderBid

    bids = TenderBid.objects.filter(vendor=profile).select_related(
        'tender',
    ).order_by('-created_at')[:limit]

    return [
        {
            'id': bid.id,
            'tender_id': bid.tender_id,
            'tender_title': bid.tender.title,
            'tender_status': bid.tender.status,
            'amount': bid.amount,
            'status': bid.status,
            # SELECTED means the customer picked it but has not paid the
            # confirmation fee, so it is deliberately NOT reported as won.
            'status_display': bid.get_status_display(),
            'timeline_days': bid.timeline_days,
            'created_at': bid.created_at,
        }
        for bid in bids
    ]


@tool('vendor_open_tenders', audiences=VENDOR)
def vendor_open_tenders(user, limit=5):
    """
    Projects open for bids that the caller has not bid on yet.

    Narrowed to where they work, by the same rule the rest of the platform
    uses: no regions on the profile means every state.
    """
    profile = _profile(user)
    if profile is None:
        return []
    from tenders.models import Tender

    tenders = Tender.objects.filter(
        status=Tender.Status.OPEN,
    ).exclude(bids__vendor=profile).order_by('-published_at', '-created_at')

    open_to_them = [
        tender for tender in tenders
        if profile.serves(tender.address_state, tender.address_district)
    ][:limit]

    return [
        {
            'id': tender.id,
            'title': tender.title,
            'expected_budget': tender.expected_budget,
            'bid_deadline': tender.bid_deadline,
            'area': ', '.join(
                part for part in
                (tender.address_district, tender.address_state) if part
            ),
        }
        for tender in open_to_them
    ]


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@tool('vendor_subscription', audiences=VENDOR)
def vendor_subscription(user):
    """
    The caller's plan, and any upgrade they have asked for.

    Nothing on the platform charges for a plan or gates anything behind one:
    a vendor asks an admin for a tier and an admin grants it. The handler says
    so rather than implying there is a checkout.
    """
    profile = _profile(user)
    if profile is None:
        return None
    from subscriptions.models import SubscriptionUpgradeRequest, VendorSubscription

    current = VendorSubscription.objects.filter(
        vendor=profile,
    ).select_related('plan').order_by('-start_date', '-created_at').first()

    pending = SubscriptionUpgradeRequest.objects.filter(
        vendor=profile, status=SubscriptionUpgradeRequest.Status.PENDING,
    ).select_related('plan').first()

    return {
        'plan_name': current.plan.name if current else '',
        'is_active': current.is_active if current else False,
        'status_display': current.get_status_display() if current else '',
        'is_lifetime': current.is_lifetime if current else False,
        'days_remaining': current.days_remaining if current else None,
        'end_date': current.end_date if current else None,
        'pending_request_plan': pending.plan.name if pending else '',
    }


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

@tool('vendor_open_tickets', audiences=VENDOR)
def vendor_open_tickets(user, limit=5):
    """The caller's support tickets that are still being worked on."""
    profile = _profile(user)
    if profile is None:
        return []
    from support.models import SupportTicket

    tickets = SupportTicket.objects.filter(
        vendor=profile,
        status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS],
    ).order_by('-updated_at')[:limit]

    return [
        {
            'id': ticket.id,
            'subject': ticket.subject,
            'status': ticket.status,
            'status_display': ticket.get_status_display(),
            'awaiting_admin_reply': ticket.awaiting_admin_reply,
            'updated_at': ticket.updated_at,
        }
        for ticket in tickets
    ]
