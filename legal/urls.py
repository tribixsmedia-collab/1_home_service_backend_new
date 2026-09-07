"""
Public legal pages. No authentication, deliberately.

Google Play refuses a listing without a privacy policy reachable by anyone,
and its account-deletion policy requires a public URL a person can use without
installing the app or signing in. Both are checked by a reviewer following the
link from a signed-out browser, so nothing here may sit behind a login.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('privacy/', views.privacy_view, name='privacy_policy'),
    path('terms/', views.terms_view, name='terms_of_service'),
    path('data-deletion/', views.data_deletion_view, name='data_deletion'),
]
