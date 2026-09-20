"""The vocabulary every other module speaks.

Everything here is immutable. A plan is built once and executed by several
workers at the same time; a mutable item shared between them is a race waiting
to be debugged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from shyferry.core.errors import LocatorError

LOCAL = "local"

# `provider[@account]:path`. The provider is matched as at least two characters
# so a Windows drive letter is read as part of a path and not as a provider:
# a third of the test matrix runs on Windows, and `C:\Users\...` must mean what
# the user obviously intends.
_LOCATOR = re.compile(
    r"^(?P<provider>[A-Za-z][A-Za-z0-9_-]+)(?:@(?P<account>[^:@]+))?:(?P<path>.+)$"
)
# The same prefix without requiring a path, used only to tell "this is a
# malformed locator" from "this is a local path".
_LOCATOR_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9_-]+(?:@[^:@]*)?:")


class CollisionPolicy(StrEnum):
    """What to do when the destination already holds that name."""

    SKIP_IF_IDENTICAL = "skip-if-identical"
    RENAME = "rename"
    OVERWRITE = "overwrite"
    FAIL = "fail"

    @classmethod
    def default(cls) -> CollisionPolicy:
        return cls.SKIP_IF_IDENTICAL


@dataclass(frozen=True, slots=True)
class Locator:
    """Where bytes come from, or go to.

    Parses to a provider, an account and a path - which is exactly the triple
    INV-12 compares when deciding whether a destination sits inside its source.
    """

    provider: str
    account: str | None
    path: PurePosixPath

    @classmethod
    def parse(cls, text: str) -> Locator:
        if not text or not text.strip():
            raise LocatorError("a source or destination cannot be empty")
        text = text.strip()

        match = _LOCATOR.match(text)
        if match is None:
            # A string that is *trying* to be a locator and failing must be
            # refused, not quietly reinterpreted as a local path. `gdrive:`
            # names no path and `@work:/x` names no provider; treating either
            # as a filename would send the run somewhere nobody asked for.
            if text.startswith("@"):
                raise LocatorError(f"{text!r} names an account but no provider")
            if _LOCATOR_PREFIX.match(text):
                raise LocatorError(
                    f"{text!r} names a provider but no path; write `/` for the whole drive"
                )
            # No provider prefix at all, so it is a local path. This covers
            # bare paths and Windows drive letters alike.
            return cls(LOCAL, None, cls._normalise(text))

        account = match.group("account")
        if account is not None and not account.strip():
            raise LocatorError(f"{text!r} names an empty account")
        return cls(match.group("provider"), account, cls._normalise(match.group("path")))

    @staticmethod
    def _normalise(raw: str) -> PurePosixPath:
        if not raw or not raw.strip():
            raise LocatorError("a locator needs a path; write `/` for the whole drive")
        # Windows separators are accepted on the way in and normalised, because
        # the remote namespace is POSIX-shaped whatever the local platform is.
        return PurePosixPath(raw.strip().replace("\\", "/"))

    def is_within(self, other: Locator) -> bool:
        """True when this locator names a place inside `other` on one account.

        Compared segment by segment rather than by string prefix: `/Photos2` is
        not inside `/Photos`, and refusing that transfer would be wrong.
        """
        if (self.provider, self.account) != (other.provider, other.account):
            return False
        return self.path == other.path or other.path in self.path.parents

    def __str__(self) -> str:
        account = f"@{self.account}" if self.account else ""
        return f"{self.provider}{account}:{self.path}"


@dataclass(frozen=True, slots=True)
class RemoteItem:
    """One file or folder as a provider reports it."""

    id: str
    path: PurePosixPath
    size: int
    modified: datetime | None
    hashes: Mapping[str, str]
    mime: str
    is_folder: bool
    is_native: bool
    # Opaque and provider-defined; it changes whenever the content changes.
    # Graph's eTag, Drive's headRevisionId, the local provider's size and
    # modification time. INV-9 cannot be evaluated without it.
    revision: str


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where one item is going, and under what rules."""

    path: PurePosixPath
    size: int
    modified: datetime | None
    collision: CollisionPolicy = CollisionPolicy.SKIP_IF_IDENTICAL


@dataclass(frozen=True, slots=True)
class Quota:
    """What a destination has room for."""

    total: int | None
    used: int
    available: int | None


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Who a provider is signed in as, and of what kind.

    `kind` is what INV-14 gates on: an account type outside the supported set
    is refused at authentication rather than partially supported.
    """

    identifier: str
    display_name: str
    kind: str
