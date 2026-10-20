"""
What the in-app assistant is, remembers, and is allowed to say.

Four tables:

  AssistantSettings  -- one row. Which engine answers, who the assistant is
                        switched on for, and the caps that stop it running
                        away with somebody's money.
  KnowledgeEntry     -- the answer book. Admin-written questions and answers
                        the assistant may quote verbatim.
  Conversation       -- one running chat, belonging to exactly one customer,
                        vendor or dashboard admin.
  Message            -- a turn in it, with the audit trail of what the
                        assistant read to answer.

The assistant deliberately has no table of its own facts about bookings,
payments or payouts. Everything it says about those is read live through
`assistant.tools`, scoped to the asker, at the moment it answers -- so a
transcript can go stale but an answer never can.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AssistantSettings(models.Model):
    """
    One row, edited from the dashboard.

    `engine` is the switch this whole app is built around. The rules engine
    costs nothing and runs offline; Claude costs money per question and needs
    a key. Picking Claude without a key reads back as the rules engine rather
    than failing, exactly as a map with no Google key keeps drawing the free
    basemap -- a half-finished setup leaves a working assistant.
    """

    class Engine(models.TextChoices):
        RULES = 'RULES', 'Rules engine (free)'
        CLAUDE = 'CLAUDE', 'Claude AI (paid API)'

    engine = models.CharField(
        max_length=10, choices=Engine.choices, default=Engine.RULES,
        help_text='Which engine answers. The rules engine is free and needs '
                  'no key.',
    )

    # Who it is switched on for. Each app checks its own flag, so the
    # assistant can be trialled with vendors before customers ever see it.
    customer_enabled = models.BooleanField(
        default=True, help_text='Show the assistant in the customer app.',
    )
    vendor_enabled = models.BooleanField(
        default=True, help_text='Show the assistant in the vendor app.',
    )
    admin_enabled = models.BooleanField(
        default=True, help_text='Let dashboard users ask the assistant.',
    )

    # --- Caps --------------------------------------------------------------
    #
    # The rules engine costs nothing, so these only bite once Claude is on.
    # They are enforced anyway: a runaway client looping on the endpoint is
    # the same problem whether or not each question is billable.
    daily_message_limit = models.PositiveIntegerField(
        default=50,
        help_text='Most questions one person may ask in a day. 0 removes the '
                  'limit.',
    )

    # --- Claude, for when the engine is switched over -----------------------
    claude_api_key = models.CharField(
        max_length=200, blank=True,
        help_text='Anthropic API key. Without one the rules engine keeps '
                  'answering.',
    )
    claude_model = models.CharField(
        max_length=60, default='claude-haiku-5-5',
        help_text='Which Claude model to bill against.',
    )
    monthly_token_cap = models.PositiveIntegerField(
        default=0,
        help_text='Stop calling Claude once this many tokens have been spent '
                  'this month. 0 removes the cap.',
    )

    # --- Wording the admin owns -------------------------------------------
    greeting = models.TextField(
        default="Hi! I can help with your bookings, payments and our "
                "services. What do you need?",
        help_text='First thing the assistant says in a new chat.',
    )
    fallback_message = models.TextField(
        default="I'm not sure about that one. I can pass this to our support "
                "team, who will reply in the app.",
        help_text='Shown when nothing in the answer book matches.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Assistant Settings'
        verbose_name_plural = 'Assistant Settings'

    def __str__(self):
        return f'Assistant Settings ({self.get_engine_display()})'

    @classmethod
    def get_solo(cls):
        """The one and only settings row, created with defaults on first use."""
        settings_row, _ = cls.objects.get_or_create(pk=1)
        return settings_row

    # ------------------------------------------------------------------
    # What is actually in force
    # ------------------------------------------------------------------

    @property
    def effective_engine(self):
        """
        The engine that can really answer right now.

        Claude with no key is not Claude, it is a 401, so it reads back as the
        rules engine until somebody pastes one in.
        """
        if self.engine == self.Engine.CLAUDE and self.claude_api_key.strip():
            return self.Engine.CLAUDE
        return self.Engine.RULES

    @property
    def is_awaiting_key(self):
        """Claude was picked but no key was pasted, so the rules engine runs."""
        return self.engine == self.Engine.CLAUDE and not self.claude_api_key.strip()

    def enabled_for(self, audience):
        """Whether the assistant answers this audience at all."""
        return {
            Conversation.Audience.CUSTOMER: self.customer_enabled,
            Conversation.Audience.VENDOR: self.vendor_enabled,
            Conversation.Audience.ADMIN: self.admin_enabled,
        }.get(audience, False)


class KnowledgeEntry(models.Model):
    """
    One admin-written question and its answer.

    This is the only text the assistant is allowed to produce that nobody on
    the team wrote: there isn't any. An intent answers from live data, and
    everything else comes from a row here, word for word. That is what makes
    the rules engine safe to point at customers -- it cannot invent a refund
    policy, because it has no way to write a sentence.

    `keywords` is the slack in the system. The question itself is matched, but
    real people ask "my guy never showed up" rather than "what happens if the
    vendor does not arrive", so the admin lists the words they actually use.
    """

    class Audience(models.TextChoices):
        ALL = 'ALL', 'Everyone'
        CUSTOMER = 'CUSTOMER', 'Customers only'
        VENDOR = 'VENDOR', 'Vendors only'

    question = models.CharField(
        max_length=200,
        help_text='The question as you would write it. Shown to the person '
                  'when the assistant offers related topics.',
    )
    keywords = models.CharField(
        max_length=300, blank=True,
        help_text='Comma-separated words that should also find this answer, '
                  'in the words customers actually use.',
    )
    answer = models.TextField(
        help_text='Sent to the person exactly as written. Keep it short.',
    )
    audience = models.CharField(
        max_length=10, choices=Audience.choices, default=Audience.ALL,
        help_text='Who may be given this answer.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Switch off to retire an answer without deleting it.',
    )
    sort_order = models.PositiveIntegerField(
        default=0, help_text='Lower number = offered first.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'question']
        verbose_name = 'Answer book entry'
        verbose_name_plural = 'Answer book'

    def __str__(self):
        return self.question

    @property
    def keyword_list(self):
        return [word.strip() for word in self.keywords.split(',') if word.strip()]

    def serves(self, audience):
        """Whether this entry may be given to `audience`."""
        if self.audience == self.Audience.ALL:
            return True
        return self.audience == audience


class Conversation(models.Model):
    """
    One running chat with the assistant.

    Belongs to exactly one party, and `audience` says which -- the same shape
    `support.SupportTicket` uses, and for the same reason: every queryset
    filters on one column instead of testing three foreign keys. The database
    constraint keeps `audience` honest about which column is filled.
    """

    class Audience(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        VENDOR = 'VENDOR', 'Vendor'
        ADMIN = 'ADMIN', 'Admin'

    audience = models.CharField(
        max_length=10, choices=Audience.choices, db_index=True,
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE,
        null=True, blank=True, related_name='assistant_conversations',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        null=True, blank=True, related_name='assistant_conversations',
    )
    # A dashboard user rather than an AdminProfile: the profile can be deleted
    # while the transcript it produced is still worth keeping.
    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='assistant_conversations',
    )

    # Set when the assistant gave up and handed the chat to a human. Having it
    # here is what lets the dashboard show "the bot could not answer these".
    escalated_ticket = models.ForeignKey(
        'support.SupportTicket', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assistant_conversations',
    )
    escalated_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['audience', '-updated_at'])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        audience='CUSTOMER',
                        customer__isnull=False,
                        vendor__isnull=True,
                        admin_user__isnull=True,
                    )
                    | models.Q(
                        audience='VENDOR',
                        customer__isnull=True,
                        vendor__isnull=False,
                        admin_user__isnull=True,
                    )
                    | models.Q(
                        audience='ADMIN',
                        customer__isnull=True,
                        vendor__isnull=True,
                        admin_user__isnull=False,
                    )
                ),
                name='assistant_conversation_party_matches_audience',
            ),
        ]

    def __str__(self):
        return f'Chat #{self.id} with {self.party_name}'

    # ------------------------------------------------------------- the party
    @property
    def party(self):
        """The Customer, Vendor or User this chat belongs to."""
        if self.audience == self.Audience.VENDOR:
            return self.vendor
        if self.audience == self.Audience.ADMIN:
            return self.admin_user
        return self.customer

    @property
    def party_user(self):
        """The `accounts.User` behind the party, whichever kind it is."""
        party = self.party
        if self.audience == self.Audience.ADMIN:
            return party
        return getattr(party, 'user', None)

    @property
    def party_name(self):
        user = self.party_user
        if user is None:
            return 'Unknown'
        return user.get_full_name() or user.username

    @property
    def party_phone(self):
        return getattr(self.party_user, 'phone_number', '') or ''

    # ------------------------------------------------------------- transcript
    @property
    def last_message(self):
        return self.messages.last()

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def is_escalated(self):
        return self.escalated_at is not None

    @property
    def unanswered_count(self):
        """
        How many questions the assistant could not answer.

        The number the admin actually wants: a chat full of these is a gap in
        the answer book, and the detail page shows which questions they were.
        """
        return self.messages.filter(intent=Message.FALLBACK_INTENT).count()

    def touch(self):
        """Bump `updated_at` so the dashboard list sorts by recent activity."""
        self.save(update_fields=['updated_at'])


class Message(models.Model):
    """
    One turn in a conversation.

    Bot messages carry the audit trail: `intent` is the rule that fired,
    `tool_calls` is every piece of data it read to answer, and `tokens_used`
    is what it cost (always zero on the rules engine). Together those answer
    "why did it say that", which is the question any complaint about a bot
    comes down to.
    """

    #: `intent` on a bot message that nothing matched. Named because both the
    #: engine and the dashboard count these.
    FALLBACK_INTENT = 'fallback'

    class Role(models.TextChoices):
        USER = 'USER', 'Person'
        BOT = 'BOT', 'Assistant'

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages',
    )
    role = models.CharField(max_length=5, choices=Role.choices)
    text = models.TextField()

    # --- Audit, on bot messages only ---------------------------------------
    intent = models.CharField(
        max_length=50, blank=True,
        help_text='Which rule answered. Empty on a question.',
    )
    engine = models.CharField(
        max_length=10, blank=True,
        help_text='Which engine produced this answer.',
    )
    tool_calls = models.JSONField(
        default=list, blank=True,
        help_text='Every data reader this answer called, with its arguments.',
    )
    tokens_used = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['conversation', 'created_at'])]

    def __str__(self):
        return f'{self.get_role_display()} in chat #{self.conversation_id}'

    @property
    def is_bot(self):
        return self.role == self.Role.BOT

    @property
    def is_unanswered(self):
        return self.intent == self.FALLBACK_INTENT

    @property
    def tool_names(self):
        """Just the reader names, for the transcript's "read:" line."""
        return [
            call.get('name', '?')
            for call in (self.tool_calls or [])
            if isinstance(call, dict)
        ]


def questions_asked_today(user):
    """
    How many questions `user` has put to the assistant since midnight.

    Counted off Message rather than a counter column so it cannot drift, and
    scoped by the conversation's party rather than by a user id on the message
    -- a message has no author of its own, its conversation does.
    """
    start_of_day = timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return Message.objects.filter(
        role=Message.Role.USER,
        created_at__gte=start_of_day,
        conversation__in=Conversation.objects.filter(
            models.Q(customer__user=user)
            | models.Q(vendor__user=user)
            | models.Q(admin_user=user)
        ),
    ).count()
