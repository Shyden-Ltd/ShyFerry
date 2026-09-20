"""Behaviour specific to the local provider, which the shared suite cannot express.

The conformance suite asks every provider the same questions. These are the
ones only this provider can be asked: where its recycle bin lives, what its
revision token is made of, and what it does on a second run over a root it has
already emptied.
"""

from __future__ import annotations

import io
from pathlib import Path, PurePosixPath

import pytest

from shyferry.core.models import UploadTarget
from shyferry.core.provider import StaleRevisionError
from shyferry.providers.local import TRASH_DIRECTORY, LocalProvider


@pytest.fixture()
def provider(tmp_path: Path) -> LocalProvider:
    return LocalProvider(tmp_path)


def put(provider: LocalProvider, path: str, payload: bytes) -> None:
    provider.upload(
        io.BytesIO(payload),
        UploadTarget(path=PurePosixPath(path), size=len(payload), modified=None),
    )


class TestTheTrash:
    def test_recycling_moves_the_file_and_keeps_its_relative_path(
        self, provider: LocalProvider, tmp_path: Path
    ) -> None:
        put(provider, "/holiday/photos/beach.jpg", b"sand")
        item = provider.stat(PurePosixPath("/holiday/photos/beach.jpg"))
        assert item is not None

        provider.recycle(item, expected_revision=item.revision)

        assert not (tmp_path / "holiday" / "photos" / "beach.jpg").exists()
        recycled = tmp_path / TRASH_DIRECTORY / "holiday" / "photos" / "beach.jpg"
        assert recycled.read_bytes() == b"sand", (
            "the bytes must survive, this is a bin not a shredder"
        )

    def test_a_second_run_does_not_ferry_recycled_files_back(self, provider: LocalProvider) -> None:
        """The exclusion is the provider's own, not a filter the caller passes.

        Left to a user-supplied filter, a second run over the same root would
        find everything the first run recycled and carry it across again -
        and, worse, would then recycle it a second time.
        """
        put(provider, "/recycled.txt", b"one")
        # A second file that stays put, so the enumeration below is not empty.
        # Without it, "no trash path appears" passes because nothing appears
        # at all - which is the vacuity this whole codebase keeps hunting.
        put(provider, "/kept.txt", b"two")

        item = provider.stat(PurePosixPath("/recycled.txt"))
        assert item is not None
        provider.recycle(item, expected_revision=item.revision)

        seen = [str(i.path) for i in provider.iter_items(PurePosixPath("/"), recursive=True)]
        assert "/kept.txt" in seen, "positive control: the survivor must be enumerable"
        assert not any(TRASH_DIRECTORY in path for path in seen)
        assert "/recycled.txt" not in seen

    def test_two_files_recycled_from_one_path_do_not_overwrite_each_other(
        self, provider: LocalProvider, tmp_path: Path
    ) -> None:
        # A bin that silently overwrites is a shredder with extra steps.
        put(provider, "/notes.txt", b"first")
        first = provider.stat(PurePosixPath("/notes.txt"))
        assert first is not None
        provider.recycle(first, expected_revision=first.revision)

        put(provider, "/notes.txt", b"second-and-longer")
        second = provider.stat(PurePosixPath("/notes.txt"))
        assert second is not None
        provider.recycle(second, expected_revision=second.revision)

        recycled = sorted((tmp_path / TRASH_DIRECTORY).glob("notes.txt*"))
        assert len(recycled) == 2
        assert {path.read_bytes() for path in recycled} == {b"first", b"second-and-longer"}


class TestTheRevisionToken:
    def test_it_changes_when_the_content_changes(self, provider: LocalProvider) -> None:
        put(provider, "/f.txt", b"one")
        before = provider.stat(PurePosixPath("/f.txt"))
        put(provider, "/f.txt", b"two-and-longer")
        after = provider.stat(PurePosixPath("/f.txt"))
        assert before is not None and after is not None
        assert before.revision != after.revision

    def test_recycling_refuses_a_file_that_changed_since_it_was_recorded(
        self, provider: LocalProvider
    ) -> None:
        """INV-9 at its smallest scale.

        The destination holds what was transferred. Deleting a source that has
        since been edited destroys the only copy of the newer content.
        """
        put(provider, "/edited.txt", b"as transferred")
        recorded = provider.stat(PurePosixPath("/edited.txt"))
        assert recorded is not None

        put(provider, "/edited.txt", b"edited afterwards, longer")

        with pytest.raises(StaleRevisionError) as raised:
            provider.recycle(recorded, expected_revision=recorded.revision)
        assert "changed after it was transferred" in str(raised.value)
        assert provider.stat(PurePosixPath("/edited.txt")) is not None


class TestCapabilities:
    def test_case_sensitivity_is_measured_not_assumed(self, provider: LocalProvider) -> None:
        # Asked of the filesystem where the files actually are: macOS is
        # usually case-insensitive and occasionally not, and a network mount
        # on Linux can be either.
        assert isinstance(provider.capabilities.case_sensitive, bool)

    def test_it_forbids_the_union_of_what_the_clouds_forbid(self, provider: LocalProvider) -> None:
        # So that a tree which survives a round trip through `local` survives
        # a round trip through either cloud.
        capabilities = provider.capabilities
        assert capabilities.rejects("ordinary.txt") is None
        for name in ('quote".txt', "star*.txt", "colon:.txt", "pipe|.txt", "CON.txt", "~$temp.doc"):
            assert capabilities.rejects(name) is not None, f"{name!r} should have been refused"

    def test_the_chunk_granularity_suits_both_clouds(self, provider: LocalProvider) -> None:
        from shyferry.core.provider import (
            DRIVE_GRANULARITY,
            GRAPH_GRANULARITY,
            common_granularity,
        )

        shared = common_granularity(DRIVE_GRANULARITY, GRAPH_GRANULARITY)
        assert shared == 1_310_720, "1.25 MiB, the lowest common multiple of 256 KB and 320 KiB"
        # 7.5 MiB is the sixth multiple of it and sits inside Graph's
        # recommended 5-10 MiB band. A plain 8 MiB is NOT a multiple of
        # 320 KiB, and Graph warns that such a size can fail after the last
        # byte range is uploaded - after the whole file has crossed.
        assert (7.5 * 1024 * 1024) % shared == 0
        assert (8 * 1024 * 1024) % GRAPH_GRANULARITY != 0
