"""
What an intent is, and what a handler is handed.

An intent is a named bundle of triggers and one function. The engine picks
the intent whose trigger matched most specifically (see
`matching.trigger_score`) and calls its handler with a Context; the handler
reads whatever it needs through `ctx.call` and returns a Reply.

A handler may return None, which means "that trigger fired but there is
nothing here to say" -- an empty booking list, say. The engine then carries on
to the answer book rather than printing a cheerful sentence about nothing.
"""

from dataclasses import dataclass, field
from typing import Callable

from .. import matching


@dataclass(frozen=True)
class Reply:
    """What a handler produced."""

    text: str
    #: Follow-up questions to offer as tappable chips in the app.
    suggestions: tuple = ()
    #: True to offer "talk to a human" alongside the answer.
    escalate: bool = False


@dataclass(frozen=True)
class Intent:
    """
    One rule.

    `triggers` is a tuple whose members are each either a phrase or a tuple of
    phrases that must all appear. `weight` settles a tie between two intents
    whose triggers spell out the same number of characters; it is a nudge, not
    a priority order, because trigger specificity should be doing the work.
    """

    name: str
    triggers: tuple
    handler: Callable
    weight: int = 0

    def score(self, question):
        """The best score any of this intent's triggers gets on `question`."""
        best = max(
            (matching.trigger_score(question, trigger) for trigger in self.triggers),
            default=0,
        )
        return best + self.weight if best else 0


@dataclass
class Context:
    """
    Everything a handler is allowed to reach.

    Handlers get no request, no queryset and no model imports they need to
    scope themselves -- just `call`, which goes through the tool registry and
    is therefore both audience-checked and logged.
    """

    question: str
    audience: str
    user: object
    settings: object
    toolbox: object
    _keywords: set = field(default=None, repr=False)

    @property
    def keywords(self):
        if self._keywords is None:
            self._keywords = matching.keywords(self.question)
        return self._keywords

    def call(self, name, **kwargs):
        """Read something, through the registry, recorded on the transcript."""
        return self.toolbox.call(name, **kwargs)

    def may(self, name):
        """
        Whether `call(name)` is allowed for this asker.

        Only the admin reports can answer no: they are gated on the dashboard
        permission their equivalent page needs. A handler asks this so a
        permission it does not hold reads as "you don't have access to that"
        rather than raising out of the engine.
        """
        return self.toolbox.may_call(name)

    def mentions(self, *phrases):
        """Whether the question used any of these phrases."""
        return any(matching.contains(self.question, phrase) for phrase in phrases)

    def number(self):
        """
        The first number in the question, or None.

        For "what about booking 412" -- the id a handler should look up rather
        than guessing at the latest one.
        """
        for word in matching.words(self.question):
            if word.isdigit():
                return int(word)
        return None

    # ------------------------------------------------------------- answer book
    def knowledge(self, *phrases, threshold=0.34):
        """
        The best answer-book entry for `phrases`, or None.

        Intents use this for anything that is policy rather than data: what
        the cancellation terms are, how long a refund takes. The assistant
        must not be the author of those sentences, so a handler that has no
        entry to quote says it does not know and offers a human instead.

        Matching is deliberately the same overlap score the engine's own
        fallback search uses, so an entry that an intent can find is also an
        entry the fallback can find.
        """
        from ..models import KnowledgeEntry

        wanted = set()
        for phrase in phrases:
            wanted |= matching.keywords(phrase)
        if not wanted:
            return None

        best, best_score = None, 0.0
        for entry in KnowledgeEntry.objects.filter(is_active=True):
            if not entry.serves(self.audience):
                continue
            score = max(
                matching.overlap_score(wanted, entry.question),
                matching.overlap_score(wanted, entry.keywords),
            )
            if score > best_score:
                best, best_score = entry, score

        return best if best_score >= threshold else None
