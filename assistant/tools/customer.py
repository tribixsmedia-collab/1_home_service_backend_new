"""
What the assistant may read on behalf of a customer.

Every function takes the asking user and reaches their own profile through
`user.customer_profile`, so the scoping is not something a caller can get
wrong. They return plain dicts rather than model instances: an intent should
be formatting a string, not following relations, and a dict is what the
transcript's audit log can be checked against later.

Services and categories are public catalogue data and would be readable
without signing in at all -- they go through the registry anyway, so "what
did this answer look at" has one place to look.
"""

from django.db.models import Q

from services.pricing import price_label

from . import tool

CUSTOMER = ['CUSTOMER']


def _profile(user):
    """The caller's customer profile, or None if they somehow have none."""
    return getattr(user, 'customer_profile', None)


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def _booking_dict(booking):
    return {
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
        'vendor_name': (
            booking.vendor.user.get_full_name() or booking.vendor.user.username
            if booking.vendor_id else ''
        ),
        # The vendor's number is theirs to give out, and the customer already
        # has it on the booking screen once a vendor is assigned.
        'vendor_phone': (
            getattr(booking.vendor.user, 'phone_number', '') or ''
            if booking.vendor_id else ''
        ),
        'created_at': booking.created_at,
        'completed_at': booking.completed_at,
        'services': [
            line.get('name', '') for line in (booking.services_json or [])
            if isinstance(line, dict)
        ],
    }


def _own_bookings(user):
    profile = _profile(user)
    if profile is None:
        return None
    from bookings.models import Booking

    return Booking.objects.filter(customer=profile).select_related(
        'category', 'subcategory', 'vendor__user',
    )


@tool('customer_bookings', audiences=CUSTOMER)
def customer_bookings(user, limit=5):
    """The caller's most recent bookings."""
    bookings = _own_bookings(user)
    if bookings is None:
        return []
    return [
        _booking_dict(booking)
        for booking in bookings.order_by('-created_at')[:limit]
    ]


@tool('customer_booking', audiences=CUSTOMER)
def customer_booking(user, booking_id=None):
    """One booking of the caller's -- the named one, or the latest."""
    bookings = _own_bookings(user)
    if bookings is None:
        return None
    if booking_id is not None:
        # Filtered, not fetched by id: a booking somebody else owns reads
        # back as "no such booking" rather than as a permission error, which
        # is also all the caller is entitled to know about it.
        booking = bookings.filter(id=booking_id).first()
    else:
        booking = bookings.order_by('-created_at').first()
    return _booking_dict(booking) if booking else None


@tool('customer_active_booking', audiences=CUSTOMER)
def customer_active_booking(user):
    """The caller's live booking -- the one "where is my booking" means."""
    bookings = _own_bookings(user)
    if bookings is None:
        return None
    from bookings.models import Booking

    live = [
        Booking.Status.IN_PROGRESS,
        Booking.Status.ASSIGNED,
        Booking.Status.PENDING,
    ]
    # Ordered by how far along the work is rather than by date: with two open
    # bookings, the one a vendor is currently working on is the one being
    # asked about.
    for status in live:
        booking = bookings.filter(status=status).order_by('-created_at').first()
        if booking:
            return _booking_dict(booking)
    return None


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

@tool('customer_payments', audiences=CUSTOMER)
def customer_payments(user, limit=5):
    """The caller's recent gateway payments."""
    profile = _profile(user)
    if profile is None:
        return []
    from payments.models import Payment

    payments = Payment.objects.filter(customer=profile).select_related(
        'booking__category',
    ).order_by('-created_at')[:limit]

    return [
        {
            'id': payment.id,
            'booking_id': payment.booking_id,
            'amount': payment.amount,
            'amount_refunded': payment.amount_refunded,
            'status': payment.status,
            'status_display': payment.get_status_display(),
            'payout_status': payment.payout_status,
            'method': payment.method,
            'failure_reason': payment.failure_reason,
            'created_at': payment.created_at,
            'captured_at': payment.captured_at,
        }
        for payment in payments
    ]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@tool('service_search', audiences=CUSTOMER)
def service_search(user, terms=(), limit=5):
    """Active services whose name or category matches any of `terms`."""
    if not terms:
        return []
    from services.models import Service

    query = Q()
    for term in terms:
        query |= (
            Q(name__icontains=term)
            | Q(category__name__icontains=term)
            | Q(subcategory__name__icontains=term)
        )

    services = Service.objects.filter(
        query, is_active=True, category__is_active=True,
    ).select_related('category', 'subcategory').distinct()[:limit]

    return [
        {
            'id': service.id,
            'name': service.name,
            'category': service.category.name if service.category_id else '',
            'price': service.price,
            'pricing_type': service.pricing_type,
            # Formatted here so every answer writes a rate the same way the
            # app's service card does.
            'price_label': price_label(service.price, service.pricing_type),
        }
        for service in services
    ]


@tool('service_categories', audiences=CUSTOMER)
def service_categories(user, limit=20):
    """Every category the customer app is currently showing."""
    from services.models import ServiceCategory

    categories = ServiceCategory.objects.filter(
        is_active=True,
    ).order_by('sort_order', 'name')[:limit]
    return [{'id': c.id, 'name': c.name} for c in categories]


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------

@tool('customer_tenders', audiences=CUSTOMER)
def customer_tenders(user, limit=5):
    """The caller's posted projects, with how many bids each has."""
    profile = _profile(user)
    if profile is None:
        return []
    from django.db.models import Count

    from tenders.models import Tender, TenderBid

    tenders = Tender.objects.filter(customer=profile).annotate(
        # Withdrawn bids are not something to offer the customer to choose
        # from, so they are not counted as bids they have.
        live_bids=Count('bids', filter=~Q(bids__status=TenderBid.Status.WITHDRAWN)),
    ).order_by('-created_at')[:limit]

    return [
        {
            'id': tender.id,
            'title': tender.title,
            'status': tender.status,
            'status_display': tender.get_status_display(),
            'bid_count': tender.live_bids,
            'bid_deadline': tender.bid_deadline,
            'payment_status': tender.payment_status,
            'created_at': tender.created_at,
        }
        for tender in tenders
    ]


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

@tool('customer_open_tickets', audiences=CUSTOMER)
def customer_open_tickets(user, limit=5):
    """The caller's support tickets that are still being worked on."""
    profile = _profile(user)
    if profile is None:
        return []
    from support.models import SupportTicket

    tickets = SupportTicket.objects.filter(
        customer=profile,
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
