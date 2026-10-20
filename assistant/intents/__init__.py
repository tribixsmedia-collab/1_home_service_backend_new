"""
Which intents serve which audience.

One registry so the engine never has to know how many audiences exist, and so
adding the vendor or admin catalogue is a new module plus one line here rather
than a change to the engine.
"""

from . import admin, customer, vendor

#: audience -> the intents that may answer it, in declaration order.
CATALOGUES = {
    'CUSTOMER': customer.INTENTS,
    'VENDOR': vendor.INTENTS,
    'ADMIN': admin.INTENTS,
}

#: audience -> the chips to offer in a fresh chat.
STARTERS = {
    'CUSTOMER': customer.STARTERS,
    'VENDOR': vendor.STARTERS,
    'ADMIN': admin.STARTERS,
}


def for_audience(audience):
    return CATALOGUES.get(audience, ())


def starters_for(audience):
    return STARTERS.get(audience, ())
