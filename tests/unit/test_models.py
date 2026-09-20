"""The vocabulary every other module speaks."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from shyferry.core.errors import LocatorError
from shyferry.core.models import CollisionPolicy, Locator, RemoteItem


class TestLocator:
    def test_it_parses_provider_account_and_path(self) -> None:
        locator = Locator.parse("gdrive@work:/Archive/2024")
        assert locator.provider == "gdrive"
        assert locator.account == "work"
        assert locator.path == PurePosixPath("/Archive/2024")

    def test_the_account_is_optional(self) -> None:
        locator = Locator.parse("onedrive:/Photos")
        assert locator.provider == "onedrive"
        assert locator.account is None
        assert locator.path == PurePosixPath("/Photos")

    def test_a_bare_path_means_local(self) -> None:
        # Typing a path and getting a cryptic error about an unknown provider
        # would be a poor first five seconds with the tool.
        assert Locator.parse("/tmp/backup") == Locator("local", None, PurePosixPath("/tmp/backup"))
        assert Locator.parse("./relative").provider == "local"

    def test_a_windows_drive_letter_is_a_path_not_a_provider(self) -> None:
        # The one place the `provider:path` grammar is genuinely ambiguous, and
        # a third of the test matrix runs on Windows.
        locator = Locator.parse(r"C:\Users\shyden\Backup")
        assert locator.provider == "local"
        assert "Users" in str(locator.path)

    def test_an_empty_path_is_refused_rather_than_guessed(self) -> None:
        with pytest.raises(LocatorError):
            Locator.parse("gdrive:")

    def test_an_empty_provider_is_refused(self) -> None:
        with pytest.raises(LocatorError):
            Locator.parse("@work:/x")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("gdrive:/", PurePosixPath("/")),
            ("gdrive:/a/b/", PurePosixPath("/a/b")),
            ("local:~/Backup", PurePosixPath("~/Backup")),
        ],
    )
    def test_paths_normalise_without_losing_meaning(
        self, text: str, expected: PurePosixPath
    ) -> None:
        assert Locator.parse(text).path == expected

    def test_it_round_trips_through_its_own_text(self) -> None:
        for text in ("gdrive@work:/Archive", "onedrive:/Photos", "local:/tmp/x"):
            assert str(Locator.parse(text)) == text


class TestContainment:
    """INV-12's arithmetic. The refusal itself is pre-flight's job."""

    def test_a_destination_inside_its_source_is_contained(self) -> None:
        source = Locator("gdrive", "me", PurePosixPath("/Photos"))
        destination = Locator("gdrive", "me", PurePosixPath("/Photos/Copy"))
        assert destination.is_within(source)

    def test_the_same_path_is_contained(self) -> None:
        source = Locator("gdrive", "me", PurePosixPath("/Photos"))
        assert source.is_within(source)

    def test_a_sibling_whose_name_shares_a_prefix_is_not_contained(self) -> None:
        # String containment would call /Photos2 a child of /Photos, and
        # refuse a transfer that is perfectly legitimate.
        source = Locator("gdrive", "me", PurePosixPath("/Photos"))
        assert not Locator("gdrive", "me", PurePosixPath("/Photos2")).is_within(source)

    def test_the_same_path_on_another_account_is_not_contained(self) -> None:
        source = Locator("gdrive", "me", PurePosixPath("/Photos"))
        assert not Locator("gdrive", "other", PurePosixPath("/Photos/Copy")).is_within(source)

    def test_the_same_path_on_another_provider_is_not_contained(self) -> None:
        source = Locator("gdrive", "me", PurePosixPath("/Photos"))
        assert not Locator("onedrive", "me", PurePosixPath("/Photos/Copy")).is_within(source)


class TestRemoteItem:
    def test_it_carries_the_revision_token_inv_9_depends_on(self) -> None:
        item = RemoteItem(
            id="abc",
            path=PurePosixPath("/a/b.txt"),
            size=12,
            modified=None,
            hashes={"sha256": "deadbeef"},
            mime="text/plain",
            is_folder=False,
            is_native=False,
            revision="etag-1",
        )
        assert item.revision == "etag-1"

    def test_it_is_immutable(self) -> None:
        # A plan is built once and executed by several workers. A mutable item
        # shared between them is a race waiting to be debugged.
        item = RemoteItem(
            id="abc",
            path=PurePosixPath("/a/b.txt"),
            size=12,
            modified=None,
            hashes={},
            mime="text/plain",
            is_folder=False,
            is_native=False,
            revision="r",
        )
        with pytest.raises((AttributeError, TypeError)):
            item.size = 13  # type: ignore[misc]


class TestCollisionPolicy:
    def test_the_default_is_the_conservative_one(self) -> None:
        assert CollisionPolicy.default() is CollisionPolicy.SKIP_IF_IDENTICAL

    def test_every_policy_the_specification_names_exists(self) -> None:
        assert {p.value for p in CollisionPolicy} == {
            "skip-if-identical",
            "rename",
            "overwrite",
            "fail",
        }
