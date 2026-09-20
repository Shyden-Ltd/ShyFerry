"""Provider discovery through entry points."""

from __future__ import annotations

import pytest

from shyferry.core import registry
from shyferry.core.errors import ConfigurationError
from shyferry.providers.local import LocalProvider


def test_the_local_provider_is_discovered() -> None:
    # It is declared in pyproject.toml under the `shyferry.providers` group,
    # exactly as a third party's provider would be. If this fails, the
    # extensibility story is broken for everyone, not only for us.
    assert "local" in registry.discovered()


def test_loading_returns_the_class_itself() -> None:
    assert registry.load("local") is LocalProvider


def test_an_unknown_provider_says_what_is_available(tmp_path: object) -> None:
    with pytest.raises(ConfigurationError) as raised:
        registry.load("gdrve")
    message = str(raised.value)
    assert "gdrve" in message
    # "unknown provider" is half an error message. The half that helps is the
    # list of names that would have worked.
    assert "local" in message


def test_hosts_are_derived_from_the_providers_in_hand(tmp_path: object) -> None:
    local = LocalProvider(str(tmp_path))
    assert registry.hosts_of(local) == frozenset()

    class Elsewhere:
        capabilities = type("Caps", (), {"hosts": frozenset({"graph.microsoft.com"})})()

    assert registry.hosts_of(local, Elsewhere()) == frozenset({"graph.microsoft.com"})
