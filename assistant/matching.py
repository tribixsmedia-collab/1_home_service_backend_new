"""
Turning what somebody typed into something the rules engine can match on.

Deliberately small. Every function here is pure, takes a string and returns a
string, a set or a boolean -- which is what makes the rules engine's choices
reproducible in a test rather than a thing you have to try in the app.

The one piece of cleverness is plural tolerance: people type "my bookings"
and the trigger is written "booking", so a trailing s on the last word of a
phrase is optional. Nothing more than that -- no stemming, because "statu"
is what stemming "status" gets you.
"""

import re
from functools import lru_cache

#: Words that carry no signal in a question and would otherwise make every
#: knowledge entry look slightly relevant.
STOPWORDS = frozenset({
    'a', 'about', 'am', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'been',
    'but', 'by', 'can', 'could', 'did', 'do', 'does', 'for', 'from', 'get',
    'had', 'has', 'have', 'he', 'her', 'his', 'how', 'i', 'if', 'in', 'is',
    'it', 'its', 'just', 'me', 'my', 'need', 'no', 'not', 'of', 'on', 'or',
    'our', 'out', 'please', 'she', 'should', 'so', 'some', 'tell', 'that',
    'the', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'to',
    'up', 'want', 'was', 'we', 'were', 'what', 'when', 'where', 'which',
    'who', 'why', 'will', 'with', 'would', 'you', 'your',
})


def normalise(text):
    """
    Lowercased, punctuation flattened to spaces, runs of space collapsed.

    Punctuation becomes a space rather than nothing so "booking/payment" is
    two words, not one word nobody will ever match.
    """
    lowered = (text or '').lower()
    flattened = re.sub(r'[^a-z0-9₹]+', ' ', lowered)
    return re.sub(r'\s+', ' ', flattened).strip()


def words(text):
    """Every word in the question, in order, stopwords included."""
    return normalise(text).split()


def keywords(text):
    """The words worth matching on -- no stopwords, nothing one letter long."""
    return {
        word for word in words(text)
        if word not in STOPWORDS and len(word) > 1
    }


@lru_cache(maxsize=2048)
def _phrase_pattern(phrase):
    """
    A phrase as a word-boundaried regex, tolerating a plural on the last word.

    Boundaried on purpose: without it "car" matches "card" and a question
    about a card payment gets answered as a question about a car.
    """
    parts = [re.escape(part) for part in normalise(phrase).split()]
    if not parts:
        # Never matches. An empty trigger is a mistake, not a wildcard.
        return re.compile(r'(?!)')
    parts[-1] = parts[-1] + 's?'
    return re.compile(r'\b' + r'\s+'.join(parts) + r'\b')


def contains(text, phrase):
    """Whether `phrase` appears in `text` as whole words."""
    return bool(_phrase_pattern(phrase).search(normalise(text)))


def trigger_score(text, trigger):
    """
    How strongly one trigger matches, or 0 when it does not.

    A trigger is either a phrase, or a tuple of phrases that must *all*
    appear -- ('cancel', 'booking') fires on "can I cancel this booking?" but
    not on "cancel" alone.

    The score is the number of characters the trigger spells out, so a longer,
    more specific trigger beats a shorter one and the engine can pick between
    two intents that both matched without anybody having to rank them by hand.
    """
    parts = (trigger,) if isinstance(trigger, str) else tuple(trigger)
    total = 0
    for part in parts:
        if not contains(text, part):
            return 0
        total += len(normalise(part).replace(' ', ''))
    return total


def overlap_score(question_keywords, candidate_text):
    """
    Share of a candidate's keywords that the question also used, 0.0 - 1.0.

    Used to rank answer-book entries. Measured against the candidate rather
    than the question so a short, pointed entry is not punished for a long,
    rambling question -- "how do I cancel" should find the cancellation entry
    even when it arrives wrapped in two sentences of context.
    """
    candidate = keywords(candidate_text)
    if not candidate or not question_keywords:
        return 0.0
    return len(candidate & question_keywords) / len(candidate)
