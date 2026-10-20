"""
Readers that serve more than one audience.

Only platform settings and public catalogue data belong here -- things that
are the same fact whoever asks. Anything scoped to the asker lives in that
audience's own module, so "which rows can this audience reach" stays one
file per audience rather than a condition inside a shared function.
"""

from . import tool

EVERYONE_IN_THE_APPS = ['CUSTOMER', 'VENDOR']


@tool('tender_fee_terms', audiences=EVERYONE_IN_THE_APPS)
def tender_fee_terms(user):
    """
    The confirmation fee the platform charges right now.

    Both sides ask about it and both get the same answer, but for opposite
    reasons: the customer pays it, and the vendor wants to know whether it
    comes out of their bid. It does not -- which is why the vendor-side
    handler says so.
    """
    from tenders.models import TenderSettings

    fee_settings = TenderSettings.get_solo()
    return {
        'percent': fee_settings.effective_percent,
        'is_active': fee_settings.is_confirmation_fee_active,
    }
