# @author Daniel McCoy Stephenson
"""EventReporter: tell trace that something happened."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventReporter(Protocol):
    """report(name, tags) records one event (e.g. "page-served", with
    {"slug": ...}). It never raises and never blocks a request: a reporter
    that sends over the network queues and sends on its own thread.
    Thread-safe."""

    def report(self, name, tags=None):
        ...
