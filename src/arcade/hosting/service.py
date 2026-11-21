# @author Daniel McCoy Stephenson
"""The composition root: a Hosting core wired to the production adapters."""

from arcade.hosting.adapters.null_reporter import NullReporter
from arcade.hosting.adapters.reloading_yaml_catalog import ReloadingYamlCatalog
from arcade.hosting.core import Hosting
from arcade.store import Store


class Service(object):
    """Builds the core from a server Config.

    The catalog is built first: a missing or invalid games.yaml raises before
    anything is written to the data directory. `reporter` is the caller's
    choice (None: trace is off). `notes` and `visits` are shared with the rest
    of the server (the hall, and arcade.server.Arcade), so the caller builds
    them and passes them in. `log` takes one line for the server's log.
    """

    def __init__(self, config, notes, visits, log, reporter=None):
        self.catalog = ReloadingYamlCatalog(config.registryPath, config.domain, log)
        self.store = Store(config.dataDirectory, keep=config.keep)
        self.core = Hosting(
            domain=config.domain,
            catalog=self.catalog,
            versions=self.store,
            counter=self.store,
            reporter=reporter if reporter is not None else NullReporter(),
            notes=notes,
            visits=visits,
            maxUploadBytes=config.maxUploadBytes,
            log=log,
        )
