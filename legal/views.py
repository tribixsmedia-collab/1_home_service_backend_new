"""
Public legal pages.

Company details come from settings rather than being written into the
templates, so the client's real address and support email can be set at deploy
time without a code change -- see LEGAL_* in .env.example.
"""
from django.conf import settings
from django.shortcuts import render


def _context():
    return {
        'company': settings.LEGAL_COMPANY_NAME,
        'contact_email': settings.LEGAL_CONTACT_EMAIL,
        'contact_phone': settings.LEGAL_CONTACT_PHONE,
        'address': settings.LEGAL_ADDRESS,
        'updated': settings.LEGAL_LAST_UPDATED,
        'placeholders': settings.LEGAL_HAS_PLACEHOLDERS,
    }


def privacy_view(request):
    return render(request, 'legal/privacy.html', _context())


def terms_view(request):
    return render(request, 'legal/terms.html', _context())


def data_deletion_view(request):
    return render(request, 'legal/data_deletion.html', _context())
