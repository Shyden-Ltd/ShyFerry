"""`core` must not import `providers`.

The seam only holds while the dependency runs one way. The moment `core`
imports a provider, "every difference between clouds is expressed through
capabilities" stops being true and nobody notices until the third cloud.

Parsed with `ast`, not grepped. An import is a structural fact: the string
"shyferry.providers" appears in `registry.py`'s entry-point group name and in
several docstrings, and a text search would flag all of them while missing
`__import__("shyferry.providers.local")`.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "shyferry"
CORE = SOURCE / "core"
FORBIDDEN_PREFIX = "shyferry.providers"


def imports_of(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def core_modules() -> list[Path]:
    """Derived from the filesystem: a module added next year is covered."""
    return sorted(CORE.glob("*.py"))


def test_there_are_core_modules_to_check() -> None:
    # Positive control. Every assertion below iterates a population found at
    # runtime, and an empty one passes while asserting nothing.
    assert core_modules(), "no core modules found; this guard would be vacuous"
    assert any(imports_of(module) for module in core_modules()), (
        "no imports parsed at all; the parser would flag nothing whatever core did"
    )


def test_core_never_imports_a_provider() -> None:
    for module in core_modules():
        for imported in imports_of(module):
            assert not imported.startswith(FORBIDDEN_PREFIX), (
                f"{module.name} imports {imported!r}. `core` expresses every difference "
                "between clouds through ProviderCapabilities; importing one directly is how "
                "that stops being true."
            )


def test_providers_never_import_each_other() -> None:
    provider_packages = sorted((SOURCE / "providers").glob("*/__init__.py"))
    assert provider_packages, "no providers found; this guard would be vacuous"
    for module in provider_packages:
        own = f"{FORBIDDEN_PREFIX}.{module.parent.name}"
        for imported in imports_of(module):
            if imported.startswith(FORBIDDEN_PREFIX) and not imported.startswith(own):
                raise AssertionError(
                    f"{module.parent.name} imports {imported!r}. Providers are siblings; "
                    "shared behaviour belongs in core, not in whichever one was written first."
                )
