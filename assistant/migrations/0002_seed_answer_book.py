"""
A starting answer book, so the assistant is useful the day it is switched on.

Two kinds of row go in here, and the difference is who is entitled to author
the sentence:

  Active entries state how the platform mechanically works -- that money is
  held until the job is marked complete, that a vendor's arrival is recorded
  with a geotagged photo, that accepting a bid holds it until the
  confirmation fee is paid. Every one of those was read off the models in
  this repository, so it is a description of the code rather than a promise.

  Drafts are switched OFF and say so. Cancellation charges, refund windows,
  what happens when a vendor fails to turn up: those are the business's
  terms, not facts about the software, and nobody writing a migration gets to
  decide them. Until an admin writes one and switches it on, the assistant
  answers those questions with "I don't know, let me get you a person" --
  which is the right answer, where the alternative is a bot inventing a refund
  window the business then has to honour.
"""

from django.db import migrations

ACTIVE = [
    (
        'How do I book a service?',
        'book,booking,how to book,order,new booking,place order',
        'Pick a category on the home screen, choose the service you need, '
        'then set the date, time and address. You pay in the app and the '
        'booking is created straight away.',
        'CUSTOMER',
        10,
    ),
    (
        'How is a vendor assigned to my booking?',
        'assign,assigned,who will come,vendor allocation,waiting for vendor',
        'A new booking starts as Pending Assignment while we match it with a '
        'verified vendor who covers your area. You get a notification the '
        'moment one is assigned, and their name and number then show on the '
        'booking.',
        'CUSTOMER',
        20,
    ),
    (
        'How do I know the vendor has arrived?',
        'arrived,arrival,reached,started work,on the way',
        'The vendor records their arrival with a photo taken at your address, '
        'and the booking moves to Work In Progress at that point. You can see '
        'it on the booking screen.',
        'CUSTOMER',
        30,
    ),
    (
        'When does the vendor get paid?',
        'vendor payment,when paid,money held,escrow,release payment',
        'We hold your payment until the job is marked complete, and only then '
        'release it to the vendor. That is why a captured payment can show as '
        'held rather than paid out.',
        'CUSTOMER',
        40,
    ),
    (
        'What payment methods can I use?',
        'payment method,upi,card,netbanking,how to pay,cash',
        'You can pay by UPI, debit or credit card, or netbanking through our '
        'payment gateway.',
        'CUSTOMER',
        50,
    ),
    (
        'How do I post a project for vendors to bid on?',
        'tender,post project,bids,quotation,big job,renovation',
        'Post the project with your requirement, area and budget. Verified '
        'vendors then send bids with their price and timeline, and you pick '
        'the one you want.',
        'CUSTOMER',
        60,
    ),
    (
        'What happens after I accept a bid?',
        'accept bid,selected bid,awaiting confirmation,confirm bid',
        'Your choice is held first, not awarded. The vendor is not told they '
        'have won until the confirmation fee is paid, so until then you can '
        'still change your mind and go back to the other bids.',
        'CUSTOMER',
        70,
    ),
    (
        'How do I contact support?',
        'support,help,complaint,contact,human,customer care',
        'Open Help & Support in the app to raise a ticket. Replies come back '
        'in the app on the same ticket. I can also pass this chat straight to '
        'the team if you like.',
        'ALL',
        80,
    ),
    (
        'Can I use the same phone number for a customer and a vendor account?',
        'same number,two accounts,vendor account,phone number,register again',
        'Yes. One phone number can hold a customer account and a vendor '
        'account at the same time, and you sign in to whichever one you need.',
        'ALL',
        90,
    ),
]

#: (question, keywords, audience, sort_order) -- answers are left for an admin.
DRAFTS = [
    (
        'What is your cancellation policy?',
        'cancel,cancellation,cancellation charge,cancel booking,call off',
        'CUSTOMER',
        110,
    ),
    (
        'How long does a refund take?',
        'refund,refund time,money back,how long refund,reversal',
        'CUSTOMER',
        120,
    ),
    (
        "What if the vendor doesn't turn up?",
        'no show,did not come,never came,vendor absent,nobody arrived',
        'CUSTOMER',
        130,
    ),
    (
        "What if I'm not happy with the work?",
        'not happy,bad work,poor quality,complaint about work,redo',
        'CUSTOMER',
        140,
    ),
]

DRAFT_ANSWER = (
    'NOT WRITTEN YET. Replace this with the official wording, then switch '
    'this entry on. While it is off the assistant says it does not know and '
    'offers the customer a person instead, which is deliberate -- it must not '
    'invent our terms.'
)


def seed(apps, schema_editor):
    KnowledgeEntry = apps.get_model('assistant', 'KnowledgeEntry')

    for question, keywords, answer, audience, order in ACTIVE:
        KnowledgeEntry.objects.get_or_create(
            question=question,
            defaults={
                'keywords': keywords,
                'answer': answer,
                'audience': audience,
                'sort_order': order,
                'is_active': True,
            },
        )

    for question, keywords, audience, order in DRAFTS:
        KnowledgeEntry.objects.get_or_create(
            question=question,
            defaults={
                'keywords': keywords,
                'answer': DRAFT_ANSWER,
                'audience': audience,
                'sort_order': order,
                'is_active': False,
            },
        )


def unseed(apps, schema_editor):
    """
    Remove only the rows this migration added, and only if untouched.

    An admin who has edited an answer has written something this migration has
    no business deleting, so a changed row is left behind.
    """
    KnowledgeEntry = apps.get_model('assistant', 'KnowledgeEntry')

    for question, _keywords, answer, _audience, _order in ACTIVE:
        KnowledgeEntry.objects.filter(question=question, answer=answer).delete()
    for question, _keywords, _audience, _order in DRAFTS:
        KnowledgeEntry.objects.filter(question=question, answer=DRAFT_ANSWER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('assistant', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
