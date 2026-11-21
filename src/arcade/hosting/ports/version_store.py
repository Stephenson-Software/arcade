# @author Daniel McCoy Stephenson
"""VersionStore: which versions of a game exist, and which is current?"""

from typing import Protocol, runtime_checkable

# The store's own version rule and outcomes are the contract; they live in
# arcade.store (shared with its tests and arcade.bundle) and are named here.
from arcade.store import VERSION_PATTERN, NoSuchVersion, VersionExists

__all__ = ["NoSuchVersion", "VERSION_PATTERN", "VersionExists", "VersionStore"]


@runtime_checkable
class VersionStore(Protocol):
    """A game's uploaded versions.

    current(slug)  -> the current version's name, or None
    versions(slug) -> every stored version's name, oldest upload first
    added(slug)    -> time.time_ns() of the slug's first upload, or None
    add(slug, version, files, activate=True, static=False)
                   stores `files` ({name: bytes}) as an immutable version,
                   making it current when `activate`. Raises VersionExists if
                   the version is already stored; ValueError or OSError if
                   the files cannot be stored.
    setCurrent(slug, version)
                   makes a stored version current; NoSuchVersion if it is not.

    All may touch disk and block; all are called from request threads at
    once and must be thread-safe.
    """

    def current(self, slug):
        ...

    def versions(self, slug):
        ...

    def added(self, slug):
        ...

    def add(self, slug, version, files, activate=True, static=False):
        ...

    def setCurrent(self, slug, version):
        ...
