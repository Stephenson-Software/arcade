# @author Daniel McCoy Stephenson
"""The hosting core's adapters, one implementation per file, and the
registries that name them.

Three production adapters are existing modules that already have exactly the
port's shape, so they are registered here rather than wrapped:

  arcade.store.Store             VersionStore and PlayCounter (the data directory)
  arcade.remote.Remote           ReleaseNotes (GitHub releases, cached on disk)
  arcade.trace_client.TraceClient EventReporter (vendored byte-for-byte from
                                 trace-client-python, so never edited here)
"""

from arcade.hosting.adapters.null_reporter import NullReporter
from arcade.hosting.adapters.reloading_yaml_catalog import ReloadingYamlCatalog
from arcade.remote import Remote
from arcade.store import Store

CATALOGS = {"yaml": ReloadingYamlCatalog}
STORES = {"filesystem": Store}
RELEASE_NOTES = {"github": Remote}
# TraceClient is imported where it is built (arcade.__main__), only when a key is set.
REPORTERS = {"none": NullReporter}

__all__ = ["CATALOGS", "NullReporter", "RELEASE_NOTES", "REPORTERS", "ReloadingYamlCatalog", "STORES"]
