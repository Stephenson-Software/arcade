# @author Daniel McCoy Stephenson
"""NullReporter: the EventReporter when trace is off (no ARCADE_TRACE_KEY)."""


class NullReporter(object):
    """Drops every event."""

    def report(self, name, tags=None):
        pass
