"""
What the apps see of a conversation.

The audit fields -- which tool was read, which rule fired, what it cost -- are
deliberately left out. They are for the dashboard, where somebody is working
out why the assistant said what it said. In the app they would only be
something to screenshot.
"""

from rest_framework import serializers

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    is_bot = serializers.BooleanField(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'role', 'is_bot', 'text', 'created_at']


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    is_escalated = serializers.BooleanField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            'id', 'audience', 'is_escalated', 'escalated_ticket',
            'started_at', 'updated_at', 'messages',
        ]


class AskSerializer(serializers.Serializer):
    """One question from the app."""

    question = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate_question(self, value):
        if not value.strip():
            raise serializers.ValidationError('Type a question first.')
        return value.strip()
