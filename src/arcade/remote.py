# @author Daniel McCoy Stephenson
"""Things arcade looks up elsewhere, in the background, and keeps on disk.

Two kinds, both optional decoration that a page shows when it is there and
does without when it is not:

  posters  a game's trailer still, https://danielstephenson.dev/trailers/
           <repo-name>.jpg (arcade.hall.poster_urls), for the screen of a
           cabinet that has no poster in hall_assets/posters/ yet (a game
           registered since tools/make_hall_posters.py last ran). Fetched once
           and again after REFRESH_SECONDS, so a trailer published later
           appears without anyone running a tool.
  notes    "What's new": the GitHub release whose tag is the game's current
           version (0.4.0 or v0.4.0 for a current of 0.4.0+g1a2b3c4), its body
           cut to the part a player reads (release_text). One unauthenticated
           request to the repository's release list per new version, and never
           for a development build (a -SNAPSHOT or untagged version), so
           GitHub's 60 requests an hour for an address without a token are
           never approached; GITHUB_PER_HOUR caps it regardless, and a 403 or
           429 from GitHub pauses every GitHub request for GITHUB_BACKOFF.

A request never waits for any of this. Handlers ask for what is cached
(poster(), notes()), which also queues a fetch when there is nothing yet;
one daemon thread works through the queue. Failures are silent: a lookup that
fails (no network, a 404, a timeout, a body that is not what was asked for) is
tried again after RETRY_SECONDS at the earliest, and until then the page
simply has no poster or no notes. Results are written atomically under
<ARCADE_DATA>/.remote/ (a dot name, so never a slug), and survive restarts.

ARCADE_REMOTE=off turns the fetching off (the cache is still read).

Standard library only: the server imports it.
"""

import collections
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

from arcade import __version__

RETRY_SECONDS = 6 * 3600
REFRESH_SECONDS = 7 * 86400
TIMEOUT = 10
MAX_POSTER_BYTES = 2 * 1024 * 1024
MAX_RELEASES_BYTES = 2 * 1024 * 1024
GITHUB_PER_HOUR = 30
GITHUB_BACKOFF = 3600
NOTES_MAX = 600
MAX_BODY = 20000
QUEUE_MAX = 256
USER_AGENT = "arcade/%s (+https://github.com/Stephenson-Software/arcade)" % __version__
RELEASES = "https://api.github.com/repos/{repo}/releases?per_page=30"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# A released version: 1.2.3, maybe with a pre-release part (1.2.3-rc.1), but
# never a development build (-SNAPSHOT) or a bare commit.
_RELEASED = re.compile(r"^v?\d+(?:\.\d+){1,3}(?:-(?!.*SNAPSHOT)[0-9A-Za-z.]+)?$", re.I)


class Failed(Exception):
    """A lookup that did not give what was asked for (already logged or not worth it)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def httpGet(url, maxBytes, accept):
    """The body of a 200 response to GET `url`, at most `maxBytes`; Failed otherwise."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise Failed("HTTP %d" % response.status, response.status)
            contentType = response.headers.get("Content-Type") or ""
            data = response.read(maxBytes + 1)
    except urllib.error.HTTPError as e:
        raise Failed("HTTP %d" % e.code, e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Failed(str(e))
    if len(data) > maxBytes:
        raise Failed("too large")
    return contentType, data


def releasedVersion(current):
    """The release a current version names (0.4.0 for 0.4.0+g1a2b3c4), or
    None for a development build, which has no release to look up."""
    if not current:
        return None
    base = current.split("+", 1)[0]
    return base if _RELEASED.match(base) else None


_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_BY = re.compile(r"\s+by @[\w-]+ in https?://\S+$")
_VERSION_LINE = re.compile(r"^v?\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.]+)?$")
_STOP = re.compile(r"^(?:#{1,6}\s*(?:Version|Verification)\b|---+\s*$|\*\*Full Changelog\*\*)", re.I)


def release_text(body, limit=NOTES_MAX):
    """A release body as a few plain lines a player reads: up to the
    release tooling's own sections (### Version, ### Verification, ---),
    without the sign-off, links reduced to their text, bold and headings
    unmarked, list items as bullets; at most `limit` characters, cut at a
    word. '' when nothing is left."""
    lines = []
    for raw in (body or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if _STOP.match(line.strip()):
            break
        stripped = line.strip()
        if stripped.startswith("_drafted by") or stripped.startswith("<!--"):
            continue
        if not lines and not stripped:
            continue
        line = _LINK.sub(lambda m: m.group(1), line)
        line = _BY.sub("", line)
        line = line.replace("**", "").replace("__", "")
        line = re.sub(r"`([^`]*)`", r"\1", line)
        heading = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if heading:
            line = heading.group(1)
        if not lines and _VERSION_LINE.match(line.strip()):
            continue  # a heading that only repeats the version ("## 0.3.0"): the page says it already
        bullet = re.match(r"^(\s*)[*+-]\s+(.*)$", line)
        if bullet:
            line = "%s• %s" % ("  " if bullet.group(1) else "", bullet.group(2))
        lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.-• \n")
    return cut + "…"


def first_sentence(text, limit=140):
    """The first sentence (or line) of some notes, for a cabinet with no blurb."""
    for line in (text or "").split("\n"):
        line = line.strip().lstrip("• ").strip()
        if len(line) < 12 or line.endswith(":"):
            continue
        match = re.match(r"^(.+?[.!?])(?:\s|$)", line)
        sentence = match.group(1) if match else line
        if sentence.lower().startswith("first release:"):
            sentence = sentence.split(":", 1)[1].strip()
            sentence = sentence[:1].upper() + sentence[1:]
        if len(sentence) > limit:
            sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
        return sentence
    return None


class Remote(object):
    """The cache under `root`, and the thread that fills it."""

    def __init__(self, root, enabled=True, get=httpGet, clock=time.time, start=True):
        self.root = root
        self.enabled = enabled
        self._get = get
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue = collections.OrderedDict()  # key -> job
        self._tried = {}  # key -> when it last failed (memory only)
        self._github = collections.deque()  # times of recent GitHub requests
        self._githubPausedUntil = 0
        self._notes = {}  # slug -> (mtime, document)
        self._thread = None
        self._start = start

    # --- what handlers call (never blocks on the network) ---------------

    def poster(self, slug, urls):
        """The cached poster's path for `slug`, or None. Queues a fetch from
        `urls` (best first) when there is none, or when it is old."""
        if not _SLUG.match(slug or ""):
            return None
        path = os.path.join(self.root, "posters", slug + ".jpg")
        try:
            age = self._clock() - os.stat(path).st_mtime
        except OSError:
            age = None
        if age is None or age > REFRESH_SECONDS:
            self._want("poster:" + slug, ("poster", slug, tuple(urls)))
        return path if age is not None else None

    def notes(self, slug, repo, current):
        """{"version", "text", "url"} for the release `current` names, or None.
        Queues one lookup per new released version."""
        version = releasedVersion(current)
        if not version or not _SLUG.match(slug or "") or not _REPO.match(repo or ""):
            return None
        doc = self._readNotes(slug)
        if doc is None or doc.get("version") != version:
            self._want("notes:%s:%s" % (slug, version), ("notes", slug, repo, version))
            return None
        if not doc.get("text"):
            return None  # looked up: no release for this version, or an empty one
        url = doc.get("url")
        return {"version": version, "text": doc["text"], "url": url if isinstance(url, str) else None}

    # --- the queue --------------------------------------------------------

    def _want(self, key, job):
        if not self.enabled:
            return
        with self._lock:
            if key in self._queue:
                return
            failed = self._tried.get(key)
            if failed is not None and self._clock() - failed < RETRY_SECONDS:
                return
            if len(self._queue) >= QUEUE_MAX:
                return
            self._queue[key] = job
            if self._start and self._thread is None:
                self._thread = threading.Thread(target=self._run, name="arcade-remote", daemon=True)
                self._thread.start()
            self._wake.notify()

    def _run(self):
        while True:
            with self._lock:
                while not self._queue:
                    self._wake.wait()
            self.runPending()

    def runPending(self):
        """Work through the queue now (the thread's loop; tests call it directly)."""
        while True:
            with self._lock:
                if not self._queue:
                    return
                key, job = self._queue.popitem(last=False)
            try:
                ok = self._do(job)
            except Exception:  # never let one lookup stop the thread
                ok = False
            if not ok:
                with self._lock:
                    self._tried[key] = self._clock()

    def _do(self, job):
        if job[0] == "poster":
            return self._fetchPoster(job[1], job[2])
        if job[0] == "notes":
            return self._fetchNotes(job[1], job[2], job[3])
        return False

    # --- posters ----------------------------------------------------------

    def _fetchPoster(self, slug, urls):
        for url in urls:
            try:
                contentType, data = self._get(url, MAX_POSTER_BYTES, "image/jpeg")
            except Failed:
                continue
            if contentType.split(";")[0].strip().lower() != "image/jpeg" or not data.startswith(
                b"\xff\xd8\xff"
            ):
                continue
            self._write(os.path.join(self.root, "posters"), slug + ".jpg", data)
            return True
        return False

    # --- release notes ---------------------------------------------------

    def _githubAllowed(self):
        now = self._clock()
        with self._lock:
            if now < self._githubPausedUntil:
                return False
            while self._github and now - self._github[0] > 3600:
                self._github.popleft()
            if len(self._github) >= GITHUB_PER_HOUR:
                return False
            self._github.append(now)
            return True

    def _fetchNotes(self, slug, repo, version):
        if not self._githubAllowed():
            return False
        try:
            _, data = self._get(RELEASES.format(repo=repo), MAX_RELEASES_BYTES, "application/vnd.github+json")
            releases = json.loads(data.decode("utf-8"))
        except Failed as e:
            if e.status in (403, 429):
                with self._lock:
                    self._githubPausedUntil = self._clock() + GITHUB_BACKOFF
            return False
        except (UnicodeDecodeError, ValueError, RecursionError):
            return False
        if not isinstance(releases, list):
            return False
        wanted = {version.lstrip("vV"), "v" + version.lstrip("vV")}
        found = None
        for release in releases:
            if isinstance(release, dict) and release.get("tag_name") in wanted and not release.get("draft"):
                found = release
                break
        doc = {"version": version, "body": "", "url": None}
        if found is not None:
            body = found.get("body") if isinstance(found.get("body"), str) else ""
            # Kept as written (capped); cut to what a player reads when it is read, so a
            # change to release_text applies to notes already on disk.
            doc["body"] = body[:MAX_BODY]
            url = found.get("html_url")
            doc["url"] = url if isinstance(url, str) and url.startswith("https://github.com/") else None
        # Written even when there is no such release: one lookup per version.
        self._write(
            os.path.join(self.root, "notes"), slug + ".json", json.dumps(doc, sort_keys=True).encode("utf-8")
        )
        return True

    def _readNotes(self, slug):
        path = os.path.join(self.root, "notes", slug + ".json")
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return None
        cached = self._notes.get(slug)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        body = doc.get("body", "")
        if not isinstance(body, str) or not isinstance(doc.get("text", ""), str):
            return None
        doc["text"] = release_text(body) if body else doc.get("text", "")
        self._notes[slug] = (mtime, doc)
        return doc

    # --- disk -------------------------------------------------------------

    @staticmethod
    def _write(directory, name, data):
        os.makedirs(directory, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".fetch-", dir=directory)
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            os.replace(temporary, os.path.join(directory, name))
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
