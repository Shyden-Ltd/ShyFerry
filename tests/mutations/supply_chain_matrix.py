"""Mutation matrix for the supply-chain guard.

    python3 tests/mutations/supply_chain_matrix.py <expected test count>

Works on a copy of the repository; the real files are never touched. Every
mutant runs the WHOLE guard file, and a verdict is believed only when the test
count matches - a denominator that moves means tests were dropped rather than
passed. Each anchor must match exactly once, and each mutation prints the text
it changed, so a pass after a no-op mutation cannot be read as evidence.

M5 is the one worth reading twice. It removes the sub-path group while leaving
the comment that explains it in place, which is the exact defect shyden.co.uk
shipped as issue #23: a guard matched against raw text was satisfied by the
file's own documentation, and passed with nothing configured at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUARD = "tests/guards/test_supply_chain.py"

CI = ".github/workflows/ci.yml"
DEPENDABOT = ".github/dependabot.yml"
PYPROJECT = "pyproject.toml"

Mutation = tuple[str, str, str, str, str]

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
    # second target-branch key, which PyYAML resolves to the last one. The
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
        "tests/guards/test_supply_chain.py",
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


def run_guard(root: Path, expected: int) -> tuple[str, int, list[str]]:
    done = subprocess.run(
        # `-o addopts=` clears the project's own `-q`. Two levels of quiet
        # suppress the summary line entirely, and a harness that reads no
        # summary counts zero tests - which looks exactly like a run that
        # collected nothing.
        [
            sys.executable,
            "-m",
            "pytest",
            GUARD,
            "-o",
            "addopts=",
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    out = done.stdout + done.stderr
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", out))
    failed = sum(int(n) for n in re.findall(r"(\d+) failed", out))
    errors = sum(int(n) for n in re.findall(r"(\d+) error", out))
    ran = passed + failed + errors
    failing = sorted(
        set(re.findall(r"FAILED \S+::(\w+)::(\w+)", out))
        | set(re.findall(r"ERROR \S+::(\w+)::(\w+)", out))
    )
    verdict = "GREEN" if failed == 0 and errors == 0 else "RED"
    if ran != expected:
        verdict = f"DENOMINATOR MOVED ({ran} != {expected})"
    return verdict, ran, [f"{cls}.{name}" for cls, name in failing]


def main() -> None:
    expected = int(sys.argv[1])
    mismatches = 0

    baseline, ran, _ = run_guard(REPO, expected)
    print(f"baseline: {baseline}, ran={ran}")
    if baseline != "GREEN":
        raise SystemExit("the unmodified tree is not green; nothing below would mean anything")

    for name, relative, old, new, predicted in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(
                REPO,
                root,
                ignore=shutil.ignore_patterns(
                    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"
                ),
            )
            target = root / relative
            text = target.read_text(encoding="utf-8")
            hits = text.count(old)
            if hits != 1:
                print(f"{name}: ANCHOR MATCHED {hits} TIMES, mutation not applied")
                mismatches += 1
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            shown = (new or "<deleted>").splitlines()[0][:70]
            print(f"{name}: {old.splitlines()[0][:60]!r} -> {shown!r}")

            verdict, ran, failing = run_guard(root, expected)
            ok = verdict == predicted
            mismatches += 0 if ok else 1
            print(
                f"   {'as predicted' if ok else 'MISMATCH'}: {verdict} "
                f"(predicted {predicted}), ran={ran} failing={failing}"
            )

    print(f"\nMISMATCHES: {mismatches} of {len(MUTATIONS)}")
    raise SystemExit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
