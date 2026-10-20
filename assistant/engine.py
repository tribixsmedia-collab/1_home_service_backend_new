"""
Which engine answers, and the shape of an answer.

The apps and the dashboard call `ask()` and never learn which engine served
them. That is the whole point of the seam: the rules engine ships now, for
nothing, and switching the dashboard setting to Claude later changes what
happens inside here and nothing else -- no new endpoint, no app rebuild.

`Answer` is the contract both engines fill. `tool_calls` and `tokens_used` are
part of it because both are things the dashboard has to be able to show: what
an answer read, and what it cost.
"""

from dataclasses import dataclass, field

from . import rules
from .models import AssistantSettings
from .tools import ToolBox


@dataclass
class Answer:
    """One reply, with everything the transcript needs to record about it."""

    text: str
    intent: str
    engine: str
    suggestions: tuple = ()
    #: True to offer the person a handover to a human alongside this answer.
    escalate: bool = False
    tool_calls: list = field(default_factory=list)
    tokens_used: int = 0


#: The engines that actually exist. Claude is designed for (see
#: AssistantSettings) but not written: the settings page says so, and
#: `resolve_engine` keeps answering with the rules engine until it is.
IMPLEMENTED = {
    AssistantSettings.Engine.RULES: rules.answer,
}


def resolve_engine(settings_row):
    """
    The engine that will really answer, and the one that was asked for.

    Returns (engine_key, answer_callable). A choice that cannot be served --
    Claude with no key, or Claude before the module exists -- falls back to
    the rules engine rather than failing the request, the same way a map with
    no Google key keeps drawing the free basemap.
    """
    wanted = settings_row.effective_engine
    if wanted in IMPLEMENTED:
        return wanted, IMPLEMENTED[wanted]
    return AssistantSettings.Engine.RULES, IMPLEMENTED[AssistantSettings.Engine.RULES]


def ask(question, *, audience, user, settings_row=None, permissions=()):
    """
    Put one question to the assistant.

    `permissions` is the asker's dashboard permission codes, and matters only
    for an admin conversation: the admin reports read the whole platform, so
    each is gated on the permission its equivalent dashboard page needs. The
    caller passes `request.admin_perms`; for a customer or vendor it stays
    empty and nothing consults it.

    Does not touch the database beyond reading: persisting the turn is the
    caller's job (see `assistant.views`), so the engine can be exercised in a
    test without a conversation existing.
    """
    settings_row = settings_row or AssistantSettings.get_solo()
    _key, engine = resolve_engine(settings_row)
    toolbox = ToolBox(
        audience=audience, user=user, permissions=frozenset(permissions),
    )
    return engine(
        question,
        audience=audience,
        user=user,
        settings_row=settings_row,
        toolbox=toolbox,
    )
