# @author Daniel McCoy Stephenson
"""ReleaseNotes: what's new in a game's current version?"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ReleaseNotes(Protocol):
    """notes(slug, repo, current) -> {"version", "text", "url"} for the
    release `current` names, or None when there is none yet (not released,
    not looked up yet, or empty). It never raises and never waits on the
    network: a lookup it does not have yet is queued and answered later.
    Thread-safe."""

    def notes(self, slug, repo, current):
        ...
