"""A provider over the local filesystem.

This is not a test double. It is a supported target - ferry a cloud library to
a disk - and it contains no test-only branch. That matters twice over: the
conformance suite runs against real bytes, real directory structures and real
failure modes without a network, and the abstraction is forced to be honest,
because anything the protocol cannot express this provider cannot implement
either.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from shyferry.core.models import AccountInfo, Quota, RemoteItem, UploadTarget
from shyferry.core.provider import (
    DRIVE_GRANULARITY,
    ProviderCapabilities,
    StaleRevisionError,
    UnsupportedOperationError,
)

TRASH_DIRECTORY = ".shyferry-trash"
HASH_ALGORITHMS = ("sha256", "md5")
READ_CHUNK = 1024 * 1024


def _case_sensitive(root: Path) -> bool:
    """Ask the filesystem rather than the platform.

    macOS is usually case-insensitive and occasionally not; a network mount on
    Linux can be either. The planner's collision handling depends on the
    answer, so it is measured where the files actually are.
    """
    probe = root / ".shyferry-case-probe"
    try:
        probe.write_bytes(b"")
        return not (root / ".SHYFERRY-CASE-PROBE").exists()
    except OSError:  # pragma: no cover - unwritable root, handled by callers
        return os.name != "nt"
    finally:
        probe.unlink(missing_ok=True)


class LocalProvider:
    """The filesystem under `root`, addressed with POSIX-shaped paths."""

    name = "local"

    def __init__(self, root: Path | str, *, hash_on_list: bool = True) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Listing a cloud gets hashes for free in the provider's response; a
        # filesystem has to read the bytes. Computing them anyway is what lets
        # a local-to-local transfer be genuinely verified, which is the whole
        # point of this provider existing.
        self._hash_on_list = hash_on_list
        self._folder_lock = threading.Lock()
        self.capabilities = ProviderCapabilities(
            hash_algorithms=frozenset(HASH_ALGORITHMS),
            # Deliberately the union of what the two clouds forbid, so a tree
            # that survives a round trip through `local` survives a round trip
            # through either of them.
            forbidden_characters=frozenset('"*:<>?/\\|'),
            reserved_names=frozenset(
                {".lock", "CON", "PRN", "AUX", "NUL", "desktop.ini"}
                | {f"COM{n}" for n in range(10)}
                | {f"LPT{n}" for n in range(10)}
            ),
            forbidden_name_prefixes=("~$",),
            max_path_length=None,
            case_sensitive=_case_sensitive(self.root),
            allows_duplicate_names=False,
            chunk_granularity=DRIVE_GRANULARITY,
            has_native_documents=False,
            hosts=frozenset(),
        )

    # --- addressing -------------------------------------------------------

    def _local(self, path: PurePosixPath) -> Path:
        relative = PurePosixPath(*[part for part in path.parts if part != "/"])
        return self.root / Path(*relative.parts)

    def _remote(self, path: Path) -> PurePosixPath:
        return PurePosixPath("/") / PurePosixPath(*path.relative_to(self.root).parts)

    @property
    def _trash(self) -> Path:
        return self.root / TRASH_DIRECTORY

    # --- identity and space ----------------------------------------------

    def account_info(self) -> AccountInfo:
        return AccountInfo(identifier=str(self.root), display_name=str(self.root), kind="personal")

    def quota(self) -> Quota:
        usage = shutil.disk_usage(self.root)
        return Quota(total=usage.total, used=usage.used, available=usage.free)

    # --- reading ----------------------------------------------------------

    def _hashes(self, path: Path) -> dict[str, str]:
        digests = {name: hashlib.new(name) for name in HASH_ALGORITHMS}
        with path.open("rb") as handle:
            while chunk := handle.read(READ_CHUNK):
                for digest in digests.values():
                    digest.update(chunk)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def _item(self, path: Path, *, with_hashes: bool) -> RemoteItem:
        stat = path.stat()
        is_folder = path.is_dir()
        return RemoteItem(
            id=str(path),
            path=self._remote(path),
            size=0 if is_folder else stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            hashes={} if is_folder or not with_hashes else self._hashes(path),
            mime="inode/directory" if is_folder else "application/octet-stream",
            is_folder=is_folder,
            is_native=False,
            # Size and modification time: what a filesystem offers, and enough
            # to answer INV-9's question of whether the content changed since
            # it was recorded.
            revision=f"{stat.st_size}-{stat.st_mtime_ns}",
        )

    def iter_items(self, root: PurePosixPath, *, recursive: bool) -> Iterator[RemoteItem]:
        start = self._local(root)
        if not start.exists():
            return
        entries = sorted(start.rglob("*") if recursive else start.glob("*"))
        for path in entries:
            # Excluded by the provider itself, unconditionally. Left to a
            # user-supplied filter, a second run over the same root would
            # ferry previously recycled files back again.
            if TRASH_DIRECTORY in path.relative_to(self.root).parts:
                continue
            yield self._item(path, with_hashes=self._hash_on_list and path.is_file())

    @contextmanager
    def open_read(self, item: RemoteItem) -> Iterator[BinaryIO]:
        with self._local(item.path).open("rb") as handle:
            yield handle

    def export(self, item: RemoteItem, target_mime: str) -> AbstractContextManager[BinaryIO]:
        # Raises on call rather than on entry, which is what the caller wants:
        # `with provider.export(...)` fails before any resource is acquired.
        # Writing this as a generator with an unreachable yield would make it
        # a context manager that raises later and reads as dead code.
        raise UnsupportedOperationError(
            f"{self.name} has no native document types; nothing here needs exporting"
        )

    def stat(self, path: PurePosixPath) -> RemoteItem | None:
        local = self._local(path)
        if not local.exists():
            return None
        return self._item(local, with_hashes=local.is_file())

    # --- writing ----------------------------------------------------------

    def ensure_folder(self, path: PurePosixPath) -> RemoteItem:
        local = self._local(path)
        # Single-flight. A filesystem tolerates a racing mkdir, but the item
        # identity returned must still be one thing: the conformance suite
        # races eight workers at one path and asserts a single identifier,
        # because Drive would otherwise create two folders of the same name
        # and split the tree beneath them.
        with self._folder_lock:
            local.mkdir(parents=True, exist_ok=True)
        return self._item(local, with_hashes=False)

    def upload(self, stream: BinaryIO, dest: UploadTarget) -> RemoteItem:
        local = self._local(dest.path)
        local.parent.mkdir(parents=True, exist_ok=True)
        with local.open("wb") as handle:
            while chunk := stream.read(READ_CHUNK):
                handle.write(chunk)
        if dest.modified is not None:
            stamp = dest.modified.timestamp()
            os.utime(local, (stamp, stamp))
        return self._item(local, with_hashes=True)

    # --- deletion, which is only ever the recycle bin ---------------------

    def recycle(self, item: RemoteItem, *, expected_revision: str) -> None:
        local = self._local(item.path)
        if not local.exists():
            raise FileNotFoundError(f"{item.path} is already gone")

        current = self._item(local, with_hashes=False).revision
        if current != expected_revision:
            raise StaleRevisionError(
                f"{item.path} is at revision {current!r}, not the recorded {expected_revision!r}. "
                "It changed after it was transferred, so the destination holds the old content."
            )

        # The desktop trash differs per platform and cannot be asserted
        # identically across the CI matrix, so this provider keeps its own and
        # excludes it from enumeration.
        destination = self._trash / local.relative_to(self.root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination = destination.with_name(f"{destination.name}.{item.revision}")
        shutil.move(str(local), str(destination))
