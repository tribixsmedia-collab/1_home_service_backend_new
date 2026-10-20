from django.contrib import admin

from .models import AssistantSettings, Conversation, KnowledgeEntry, Message


@admin.register(KnowledgeEntry)
class KnowledgeEntryAdmin(admin.ModelAdmin):
    list_display = ['question', 'audience', 'is_active', 'sort_order']
    list_filter = ['audience', 'is_active']
    search_fields = ['question', 'keywords', 'answer']


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ['role', 'text', 'intent', 'engine', 'tool_calls',
                       'tokens_used', 'created_at']
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'audience', 'party_name', 'message_count',
                    'is_escalated', 'updated_at']
    list_filter = ['audience']
    inlines = [MessageInline]


admin.site.register(AssistantSettings)
