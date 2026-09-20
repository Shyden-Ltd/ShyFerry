"""Mutation matrix for the supply-chain guard (S-01).

    python3 tests/mutations/supply_chain_matrix.py <expected test count>

M5 is the one worth reading twice. It removes the sub-path group while leaving
the comment that explains it in place, which is the exact defect shyden.co.uk
shipped as issue #23: a guard matched against raw text was satisfied by the
file's own documentation, and passed with nothing configured at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Mutation, main

CI = ".github/workflows/ci.yml"
DEPENDABOT = ".github/dependabot.yml"
PYPROJECT = "pyproject.toml"
GUARD = "tests/guards/test_supply_chain.py"

TARGETS = (GUARD,)

MUTATIONS: list[Mutation] = [
    (
        "M1 an action pinned to a mutable tag",
        CI,
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
        "actions/setup-python@v7 # v7.0.0",
        "RED",
    ),
    (
        "M2 a pinned action loses its version comment",
        CI,
        "astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0\n"
        "        with:\n          enable-cache: true\n          python-version:",
        "astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4\n"
        "        with:\n          enable-cache: true\n          python-version:",
        "RED",
    ),
    # Anchored across the whole pip block: `target-branch: "develop"` alone
    # appears twice, and an earlier version of this mutation simply ADDED a
    # second target-branch key, which YAML resolves to the last one. The
    # config was unchanged in effect and the guard was right to stay green.
    (
        "M3 pip stops targeting develop",
        DEPENDABOT,
        '    target-branch: "develop"\n    open-pull-requests-limit: 5\n    groups:\n'
        '      patch-updates:\n        update-types: ["patch"]\n\n'
        '  - package-ecosystem: "github-actions"',
        '    target-branch: "main"\n    open-pull-requests-limit: 5\n    groups:\n'
        '      patch-updates:\n        update-types: ["patch"]\n\n'
        '  - package-ecosystem: "github-actions"',
        "RED",
    ),
    # The liveness control on the raw-text scan: it must notice when the scan
    # stops reading anything, not only when a comment is missing.
    (
        "M3b the version-comment scan is blinded",
        GUARD,
        'USES_LINE = re.compile(r"^-?\\s*uses:\\s*(\\S+)")',
        'USES_LINE = re.compile(r"^uses:\\s*(\\S+)")',
        "RED",
    ),
    (
        "M4 the catch-all group moves above the sub-path group",
        DEPENDABOT,
        "      same-repository-sub-paths:\n        patterns:\n"
        '          - "actions/cache*"\n          - "actions/upload-artifact*"\n'
        '          - "actions/download-artifact*"\n'
        '      patch-updates:\n        update-types: ["patch"]\n',
        '      patch-updates:\n        patterns:\n          - "*"\n'
        "      same-repository-sub-paths:\n        patterns:\n"
        '          - "actions/cache*"\n          - "actions/upload-artifact*"\n'
        '          - "actions/download-artifact*"\n',
        "RED",
    ),
    (
        "M5 the sub-path group is deleted, its comment left in place",
        DEPENDABOT,
        "      same-repository-sub-paths:\n        patterns:\n"
        '          - "actions/cache*"\n          - "actions/upload-artifact*"\n'
        '          - "actions/download-artifact*"\n',
        "",
        "RED",
    ),
    (
        "M6 the package claims a version nothing tests",
        PYPROJECT,
        'requires-python = ">=3.11"',
        'requires-python = ">=3.9"',
        "RED",
    ),
    (
        "M7 github-actions is no longer covered at all",
        DEPENDABOT,
        '  - package-ecosystem: "github-actions"',
        '  - package-ecosystem: "npm"',
        "RED",
    ),
    # The control: a change that touches the same files and must NOT be caught,
    # so a guard that simply reddens at any edit is distinguishable from one
    # that asserts something.
    (
        "M8 CONTROL an unrelated comment is reworded",
        CI,
        "# A superseded run on the same ref is wasted compute and a misleading green.",
        "# Cancel superseded runs.",
        "GREEN",
    ),
]

if __name__ == "__main__":
    main(MUTATIONS, TARGETS)
