from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='dashboard_login'),
    path('logout/', views.logout_view, name='dashboard_logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Bookings
    path('bookings/', views.bookings_list_view, name='bookings_list'),
    path('bookings/<int:booking_id>/', views.booking_detail_view, name='booking_detail'),
    path('bookings/<int:booking_id>/assign-vendor/', views.assign_vendor_view, name='assign_vendor'),
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking_view, name='cancel_booking'),
    path('bookings/<int:booking_id>/reschedule/', views.reschedule_booking_view, name='reschedule_booking'),
    path('bookings/<int:booking_id>/update-payment/', views.update_payment_view, name='update_payment'),

    # Gateway payments (Razorpay)
    path('payments/', views.payments_list_view, name='payments_list'),
    path('payments/<int:payment_id>/release/', views.release_payment_view, name='release_payment'),
    path('payments/<int:payment_id>/refund/', views.refund_payment_view, name='refund_payment'),
    path('vendors/<int:vendor_id>/verify-bank-account/', views.verify_bank_account_view, name='verify_bank_account'),
    path('vendors/<int:vendor_id>/validate-bank-account/', views.validate_bank_account_view, name='validate_bank_account'),
    path('payments/<int:payment_id>/retry-payout/', views.retry_payout_view, name='retry_payout'),
    # Tenders (customer-posted requirements vendors bid on)
    path('tenders/', views.tenders_list_view, name='tenders_list'),
    path('tenders/settings/', views.tender_settings_view, name='tender_settings'),
    path('tenders/<int:tender_id>/', views.tender_detail_view, name='tender_detail'),
    path('tenders/<int:tender_id>/approve/', views.tender_approve_view, name='tender_approve'),
    path('tenders/<int:tender_id>/reject/', views.tender_reject_view, name='tender_reject'),
    path('tenders/<int:tender_id>/award/', views.tender_award_view, name='tender_award'),
    path('tenders/<int:tender_id>/cancel/', views.tender_cancel_view, name='tender_cancel'),
    path('tenders/<int:tender_id>/release-selection/',
         views.tender_release_selection_view, name='tender_release_selection'),

    # Vendors
    path('vendors/', views.vendors_list_view, name='vendors_list'),
    path('vendors/add/', views.vendor_add_view, name='vendor_add'),
    path('vendors/<int:vendor_id>/', views.vendor_detail_view, name='vendor_detail'),
    path('vendors/<int:vendor_id>/edit/', views.vendor_edit_view, name='vendor_edit'),
    path('vendors/<int:vendor_id>/verify/', views.verify_vendor_view, name='verify_vendor'),
    path('vendors/<int:vendor_id>/documents/<int:doc_id>/', views.vendor_document_view, name='vendor_document'),

    # Vendor Subscriptions
    path('subscription-plans/', views.subscription_plans_list_view, name='subscription_plans_list'),
    path('subscription-plans/add/', views.subscription_plan_add_view, name='subscription_plan_add'),
    path('subscription-plans/<int:plan_id>/edit/', views.subscription_plan_edit_view, name='subscription_plan_edit'),
    path('subscription-plans/<int:plan_id>/toggle/', views.subscription_plan_toggle_view, name='subscription_plan_toggle'),
    path('subscription-plans/<int:plan_id>/delete/', views.subscription_plan_delete_view, name='subscription_plan_delete'),
    path('subscribers/', views.subscribers_list_view, name='subscribers_list'),
    path('subscribers/assign/', views.subscription_assign_view, name='subscription_assign'),
    path('subscriptions/<int:subscription_id>/renew/', views.subscription_renew_view, name='subscription_renew'),
    path('subscriptions/<int:subscription_id>/cancel/', views.subscription_cancel_view, name='subscription_cancel'),
    path('vendors/<int:vendor_id>/subscription/', views.vendor_subscription_view, name='vendor_subscription'),
    path('subscription-requests/', views.subscription_requests_list_view, name='subscription_requests_list'),
    path('subscription-requests/<int:request_id>/approve/', views.subscription_request_approve_view, name='subscription_request_approve'),
    path('subscription-requests/<int:request_id>/reject/', views.subscription_request_reject_view, name='subscription_request_reject'),

    # Categories
    path('categories/', views.categories_list_view, name='categories_list'),
    path('categories/add/', views.category_add_view, name='category_add'),
    path('categories/<int:category_id>/edit/', views.category_edit_view, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'),

    # Subcategories
    path('categories/<int:category_id>/subcategories/', views.subcategories_list_view, name='subcategories_list'),
    path('categories/<int:category_id>/subcategories/add/', views.subcategory_add_view, name='subcategory_add'),
    path('subcategories/<int:subcategory_id>/edit/', views.subcategory_edit_view, name='subcategory_edit'),
    path('subcategories/<int:subcategory_id>/delete/', views.subcategory_delete_view, name='subcategory_delete'),

    # Services
    path('categories/<int:category_id>/services/', views.services_list_view, name='services_list_cat'),
    path('subcategories/<int:subcategory_id>/services/', views.services_list_view, name='services_list_sub'),
    path('categories/<int:category_id>/services/add/', views.service_add_view, name='service_add_cat'),
    path('subcategories/<int:subcategory_id>/services/add/', views.service_add_view, name='service_add_sub'),
    path('services/<int:service_id>/edit/', views.service_edit_view, name='service_edit'),
    path('services/<int:service_id>/delete/', views.service_delete_view, name='service_delete'),


    # App branding
    path('branding/', views.branding_view, name='branding'),

    # Refer & Earn
    path('referrals/', views.referrals_list_view, name='referrals_list'),
    path('referrals/settings/', views.referral_settings_view, name='referral_settings'),
    path('referrals/<int:referral_id>/settle/', views.referral_settle_view, name='referral_settle'),

    # Promo Cards (large home page cards around the home sections)
    path('promo-cards/', views.promo_cards_list_view, name='promo_cards_list'),
    path('promo-cards/add/', views.promo_card_add_view, name='promo_card_add'),
    path('promo-cards/<int:card_id>/edit/', views.promo_card_edit_view, name='promo_card_edit'),
    path('promo-cards/<int:card_id>/delete/', views.promo_card_delete_view, name='promo_card_delete'),
    path('promo-cards/<int:card_id>/toggle/', views.promo_card_toggle_view, name='promo_card_toggle'),

    # Header Banners (home hero carousel)
    path('header-banners/', views.header_banners_list_view, name='header_banners_list'),
    path('header-banners/add/', views.header_banner_add_view, name='header_banner_add'),
    path('header-banners/<int:banner_id>/edit/', views.header_banner_edit_view, name='header_banner_edit'),
    path('header-banners/<int:banner_id>/delete/', views.header_banner_delete_view, name='header_banner_delete'),
    path('header-banners/<int:banner_id>/toggle/', views.header_banner_toggle_view, name='header_banner_toggle'),

    # Spotlights
    path('spotlights/', views.spotlights_list_view, name='spotlights_list'),
    path('spotlights/add/', views.spotlight_add_view, name='spotlight_add'),
    path('spotlights/<int:spotlight_id>/edit/', views.spotlight_edit_view, name='spotlight_edit'),
    path('spotlights/<int:spotlight_id>/delete/', views.spotlight_delete_view, name='spotlight_delete'),
    path('spotlights/<int:spotlight_id>/toggle/', views.spotlight_toggle_view, name='spotlight_toggle'),

    # Home Sections
    path('home-sections/', views.home_sections_list_view, name='home_sections_list'),
    path('home-sections/add/', views.home_section_add_view, name='home_section_add'),
    path('home-sections/<int:section_id>/', views.home_section_detail_view, name='home_section_detail'),
    path('home-sections/<int:section_id>/edit/', views.home_section_edit_view, name='home_section_edit'),
    path('home-sections/<int:section_id>/delete/', views.home_section_delete_view, name='home_section_delete'),
    path('home-sections/<int:section_id>/add-item/', views.home_section_add_item_view, name='home_section_add_item'),
    path('home-section-items/<int:item_id>/remove/', views.home_section_remove_item_view, name='home_section_remove_item'),
    path('home-section-items/<int:item_id>/reorder/', views.home_section_reorder_view, name='home_section_reorder'),



    # Pro Vendors (customer-facing vendor showcase)
    path('pro-vendors/', views.pro_vendors_list_view, name='pro_vendors_list'),
    path('pro-vendors/<int:vendor_id>/toggle/', views.pro_vendor_toggle_view, name='pro_vendor_toggle'),

    # Pro Vendor Sections
    path('pro-vendor-sections/', views.pro_vendor_sections_list_view, name='pro_vendor_sections_list'),
    path('pro-vendor-sections/add/', views.pro_vendor_section_add_view, name='pro_vendor_section_add'),
    path('pro-vendor-sections/<int:section_id>/', views.pro_vendor_section_detail_view, name='pro_vendor_section_detail'),
    path('pro-vendor-sections/<int:section_id>/edit/', views.pro_vendor_section_edit_view, name='pro_vendor_section_edit'),
    path('pro-vendor-sections/<int:section_id>/delete/', views.pro_vendor_section_delete_view, name='pro_vendor_section_delete'),
    path('pro-vendor-sections/<int:section_id>/add-vendor/', views.pro_vendor_section_add_item_view, name='pro_vendor_section_add_item'),
    path('pro-vendor-section-items/<int:item_id>/remove/', views.pro_vendor_section_remove_item_view, name='pro_vendor_section_remove_item'),
    path('pro-vendor-section-items/<int:item_id>/reorder/', views.pro_vendor_section_reorder_view, name='pro_vendor_section_reorder'),

    # Curations
    path('curations/', views.curations_list_view, name='curations_list'),
    path('curations/add/', views.curation_section_add_view, name='curation_section_add'),
    path('curations/<int:section_id>/', views.curation_section_detail_view, name='curation_section_detail'),
    path('curations/<int:section_id>/edit/', views.curation_section_edit_view, name='curation_section_edit'),
    path('curations/<int:section_id>/delete/', views.curation_section_delete_view, name='curation_section_delete'),
    path('curations/<int:section_id>/add-video/', views.curation_item_add_view, name='curation_item_add'),
    path('curation-items/<int:item_id>/edit/', views.curation_item_edit_view, name='curation_item_edit'),
    path('curation-items/<int:item_id>/delete/', views.curation_item_delete_view, name='curation_item_delete'),



    # Service Forms
    path('forms/', views.forms_list_view, name='forms_list'),
    path('forms/add/', views.form_add_view, name='form_add'),
    path('forms/<int:form_id>/', views.form_detail_view, name='form_detail'),
    path('forms/<int:form_id>/edit/', views.form_edit_view, name='form_edit'),
    path('forms/<int:form_id>/delete/', views.form_delete_view, name='form_delete'),
    path('forms/<int:form_id>/submissions/', views.form_submissions_view, name='form_submissions'),
    path('forms/<int:form_id>/add-step/', views.form_step_add_view, name='form_step_add'),
    path('form-steps/<int:step_id>/edit/', views.form_step_edit_view, name='form_step_edit'),
    path('form-steps/<int:step_id>/delete/', views.form_step_delete_view, name='form_step_delete'),
    path('form-steps/<int:step_id>/reorder/', views.form_step_reorder_view, name='form_step_reorder'),

    # Discounts
    path('discounts/', views.discounts_list_view, name='discounts_list'),
    path('discounts/add/', views.discount_add_view, name='discount_add'),
    path('discounts/<int:discount_id>/edit/', views.discount_edit_view, name='discount_edit'),
    path('discounts/<int:discount_id>/delete/', views.discount_delete_view, name='discount_delete'),

    # Coupons
    path('coupons/', views.coupons_list_view, name='coupons_list'),
    path('coupons/add/', views.coupon_add_view, name='coupon_add'),
    path('coupons/<int:coupon_id>/edit/', views.coupon_edit_view, name='coupon_edit'),
    path('coupons/<int:coupon_id>/delete/', views.coupon_delete_view, name='coupon_delete'),
    path('coupons/<int:coupon_id>/usage/', views.coupon_usage_view, name='coupon_usage'),

    # Reports
    path('reports/', views.reports_view, name='reports'),

    # Customers
    path('customers/', views.customers_list_view, name='customers_list'),
    path('customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),

    # Roles (admin names a role and picks what it can reach)
    path('roles/', views.roles_list_view, name='roles_list'),
    path('roles/add/', views.role_add_view, name='role_add'),
    path('roles/<int:role_id>/edit/', views.role_edit_view, name='role_edit'),
    path('roles/<int:role_id>/delete/', views.role_delete_view, name='role_delete'),

    # Dashboard users (username + password + a role)
    path('admin-users/', views.admin_users_list_view, name='admin_users_list'),
    path('admin-users/add/', views.admin_user_add_view, name='admin_user_add'),
    path('admin-users/<int:user_id>/edit/', views.admin_user_edit_view, name='admin_user_edit'),
    path('admin-users/<int:user_id>/password/', views.admin_user_password_view, name='admin_user_password'),
    path('admin-users/<int:user_id>/delete/', views.admin_user_delete_view, name='admin_user_delete'),

    # Which map every screen draws, and the Google key behind it
    path('settings/maps/', views.map_settings_view, name='map_settings'),

    # Sign-in log and lockouts
    path('login-security/', views.login_security_view, name='login_security'),
    path('login-security/unlock/', views.login_security_unlock_view, name='login_security_unlock'),
    path('support/', views.support_tickets_view, name='support_tickets'),
    path('support/<int:ticket_id>/', views.support_ticket_detail_view, name='support_ticket_detail'),

    # AI assistant: what it was asked, and what it is allowed to answer
    path('assistant/', views.assistant_conversations_view, name='assistant_conversations'),
    path('assistant/settings/', views.assistant_settings_view, name='assistant_settings'),
    path('assistant/ask/', views.assistant_admin_chat_view, name='assistant_admin_chat'),
    path('assistant/answers/', views.assistant_knowledge_list_view, name='assistant_knowledge_list'),
    path('assistant/answers/add/', views.assistant_knowledge_add_view, name='assistant_knowledge_add'),
    path('assistant/answers/<int:entry_id>/edit/', views.assistant_knowledge_edit_view, name='assistant_knowledge_edit'),
    path('assistant/answers/<int:entry_id>/delete/', views.assistant_knowledge_delete_view, name='assistant_knowledge_delete'),
    path('assistant/answers/<int:entry_id>/toggle/', views.assistant_knowledge_toggle_view, name='assistant_knowledge_toggle'),
    path('assistant/<int:conversation_id>/', views.assistant_conversation_detail_view, name='assistant_conversation_detail'),
    path('assignment-center/', views.assignment_center_view, name='assignment_center'),
    path('bookings/<int:booking_id>/auto-assign/', views.auto_assign_view, name='auto_assign'),
    path('bulk-auto-assign/', views.bulk_auto_assign_view, name='bulk_auto_assign'),
    
]