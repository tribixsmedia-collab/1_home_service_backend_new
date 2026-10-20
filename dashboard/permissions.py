"""
The access catalogue for the admin dashboard.

Two things live here:

  PERMISSION_GROUPS  -- every access an admin can hand to a role, grouped the
                        way the sidebar is grouped so the role form reads like
                        the panel it controls.
  URL_PERMISSIONS    -- which access each dashboard URL needs.

Permissions are defined in code rather than in a database table on purpose:
they only mean anything because a view enforces them, so the list has to move
with the code. A role just stores the codes it was granted.

Enforcement is centralised in `dashboard.decorators.admin_login_required`,
which every dashboard view already wears. It looks the request's URL name up in
URL_PERMISSIONS, so a new view is covered the moment it is added to the map --
and `tests_access.py` fails the build if a URL is left out of it.
"""

# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# (group label, [(code, label, help text), ...])

PERMISSION_GROUPS = [
    ('Bookings', [
        ('bookings.view', 'View bookings',
         'See the booking list and open any booking.'),
        ('bookings.manage', 'Manage bookings',
         'Assign a vendor, cancel, reschedule, record a manual payment.'),
        ('bookings.assign', 'Assignment centre',
         'Use the assignment centre and run auto-assign.'),
    ]),
    ('Payments', [
        ('payments.view', 'View payments',
         'See gateway payments and their status.'),
        ('payments.manage', 'Manage payments',
         'Release money to vendors, refund a customer, retry a payout, '
         'verify vendor bank accounts.'),
    ]),
    ('Tenders', [
        ('tenders.view', 'View tenders',
         'See customer-posted tenders and the bids on them.'),
        ('tenders.manage', 'Manage tenders',
         'Approve, reject, award or cancel a tender, release a held '
         'selection, and set the confirmation fee.'),
    ]),
    ('Vendors', [
        ('vendors.view', 'View vendors',
         'See the vendor list and vendor profiles.'),
        ('vendors.manage', 'Manage vendors',
         'Add or edit a vendor, verify documents, feature a vendor as Pro.'),
    ]),
    ('Subscriptions', [
        ('subscriptions.view', 'View subscriptions',
         'See plans, subscribers and upgrade requests.'),
        ('subscriptions.manage', 'Manage subscriptions',
         'Create plans, assign or cancel a subscription, approve requests.'),
    ]),
    ('Catalogue', [
        ('catalogue.view', 'View catalogue',
         'See categories, subcategories and services.'),
        ('catalogue.manage', 'Manage catalogue',
         'Add, edit or delete categories, subcategories and services.'),
    ]),
    ('Home page & content', [
        ('content.view', 'View content',
         'See banners, spotlights, promo cards, home sections and curations.'),
        ('content.manage', 'Manage content',
         'Edit everything the customer app shows on its home page, plus app '
         'branding.'),
    ]),
    ('Service forms', [
        ('forms.view', 'View service forms',
         'See forms, their steps and submissions.'),
        ('forms.manage', 'Manage service forms',
         'Create and edit the multi-step forms customers fill in.'),
    ]),
    ('Discounts & coupons', [
        ('marketing.view', 'View discounts and coupons',
         'See discounts, coupons and coupon usage.'),
        ('marketing.manage', 'Manage discounts and coupons',
         'Create, edit and delete discounts and coupons.'),
    ]),
    ('Refer & earn', [
        ('referrals.view', 'View referrals',
         'See referrals and the reward settings.'),
        ('referrals.manage', 'Manage referrals',
         'Change reward settings and settle a referral payout.'),
    ]),
    ('Customers', [
        ('customers.view', 'View customers',
         'See the customer list and customer profiles.'),
    ]),
    ('Help & support', [
        ('support.view', 'View support tickets',
         'Read tickets raised by customers and vendors.'),
        ('support.manage', 'Answer support tickets',
         'Reply to a ticket and change its status.'),
    ]),
    ('AI assistant', [
        ('assistant.view', 'View assistant chats',
         'Read what customers and vendors asked the assistant, and what it '
         'answered.'),
        ('assistant.manage', 'Manage the assistant',
         'Write the answer book, and switch the assistant on or off per app.'),
    ]),
    ('Reports', [
        ('reports.view', 'View reports',
         'Open the reports page and its revenue figures.'),
    ]),
    ('System', [
        ('system.maps', 'Map settings',
         'Choose between the free map and Google Maps, and hold the '
         'Google API key.'),
        ('system.roles', 'Manage roles',
         'Create roles and choose what each one can reach.'),
        ('system.staff', 'Manage dashboard users',
         'Create dashboard logins, set their password and assign a role.'),
        ('system.security', 'Login security',
         'Review sign-in attempts and unlock a locked-out account.'),
    ]),
]

#: Every valid permission code, for validating what a role was saved with.
ALL_PERMISSIONS = frozenset(
    code for _group, entries in PERMISSION_GROUPS for code, _label, _help in entries
)

PERMISSION_LABELS = {
    code: label
    for _group, entries in PERMISSION_GROUPS
    for code, label, _help in entries
}


# ---------------------------------------------------------------------------
# URL -> permission
# ---------------------------------------------------------------------------
# A value is either a single code, or a {method: code} mapping for the handful
# of views that both show a page and accept an edit on the same URL.
#
# URLs reachable by every signed-in dashboard user carry None.

URL_PERMISSIONS = {
    # Always reachable once signed in
    'dashboard': None,
    'dashboard_logout': None,

    # Bookings
    'bookings_list': 'bookings.view',
    'booking_detail': 'bookings.view',
    'assign_vendor': 'bookings.manage',
    'cancel_booking': 'bookings.manage',
    'reschedule_booking': 'bookings.manage',
    'update_payment': 'bookings.manage',
    'assignment_center': 'bookings.assign',
    'auto_assign': 'bookings.assign',
    'bulk_auto_assign': 'bookings.assign',

    # Payments
    'payments_list': 'payments.view',
    'release_payment': 'payments.manage',
    'refund_payment': 'payments.manage',
    'retry_payout': 'payments.manage',
    'verify_bank_account': 'payments.manage',
    'validate_bank_account': 'payments.manage',

    # Tenders
    'tenders_list': 'tenders.view',
    'tender_detail': 'tenders.view',
    'tender_approve': 'tenders.manage',
    'tender_reject': 'tenders.manage',
    'tender_award': 'tenders.manage',
    'tender_cancel': 'tenders.manage',
    'tender_release_selection': 'tenders.manage',
    'tender_settings': {'GET': 'tenders.view', 'POST': 'tenders.manage'},

    # Vendors
    'vendors_list': 'vendors.view',
    'vendor_detail': 'vendors.view',
    'vendor_document': 'vendors.view',
    'vendor_add': 'vendors.manage',
    'vendor_edit': 'vendors.manage',
    'verify_vendor': 'vendors.manage',
    'pro_vendors_list': 'vendors.view',
    'pro_vendor_toggle': 'vendors.manage',

    # Subscriptions
    'subscription_plans_list': 'subscriptions.view',
    'subscribers_list': 'subscriptions.view',
    'subscription_requests_list': 'subscriptions.view',
    'vendor_subscription': 'subscriptions.view',
    'subscription_plan_add': 'subscriptions.manage',
    'subscription_plan_edit': 'subscriptions.manage',
    'subscription_plan_toggle': 'subscriptions.manage',
    'subscription_plan_delete': 'subscriptions.manage',
    'subscription_assign': 'subscriptions.manage',
    'subscription_renew': 'subscriptions.manage',
    'subscription_cancel': 'subscriptions.manage',
    'subscription_request_approve': 'subscriptions.manage',
    'subscription_request_reject': 'subscriptions.manage',

    # Catalogue
    'categories_list': 'catalogue.view',
    'subcategories_list': 'catalogue.view',
    'services_list_cat': 'catalogue.view',
    'services_list_sub': 'catalogue.view',
    'category_add': 'catalogue.manage',
    'category_edit': 'catalogue.manage',
    'category_delete': 'catalogue.manage',
    'subcategory_add': 'catalogue.manage',
    'subcategory_edit': 'catalogue.manage',
    'subcategory_delete': 'catalogue.manage',
    'service_add_cat': 'catalogue.manage',
    'service_add_sub': 'catalogue.manage',
    'service_edit': 'catalogue.manage',
    'service_delete': 'catalogue.manage',

    # Home page & content
    'branding': {'GET': 'content.view', 'POST': 'content.manage'},
    'header_banners_list': 'content.view',
    'spotlights_list': 'content.view',
    'promo_cards_list': 'content.view',
    'home_sections_list': 'content.view',
    'home_section_detail': 'content.view',
    'pro_vendor_sections_list': 'content.view',
    'pro_vendor_section_detail': 'content.view',
    'curations_list': 'content.view',
    'curation_section_detail': 'content.view',
    'header_banner_add': 'content.manage',
    'header_banner_edit': 'content.manage',
    'header_banner_delete': 'content.manage',
    'header_banner_toggle': 'content.manage',
    'spotlight_add': 'content.manage',
    'spotlight_edit': 'content.manage',
    'spotlight_delete': 'content.manage',
    'spotlight_toggle': 'content.manage',
    'promo_card_add': 'content.manage',
    'promo_card_edit': 'content.manage',
    'promo_card_delete': 'content.manage',
    'promo_card_toggle': 'content.manage',
    'home_section_add': 'content.manage',
    'home_section_edit': 'content.manage',
    'home_section_delete': 'content.manage',
    'home_section_add_item': 'content.manage',
    'home_section_remove_item': 'content.manage',
    'home_section_reorder': 'content.manage',
    'pro_vendor_section_add': 'content.manage',
    'pro_vendor_section_edit': 'content.manage',
    'pro_vendor_section_delete': 'content.manage',
    'pro_vendor_section_add_item': 'content.manage',
    'pro_vendor_section_remove_item': 'content.manage',
    'pro_vendor_section_reorder': 'content.manage',
    'curation_section_add': 'content.manage',
    'curation_section_edit': 'content.manage',
    'curation_section_delete': 'content.manage',
    'curation_item_add': 'content.manage',
    'curation_item_edit': 'content.manage',
    'curation_item_delete': 'content.manage',

    # Service forms
    'forms_list': 'forms.view',
    'form_detail': 'forms.view',
    'form_submissions': 'forms.view',
    'form_add': 'forms.manage',
    'form_edit': 'forms.manage',
    'form_delete': 'forms.manage',
    'form_step_add': 'forms.manage',
    'form_step_edit': 'forms.manage',
    'form_step_delete': 'forms.manage',
    'form_step_reorder': 'forms.manage',

    # Discounts & coupons
    'discounts_list': 'marketing.view',
    'coupons_list': 'marketing.view',
    'coupon_usage': 'marketing.view',
    'discount_add': 'marketing.manage',
    'discount_edit': 'marketing.manage',
    'discount_delete': 'marketing.manage',
    'coupon_add': 'marketing.manage',
    'coupon_edit': 'marketing.manage',
    'coupon_delete': 'marketing.manage',

    # Refer & earn
    'referrals_list': 'referrals.view',
    'referral_settings': {'GET': 'referrals.view', 'POST': 'referrals.manage'},
    'referral_settle': 'referrals.manage',

    # Customers
    'customers_list': 'customers.view',
    'customer_detail': 'customers.view',

    # Help & support
    'support_tickets': 'support.view',
    'support_ticket_detail': {'GET': 'support.view', 'POST': 'support.manage'},

    # AI assistant
    'assistant_conversations': 'assistant.view',
    'assistant_admin_chat': 'assistant.view',
    'assistant_conversation_detail': 'assistant.view',
    'assistant_knowledge_list': 'assistant.view',
    'assistant_settings': {'GET': 'assistant.view', 'POST': 'assistant.manage'},
    'assistant_knowledge_add': 'assistant.manage',
    'assistant_knowledge_edit': 'assistant.manage',
    'assistant_knowledge_delete': 'assistant.manage',
    'assistant_knowledge_toggle': 'assistant.manage',

    # Reports
    'reports': 'reports.view',

    # System
    'map_settings': 'system.maps',
    'roles_list': 'system.roles',
    'role_add': 'system.roles',
    'role_edit': 'system.roles',
    'role_delete': 'system.roles',
    'admin_users_list': 'system.staff',
    'admin_user_add': 'system.staff',
    'admin_user_edit': 'system.staff',
    'admin_user_delete': 'system.staff',
    'admin_user_password': 'system.staff',
    'login_security': 'system.security',
    'login_security_unlock': 'system.security',
}

#: URLs served before a user is signed in, so they never need a permission.
PUBLIC_URL_NAMES = frozenset({'dashboard_login'})


def permission_for(url_name, method='GET'):
    """
    The permission a request needs, or None when any signed-in user may pass.

    Raises KeyError for an unmapped URL. The caller treats that as a denial: a
    view nobody remembered to classify must not be reachable by everybody.
    """
    required = URL_PERMISSIONS[url_name]
    if isinstance(required, dict):
        # Anything that is not a plain read is held to the write permission.
        return required.get(method, required.get('POST'))
    return required


def clean_permissions(codes):
    """Drop anything that is not in the catalogue, keeping catalogue order."""
    given = set(codes or ())
    return [
        code
        for _group, entries in PERMISSION_GROUPS
        for code, _label, _help in entries
        if code in given
    ]
