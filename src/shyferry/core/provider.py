"""The only seam in the system.

Every difference between clouds is expressed through `ProviderCapabilities`, so
`core` contains no provider name and no conditional on one. A third party ships
a provider as a separate package and ShyFerry finds it at runtime.

**There is no method here that deletes permanently.** No `delete`, no `erase`,
no boolean on `recycle` that would change what it does. Both clouds expose
permanent deletion within the exact scopes ShyFerry must hold in order to
upload anything, so the guarantee cannot rest on the API lacking it - it rests
on this interface not being able to express it.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import BinaryIO, Protocol, runtime_checkable

from shyferry.core.models import AccountInfo, Quota, RemoteItem, UploadTarget

# Google requires resumable chunks in multiples of 256 KB; Microsoft Graph
# requires byte ranges in multiples of 320 KiB and warns that a size which does
# not divide evenly "can result in large file transfers failing after the last
# byte range is uploaded" - after the whole file has crossed the wire.
DRIVE_GRANULARITY = 256 * 1024
GRAPH_GRANULARITY = 320 * 1024


def common_granularity(*sizes: int) -> int:
    """The smallest chunk size satisfying every provider in a transfer.

    Their lowest common multiple, not a constant: a provider added later
    brings its own requirement rather than inheriting one that happened to
    suit the two clouds shipped first.
    """
    if not sizes:
        raise ValueError("a transfer has at least one provider")
    return math.lcm(*sizes)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What the planner and the engine must adapt to for this provider."""

    # Which algorithms this provider reports for a file's content. The
    # multi-hasher's set is the union of both sides' capabilities, so a
    # provider reporting only CRC32 is still verifiable.
    hash_algorithms: frozenset[str]

    # Naming. OneDrive's rules are richer than a character blacklist, and
    # Microsoft publishes no single maximum path length, so that one is a
    # configured conservative value rather than a fabricated authority.
    forbidden_characters: frozenset[str] = frozenset()
    reserved_names: frozenset[str] = frozenset()
    forbidden_name_prefixes: tuple[str, ...] = ()
    max_path_length: int | None = None
    max_file_size: int | None = None
    case_sensitive: bool = True
    allows_duplicate_names: bool = False

    # Uploads.
    chunk_granularity: int = DRIVE_GRANULARITY
    simple_upload_threshold: int = 4 * 1024 * 1024
    max_request_size: int | None = None

    # Google Workspace documents have no bytes to download and must be
    # exported; no other provider shipped so far has anything comparable.
    has_native_documents: bool = False

    # Hosts this provider is permitted to contact, which is what INV-8 checks
    # against. Derived from the loaded providers, never hand-listed in a test.
    hosts: frozenset[str] = field(default_factory=frozenset)

    def rejects(self, name: str) -> str | None:
        """Why this provider would refuse that file name, or None."""
        if not name:
            return "a name cannot be empty"
        if any(character in name for character in self.forbidden_characters):
            offending = sorted(set(name) & self.forbidden_characters)
            return f"contains {''.join(offending)!r}"
        if name != name.strip():
            return "has a leading or trailing space"
        if name.endswith("."):
            return "ends with a period"
        stem = name.split(".", 1)[0]
        if stem.upper() in {reserved.upper() for reserved in self.reserved_names}:
            return f"{stem!r} is a reserved name"
        if any(name.startswith(prefix) for prefix in self.forbidden_name_prefixes):
            return "begins with a forbidden prefix"
        return None


class StaleRevisionError(Exception):
    """The item changed since it was recorded, so it was not recycled.

    Graph refuses this at the server with a 412 when the recorded eTag is sent
    as `if-match`. Drive accepts no precondition, so its provider compares
    `headRevisionId` immediately before trashing and raises this itself.
    """


class UnsupportedOperationError(Exception):
    """The provider declares it cannot do this."""


@runtime_checkable
class StorageProvider(Protocol):
    """What every cloud, and the local filesystem, looks like from `core`."""

    name: str
    capabilities: ProviderCapabilities

    def account_info(self) -> AccountInfo:
        """Who this provider is signed in as, and of what kind (INV-14)."""

    def quota(self) -> Quota:
        """What this provider has room for (R-05)."""

    def iter_items(self, root: PurePosixPath, *, recursive: bool) -> Iterator[RemoteItem]:
        """Every item under `root` that belongs in a plan.

        Implementations exclude trashed items (INV-7) and items the user does
        not own (INV-13) at the query, not afterwards: a scope statement
        enforces nothing.
        """

    def open_read(self, item: RemoteItem) -> AbstractContextManager[BinaryIO]:
        """The item's bytes, from the beginning.

        There is no range parameter and nothing in ShyFerry ever reads part of
        a file: verification hashes the whole thing in flight, and a hash over
        the tail of a file is not a hash of that file.
        """

    def export(self, item: RemoteItem, target_mime: str) -> AbstractContextManager[BinaryIO]:
        """A native document converted to `target_mime`."""

    def ensure_folder(self, path: PurePosixPath) -> RemoteItem:
        """The folder at `path`, creating it and its parents if needed.

        Callers may race. Drive permits two folders with the same name in one
        parent, so an implementation that is not single-flight can split the
        tree beneath it.
        """

    def upload(self, stream: BinaryIO, dest: UploadTarget) -> RemoteItem:
        """Write `stream` to `dest` and return the item as it now stands."""

    def stat(self, path: PurePosixPath) -> RemoteItem | None:
        """The item at `path`, or None. Read fresh from the provider."""

    def recycle(self, item: RemoteItem, *, expected_revision: str) -> None:
        """Move the item to this provider's recycle bin. Never permanent.

        `expected_revision` is the value recorded at transfer time, and the
        caller must supply it. An implementation given only the item would stat
        it and compare the result with itself: signature satisfied, INV-9's
        description satisfied, nothing checked.

        Raises StaleRevisionError when the item has changed since.
        """
