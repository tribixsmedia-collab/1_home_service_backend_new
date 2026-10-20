"""
The assistant's API, for the customer app and the vendor app.

Admins are not served here. They reach the assistant from the dashboard, the
same way they reach everything else -- which is also why `IsCustomerOrVendor`
is the permission on every view in this file.

Three endpoints: read the chat, ask something, hand it to a human. The
audience is always taken from the authenticated user's role and never from
the request body, so there is no field an app could send that would make it
answer as somebody else.
"""

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCustomerOrVendor

from . import engine, escalation
from .intents import starters_for
from .models import AssistantSettings, Conversation, Message, questions_asked_today
from .serializers import AskSerializer, ConversationSerializer, MessageSerializer


#: Returned when the signed-in account has no customer or vendor profile.
NO_PROFILE_ERROR = {
    'error': 'Your account is not set up for the assistant yet.',
}


def _audience(request):
    return escalation.audience_for(request.user)


class AssistantSessionView(APIView):
    """
    Everything the chat screen needs to draw itself.

    Returns `enabled: false` rather than an error when the assistant is
    switched off for this audience, so the app can simply not show the entry
    point instead of handling a failure.
    """

    permission_classes = [IsCustomerOrVendor]

    def get(self, request):
        settings_row = AssistantSettings.get_solo()
        audience = _audience(request)

        if not settings_row.enabled_for(audience):
            return Response({'enabled': False})

        try:
            conversation = escalation.conversation_for(request.user)
        except escalation.NoProfile:
            return Response(NO_PROFILE_ERROR, status=403)

        return Response({
            'enabled': True,
            'greeting': settings_row.greeting,
            'suggestions': list(starters_for(audience)),
            'conversation': ConversationSerializer(conversation).data,
        })


class AskView(APIView):
    """Put one question to the assistant and store both turns."""

    permission_classes = [IsCustomerOrVendor]

    def post(self, request):
        settings_row = AssistantSettings.get_solo()
        audience = _audience(request)

        if not settings_row.enabled_for(audience):
            return Response(
                {'error': 'The assistant is not available right now.'},
                status=403,
            )

        limit = settings_row.daily_message_limit
        if limit and questions_asked_today(request.user) >= limit:
            # Checked before the engine runs: on the Claude engine this is the
            # line between a cap and a bill.
            return Response(
                {
                    'error': (
                        "You've reached today's limit for assistant questions. "
                        'Our support team can still help.'
                    ),
                    'limit_reached': True,
                },
                status=429,
            )

        form = AskSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        question = form.validated_data['question']

        try:
            conversation = escalation.conversation_for(request.user)
        except escalation.NoProfile:
            return Response(NO_PROFILE_ERROR, status=403)

        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            text=question,
        )

        answer = engine.ask(
            question,
            audience=audience,
            user=request.user,
            settings_row=settings_row,
        )

        reply = Message.objects.create(
            conversation=conversation,
            role=Message.Role.BOT,
            text=answer.text,
            intent=answer.intent,
            engine=answer.engine,
            tool_calls=answer.tool_calls,
            tokens_used=answer.tokens_used,
        )
        conversation.touch()

        return Response({
            'message': MessageSerializer(reply).data,
            'suggestions': list(answer.suggestions),
            'can_escalate': answer.escalate,
            'conversation_id': conversation.id,
        })


class EscalateView(APIView):
    """
    Hand the running chat to the support team.

    Tapping this twice is normal -- the button sits next to every answer the
    assistant was unsure about -- so the second tap answers with the ticket
    the first one opened instead of raising another.
    """

    permission_classes = [IsCustomerOrVendor]

    def post(self, request):
        # The latest chat, handed-over ones included: `conversation_for` would
        # start a fresh empty one, and escalating that is a blank ticket.
        conversation = escalation.latest_conversation(request.user)

        if conversation is None or not conversation.messages.exists():
            return Response(
                {'error': 'Ask something first, then I can pass it on.'},
                status=400,
            )

        already_had = conversation.escalated_ticket_id is not None
        ticket = escalation.escalate(conversation)

        return Response({
            'ticket_id': ticket.id,
            'subject': ticket.subject,
            'message': (
                f'Already with our support team on ticket #{ticket.id}.'
                if already_had else
                'Passed to our support team. They will reply on ticket '
                f'#{ticket.id} in the app.'
            ),
        }, status=200 if already_had else 201)
