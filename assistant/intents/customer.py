"""
What the assistant can answer for a customer.

Two kinds of intent live here, and the difference matters:

  Data intents -- "where is my booking", "did my payment go through" -- read
  the customer's own rows and state a fact. These are the ones worth having a
  bot for, because the answer is different every time and a human would only
  be reading it off the same screen.

  Policy intents -- cancelling, refunds, rescheduling -- quote the answer book
  and nothing else. The handler finds the entry, or says it does not know and
  offers a human. It never writes the policy itself, because a bot that
  improvises a refund window has just made a promise the business has to keep.

Nothing here changes anything. The cancellation intent explains how to cancel
and offers support; it does not cancel.
"""

from services.pricing import format_amount

from .base import Context, Intent, Reply  # noqa: F401  (Context re-exported)

# Offered in a fresh chat and after a dead end, so there is always something
# to tap rather than a blinking cursor.
STARTERS = (
    'Where is my booking?',
    'My payments',
    'What services do you offer?',
)


def _when(date, time=None):
    """A date, and a time when there is one, the way the apps write them."""
    if date is None:
        return ''
    stamp = date.strftime('%d %b %Y')
    if time is not None:
        stamp += time.strftime(' at %I:%M %p').replace(' 0', ' ')
    return stamp


def _booking_line(booking):
    """One booking as a single readable line."""
    what = booking['subcategory'] or booking['category'] or 'Service'
    return f"#{booking['id']} {what} — {booking['status_display']}"


# ---------------------------------------------------------------------------
# Small talk
# ---------------------------------------------------------------------------

def greeting(ctx):
    return Reply(text=ctx.settings.greeting, suggestions=STARTERS)


def thanks(ctx):
    return Reply(
        text="Happy to help. Anything else?",
        suggestions=STARTERS,
    )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def booking_status(ctx):
    """Where the customer's current booking has got to."""
    asked_id = ctx.number()
    booking = (
        ctx.call('customer_booking', booking_id=asked_id) if asked_id
        else ctx.call('customer_active_booking')
    )
    if booking is None and not asked_id:
        # No live booking, but they may be asking about a finished one.
        booking = ctx.call('customer_booking')

    if booking is None:
        if asked_id:
            return Reply(
                text=f"I can't find booking #{asked_id} on your account. "
                     "Check the number on the Bookings screen?",
                suggestions=('My bookings',),
            )
        return Reply(
            text="You don't have any bookings yet. Pick a service from the "
                 "home screen and I'll be able to track it here.",
            suggestions=('What services do you offer?',),
        )

    what = booking['subcategory'] or booking['category'] or 'Your service'
    lines = [f"Booking #{booking['id']} — {what}"]
    lines.append(f"Status: {booking['status_display']}")

    if booking['status'] == 'PENDING':
        lines.append(
            "We're matching you with a vendor. You'll get a notification the "
            "moment one is assigned."
        )
    elif booking['status'] == 'ASSIGNED':
        lines.append(
            f"{booking['vendor_name']} is assigned and will arrive on "
            f"{_when(booking['preferred_date'], booking['preferred_time'])}."
        )
    elif booking['status'] == 'IN_PROGRESS':
        lines.append(f"{booking['vendor_name']} has started the work.")
    elif booking['status'] == 'COMPLETED':
        done = _when(booking['completed_at'].date()) if booking['completed_at'] else ''
        lines.append(f"This one is finished{f' ({done})' if done else ''}.")
    elif booking['status'] == 'CANCELLED':
        lines.append("This booking was cancelled.")

    if booking['payment_status'] != 'PAID' and booking['status'] != 'CANCELLED':
        lines.append(
            f"Payment: {booking['payment_status_display']} — "
            f"{format_amount(booking['amount'])}."
        )

    suggestions = ['My bookings']
    if booking['vendor_name']:
        suggestions.append('Who is coming?')
    if booking['payment_status'] != 'PAID':
        suggestions.append('My payments')

    return Reply(text='\n'.join(lines), suggestions=tuple(suggestions))


def booking_list(ctx):
    """The customer's recent bookings, newest first."""
    bookings = ctx.call('customer_bookings', limit=5)
    if not bookings:
        return Reply(
            text="You haven't made a booking yet.",
            suggestions=('What services do you offer?',),
        )

    lines = ['Your recent bookings:']
    lines += [_booking_line(booking) for booking in bookings]
    lines.append('Ask me about any of them by number.')
    return Reply(text='\n'.join(lines), suggestions=('Where is my booking?',))


def vendor_details(ctx):
    """Who is coming, and how to reach them."""
    booking = ctx.call('customer_active_booking')
    if booking is None or not booking['vendor_name']:
        return Reply(
            text="No vendor is assigned yet. As soon as one is, their name "
                 "and number appear on the booking and I'll have them here too.",
            suggestions=('Where is my booking?',),
        )

    lines = [
        f"{booking['vendor_name']} is assigned to booking #{booking['id']}."
    ]
    if booking['vendor_phone']:
        lines.append(f"Phone: {booking['vendor_phone']}")
    if booking['status'] == 'ASSIGNED':
        lines.append(
            f"Expected {_when(booking['preferred_date'], booking['preferred_time'])}."
        )
    elif booking['status'] == 'IN_PROGRESS':
        lines.append('They have already started the work.')
    return Reply(text='\n'.join(lines), suggestions=('Where is my booking?',))


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def payment_status(ctx):
    """Whether the customer's last payment went through."""
    payments = ctx.call('customer_payments', limit=3)
    if not payments:
        return Reply(
            text="I can't see any online payments on your account yet. If you "
                 "paid the vendor directly, that won't show here.",
            suggestions=('My bookings',),
        )

    latest = payments[0]
    money = format_amount(latest['amount'])
    booking_ref = f" for booking #{latest['booking_id']}" if latest['booking_id'] else ''

    if latest['status'] == 'CAPTURED':
        text = (
            f"Your payment of {money}{booking_ref} went through on "
            f"{_when(latest['captured_at'].date()) if latest['captured_at'] else 'file'}."
        )
        if latest['payout_status'] == 'HELD':
            text += (
                "\nWe're holding it until the work is marked complete, then it "
                "goes to the vendor."
            )
    elif latest['status'] == 'FAILED':
        text = f"Your last payment of {money}{booking_ref} failed."
        if latest['failure_reason']:
            text += f"\nThe bank said: {latest['failure_reason']}"
        text += "\nNothing was charged. You can try again from the booking."
    elif latest['status'] in ('REFUNDED', 'PARTIALLY_REFUNDED'):
        text = (
            f"{format_amount(latest['amount_refunded'])} of {money}{booking_ref} "
            "has been refunded. Banks usually take 5-7 working days to show it."
        )
    else:
        # CREATED / ATTEMPTED -- checkout was opened and never finished.
        text = (
            f"Your last payment of {money}{booking_ref} wasn't completed, so "
            "nothing was charged. You can pay again from the booking screen."
        )

    if len(payments) > 1:
        text += f"\n\nI can see {len(payments)} recent payments in total."

    return Reply(
        text=text,
        suggestions=('Where is my booking?', 'I want a refund'),
        # A failed or stuck payment is the one money question where a wrong
        # guess costs the customer, so a human is always offered.
        escalate=latest['status'] not in ('CAPTURED',),
    )


def refund(ctx):
    """Where a refund has got to, plus the written refund terms."""
    payments = ctx.call('customer_payments', limit=5)
    refunded = [
        payment for payment in payments
        if payment['status'] in ('REFUNDED', 'PARTIALLY_REFUNDED')
    ]

    lines = []
    if refunded:
        latest = refunded[0]
        lines.append(
            f"A refund of {format_amount(latest['amount_refunded'])} has been "
            f"issued on payment #{latest['id']}. Banks usually take 5-7 "
            "working days to show it."
        )
    elif payments:
        lines.append("I can't see a refund on your account yet.")

    entry = ctx.knowledge('refund', 'refund policy', 'money back')
    if entry:
        lines.append(entry.answer)
    elif not refunded:
        # No policy written and nothing to report: do not invent terms.
        return Reply(
            text="I don't want to guess at our refund terms. Our support team "
                 "can check your payment and tell you exactly where it stands.",
            escalate=True,
        )

    return Reply(text='\n\n'.join(lines), escalate=True)


# ---------------------------------------------------------------------------
# Policy -- answer book only
# ---------------------------------------------------------------------------

def _policy(ctx, *phrases, subject, suggestions=()):
    """
    Quote the answer book on `subject`, or admit to not knowing.

    The shape every policy intent takes: the handler's job is to find the
    right entry, never to write one.
    """
    entry = ctx.knowledge(*phrases)
    if entry is None:
        return Reply(
            text=f"I don't have our {subject} written down, and I'd rather not "
                 "guess. Our support team can tell you properly.",
            escalate=True,
        )
    return Reply(text=entry.answer, suggestions=suggestions, escalate=True)


def cancel_booking(ctx):
    """How cancelling works -- and a note on what this booking's state allows."""
    reply = _policy(
        ctx, 'cancel', 'cancellation', 'cancel booking',
        subject='cancellation terms',
    )
    booking = ctx.call('customer_active_booking')
    if booking is None:
        return reply

    note = (
        f"Your live booking is #{booking['id']} ({booking['status_display']})."
    )
    if booking['status'] == 'IN_PROGRESS':
        note += " The vendor has already started this one."
    return Reply(
        text=f"{reply.text}\n\n{note}",
        suggestions=reply.suggestions,
        escalate=True,
    )


def reschedule_booking(ctx):
    return _policy(
        ctx, 'reschedule', 'change date', 'change time', 'postpone',
        subject='rescheduling rules',
        suggestions=('Where is my booking?',),
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def price_query(ctx):
    """What a service costs, read off the live catalogue."""
    # The question minus the words that asked it -- "how much is deep
    # cleaning" searches for "deep cleaning".
    asked_about = ctx.keywords - {
        'much', 'cost', 'costs', 'price', 'prices', 'rate', 'rates',
        'charge', 'charges', 'fee', 'fees', 'expensive', 'quote',
    }
    if not asked_about:
        return Reply(
            text="Which service did you mean? Tell me the name and I'll look "
                 "up the price.",
            suggestions=('What services do you offer?',),
        )

    services = ctx.call('service_search', terms=sorted(asked_about), limit=5)
    if not services:
        return Reply(
            text="I couldn't find that service in our list. Have a look at the "
                 "categories on the home screen, or ask me what we offer.",
            suggestions=('What services do you offer?',),
            escalate=True,
        )

    lines = ['Here is what I found:']
    for service in services:
        lines.append(f"{service['name']} — {service['price_label']}")
    lines.append(
        'Final amount depends on the quantity you pick in the app, and any '
        'coupon you apply.'
    )
    return Reply(text='\n'.join(lines), suggestions=('My bookings',))


def service_list(ctx):
    """The categories currently on offer."""
    categories = ctx.call('service_categories', limit=15)
    if not categories:
        return None

    names = ', '.join(category['name'] for category in categories)
    return Reply(
        text=f"We cover: {names}.\n\nTell me which one you need and I'll find "
             "the services and prices.",
        suggestions=('How much is cleaning?', 'My bookings'),
    )


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------

def tender_status(ctx):
    """How the customer's posted projects are doing."""
    tenders = ctx.call('customer_tenders', limit=5)
    if not tenders:
        return Reply(
            text="You haven't posted a project yet. Post one with your "
                 "requirement and budget, and vendors will bid on it.",
            suggestions=('What services do you offer?',),
        )

    lines = ['Your projects:']
    for tender in tenders:
        line = f"#{tender['id']} {tender['title']} — {tender['status_display']}"
        if tender['status'] == 'OPEN':
            count = tender['bid_count']
            line += f", {count} bid{'' if count == 1 else 's'} so far"
        lines.append(line)

    awaiting = [
        tender for tender in tenders
        if tender['status'] == 'PENDING_CONFIRMATION'
    ]
    if awaiting:
        lines.append(
            "A project waiting on confirmation needs the confirmation fee paid "
            "before the vendor is told they won."
        )

    return Reply(
        text='\n'.join(lines),
        suggestions=('What is the confirmation fee?',),
    )


def tender_fee(ctx):
    """What the confirmation fee is, at today's percentage."""
    terms = ctx.call('tender_fee_terms')
    if not terms['is_active']:
        return Reply(
            text="There's no confirmation fee at the moment — picking a bid "
                 "awards the project straight away, with nothing to pay us.",
            suggestions=('My projects',),
        )

    # Trailing zeros stripped by hand: Decimal.normalize() turns 10.00
    # into 1E+1, which is the right number and the wrong sentence.
    pretty = f"{terms['percent']:.2f}".rstrip('0').rstrip('.')
    lines = [
        f"When you accept a bid, we charge {pretty}% of the bid amount to "
        "confirm it.",
        "Until that's paid your choice is only held — the vendor isn't told "
        "they've won, and you can still change your mind and go back to the "
        "other bids.",
    ]
    entry = ctx.knowledge('confirmation fee', 'tender fee', 'platform fee')
    if entry:
        lines.append(entry.answer)
    return Reply(text='\n\n'.join(lines), suggestions=('My projects',))


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

def my_tickets(ctx):
    """Where the customer's open support tickets stand."""
    tickets = ctx.call('customer_open_tickets', limit=5)
    if not tickets:
        return Reply(
            text="You have no open support tickets. If something needs a "
                 "person, say so and I'll raise one.",
            escalate=True,
        )

    lines = ['Your open tickets:']
    for ticket in tickets:
        waiting = ' (waiting on us)' if ticket['awaiting_admin_reply'] else ''
        lines.append(
            f"#{ticket['id']} {ticket['subject']} — "
            f"{ticket['status_display']}{waiting}"
        )
    return Reply(text='\n'.join(lines))


def talk_to_human(ctx):
    """Asked for a person. Say yes and let the escalate flag do the rest."""
    return Reply(
        text="Of course. I can pass this chat to our support team — they'll "
             "reply here in the app. Tap below to hand it over.",
        escalate=True,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# Order is for readability only: the engine picks by trigger specificity, not
# by position. Triggers are written in the words customers actually type,
# which is why there are several per intent and why some of them are ugly.

INTENTS = (
    Intent('greeting', (
        'hi', 'hello', 'hey', 'good morning', 'good afternoon',
        'good evening', 'namaste', 'start',
    ), greeting),

    Intent('thanks', (
        'thanks', 'thank you', 'thank u', 'thanku', 'great thanks',
    ), thanks),

    Intent('booking_status', (
        'booking status', 'status of my booking', 'track my booking',
        ('where', 'booking'), ('status', 'booking'), ('status', 'order'),
        ('vendor', 'assigned'), ('anyone', 'assigned'),
        ('when', 'coming'), ('what time', 'coming'),
        ('update', 'booking'), ('happening', 'booking'),
    ), booking_status),

    Intent('booking_list', (
        'my bookings', 'all my bookings', 'booking history',
        'past bookings', ('list', 'booking'), ('show', 'booking'),
    ), booking_list),

    Intent('vendor_details', (
        ('who', 'coming'), ('vendor', 'number'), ('vendor', 'phone'),
        ('contact', 'vendor'), ('technician', 'number'),
        ('vendor', 'detail'), ('call', 'vendor'),
    ), vendor_details),

    Intent('payment_status', (
        'payment status', 'payment failed', 'payment pending',
        ('did', 'payment'), ('money', 'deducted'), ('money', 'debited'),
        ('charged', 'twice'), 'double charge', ('payment', 'not', 'received'),
        'my payments', ('check', 'payment'),
    ), payment_status),

    Intent('refund', (
        'refund', 'money back', 'return my money', ('get', 'money', 'back'),
    ), refund),

    Intent('cancel_booking', (
        ('cancel', 'booking'), ('cancel', 'order'), ('cancel', 'service'),
        ('how', 'cancel'), 'cancellation charge', 'cancellation fee',
        'cancellation policy',
    ), cancel_booking),

    Intent('reschedule_booking', (
        'reschedule', 'postpone', ('change', 'date'), ('change', 'time'),
        ('change', 'slot'), ('different', 'day'),
    ), reschedule_booking),

    Intent('price_query', (
        'how much', 'what is the price', 'price of', 'cost of', 'rate of',
        'charges for', 'price list', ('how much', 'charge'),
    ), price_query),

    Intent('service_list', (
        ('what', 'service'), ('which', 'service'), 'services do you offer',
        'what do you offer', ('list', 'service'), ('all', 'service'),
        ('what', 'can you do'),
    ), service_list),

    Intent('tender_status', (
        'my tender', 'my project', 'tender status', 'project status',
        ('how many', 'bid'), ('bid', 'received'), ('any', 'bid'),
        ('show', 'tender'), ('my', 'bid'),
    ), tender_status),

    Intent('tender_fee', (
        'confirmation fee', 'platform fee', ('fee', 'bid'),
        ('charge', 'accept', 'bid'), ('why', 'pay', 'fee'),
        ('10', 'fee'), ('percent', 'fee'),
    ), tender_fee),

    Intent('my_tickets', (
        'my ticket', 'my complaint', 'my tickets', ('raised', 'issue'),
        ('support', 'status'), ('complaint', 'status'),
    ), my_tickets),

    Intent('talk_to_human', (
        ('talk', 'human'), ('talk', 'person'), ('speak', 'someone'),
        ('speak', 'human'), 'customer care', 'call support', 'real person',
        'live agent', ('connect', 'agent'), ('talk', 'agent'),
        ('contact', 'support'), ('raise', 'ticket'),
    ), talk_to_human),
)
