# @author Daniel McCoy Stephenson
"""PlayCounter: how many times has a game been played?"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlayCounter(Protocol):
    """A game's play count.

    plays(slug)   -> the total count, 0 for a game never played
    addPlay(slug) counts one play today. OSError if it cannot be recorded;
                  the caller logs that and carries on (a lost play is not an
                  error the player should see).

    Both may touch disk and block; both must be thread-safe.
    """

    def plays(self, slug):
        ...

    def addPlay(self, slug):
        ...
