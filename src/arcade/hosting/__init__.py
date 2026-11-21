# @author Daniel McCoy Stephenson
"""The hosting core: games, versions, deploys and plays, behind ports.

    callers (arcade.server's HTTP handler, arcade.__main__)
        -> service.Service        composition root: production adapters
        -> core.Hosting           pure policy, no I/O
        -> ports/*                one interface per file
        <- adapters/* + existing modules that implement them

  Port            Production adapter                     Test double
  GameCatalog     adapters.ReloadingYamlCatalog          FakeCatalog
  VersionStore    arcade.store.Store                     FakeStore
  PlayCounter     arcade.store.Store                     FakeStore
  EventReporter   arcade.trace_client.TraceClient,       Recorder
                  adapters.NullReporter (trace off)
  ReleaseNotes    arcade.remote.Remote                   FakeNotes

Dependencies point inward: model, core and ports never import adapters or
service (tests/test_hosting_architecture.py enforces it).

To add a new backend for a port: one new file in adapters/ implementing it,
one entry in that port's registry in adapters/__init__.py, and a run of the
port's contract test in tests/test_hosting_contracts.py against it.
"""

from arcade.hosting.core import Hosting, addedOf, hashToken
from arcade.hosting.model import Denied, Deployed, Rejected
from arcade.hosting.service import Service

__all__ = ["Denied", "Deployed", "Hosting", "Rejected", "Service", "addedOf", "hashToken"]
