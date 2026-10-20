"""
The rules engine: the free one, and the one that ships first.

Three steps, in order:

  1. Score every intent for this audience and run the best one. Specificity
     wins -- "cancel my booking" beats the bare "booking" trigger because its
     matching trigger spells out more characters.
  2. If nothing matched, or the handler had nothing to say, search the answer
     book by keyword overlap.
  3. If that found nothing either, say so, offer the related questions it
     *nearly* matched, and offer a human.

What it cannot do is the point of it. It never writes a sentence nobody on the
team wrote: an intent either states a fact read live through the tool registry
or quotes an answer-book entry. So it cannot invent a refund window, and it
cannot be talked into one -- there is no text generation anywhere in here.
"""

from . import matching
from .intents import base, for_audience, starters_for
from .models import KnowledgeEntry, Message

#: An answer-book entry must overlap the question this much to be given as the
#: answer. Below it the entry is only offered as a suggestion -- being
#: slightly relevant is a reason to show a question, not to answer with it.
ANSWER_THRESHOLD = 0.45

#: And this much to be worth offering as a "did you mean".
SUGGEST_THRESHOLD = 0.2


def answer(question, *, audience, user, settings_row, toolbox):
    """
    Answer one question. Returns an `engine.Answer`.

    Imported lazily to keep `engine` the only module that knows about both
    engines.
    """
    from .engine import Answer

    reply, intent_name = _run_intents(question, audience, user, settings_row, toolbox)

    if reply is None:
        reply, intent_name = _search_answer_book(question, audience)

    if reply is None:
        reply, intent_name = _dead_end(question, audience, settings_row)

    return Answer(
        text=reply.text,
        intent=intent_name,
        engine='RULES',
        suggestions=tuple(reply.suggestions),
        escalate=reply.escalate,
        tool_calls=list(toolbox.calls),
        tokens_used=0,
    )


# ---------------------------------------------------------------------------
# 1. Intents
# ---------------------------------------------------------------------------

def select(question, intents):
    """
    The intent that best matches `question`, or None.

    Pulled out of `_run_intents` so the choice can be tested on a catalogue of
    two made-up intents, which is the only way to state "the more specific
    trigger wins" as a test rather than as a comment.
    """
    scored = [
        (intent.score(question), index, intent)
        for index, intent in enumerate(intents)
    ]
    # Declaration order breaks a tie, so the catalogue reads as the tiebreak
    # rather than whatever the sort happened to do.
    matched = sorted(
        (entry for entry in scored if entry[0] > 0),
        key=lambda entry: (-entry[0], entry[1]),
    )
    return matched[0][2] if matched else None


def _run_intents(question, audience, user, settings_row, toolbox):
    """The best-matching intent's reply, or (None, None)."""
    intent = select(question, for_audience(audience))
    if intent is None:
        return None, None

    context = base.Context(
        question=question,
        audience=audience,
        user=user,
        settings=settings_row,
        toolbox=toolbox,
    )

    # Only the winner runs. A handler that returns None is saying "my trigger
    # fired but there is nothing here", and the answer book gets its turn --
    # trying the runner-up intent instead would answer a question nobody
    # asked.
    reply = intent.handler(context)
    return (reply, intent.name) if reply is not None else (None, None)


# ---------------------------------------------------------------------------
# 2. The answer book
# ---------------------------------------------------------------------------

def _entries_for(audience):
    return [
        entry for entry in KnowledgeEntry.objects.filter(is_active=True)
        if entry.serves(audience)
    ]


def _ranked_entries(question, audience):
    """Every entry that is at all relevant, best first."""
    asked = matching.keywords(question)
    if not asked:
        return []

    ranked = []
    for entry in _entries_for(audience):
        score = max(
            matching.overlap_score(asked, entry.question),
            matching.overlap_score(asked, entry.keywords),
        )
        if score >= SUGGEST_THRESHOLD:
            ranked.append((score, entry))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].sort_order))
    return ranked


def _search_answer_book(question, audience):
    ranked = _ranked_entries(question, audience)
    if not ranked or ranked[0][0] < ANSWER_THRESHOLD:
        return None, None

    best_score, best = ranked[0]
    others = tuple(entry.question for _score, entry in ranked[1:4])
    return (
        base.Reply(
            text=best.answer,
            suggestions=others,
            # The answer book is the team's own words, so a match that clears
            # the bar needs no apology and no handover.
            escalate=False,
        ),
        f'knowledge:{best.id}',
    )


# ---------------------------------------------------------------------------
# 3. Giving up well
# ---------------------------------------------------------------------------

def _dead_end(question, audience, settings_row):
    """
    Nothing matched.

    Still useful: the near misses become suggestions, so a question phrased
    in words the answer book does not use gets a second chance from the
    person rather than a shrug.
    """
    near = tuple(
        entry.question for _score, entry in _ranked_entries(question, audience)[:3]
    )
    return (
        base.Reply(
            text=settings_row.fallback_message,
            suggestions=near or starters_for(audience),
            escalate=True,
        ),
        Message.FALLBACK_INTENT,
    )
