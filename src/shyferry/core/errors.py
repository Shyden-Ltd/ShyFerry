"""ShyFerry's exception hierarchy.

Every error a user can provoke is one of these, so the command line can map
them onto documented exit codes instead of letting a traceback decide.
"""

from __future__ import annotations


class ShyFerryError(Exception):
    """Anything ShyFerry raises deliberately."""


class ConfigurationError(ShyFerryError):
    """The configuration, or a credential, is missing or unusable. Exit code 2."""


class LocatorError(ConfigurationError):
    """A source or destination could not be read as `provider[@account]:path`."""


class AmbiguousAccountError(ConfigurationError):
    """A locator named no account while more than one is authenticated.

    Refused rather than guessed: choosing which of a user's two accounts to
    empty is not a decision this tool makes on their behalf.
    """


class RefusedError(ShyFerryError):
    """A safety gate refused the whole operation. Exit code 3."""


class ProviderError(ShyFerryError):
    """A provider could not complete an operation."""


class TransferFailedError(ShyFerryError):
    """One item could not be transferred. Never fails the whole run."""
