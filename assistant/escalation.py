"""
Handing a chat to a human.

The assistant's most important feature is knowing when to stop. This turns a
conversation into a real `support.SupportTicket`, so the handover lands in the
inbox the support team already works out of -- no second queue, no chat
nobody is watching.

The whole transcript goes in as one message from the requester rather than as
one ticket message per turn. `TicketMessage.Sender` has three values and none
of them is "a bot", so splitting the transcript would mean filing the
assistant's words as either the customer's or an admin's. Both are untrue, and
in a ticket a support agent is about to answer, untrue is worse than long.
"""

from django.utils import timezone

from accounts.models import User

from .models import Conversation, Message

#: Which support category a handover lands in, by the intent that gave up.
#: Anything not here is OTHER -- a wrong category is a mis-routed ticket, so
#: only the obvious ones are mapped.
_CATEGORY_BY_INTENT = {
    'payment_status': 'PAYMENT',
    'refund': 'PAYMENT',
    'booking_status': 'BOOKING',
    'booking_list': 'BOOKING',
    'cancel_booking': 'BOOKING',
    'reschedule_booking': 'BOOKING',
    'vendor_details': 'VENDOR',
}


class CannotEscalate(Exception):
    """This conversation has no human to hand over to."""


class NoProfile(Exception):
    """
    The signed-in user has no profile to chat as.

    Shouldn't happen -- signing up creates the profile -- but a hand-made
    account can reach the endpoint without one, and a 500 is the wrong way to
    say so.
    """


def subject_for(conversation):
    """
    A subject line taken from what the person actually asked first.

    Their own words, trimmed to fit: a ticket list full of "Assistant
    handover" tells the support team nothing.
    """
    first = conversation.messages.filter(role=Message.Role.USER).first()
    if first is None:
        return 'Help from the assistant'

    text = ' '.join(first.text.split())
    if len(text) > 120:
        text = text[:119] + '…'
    return text or 'Help from the assistant'


def category_for(conversation):
    """The support category this chat belongs in."""
    from support.models import SupportTicket

    last_bot = conversation.messages.filter(
        role=Message.Role.BOT,
    ).exclude(intent='').last()

    guessed = _CATEGORY_BY_INTENT.get(getattr(last_bot, 'intent', ''), 'OTHER')

    # A category only one audience is allowed to raise must not be handed to
    # the other one -- VENDOR is a customer's category, not a vendor's.
    allowed = (
        SupportTicket.VENDOR_CATEGORIES
        if conversation.audience == Conversation.Audience.VENDOR
        else SupportTicket.CUSTOMER_CATEGORIES
    )
    return guessed if guessed in allowed else SupportTicket.Category.OTHER


def transcript_text(conversation):
    """The chat as one readable block for the support agent."""
    lines = ['Handed over from the in-app assistant.', '']
    for message in conversation.messages.all():
        who = 'Me' if message.role == Message.Role.USER else 'Assistant'
        body = message.text.replace('\n', '\n    ')
        lines.append(f'{who}: {body}')
    return '\n'.join(lines)


def escalate(conversation):
    """
    Open a support ticket for this conversation, or return the one it has.

    Idempotent on purpose: the app offers the handover button next to every
    answer the assistant was unsure about, so a person tapping it twice must
    not raise two tickets about one problem.
    """
    from support.models import SupportTicket, TicketMessage
    from support.notifications import notify_admins_new_ticket

    if conversation.escalated_ticket_id:
        return conversation.escalated_ticket

    if conversation.audience == Conversation.Audience.ADMIN:
        raise CannotEscalate('An admin chat has nobody to escalate to.')

    is_vendor = conversation.audience == Conversation.Audience.VENDOR
    ticket = SupportTicket.objects.create(
        customer=None if is_vendor else conversation.customer,
        vendor=conversation.vendor if is_vendor else None,
        raised_by=(
            SupportTicket.RaisedBy.VENDOR if is_vendor
            else SupportTicket.RaisedBy.CUSTOMER
        ),
        subject=subject_for(conversation),
        category=category_for(conversation),
    )
    TicketMessage.objects.create(
        ticket=ticket,
        sender=(
            TicketMessage.Sender.VENDOR if is_vendor
            else TicketMessage.Sender.CUSTOMER
        ),
        message=transcript_text(conversation),
    )

    conversation.escalated_ticket = ticket
    conversation.escalated_at = timezone.now()
    conversation.save(update_fields=['escalated_ticket', 'escalated_at', 'updated_at'])

    notify_admins_new_ticket(ticket)
    return ticket


# ---------------------------------------------------------------------------
# Finding the conversation for a request
# ---------------------------------------------------------------------------

def audience_for(user):
    """Which catalogue answers this user, from their role and nothing else."""
    if user.role == User.Role.VENDOR:
        return Conversation.Audience.VENDOR
    if user.role == User.Role.ADMIN:
        return Conversation.Audience.ADMIN
    return Conversation.Audience.CUSTOMER


def conversation_for(user):
    """
    This user's running chat, started if they have none.

    One open conversation per person rather than a thread per question: the
    apps show a single assistant screen, and a person reopening it expects
    what they asked yesterday to still be there.

    A conversation that has been handed to support is left closed and a fresh
    one is started, so a new question does not get appended to a transcript a
    support agent has already read.
    """
    audience = audience_for(user)
    party = {
        Conversation.Audience.VENDOR: {'vendor': getattr(user, 'vendor_profile', None)},
        Conversation.Audience.ADMIN: {'admin_user': user},
        Conversation.Audience.CUSTOMER: {'customer': getattr(user, 'customer_profile', None)},
    }[audience]

    if next(iter(party.values())) is None:
        raise NoProfile(
            f'{user.username} has no {audience.lower()} profile to chat as.'
        )

    existing = Conversation.objects.filter(
        audience=audience, escalated_at__isnull=True, **party
    ).order_by('-updated_at').first()
    if existing is not None:
        return existing

    return Conversation.objects.create(audience=audience, **party)


def latest_conversation(user):
    """
    This user's most recent chat, handed-over ones included, or None.

    Separate from `conversation_for` because the two want opposite things of
    an escalated chat. Asking a question wants a fresh one; tapping "talk to
    a human" a second time wants the one that was just handed over, so the
    answer is the ticket number they already have rather than a new ticket on
    an empty chat.
    """
    audience = audience_for(user)
    party = {
        Conversation.Audience.VENDOR: {'vendor': getattr(user, 'vendor_profile', None)},
        Conversation.Audience.ADMIN: {'admin_user': user},
        Conversation.Audience.CUSTOMER: {'customer': getattr(user, 'customer_profile', None)},
    }[audience]

    if next(iter(party.values())) is None:
        return None

    return Conversation.objects.filter(
        audience=audience, **party
    ).order_by('-updated_at').first()
