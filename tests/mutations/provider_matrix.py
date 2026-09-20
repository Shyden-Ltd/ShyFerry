"""Mutation matrix for the provider seam (S-03).

    python3 tests/mutations/provider_matrix.py <expected test count>

Each mutation changes the IMPLEMENTATION, never the input. A test that merely
exercises the hazard shows the behaviour is right today; only removing the
control shows the test would notice if it stopped being right.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Mutation, main

LOCAL = "src/shyferry/providers/local/__init__.py"
PROVIDER = "src/shyferry/core/provider.py"
REGISTRY = "src/shyferry/core/registry.py"
CONFORMANCE = "src/shyferry/testing/conformance.py"

TARGETS = ("tests/conformance", "tests/unit/test_local_provider.py", "tests/guards")

MUTATIONS: list[Mutation] = [
    # INV-2. The guarantee rests on the interface, so the interface must be
    # watched: a provider that grows a permanent delete has to be caught here
    # rather than in review.
    (
        "P1 the local provider grows a permanent delete",
        LOCAL,
        "    def recycle(self, item: RemoteItem, *, expected_revision: str) -> None:",
        "    def delete(self, item: RemoteItem) -> None:\n"
        "        self._local(item.path).unlink()\n\n"
        "    def recycle(self, item: RemoteItem, *, expected_revision: str) -> None:",
        "RED",
    ),
    # The trash exclusion is the provider's own. Left to a caller's filter, a
    # second run ferries recycled files back and then recycles them again.
    (
        "P2 the trash is no longer excluded from enumeration",
        LOCAL,
        "            if TRASH_DIRECTORY in path.relative_to(self.root).parts:\n"
        "                continue\n",
        "",
        "RED",
    ),
    # INV-9 at the provider. Without the comparison, a file edited between
    # transfer and purge is recycled while the destination holds the old copy.
    (
        "P3 recycle stops comparing the recorded revision",
        LOCAL,
        "        current = self._item(local, with_hashes=False).revision\n"
        "        if current != expected_revision:",
        "        current = expected_revision\n        if current != expected_revision:",
        "RED",
    ),
    # A bin that destroys is a shredder with extra steps.
    (
        "P4 recycling deletes instead of moving to the bin",
        LOCAL,
        "        shutil.move(str(local), str(destination))",
        "        local.unlink()",
        "RED",
    ),
    # A bin that silently overwrites loses the earlier file.
    (
        "P5 the bin overwrites a name it already holds",
        LOCAL,
        "        if destination.exists():\n"
        '            destination = destination.with_name(f"{destination.name}.{item.revision}")\n',
        "",
        "RED",
    ),
    # The seam only holds while the dependency runs one way. Mutated in
    # `registry.py` rather than `provider.py` on purpose: every provider
    # imports `core.provider`, so a forbidden import THERE is a circular one
    # that crashes collection - the denominator moves and the run says nothing
    # about the guard. Here it is what the violation would actually look like,
    # someone hardcoding a built-in provider instead of discovering it.
    (
        "P6 core imports a provider",
        REGISTRY,
        "from shyferry.core.errors import ConfigurationError",
        "from shyferry.core.errors import ConfigurationError\n"
        "from shyferry.providers.local import LocalProvider  # noqa: F401",
        "RED",
    ),
    # Reserved names come in two shapes and both are enforced.
    (
        "P7 reserved names stop being refused",
        PROVIDER,
        "        if name.upper() in reserved:\n"
        '            return f"{name!r} is a reserved name"\n'
        "        if stem and stem.upper() in reserved:\n"
        '            return f"{stem!r} is a reserved name"',
        "        if False:\n            return None",
        "RED",
    ),
    # The revision must move with the content, or P3's guard passes against a
    # provider whose revision is effectively constant.
    (
        "P8 the revision token stops tracking content",
        LOCAL,
        'revision=f"{stat.st_size}-{stat.st_mtime_ns}",',
        'revision="constant",',
        "RED",
    ),
    # The control: a change to the same files that must NOT be caught, so a
    # suite that reddens at any edit is distinguishable from one that asserts.
    (
        "P9 CONTROL a comment is reworded",
        LOCAL,
        "# The desktop trash differs per platform and cannot be asserted",
        "# Platform desktop trashes differ, so this provider keeps its own.",
        "GREEN",
    ),
]

if __name__ == "__main__":
    main(MUTATIONS, TARGETS)
