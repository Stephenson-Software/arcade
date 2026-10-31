# @author Daniel McCoy Stephenson
"""How busy each game has been lately, as a coarse level (RFC 0030 §2.2).

The hall's ghosts (hall-ghosts.js) walk to cabinets in proportion to recent
plays. The per-day counts behind that (store.py's .plays-daily) are never
published: GET /api/activity serves only a level from 0 to 4 per game,
computed from the WINDOW_DAYS complete UTC days before today, with nothing
shown below K plays (RFC 0022 §4.2's k). Today is left out, so a level
changes only at midnight UTC and never at the moment someone plays.
"""

import datetime

WINDOW_DAYS = 7
K = 10
# The lowest 7-day total for levels 1, 2, 3 and 4 (RFC 0030 §2.2; unmeasured).
THRESHOLDS = (K, 25, 100, 400)
MAX_AGE = 3600  # seconds a response may be cached: the levels move once a day


def level(plays):
    """0 below K plays in the window, else 1..4 by THRESHOLDS."""
    out = 0
    for i, floor in enumerate(THRESHOLDS):
        if plays >= floor:
            out = i + 1
    return out


def maxAge(now):
    """Seconds a response made at `now` (an aware UTC datetime) may be
    cached: MAX_AGE, but never past the next midnight UTC, when the levels
    can change."""
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, min(MAX_AGE, int((midnight - now).total_seconds())))


def document(slugs, recent):
    """The /api/activity body for these slugs; recent(slug) is the slug's
    plays over the window. Only levels: never a count, a date or a time."""
    return {
        "window_days": WINDOW_DAYS,
        "k": K,
        "levels": {slug: level(recent(slug)) for slug in slugs},
    }
