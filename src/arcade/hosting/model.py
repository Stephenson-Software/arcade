# @author Daniel McCoy Stephenson
"""The hosting core's outcome values.

A game is an arcade.registry.Game and the registered set an
arcade.registry.Registry: those existing types are the domain model and are
not copied here. What the core adds is how an API call ended, as a value the
HTTP handler turns into a response; exceptions are kept for bugs.
"""


class Outcome(object):
    """How an API call ended: the HTTP status it maps to, and either an error
    message or the game it acted on."""

    __slots__ = ("status", "error", "game")

    def __init__(self, status, error=None, game=None):
        self.status = status
        self.error = error
        self.game = game

    def __eq__(self, other):
        return type(self) is type(other) and (self.status, self.error, self.game) == (
            other.status,
            other.error,
            other.game,
        )

    def __repr__(self):
        return "%s(%r, %r, %r)" % (type(self).__name__, self.status, self.error, self.game)


class Denied(Outcome):
    """The bearer token may not act on the game (401: none given; 403: wrong
    token, or no such game - the two look the same from outside)."""

    __slots__ = ()


class Rejected(Outcome):
    """The request was understood and refused (bad version, bad bundle, a
    version that exists or is missing)."""

    __slots__ = ()


class Deployed(Outcome):
    """The game's versions changed (201: uploaded; 200: current moved)."""

    __slots__ = ()
