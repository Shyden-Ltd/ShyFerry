"""Mutation matrix for core's pure logic.

    python3 tests/mutations/core_matrix.py <expected test count>

Grows with core: hashing now, then the planner, verification and purge.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Mutation, main

HASHING = "src/shyferry/core/hashing.py"
MODELS = "src/shyferry/core/models.py"

TARGETS = ("tests/unit/test_hashing.py", "tests/unit/test_models.py")

MUTATIONS: list[Mutation] = [
    # The algorithm set must come from the providers in hand. Hardcoded, a
    # provider reporting only CRC32 becomes unverifiable because nobody
    # updated a list - and unverifiable means undeletable.
    (
        "C1 the algorithm set is hardcoded",
        HASHING,
        "    wanted: set[str] = set()\n"
        "    for capability in capabilities:\n"
        "        wanted |= set(capability.hash_algorithms)\n"
        "    return frozenset(wanted)",
        '    return frozenset({"md5", "sha256"})',
        "RED",
    ),
    # An algorithm nobody implements must fail at the start of a run, not at
    # the end of a transfer that took hours.
    (
        "C2 an unusable algorithm is accepted at construction",
        HASHING,
        "        unusable = sorted(wanted - available())\n        if unusable:",
        "        unusable = sorted(wanted - available())\n        if False:",
        "RED",
    ),
    # Chunk boundaries must not change the answer, or a transfer fails on
    # file size alone.
    (
        "C3 only the first chunk is hashed",
        HASHING,
        "        for digest in self._digests.values():\n            digest.update(chunk)\n"
        "        self.length += len(chunk)",
        "        if self.length == 0:\n"
        "            for digest in self._digests.values():\n                digest.update(chunk)\n"
        "        self.length += len(chunk)",
        "RED",
    ),
    # A malformed locator must be refused, not reinterpreted as a local path,
    # or a run goes somewhere nobody asked for.
    (
        "C4 a malformed locator falls back to a local path",
        MODELS,
        "            if _LOCATOR_PREFIX.match(text):\n"
        "                raise LocatorError(\n"
        '                    f"{text!r} names a provider but no path; '
        'write `/` for the whole drive"\n'
        "                )",
        "            pass",
        "RED",
    ),
    # Containment by string prefix would call /Photos2 a child of /Photos and
    # refuse a transfer that is perfectly legitimate.
    (
        "C5 containment compares string prefixes",
        MODELS,
        "        return self.path == other.path or other.path in self.path.parents",
        "        return str(self.path).startswith(str(other.path))",
        "RED",
    ),
    # The control.
    (
        "C6 CONTROL a docstring is reworded",
        HASHING,
        '    """What a hash implementation has to offer. `hashlib` already matches."""',
        '    """The shape a hash implementation must have."""',
        "GREEN",
    ),
]

if __name__ == "__main__":
    main(MUTATIONS, TARGETS)
