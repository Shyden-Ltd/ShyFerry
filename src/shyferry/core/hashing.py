"""Computing every hash either side might report, in one pass over the bytes.

Google Drive reports MD5, SHA-1 and SHA-256, and only for files with binary
content. OneDrive reports quickXorHash, CRC32 and SHA-1, and Microsoft's own
reference says SHA-256 "isn't supported, don't use". The two sets cannot be
compared with each other, so both are compared against the value computed here
as the bytes pass through. Read integrity and write integrity become separate
questions with one answer each, and no cross-algorithm comparison is ever
needed.

Which algorithms run is derived from the providers in hand, never fixed in
code. A provider reporting only CRC32 would otherwise be unverifiable purely
because nobody remembered to add CRC32 to a list - and an item that cannot be
verified can never be deleted, so a stale list quietly costs users the feature
they came for.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from typing import Protocol

from shyferry.core.errors import ConfigurationError
from shyferry.core.provider import ProviderCapabilities


class Digest(Protocol):
    """What a hash implementation has to offer. `hashlib` already matches."""

    def update(self, data: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


# Algorithms that are not in hashlib. quickXorHash joins here in Phase 3,
# written from Microsoft's published algorithm description rather than
# transcribed from their C# sample - which keeps this Apache-2.0 repository
# clear of a vendor sample-code licensing question, and avoids inheriting the
# sample's own architecture-dependent caveats.
_REGISTERED: dict[str, Callable[[], Digest]] = {}


def register_algorithm(name: str, factory: Callable[[], Digest] | None) -> None:
    """Add a hash implementation under `name`, or remove it with None."""
    if factory is None:
        _REGISTERED.pop(name, None)
        return
    _REGISTERED[name] = factory


def available() -> frozenset[str]:
    return frozenset(hashlib.algorithms_available) | frozenset(_REGISTERED)


def algorithms_for(*capabilities: ProviderCapabilities) -> frozenset[str]:
    """Every algorithm the given providers report, taken together."""
    wanted: set[str] = set()
    for capability in capabilities:
        wanted |= set(capability.hash_algorithms)
    return frozenset(wanted)


def _make(name: str) -> Digest:
    if name in _REGISTERED:
        return _REGISTERED[name]()
    return hashlib.new(name)


class MultiHasher:
    """Feeds every chunk to every algorithm, once."""

    def __init__(self, algorithms: Iterable[str]) -> None:
        wanted = frozenset(algorithms)
        # Refused at construction, which is the start of a run, rather than
        # when the first digest is asked for - which is the end of a transfer
        # that may have taken hours.
        unusable = sorted(wanted - available())
        if unusable:
            usable = sorted(available())
            shown = ", ".join(usable[:8])
            more = f" and {len(usable) - 8} more" if len(usable) > 8 else ""
            raise ConfigurationError(
                f"no implementation for {', '.join(unusable)}. Available: {shown}{more}"
            )
        self._digests: dict[str, Digest] = {name: _make(name) for name in sorted(wanted)}
        self.length = 0

    def update(self, chunk: bytes) -> None:
        for digest in self._digests.values():
            digest.update(chunk)
        self.length += len(chunk)

    def digests(self) -> dict[str, str]:
        return {name: digest.hexdigest() for name, digest in self._digests.items()}
