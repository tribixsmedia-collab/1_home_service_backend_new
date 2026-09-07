from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from accounts.token_serializers import AppTokenObtainPairView

urlpatterns = [
    # Public legal pages: /privacy/, /terms/, /data-deletion/. Before the
    # dashboard include so a page name can never be shadowed by it.
    path('', include('legal.urls')),

    path('', include('dashboard.urls')),
    path('hjssjiasjci/', admin.site.urls),

    # Login endpoints used by BOTH the Customer app and the Vendor app.
    # POST username + password -> get back access + refresh tokens.
    # Vendors are additionally refused until an admin verifies their profile.
    path('api/token/', AppTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # App-specific APIs
    path('api/auth/', include('accounts.urls')),
    path('api/services/', include('services.urls')),
    path('api/customers/', include('customers.urls')),
    path('api/vendors/', include('vendors.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/promotions/', include('promotions.urls')),
    path('api/home/', include('home_sections.urls')),
    path('api/curations/', include('curations.urls')),
    path('api/forms/', include('service_forms.urls')),
    path('api/reviews/', include('reviews.urls')),
    path('api/discounts/', include('discounts.urls')),
    path('api/support/', include('support.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/referrals/', include('referrals.urls')),
    path('api/branding/', include('branding.urls')),
    path('api/tenders/', include('tenders.urls')),
    path('api/subscriptions/', include('subscriptions.urls')),
    path('api/maps/', include('maps.urls')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
