"""The multi-hasher: every algorithm either side might report, computed once.

The two clouds report incompatible hashes and cannot be compared with each
other. Both are compared instead against the value computed locally as the
bytes pass through, which is what makes read integrity and write integrity
separate questions with one answer each.
"""

from __future__ import annotations

import hashlib

import pytest

from shyferry.core.errors import ConfigurationError
from shyferry.core.hashing import MultiHasher, algorithms_for, register_algorithm
from shyferry.core.provider import ProviderCapabilities

PAYLOAD = b"the bytes that must survive the crossing"


def capabilities(*algorithms: str) -> ProviderCapabilities:
    return ProviderCapabilities(hash_algorithms=frozenset(algorithms))


class TestTheAlgorithmSet:
    def test_it_is_the_union_of_both_sides(self) -> None:
        # Derived from the providers in hand, never a constant. A provider
        # reporting only CRC32 would otherwise be unverifiable because nobody
        # remembered to add CRC32 to a list - and unverifiable means
        # undeletable, so a stale list quietly costs users the feature they
        # came for.
        source = capabilities("md5", "sha256")
        destination = capabilities("quickxorhash", "sha1")
        assert algorithms_for(source, destination) == frozenset(
            {"md5", "sha256", "quickxorhash", "sha1"}
        )

    def test_one_provider_alone_still_gives_a_set(self) -> None:
        assert algorithms_for(capabilities("sha256")) == frozenset({"sha256"})

    def test_an_algorithm_nobody_implements_is_refused_loudly(self) -> None:
        # Better here, at the start of a run, than in the middle of a 400GB
        # transfer when the first digest is asked for.
        with pytest.raises(ConfigurationError) as raised:
            MultiHasher(frozenset({"sha256", "imaginary"}))
        # Only the unusable one is named as the problem. The message goes on
        # to list what IS available, which legitimately includes sha256, so
        # the assertion is about where the name appears rather than whether.
        assert str(raised.value).startswith("no implementation for imaginary")


class TestComputing:
    def test_it_computes_every_requested_algorithm(self) -> None:
        hasher = MultiHasher(frozenset({"md5", "sha256"}))
        hasher.update(PAYLOAD)
        assert hasher.digests() == {
            "md5": hashlib.md5(PAYLOAD).hexdigest(),
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        }

    def test_chunking_does_not_change_the_answer(self) -> None:
        # The engine feeds it 7.5 MiB at a time; the test feeds it one byte at
        # a time. A hasher that cared would be a transfer that fails on file
        # size alone.
        whole = MultiHasher(frozenset({"sha256"}))
        whole.update(PAYLOAD)

        piecemeal = MultiHasher(frozenset({"sha256"}))
        for index in range(len(PAYLOAD)):
            piecemeal.update(PAYLOAD[index : index + 1])

        assert whole.digests() == piecemeal.digests()

    def test_empty_input_still_produces_digests(self) -> None:
        # The simplest possible file must not be the one that breaks
        # verification and so becomes undeletable.
        hasher = MultiHasher(frozenset({"sha256"}))
        assert hasher.digests() == {"sha256": hashlib.sha256(b"").hexdigest()}

    def test_it_counts_the_bytes_it_saw(self) -> None:
        hasher = MultiHasher(frozenset({"sha256"}))
        hasher.update(PAYLOAD)
        hasher.update(PAYLOAD)
        assert hasher.length == 2 * len(PAYLOAD)


class TestExtension:
    def test_a_provider_specific_algorithm_can_be_registered(self) -> None:
        """quickXorHash joins here in Phase 3 without touching any caller.

        Microsoft publishes an algorithm description and a C# reference but no
        known-answer vectors, so it arrives as an implementation registered
        under its name rather than as a special case in the engine.
        """

        class Doubling:
            def __init__(self) -> None:
                self._seen = bytearray()

            def update(self, chunk: bytes) -> None:
                self._seen.extend(chunk)

            def hexdigest(self) -> str:
                return self._seen.hex()

        register_algorithm("doubling-test", Doubling)
        try:
            hasher = MultiHasher(frozenset({"doubling-test"}))
            hasher.update(b"\x01\x02")
            assert hasher.digests() == {"doubling-test": "0102"}
        finally:
            register_algorithm("doubling-test", None)

        with pytest.raises(ConfigurationError):
            MultiHasher(frozenset({"doubling-test"}))
