from django.urls import path

from .views import AskView, AssistantSessionView, EscalateView

urlpatterns = [
    path('session/', AssistantSessionView.as_view(), name='assistant-session'),
    path('ask/', AskView.as_view(), name='assistant-ask'),
    path('escalate/', EscalateView.as_view(), name='assistant-escalate'),
]
