# @author Daniel McCoy Stephenson
"""At most one play per visitor, per game, per UTC day, remembering no one.

A play used to be every page load a person made, so a reload, a second tab or
a game page left open across a restart counted again. Now the first load of a
game's page by a visitor on a UTC day counts and the rest of that day's loads
by the same visitor do not.

"The same visitor" is the client's address (the last X-Forwarded-For hop,
which the proxy in front appends) together with its User-Agent. Neither is
kept. Each (address, User-Agent, slug) is reduced to a keyed hash (HMAC-SHA256,
cut to 16 bytes) under a random key that exists only in this process's memory
and is replaced at every UTC midnight, when the set of hashes is emptied too.
So:

  - nothing about a visitor is written to disk, logged or reported;
  - the hashes cannot be tested against a guessed address, because the key
    is never stored or shown, and once a day is over its key is gone;
  - a restart forgets the day: a visitor may count once more after one.

Memory is bounded: at most MAX_KEYS hashes a day (about 100 bytes each). When
the set is full, further new visitors that day are not counted: that many
distinct visitors in a day is far beyond this arcade's traffic, so a full set
means something is cycling addresses or User-Agents, which is not people.

Historic counts (store.py's plays and .plays-daily) are untouched: this only
decides whether a new page load counts.

Standard library only: the server imports it.
"""

import datetime
import hashlib
import hmac
import os
import threading

MAX_KEYS = 100000
DIGEST_BYTES = 16


def utcToday():
    return datetime.datetime.now(datetime.timezone.utc).date()


class Visits(object):
    """Which (visitor, game) pairs have already counted today."""

    def __init__(self, maxKeys=MAX_KEYS, today=utcToday):
        self.maxKeys = maxKeys
        self._today = today
        self._lock = threading.Lock()
        self._day = None
        self._salt = b""
        self._seen = set()

    def _roll(self, day):
        """Under the lock: a new UTC day gets a new key and an empty set."""
        if day != self._day:
            self._day = day
            self._salt = os.urandom(32)
            self._seen = set()

    def first(self, slug, client, userAgent, day=None):
        """True if this is the visitor's first load of `slug` today (it then
        counts as a play); False for a repeat, or when the day's set is full."""
        day = day or self._today()
        with self._lock:
            self._roll(day)
            message = "\0".join((client or "", userAgent or "", slug)).encode("utf-8", "replace")
            key = hmac.new(self._salt, message, hashlib.sha256).digest()[:DIGEST_BYTES]
            if key in self._seen:
                return False
            if len(self._seen) >= self.maxKeys:
                return False
            self._seen.add(key)
            return True

    def __len__(self):
        with self._lock:
            return len(self._seen)
