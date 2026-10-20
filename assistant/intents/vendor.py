"""
What the assistant can answer for a vendor.

The vendor side earns its keep differently from the customer side. A customer
mostly asks "where is my thing", which is one row looked up. A vendor's real
questions are diagnostic -- "why am I not getting any work", "where is my
money" -- and the answer is spread across their verification state, their
availability toggle, the regions on their profile, what they cover, and
whether anybody has sent them money yet.

So `why_no_jobs` and `payout_status` below are not lookups. They walk every
switch that can be the cause, in the order a human support agent would, and
report the first ones that are actually wrong. That is the single most
support-ticket-shaped question on the platform, and it is answerable from
data without a word of policy.

As on the customer side, nothing here writes. The availability intent explains
where the toggle is; it does not flip it.
"""

from services.pricing import format_amount

from .base import Intent, Reply

STARTERS = (
    'My jobs today',
    'Why am I not getting jobs?',
    'When will I be paid?',
)


def _when(date, time=None):
    """A date, and a time when there is one, the way the apps write them."""
    if date is None:
        return ''
    stamp = date.strftime('%d %b %Y')
    if time is not None:
        stamp += time.strftime(' at %I:%M %p').replace(' 0', ' ')
    return stamp


# ---------------------------------------------------------------------------
# Small talk
# ---------------------------------------------------------------------------

def greeting(ctx):
    return Reply(text=ctx.settings.greeting, suggestions=STARTERS)


def thanks(ctx):
    return Reply(text='Any time. Anything else?', suggestions=STARTERS)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def job_list(ctx):
    """The vendor's jobs, with today's count up front."""
    counts = ctx.call('vendor_job_counts')
    if counts['total'] == 0:
        # Nothing to list. Returning None hands over to why_no_jobs' answer
        # being a tap away rather than printing an empty list.
        return Reply(
            text="You have no jobs yet.",
            suggestions=('Why am I not getting jobs?',),
        )

    jobs = ctx.call('vendor_jobs', limit=5)
    lines = []
    if counts['today']:
        lines.append(
            f"You have {counts['today']} job"
            f"{'' if counts['today'] == 1 else 's'} scheduled today."
        )
    lines.append('Your recent jobs:')
    for job in jobs:
        what = job['subcategory'] or job['category'] or 'Service'
        where = f" · {job['area']}" if job['area'] else ''
        lines.append(
            f"#{job['id']} {what} — {job['status_display']}"
            f" · {_when(job['preferred_date'])}{where}"
        )
    lines.append(
        f"{counts['live']} live, {counts['completed']} completed in total."
    )
    return Reply(
        text='\n'.join(lines),
        suggestions=('Where is my current job?', 'When will I be paid?'),
    )


def job_details(ctx):
    """The live job, with the customer's address and number."""
    asked_id = ctx.number()
    job = (
        ctx.call('vendor_job', booking_id=asked_id) if asked_id
        else ctx.call('vendor_active_job')
    )

    if job is None:
        if asked_id:
            return Reply(
                text=f"Job #{asked_id} is not assigned to you.",
                suggestions=('My jobs',),
            )
        return Reply(
            text="You have no job in progress right now.",
            suggestions=('My jobs', 'Why am I not getting jobs?'),
        )

    what = job['subcategory'] or job['category'] or 'Service'
    lines = [f"Job #{job['id']} — {what}", f"Status: {job['status_display']}"]

    # Contact details are only on the dict for a live job of theirs.
    if job.get('customer_name'):
        lines.append(f"Customer: {job['customer_name']}")
    if job.get('customer_phone'):
        lines.append(f"Phone: {job['customer_phone']}")
    if job.get('address'):
        lines.append(f"Address: {job['address']}")

    lines.append(
        f"Slot: {_when(job['preferred_date'], job['preferred_time'])}"
    )
    if job['notes']:
        lines.append(f"Customer's note: {job['notes']}")
    lines.append(f"Job value: {format_amount(job['amount'])}")

    if job['status'] == 'ASSIGNED' and not job['has_started_photo']:
        lines.append(
            'Take the arrival photo at the address when you get there — that '
            'is what moves the job to Work In Progress.'
        )

    return Reply(text='\n'.join(lines), suggestions=('My jobs',))


def why_no_jobs(ctx):
    """
    Walk every switch that stops a vendor being given work.

    Order matters: it reports the blocking reasons first and the merely
    plausible ones after, so a vendor whose account is not verified is told
    that rather than being told their category is popular.
    """
    profile = ctx.call('vendor_profile')
    if profile is None:
        return None

    counts = ctx.call('vendor_job_counts')
    blockers = []
    notes = []

    # 1. Verification. Nothing is assigned to an unverified vendor.
    if not profile['is_verified']:
        if profile['verification_status'] == 'REJECTED':
            blockers.append(
                'Your account was rejected at verification, so you will not '
                'be given jobs. Support can tell you what was wrong with the '
                'documents.'
            )
        else:
            blockers.append(
                'Your account is still Pending Review. Jobs only start coming '
                'once an admin has verified it.'
            )
            if profile['document_count'] == 0:
                blockers.append(
                    'You have no documents uploaded yet — that is what the '
                    'review is waiting for.'
                )

    # 2. The vendor's own availability.
    if not profile['is_available']:
        blockers.append(
            'Your profile is switched to unavailable, which takes you out of '
            'the assignment list.'
        )
    elif profile['status'] == 'OFFLINE':
        blockers.append(
            'Your status is Offline. Set it to Available to be given jobs.'
        )
    elif profile['status'] == 'BUSY':
        notes.append(
            'Your status is Busy, so you are behind the available vendors in '
            'the queue.'
        )

    # 3. What they cover. Nothing covered means nothing to match them to.
    if not profile['coverage_labels']:
        blockers.append(
            'No services or categories are set on your profile, so there is '
            'nothing to match you to. Support can add them.'
        )

    # 4. Where they work. Empty is "everywhere" -- say so, because an empty
    #    list looks like a problem and is the opposite of one.
    if profile['region_labels']:
        notes.append(
            'You are listed for: ' + '; '.join(profile['region_labels'])
            + '. Jobs outside that go to other vendors.'
        )
    else:
        notes.append(
            'You have no area limits set, so you are considered for every '
            'state.'
        )

    if blockers:
        lines = ['Here is what is stopping jobs reaching you:']
        lines += [f'• {reason}' for reason in blockers]
        if notes:
            lines.append('')
            lines += [f'• {note}' for note in notes]
        return Reply(
            text='\n'.join(lines),
            suggestions=('Is my account verified?',),
            # Every blocker here needs an admin to clear it.
            escalate=True,
        )

    # Nothing is wrong with the account, so say that plainly rather than
    # inventing a reason.
    lines = [
        'Your account looks fine for assignment: verified, available, and '
        f"covering {', '.join(profile['coverage_labels'][:5])}."
    ]
    lines += [f'• {note}' for note in notes]
    if counts['total']:
        lines.append(
            f"You have had {counts['total']} job"
            f"{'' if counts['total'] == 1 else 's'} so far, "
            f"{counts['live']} live right now."
        )
    else:
        lines.append(
            'Jobs are given out as customers book in your area, so there is '
            'nothing on your side left to fix.'
        )
    return Reply(text='\n'.join(lines), suggestions=('My jobs',), escalate=True)


def verification_status(ctx):
    """Where the vendor's account stands with the admin."""
    profile = ctx.call('vendor_profile')
    if profile is None:
        return None

    lines = [f"Your account is: {profile['verification_display']}."]

    if profile['is_verified']:
        lines.append('You can be given jobs and bid on projects.')
    elif profile['verification_status'] == 'REJECTED':
        lines.append(
            'Support can tell you what was wrong and what to re-upload.'
        )
    else:
        lines.append(
            f"{profile['document_count']} document"
            f"{'' if profile['document_count'] == 1 else 's'} on file."
            if profile['document_count']
            else 'No documents on file yet, which is what the review needs.'
        )

    return Reply(
        text='\n'.join(lines),
        suggestions=('Why am I not getting jobs?',),
        escalate=not profile['is_verified'],
    )


def availability(ctx):
    """What the vendor's availability is set to, and what each state means."""
    profile = ctx.call('vendor_profile')
    if profile is None:
        return None

    lines = [
        f"You are currently {profile['status_display']}"
        f"{' and marked unavailable' if not profile['is_available'] else ''}.",
        'Available means you are in the queue for new jobs, Busy puts you '
        'behind the available vendors, and Offline takes you out of it.',
        'You can change it yourself on your profile screen in the app.',
    ]
    return Reply(
        text='\n'.join(lines),
        suggestions=('Why am I not getting jobs?',),
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def payout_status(ctx):
    """
    Where the vendor's money is, in the order it moves.

    Held by the platform, then sent, then arrived. Each stage is a different
    answer and a different thing to do about it, so the reply says which
    stage the money is at rather than a single balance.
    """
    earnings = ctx.call('vendor_earnings')
    payouts = ctx.call('vendor_payouts', limit=3)
    bank = ctx.call('vendor_bank_state')

    lines = []

    if not bank['on_file']:
        # The one blocker worth leading with: nothing can be sent at all.
        lines.append(
            'You have no bank account on file, so nothing can be paid out '
            'yet. Add it on your profile screen.'
        )

    if earnings['held']:
        lines.append(
            f"{format_amount(earnings['held'])} is being held by the platform "
            'on jobs that are not marked complete yet. It is released once '
            'the job is finished.'
        )

    if earnings['in_flight']:
        lines.append(
            f"{format_amount(earnings['in_flight'])} has been sent and is on "
            'its way to your bank.'
        )

    if earnings['paid_out']:
        lines.append(
            f"{format_amount(earnings['paid_out'])} has been paid out to you "
            'in total.'
        )

    if payouts:
        latest = payouts[0]
        line = (
            f"Latest payout: {format_amount(latest['amount'])} — "
            f"{latest['status_display']}"
        )
        if latest['utr']:
            line += f" (UTR {latest['utr']})"
        lines.append(line)
        if latest['failure_reason']:
            lines.append(f"The bank said: {latest['failure_reason']}")

    if not lines:
        lines.append(
            'Nothing has been paid out to you yet, and nothing is being held. '
            'Money appears here once a job of yours is paid for.'
        )

    # A failed payout or missing bank details both need somebody to act.
    needs_a_human = (
        not bank['on_file']
        or any(payout['failure_reason'] for payout in payouts)
    )
    return Reply(
        text='\n\n'.join(lines),
        suggestions=('My jobs', 'Is my bank account set up?'),
        escalate=needs_a_human,
    )


def bank_state(ctx):
    """Whether payout details are on file, without reading them out."""
    bank = ctx.call('vendor_bank_state')

    if not bank['on_file']:
        return Reply(
            text='You have no bank account on file. Add it on your profile '
                 'screen — payouts cannot be sent without it.',
            escalate=True,
        )

    lines = ['Your payout details are on file.']
    if bank['bank_name']:
        lines.append(f"Bank: {bank['bank_name']}")
    lines.append(f"Verification: {bank['validation_display']}")
    if bank['has_upi']:
        lines.append('A UPI ID is on file as well.')
    lines.append(
        "I can't show the account number here. It is on your profile screen."
    )
    return Reply(text='\n'.join(lines), suggestions=('When will I be paid?',))


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------

def my_bids(ctx):
    """Every bid the vendor has placed, and where each one stands."""
    bids = ctx.call('vendor_bids', limit=5)
    if not bids:
        open_tenders = ctx.call('vendor_open_tenders', limit=3)
        if open_tenders:
            lines = ["You haven't bid on anything yet. Open right now:"]
            for tender in open_tenders:
                lines.append(
                    f"#{tender['id']} {tender['title']} — budget "
                    f"{format_amount(tender['expected_budget'])}"
                )
            return Reply(text='\n'.join(lines), suggestions=('How do I bid?',))
        return Reply(
            text="You haven't bid on anything yet, and there are no open "
                 'projects in your area at the moment.',
            suggestions=('How do I bid?',),
        )

    lines = ['Your bids:']
    for bid in bids:
        lines.append(
            f"#{bid['tender_id']} {bid['tender_title']} — "
            f"{format_amount(bid['amount'])} — {bid['status_display']}"
        )

    # SELECTED is the one that needs explaining: the customer picked them but
    # has not paid, and a vendor told "you won" at that point would be misled.
    if any(bid['status'] == 'SELECTED' for bid in bids):
        lines.append(
            'A bid marked selected has been picked by the customer but is not '
            'confirmed yet. It becomes yours once they pay the confirmation '
            'fee, and until then they can still change their mind.'
        )

    return Reply(text='\n'.join(lines), suggestions=('Any new projects?',))


def open_tenders(ctx):
    """Projects the vendor could bid on but has not."""
    tenders = ctx.call('vendor_open_tenders', limit=5)
    if not tenders:
        return Reply(
            text='Nothing open in your area that you have not already bid on.',
            suggestions=('My bids',),
        )

    lines = ['Open for bids in your area:']
    for tender in tenders:
        line = (
            f"#{tender['id']} {tender['title']} — budget "
            f"{format_amount(tender['expected_budget'])}"
        )
        if tender['bid_deadline']:
            line += f", bids close {_when(tender['bid_deadline'])}"
        lines.append(line)
    return Reply(text='\n'.join(lines), suggestions=('How do I bid?', 'My bids'))


def bid_fee(ctx):
    """
    Whether the confirmation fee comes out of the vendor's bid.

    It does not, and this is worth its own intent because it is the question
    a vendor asks when they see a percentage mentioned anywhere near a bid.
    """
    terms = ctx.call('tender_fee_terms')

    lines = ['Nothing is deducted from your bid. You are paid the amount you '
             'bid.']
    if terms['is_active']:
        percent = f"{terms['percent']:.2f}".rstrip('0').rstrip('.')
        lines.append(
            f'The customer pays us {percent}% of the bid separately to '
            'confirm their choice. That is between them and the platform.'
        )
        lines.append(
            "It is also why a bid can sit as selected for a while: we don't "
            'tell you that you have won until they have paid it.'
        )
    else:
        lines.append(
            'There is no confirmation fee at the moment, so a customer '
            'choosing your bid awards it straight away.'
        )
    return Reply(text='\n\n'.join(lines), suggestions=('My bids',))


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

def subscription(ctx):
    """
    The vendor's plan, honestly described.

    Nothing on the platform charges for a plan or gates anything behind one.
    A vendor asks, an admin grants. Saying otherwise would be selling
    something that does not exist.
    """
    plan = ctx.call('vendor_subscription')
    if plan is None:
        return None

    lines = []
    if plan['plan_name'] and plan['is_active']:
        lines.append(f"You are on the {plan['plan_name']} plan.")
        if plan['is_lifetime']:
            lines.append('It does not expire.')
        elif plan['days_remaining'] is not None:
            lines.append(
                f"{plan['days_remaining']} day"
                f"{'' if plan['days_remaining'] == 1 else 's'} left "
                f"(until {_when(plan['end_date'])})."
            )
    elif plan['plan_name']:
        lines.append(
            f"Your {plan['plan_name']} plan is {plan['status_display'].lower()}."
        )
    else:
        lines.append('You are not on a plan at the moment.')

    if plan['pending_request_plan']:
        lines.append(
            f"You have asked for {plan['pending_request_plan']} and an admin "
            'has not decided yet.'
        )
    else:
        lines.append(
            'Plans are granted by an admin — you request one from the app and '
            'they assign it. There is nothing to pay here.'
        )

    return Reply(text='\n\n'.join(lines), escalate=True)


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

def my_tickets(ctx):
    tickets = ctx.call('vendor_open_tickets', limit=5)
    if not tickets:
        return Reply(
            text='You have no open support tickets. If something needs a '
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
    return Reply(
        text='Of course. I can pass this chat to our support team — they will '
             'reply here in the app. Tap below to hand it over.',
        escalate=True,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

INTENTS = (
    Intent('greeting', (
        'hi', 'hello', 'hey', 'good morning', 'good afternoon',
        'good evening', 'namaste', 'start',
    ), greeting),

    Intent('thanks', (
        'thanks', 'thank you', 'thank u', 'thanku',
    ), thanks),

    Intent('why_no_jobs', (
        ('why', 'no job'), ('not getting', 'job'), ('no', 'work'),
        ('getting', 'no job'), ('no new', 'job'), ('why', 'no work'),
        ('not receiving', 'job'), ('job', 'not coming'),
        ('nobody', 'assigned'), ('why', 'not assigned'),
    ), why_no_jobs),

    Intent('job_list', (
        'my jobs', 'my job', 'job list', ('today', 'job'),
        ('show', 'job'), ('how many', 'job'), 'job history',
        ('list', 'job'), 'my work',
    ), job_list),

    Intent('job_details', (
        ('customer', 'number'), ('customer', 'phone'), ('customer', 'address'),
        ('where', 'job'), ('job', 'detail'), ('job', 'address'),
        ('current', 'job'), ('contact', 'customer'), ('call', 'customer'),
    ), job_details),

    Intent('verification_status', (
        ('account', 'verified'), ('am i', 'verified'), 'verification status',
        ('document', 'status'), ('document', 'approved'),
        ('profile', 'approved'), ('kyc', 'status'),
    ), verification_status),

    Intent('availability', (
        ('go', 'offline'), ('mark', 'busy'), ('mark', 'available'),
        'availability', ('change', 'status'), ('turn', 'off'),
        ('am i', 'available'), ('on leave',),
    ), availability),

    Intent('payout_status', (
        'payout', 'payout status', ('when', 'paid'), ('when', 'payment'),
        ('money', 'not received'), ('not received', 'payment'),
        ('my', 'earning'), 'my earnings', ('how much', 'earned'),
        ('payment', 'pending'), ('release', 'payment'),
        ('when', 'money'), ('get', 'money'), ('my', 'money'),
    ), payout_status),

    Intent('bank_state', (
        ('bank', 'account'), ('bank', 'detail'), ('add', 'bank'),
        ('bank account', 'verified'), ('bank account', 'approved'),
        'account number', ('change', 'bank'), ('upi', 'id'),
    ), bank_state),

    Intent('my_bids', (
        'my bids', 'my bid', ('did i', 'win'), ('bid', 'status'),
        ('show', 'bid'), ('my', 'quotation'),
    ), my_bids),

    Intent('open_tenders', (
        ('new', 'project'), ('any', 'project'), ('open', 'project'),
        ('new', 'tender'), ('any', 'tender'), ('available', 'tender'),
        ('project', 'bid on'),
    ), open_tenders),

    Intent('bid_fee', (
        ('fee', 'bid'), ('commission',), ('deduct', 'bid'),
        ('cut', 'bid'), 'confirmation fee', 'platform fee',
        ('percent', 'bid'), ('charge', 'bid'),
    ), bid_fee),

    Intent('subscription', (
        'my plan', 'subscription', ('upgrade', 'plan'), ('plan', 'expire'),
        ('which', 'plan'), ('subscription', 'status'), ('membership',),
    ), subscription),

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
