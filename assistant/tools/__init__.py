"""
The only way the assistant is allowed to read anything.

Every fact the assistant states about a booking, a payment, a job or a payout
comes from a function registered here. Three rules hold, and they are the
reason this is a registry rather than a handful of imports:

  A tool takes the asking `user` and works out the profile itself. No caller
  can pass in somebody else's customer id, because no caller passes one --
  which is what makes "the assistant only ever reads your own data" a
  property of this module instead of a promise about every handler.

  A tool declares which audiences may call it. A customer intent cannot read
  a payout even by name, and a vendor cannot read another vendor's bid.

  Every call is recorded. `ToolBox.calls` ends up on the Message, so a
  transcript says not just what the assistant answered but what it read to
  answer it.

Nothing here writes. There is no tool that cancels a booking, releases money
or changes a status, and that is deliberate: the assistant explains what will
happen and hands the doing to a human.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    audiences: frozenset
    func: Callable
    description: str = ''
    #: A dashboard permission code the caller must hold, for the admin tools
    #: that read the whole platform rather than one person's rows. Empty for
    #: the customer and vendor tools, whose scoping is the user themselves.
    requires: str = ''


#: name -> Tool. Populated by @tool at import time.
REGISTRY = {}


def tool(name, *, audiences, description='', requires=''):
    """
    Register a data reader under `name` for `audiences`.

    `audiences` holds `Conversation.Audience` values. They are plain strings
    here to keep this module importable from models without a cycle.

    `requires` names a dashboard permission. It exists because the admin tools
    break the pattern the other two audiences rely on: they read the whole
    platform, not the asker's own rows, so "whose data is this" cannot do the
    gating. Without it, an admin holding only `assistant.view` could read
    revenue through the assistant that the dashboard itself refuses them.
    """
    def register(func):
        if name in REGISTRY:
            raise RuntimeError(f'Two assistant tools are both called {name!r}')
        REGISTRY[name] = Tool(
            name=name,
            audiences=frozenset(audiences),
            func=func,
            description=description or (func.__doc__ or '').strip().split('\n')[0],
            requires=requires,
        )
        return func
    return register


class ToolDenied(Exception):
    """A tool was called for an audience it is not registered for."""


@dataclass
class ToolBox:
    """
    The tools one person may use, plus the log of what they used.

    Built fresh per question. `calls` is the audit trail that lands on the
    bot's Message. `permissions` is the asker's dashboard permission codes,
    and is only ever non-empty for an admin conversation.
    """

    audience: str
    user: object
    permissions: frozenset = frozenset()
    calls: list = field(default_factory=list)

    def call(self, name, **kwargs):
        """
        Run a registered tool for this audience, recording the call.

        An unknown name raises KeyError and a forbidden one raises ToolDenied:
        both are programming mistakes in an intent, so they fail loudly in
        tests rather than quietly returning nothing in production. A handler
        that cannot be sure it is allowed should ask `may_call` first.
        """
        spec = REGISTRY[name]
        if self.audience not in spec.audiences:
            raise ToolDenied(
                f'{name!r} is not available to {self.audience} conversations'
            )
        if spec.requires and spec.requires not in self.permissions:
            raise ToolDenied(f'{name!r} needs the {spec.requires} permission')
        result = spec.func(self.user, **kwargs)
        self.calls.append({'name': name, 'args': _loggable(kwargs)})
        return result

    def may_call(self, name):
        """Whether `call(name)` would be allowed, without running it."""
        spec = REGISTRY.get(name)
        if spec is None or self.audience not in spec.audiences:
            return False
        return not spec.requires or spec.requires in self.permissions

    def available(self):
        """Every tool name this audience may call, sorted."""
        return sorted(
            name for name, spec in REGISTRY.items() if self.may_call(name)
        )


def _loggable(kwargs):
    """
    Arguments trimmed to what is safe and useful to keep.

    Only JSON-friendly scalars survive: the log is read by a human in the
    dashboard, and a model instance repr in there would be noise at best and
    somebody else's phone number at worst.
    """
    clean = {}
    for key, value in kwargs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, (list, tuple, set)):
            clean[key] = [str(item) for item in value][:10]
        else:
            clean[key] = str(type(value).__name__)
    return clean


# Importing the per-audience modules is what registers their tools. Kept at
# the bottom so REGISTRY and @tool exist by the time they run.
from . import shared  # noqa: E402,F401  (registers the shared tools)
from . import customer  # noqa: E402,F401  (registers the customer tools)
from . import vendor  # noqa: E402,F401  (registers the vendor tools)
from . import admin  # noqa: E402,F401  (registers the admin reports)
