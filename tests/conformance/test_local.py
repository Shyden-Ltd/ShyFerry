"""The conformance suite, run against the local provider.

Every provider gets a module like this one. It is four lines, which is the
point: the tests live in the package so a third party's provider is held to
exactly the same contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shyferry.providers.local import LocalProvider
from shyferry.testing.conformance import ProviderConformance


@pytest.mark.conformance
class TestLocalProvider(ProviderConformance):
    @pytest.fixture()
    def provider(self, tmp_path: Path) -> LocalProvider:
        return LocalProvider(tmp_path)
