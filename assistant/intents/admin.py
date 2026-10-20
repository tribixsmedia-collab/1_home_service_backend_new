"""
What the assistant can answer for an admin.

Different in kind from the other two catalogues. A customer or vendor asks
about their own rows; an admin asks for a number about everybody, which means
two things the other sides never deal with.

First, permission. Every report is gated on the dashboard permission its
equivalent page needs, and a handler that is refused says so plainly instead
of raising -- so the assistant is never a way around the role an admin was
given. `ctx.may()` is how each handler checks before it reads.

Second, the shape of a useful answer. "How many bookings" is rarely the real
question; "what should I be looking at" is. So `pending_actions` is the first
intent here and the one offered in a fresh chat: it is every number the
dashboard already badges, in one reply.

No report here takes a field, a filter or a date range it was handed from the
text beyond a day count. Picking from named reports is the whole design, and
it stays true when the Claude engine is wired in behind the same tools.
"""

from services.pricing import format_amount

from .base import Intent, Reply

STARTERS = (
    'What needs my attention?',
    'Bookings this week',
    'Revenue this month',
)

#: "last month" and friends, in days. Only a window, never a filter.
_WINDOWS = (
    (('today',), 1),
    (('yesterday',), 2),
    (('this week', 'last week', 'past week', 'weekly', 'seven days'), 7),
    (('this month', 'last month', 'past month', 'monthly', 'thirty days'), 30),
    (('quarter', 'three months', '90 days', 'ninety days'), 90),
    (('this year', 'last year', 'yearly', 'annual'), 365),
)


def _window_from(ctx, default=7):
    """
    The period the question asked about, in days.

    A bare number in the question wins over a phrase, so "last 14 days" works
    without needing a phrase for every number somebody might type.
    """
    if ctx.mentions('days', 'day'):
        asked = ctx.number()
        if asked:
            return max(1, min(asked, 365))

    for phrases, days in _WINDOWS:
        if ctx.mentions(*phrases):
            return days
    return default


def _period_label(days):
    return {
        1: 'today', 2: 'the last two days', 7: 'the last 7 days',
        30: 'the last 30 days', 90: 'the last 90 days',
        365: 'the last year',
    }.get(days, f'the last {days} days')


def _refused(what, permission):
    """
    One wording for every refusal, naming the access that is missing.

    Named rather than vague on purpose: an admin who cannot see revenue should
    be told which permission they would need, because the fix is to ask for
    it, not to rephrase the question.
    """
    return Reply(
        text=f"You don't have access to {what} on this dashboard "
             f"({permission}). Ask a super admin to add it to your role.",
        suggestions=('What needs my attention?',),
    )


# ---------------------------------------------------------------------------
# The to-do list
# ---------------------------------------------------------------------------

def pending_actions(ctx):
    """Everything waiting on an admin, in one reply."""
    work = ctx.call('report_pending_actions')

    items = [
        (work['unassigned_bookings'], 'booking', 'bookings', 'waiting to be assigned'),
        (work['vendors_awaiting_verification'], 'vendor', 'vendors', 'awaiting verification'),
        (work['tenders_awaiting_approval'], 'tender', 'tenders', 'awaiting approval'),
        (work['tickets_awaiting_reply'], 'ticket', 'tickets', 'with nobody having replied'),
        (work['failed_payouts'], 'payout', 'payouts', 'failed and retryable'),
        (work['subscription_requests'], 'request', 'requests', 'for a subscription plan'),
        (work['unanswered_assistant_questions'], 'chat', 'chats',
         'where I could not answer — gaps in the answer book'),
    ]
    outstanding = [
        f"• {count} {singular if count == 1 else plural} {tail}"
        for count, singular, plural, tail in items if count
    ]

    if not outstanding:
        return Reply(
            text='Nothing is waiting on an admin right now.',
            suggestions=('Bookings this week', 'Revenue this month'),
        )

    lines = ['Waiting on an admin:'] + outstanding
    if work['open_tickets']:
        lines.append(f"\n{work['open_tickets']} support tickets are open in total.")
    return Reply(
        text='\n'.join(lines),
        suggestions=('Bookings this week', 'Revenue this month'),
    )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def bookings_report(ctx):
    if not ctx.may('report_bookings'):
        return _refused('booking figures', 'bookings.view')

    days = _window_from(ctx)
    report = ctx.call('report_bookings', days=days)

    lines = [
        f"{report['total']} bookings created in {_period_label(report['days'])}."
    ]
    breakdown = [
        f"{count} {report['labels'][status].lower()}"
        for status, count in report['by_status'].items() if count
    ]
    if breakdown:
        lines.append('Of those: ' + ', '.join(breakdown) + '.')

    lines.append(
        f"Right now: {report['live_now']} live, "
        f"{report['unassigned_now']} waiting to be assigned."
    )
    return Reply(
        text='\n'.join(lines),
        suggestions=('Busiest categories', 'What needs my attention?'),
    )


def top_categories(ctx):
    if not ctx.may('report_top_categories'):
        return _refused('booking figures', 'bookings.view')

    days = _window_from(ctx, default=30)
    report = ctx.call('report_top_categories', days=days, limit=5)
    if not report['rows']:
        return Reply(text=f"No bookings at all in {_period_label(days)}.")

    lines = [f"Busiest categories in {_period_label(report['days'])}:"]
    for row in report['rows']:
        lines.append(f"• {row['name']} — {row['bookings']}")
    return Reply(text='\n'.join(lines), suggestions=('Bookings this week',))


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def revenue_report(ctx):
    if not ctx.may('report_revenue'):
        return _refused('revenue figures', 'reports.view')

    days = _window_from(ctx, default=30)
    report = ctx.call('report_revenue', days=days)

    lines = [
        f"In {_period_label(report['days'])}: "
        f"{format_amount(report['captured_total'])} taken across "
        f"{report['captured_count']} payments."
    ]
    if report['refunded_total']:
        lines.append(f"Refunded: {format_amount(report['refunded_total'])}.")
    if report['failed_count']:
        lines.append(f"{report['failed_count']} payments failed.")

    lines.append(
        f"Held by the platform right now: "
        f"{format_amount(report['held_total'])}. "
        f"Released to vendors to date: "
        f"{format_amount(report['released_total'])}."
    )
    return Reply(
        text='\n'.join(lines),
        suggestions=('Payout status', 'What needs my attention?'),
    )


def payouts_report(ctx):
    if not ctx.may('report_payouts'):
        return _refused('payout figures', 'payments.view')

    report = ctx.call('report_payouts')
    lines = [
        f"{format_amount(report['paid_total'])} paid out to vendors in total."
    ]
    breakdown = [
        f"{count} {report['labels'][status].lower()}"
        for status, count in report['by_status'].items() if count
    ]
    if breakdown:
        lines.append('Payouts: ' + ', '.join(breakdown) + '.')
    if report['stuck_count']:
        lines.append(
            f"{report['stuck_count']} payouts failed and can be retried, "
            f"worth {format_amount(report['stuck_total'])}."
        )
    return Reply(text='\n'.join(lines), suggestions=('Revenue this month',))


# ---------------------------------------------------------------------------
# Vendors and customers
# ---------------------------------------------------------------------------

def vendors_report(ctx):
    if not ctx.may('report_vendors'):
        return _refused('vendor figures', 'vendors.view')

    report = ctx.call('report_vendors')
    lines = [
        f"{report['total']} vendors: {report['verified']} verified, "
        f"{report['pending']} pending review, {report['rejected']} rejected."
    ]
    lines.append(
        f"{report['available']} are available right now, "
        f"{report['pro']} are featured as Pro."
    )
    if report['without_bank']:
        lines.append(
            f"{report['without_bank']} verified vendors have no bank account "
            'on file, so they cannot be paid.'
        )
    return Reply(
        text='\n'.join(lines),
        suggestions=('What needs my attention?',),
    )


def customers_report(ctx):
    if not ctx.may('report_customers'):
        return _refused('customer figures', 'customers.view')

    days = _window_from(ctx, default=30)
    report = ctx.call('report_customers', days=days)
    return Reply(
        text=f"{report['new']} new customers in {_period_label(report['days'])}. "
             f"{report['total']} in total.",
        suggestions=('Bookings this week',),
    )


# ---------------------------------------------------------------------------
# Tenders and subscriptions
# ---------------------------------------------------------------------------

def tenders_report(ctx):
    if not ctx.may('report_tenders'):
        return _refused('tender figures', 'tenders.view')

    report = ctx.call('report_tenders')
    lines = [
        f"{report['open_count']} tenders open for bids, "
        f"{report['live_bids']} live bids across all of them."
    ]
    if report['awaiting_approval']:
        lines.append(
            f"{report['awaiting_approval']} are waiting for an admin to "
            'approve them before vendors see them.'
        )
    breakdown = [
        f"{count} {report['labels'][status].lower()}"
        for status, count in report['by_status'].items() if count
    ]
    if breakdown:
        lines.append('All tenders: ' + ', '.join(breakdown) + '.')
    return Reply(text='\n'.join(lines), suggestions=('What needs my attention?',))


def subscriptions_report(ctx):
    if not ctx.may('report_subscriptions'):
        return _refused('subscription figures', 'subscriptions.view')

    report = ctx.call('report_subscriptions')
    if not report['rows']:
        lines = ['No vendor is on an active plan.']
    else:
        lines = ['Active plans:']
        for row in report['rows']:
            lines.append(f"• {row['plan']} — {row['vendors']} vendors")

    if report['pending_requests']:
        lines.append(
            f"{report['pending_requests']} vendors have asked for a plan and "
            'are waiting on an admin.'
        )
    return Reply(text='\n'.join(lines), suggestions=('What needs my attention?',))


# ---------------------------------------------------------------------------
# Small talk and limits
# ---------------------------------------------------------------------------

def greeting(ctx):
    return Reply(text=ctx.settings.greeting, suggestions=STARTERS)


def what_can_you_do(ctx):
    """
    List the reports this admin can actually get.

    Built from what they may call, so it never offers a figure that would then
    be refused.
    """
    offers = [
        ('report_pending_actions', 'what is waiting on an admin'),
        ('report_bookings', 'booking counts by status'),
        ('report_top_categories', 'the busiest categories'),
        ('report_revenue', 'revenue, refunds and money held'),
        ('report_payouts', 'vendor payouts and anything stuck'),
        ('report_vendors', 'vendor verification and availability'),
        ('report_customers', 'customer sign-ups'),
        ('report_tenders', 'tenders and bids'),
        ('report_subscriptions', 'who is on which plan'),
    ]
    allowed = [label for name, label in offers if ctx.may(name)]

    lines = ['I can give you:']
    lines += [f'• {label}' for label in allowed]
    lines.append(
        'Add "today", "this week" or "last 30 days" to any of them. I only '
        'read figures — I cannot change anything.'
    )
    return Reply(text='\n'.join(lines), suggestions=STARTERS)


def cannot_act(ctx):
    """
    Asked to do something rather than report something.

    Worth its own intent: an admin who types "assign booking 412" should be
    told plainly that the assistant does not act, not given a booking count
    that looks like it might have worked.
    """
    return Reply(
        text="I only read figures — I can't assign, approve, cancel, refund or "
             'change anything. Use the dashboard page for that and it will be '
             'recorded against your name.',
        suggestions=STARTERS,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

INTENTS = (
    Intent('greeting', (
        'hi', 'hello', 'hey', 'good morning', 'good afternoon',
        'good evening', 'namaste',
    ), greeting),

    Intent('what_can_you_do', (
        ('what', 'can you do'), ('what', 'can you tell'), 'help',
        ('what', 'report'), ('list', 'report'), ('your', 'capability'),
    ), what_can_you_do),

    Intent('cannot_act', (
        ('assign', 'booking'), ('approve', 'vendor'), ('approve', 'tender'),
        ('cancel', 'booking'), ('refund', 'payment'), ('release', 'payment'),
        ('verify', 'vendor'), ('delete',), ('reject', 'tender'),
        ('change', 'status'), ('retry', 'payout'),
    ), cannot_act),

    Intent('pending_actions', (
        ('what', 'attention'), ('need', 'attention'), ('pending',),
        ('waiting', 'on me'), ('to do',), ('anything', 'waiting'),
        ('what', 'should i'), ('outstanding',), ('action', 'required'),
    ), pending_actions),

    Intent('bookings_report', (
        ('how many', 'booking'), ('booking', 'count'), 'bookings this week',
        ('total', 'booking'), ('booking', 'report'), ('booking', 'summary'),
        ('new', 'booking'), ('booking', 'this month'),
    ), bookings_report),

    Intent('top_categories', (
        ('busiest', 'category'), ('busiest', 'categories'),
        ('top', 'category'), ('top', 'categories'),
        ('popular', 'category'), ('popular', 'categories'),
        ('popular', 'service'), ('best', 'selling'),
        ('category', 'report'), ('categories', 'report'),
    ), top_categories),

    Intent('revenue_report', (
        ('revenue',), ('turnover',), ('how much', 'earned'),
        ('how much', 'taken'), ('total', 'collection'), ('sales',),
        ('income',), ('gmv',), ('how much', 'money'),
    ), revenue_report),

    Intent('payouts_report', (
        ('payout',), ('paid', 'vendor'), ('vendor', 'payment'),
        ('money', 'sent'), ('failed', 'payout'),
    ), payouts_report),

    Intent('vendors_report', (
        ('how many', 'vendor'), ('vendor', 'count'), ('vendor', 'report'),
        ('vendor', 'summary'), ('unverified', 'vendor'),
        ('pending', 'vendor'), ('vendor', 'available'),
    ), vendors_report),

    Intent('customers_report', (
        ('how many', 'customer'), ('customer', 'count'),
        ('new', 'customer'), ('customer', 'signup'),
        ('customer', 'report'), ('user', 'count'),
    ), customers_report),

    Intent('tenders_report', (
        ('how many', 'tender'), ('tender', 'report'), ('tender', 'summary'),
        ('open', 'tender'), ('tender', 'count'), ('how many', 'bid'),
    ), tenders_report),

    Intent('subscriptions_report', (
        ('subscription', 'report'), ('how many', 'subscription'),
        ('how many', 'subscriber'), ('who', 'plan'), ('active', 'plan'),
        ('plan', 'report'), ('subscription', 'summary'),
    ), subscriptions_report),
)
