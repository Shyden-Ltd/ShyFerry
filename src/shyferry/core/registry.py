"""Finding providers, including ones this codebase has never heard of.

A third party ships a provider as a separate package on PyPI declaring the
`shyferry.providers` entry-point group, and ShyFerry finds it at runtime. That
is what makes the extensibility structural rather than aspirational: adding a
cloud requires no change here.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

from shyferry.core.errors import ConfigurationError

GROUP = "shyferry.providers"


def discovered() -> Mapping[str, Any]:
    """Every provider factory currently installed, by the name it registers."""
    return {entry.name: entry for entry in entry_points(group=GROUP)}


def load(name: str) -> Any:
    """The provider class registered under `name`.

    Raises ConfigurationError naming what IS available, because "unknown
    provider: gdrve" is only half an error message.
    """
    found = discovered()
    if name not in found:
        available = ", ".join(sorted(found)) or "none"
        raise ConfigurationError(f"no provider named {name!r} is installed. Available: {available}")
    return found[name].load()


def hosts_of(*providers: Any) -> frozenset[str]:
    """Every host the given providers declare they contact.

    INV-8 asserts that ShyFerry reaches nothing else. The allowed set is
    derived from the providers actually loaded, never written into a test: a
    hand-listed set goes stale the first time a provider adds an endpoint, and
    goes stale silently.
    """
    hosts: set[str] = set()
    for provider in providers:
        hosts |= set(provider.capabilities.hosts)
    return frozenset(hosts)
