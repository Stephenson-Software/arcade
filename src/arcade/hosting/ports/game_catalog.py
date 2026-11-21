# @author Daniel McCoy Stephenson
"""GameCatalog: which games are registered right now?"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class GameCatalog(Protocol):
    """The registered games.

    games() returns an arcade.registry.Registry (the existing in-repo type is
    the contract: get(slug), forAlias(host), iteration in slug order, len).
    It never raises once the catalog has been built: a source that later goes
    missing or stops parsing keeps answering with the last good registry.
    Building one may raise (a missing or invalid registry at start-up).
    It may read a file, so it can block briefly; it is called from many
    request threads at once and must be thread-safe.
    """

    def games(self):
        ...
