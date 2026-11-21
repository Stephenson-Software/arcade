# @author Daniel McCoy Stephenson
"""ReloadingYamlCatalog: the GameCatalog read from games.yaml."""

import os
import threading

from arcade import registry as registryModule


class ReloadingYamlCatalog(object):
    """The registry, reloaded when its file changes. A file that no longer
    parses is logged and the last good registry stays in force."""

    def __init__(self, path, domain, log):
        self.path = path
        self.domain = domain
        self._log = log
        self._lock = threading.Lock()
        self._mtime = None
        self._registry = registryModule.Registry([])
        self.refresh(initial=True)

    def refresh(self, initial=False):
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError as e:
            if initial:
                raise
            self._log("registry unreadable, keeping the last good one: %s" % e)
            return
        with self._lock:
            if mtime == self._mtime:
                return
            try:
                loaded = registryModule.load(self.path, domain=self.domain)
            except (registryModule.RegistryError, OSError) as e:
                if initial:
                    raise
                self._log("registry invalid, keeping the last good one: %s" % e)
                self._mtime = mtime
                return
            self._registry = loaded
            self._mtime = mtime
            self._log("registry loaded: %d game(s): %s" % (len(loaded), ", ".join(g.slug for g in loaded)))

    @property
    def registry(self):
        self.refresh()
        return self._registry

    def games(self):
        return self.registry
