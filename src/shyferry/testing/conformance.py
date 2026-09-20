"""One suite, run against every provider.

A provider is correct when it passes this. It ships inside the package rather
than under `tests/`, so a third party writing a provider for another cloud can
prove it against exactly the tests the built-in ones pass:

    from shyferry.testing.conformance import ProviderConformance

    class TestDropbox(ProviderConformance):
        @pytest.fixture()
        def provider(self):
            return DropboxProvider(...)

Every assertion here is about behaviour the engine relies on. Where a provider
legitimately differs - which hashes it reports, whether names are case
sensitive - the suite asks its capabilities rather than assuming.
"""

from __future__ import annotations

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

import pytest

from shyferry.core.models import RemoteItem, UploadTarget
from shyferry.core.provider import (
    StaleRevisionError,
    StorageProvider,
    UnsupportedOperationError,
)

# Names no provider may be asked to reject, used as the positive control for
# the naming test: if a provider forbids nothing, that test must still be
# exercising something.
PLAIN_NAME = "plain-file.txt"

FORBIDDEN_METHOD_NAMES = (
    "delete",
    "delete_permanently",
    "erase",
    "destroy",
    "purge",
    "empty_trash",
    "permanent_delete",
)


class ProviderConformance:
    """Subclass this and supply a `provider` fixture."""

    @pytest.fixture()
    def provider(self) -> StorageProvider:  # pragma: no cover - overridden
        raise NotImplementedError("a conformance subclass supplies its provider")

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def put(provider: StorageProvider, path: str, payload: bytes) -> RemoteItem:
        parent = PurePosixPath(path).parent
        if str(parent) not in (".", "/"):
            provider.ensure_folder(parent)
        return provider.upload(
            io.BytesIO(payload),
            UploadTarget(path=PurePosixPath(path), size=len(payload), modified=None),
        )

    @staticmethod
    def read(provider: StorageProvider, item: RemoteItem) -> bytes:
        with provider.open_read(item) as stream:
            return stream.read()

    # --- the protocol itself ---------------------------------------------

    def test_the_protocol_exposes_no_way_to_delete_permanently(
        self, provider: StorageProvider
    ) -> None:
        """INV-2. The guarantee cannot rest on the API lacking the capability.

        Both clouds expose permanent deletion within the exact scopes ShyFerry
        must hold to upload anything, so it rests on this interface not being
        able to express it.
        """
        for name in FORBIDDEN_METHOD_NAMES:
            assert not hasattr(provider, name), (
                f"{type(provider).__name__} exposes {name!r}. Deletion is the recycle bin, "
                "and no code path may be able to express anything else."
            )
        # Positive control: the method that IS allowed must exist, or this
        # test would pass against an object with no methods at all.
        assert hasattr(provider, "recycle")

    def test_it_declares_at_least_one_hash_algorithm(self, provider: StorageProvider) -> None:
        # A provider reporting no hash can never have a file verified, and an
        # unverifiable file can never be deleted. That is a legitimate state
        # per item, but not a legitimate provider.
        assert provider.capabilities.hash_algorithms

    def test_its_chunk_granularity_is_usable(self, provider: StorageProvider) -> None:
        granularity = provider.capabilities.chunk_granularity
        assert granularity > 0
        assert granularity % 1024 == 0, "every provider so far counts in whole kibibytes"

    # --- round trips ------------------------------------------------------

    def test_a_file_round_trips_byte_for_byte(self, provider: StorageProvider) -> None:
        payload = b"ferry me across\n\x00\xff binary too"
        item = self.put(provider, "/round-trip.bin", payload)
        assert item.size == len(payload)
        assert self.read(provider, item) == payload

    def test_a_zero_byte_file_round_trips(self, provider: StorageProvider) -> None:
        """The awkward boundary: providers differ on whether they hash nothing.

        A zero-byte file whose destination reports no hash is unverifiable and
        therefore undeletable, which would be a surprising outcome for the
        simplest possible file. The suite records which it is rather than
        leaving it to be discovered.
        """
        item = self.put(provider, "/empty.bin", b"")
        assert item.size == 0
        assert self.read(provider, item) == b""
        # Not an assertion about which way it goes - an assertion that the
        # provider answers the question at all.
        assert isinstance(item.hashes, dict | type({}.items().mapping))

    def test_reported_hashes_match_locally_computed_values(self, provider: StorageProvider) -> None:
        payload = b"the bytes that must survive the crossing"
        item = self.put(provider, "/hashed.bin", payload)
        checked = 0
        for algorithm, reported in item.hashes.items():
            if algorithm not in hashlib.algorithms_available:
                continue  # a provider-specific algorithm, checked in its own suite
            digest = hashlib.new(algorithm, payload).hexdigest()
            assert reported.lower() == digest, f"{algorithm} disagrees with the bytes we sent"
            checked += 1
        assert checked, (
            "no reported hash could be checked against hashlib. A provider whose only "
            "algorithm is its own must assert it in its own suite, or this passes vacuously."
        )

    # --- folders ----------------------------------------------------------

    def test_an_empty_folder_is_created_and_found(self, provider: StorageProvider) -> None:
        # An empty folder is content: a migration that silently drops the
        # user's folder structure has not moved their library.
        created = provider.ensure_folder(PurePosixPath("/empty-folder"))
        assert created.is_folder
        found = provider.stat(PurePosixPath("/empty-folder"))
        assert found is not None and found.is_folder

    def test_it_enumerates_a_nested_tree(self, provider: StorageProvider) -> None:
        self.put(provider, "/tree/a.txt", b"a")
        self.put(provider, "/tree/deeper/b.txt", b"b")
        paths = {
            str(item.path) for item in provider.iter_items(PurePosixPath("/tree"), recursive=True)
        }
        assert "/tree/a.txt" in paths
        assert "/tree/deeper/b.txt" in paths

    def test_a_shallow_enumeration_stops_at_the_first_level(
        self, provider: StorageProvider
    ) -> None:
        self.put(provider, "/shallow/top.txt", b"top")
        self.put(provider, "/shallow/down/deep.txt", b"deep")
        paths = {
            str(item.path)
            for item in provider.iter_items(PurePosixPath("/shallow"), recursive=False)
        }
        assert "/shallow/top.txt" in paths
        assert "/shallow/down/deep.txt" not in paths

    def test_racing_workers_at_one_path_produce_one_folder(self, provider: StorageProvider) -> None:
        """Drive permits two folders with the same name in the same parent.

        Two workers creating the same path concurrently would produce two
        folders and silently split the tree beneath them, so single-flight
        creation is a correctness requirement and not an optimisation.
        """
        path = PurePosixPath("/raced/deeply/nested")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: provider.ensure_folder(path), range(8)))
        assert len({item.id for item in results}) == 1, "the tree was split by a race"

    # --- naming -----------------------------------------------------------

    def test_it_refuses_the_names_its_capabilities_forbid(self, provider: StorageProvider) -> None:
        capabilities = provider.capabilities
        assert capabilities.rejects(PLAIN_NAME) is None, (
            "positive control: an ordinary name must be accepted, or every "
            "assertion below passes for the wrong reason"
        )
        for character in capabilities.forbidden_characters:
            assert capabilities.rejects(f"bad{character}name.txt") is not None
        for reserved in capabilities.reserved_names:
            assert capabilities.rejects(reserved) is not None
            if "." not in reserved:
                # Two shapes, and a dot in the reserved name tells them apart.
                # `CON` is reserved as a STEM, so Windows refuses `CON.txt` as
                # readily as `CON`. `.lock` and `desktop.ini` are reserved as
                # WHOLE names, and `desktop.ini.txt` is an ordinary file that
                # nobody should refuse.
                assert capabilities.rejects(f"{reserved}.txt") is not None
        for prefix in capabilities.forbidden_name_prefixes:
            assert capabilities.rejects(f"{prefix}file.txt") is not None

    # --- recycling --------------------------------------------------------

    def test_recycle_removes_an_item_from_the_listing(self, provider: StorageProvider) -> None:
        item = self.put(provider, "/to-recycle.txt", b"bye")
        provider.recycle(item, expected_revision=item.revision)
        assert provider.stat(PurePosixPath("/to-recycle.txt")) is None

    def test_recycle_refuses_a_stale_revision(self, provider: StorageProvider) -> None:
        """INV-9, at the provider.

        A file edited between transfer and purge must not be recycled: the
        destination holds the old content, and deleting the new one loses it.
        """
        item = self.put(provider, "/changed.txt", b"before")
        self.put(provider, "/changed.txt", b"after-and-longer")
        with pytest.raises(StaleRevisionError):
            provider.recycle(item, expected_revision=item.revision)
        assert provider.stat(PurePosixPath("/changed.txt")) is not None

    def test_a_revision_changes_when_the_content_does(self, provider: StorageProvider) -> None:
        # Without this, the stale-revision test above could pass against a
        # provider whose revision is a constant.
        first = self.put(provider, "/revised.txt", b"one")
        second = self.put(provider, "/revised.txt", b"two-and-different")
        assert first.revision != second.revision

    # --- declared limits --------------------------------------------------

    def test_it_refuses_what_it_declares_it_cannot_do(self, provider: StorageProvider) -> None:
        if provider.capabilities.has_native_documents:
            pytest.skip("this provider exports native documents; covered by its own suite")
        item = self.put(provider, "/not-native.txt", b"x")
        # Called, not entered: a provider that cannot export must refuse
        # before it hands back anything to be closed.
        with pytest.raises(UnsupportedOperationError):
            provider.export(item, "application/pdf")
