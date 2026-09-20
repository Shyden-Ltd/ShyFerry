"""The one place a mutation matrix is run.

Two matrices exist already and more will follow. A second copy of this loop is
how the duplication rule gets broken by the code that enforces everything else.

What it insists on, each learned the hard way:

- **The anchor matches exactly once.** An anchor matching zero times means the
  mutation never applied and the following pass is worthless; matching twice
  means it changed something you did not intend.
- **The change is printed.** A pass after a no-op mutation reads exactly like a
  pass after a real one.
- **The whole guard file runs**, and the test count must match. A denominator
  that moves means tests were dropped rather than passed.
- **The baseline is green first.** If the unmodified tree is red, nothing below
  means anything.
- **`-o addopts=` clears the project's own `-q`.** Two levels of quiet suppress
  pytest's summary line entirely, and a harness that reads no summary counts
  zero tests - which looks exactly like a run that collected nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IGNORED = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"
)

# name, file relative to the repository, text to find, text to put there, verdict
Mutation = tuple[str, str, str, str, str]


def run_tests(root: Path, targets: Sequence[str], expected: int) -> tuple[str, int, list[str]]:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *targets,
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
    counted = {
        word: sum(int(n) for n in re.findall(rf"(\d+) {word}", out))
        for word in ("passed", "failed", "error")
    }
    ran = sum(counted.values())
    failing = sorted(
        set(re.findall(r"FAILED \S+::(\w+)(?:::(\w+))?", out))
        | set(re.findall(r"ERROR \S+::(\w+)(?:::(\w+))?", out))
    )
    verdict = "GREEN" if counted["failed"] == 0 and counted["error"] == 0 else "RED"
    if ran != expected:
        verdict = f"DENOMINATOR MOVED ({ran} != {expected})"
    return verdict, ran, [".".join(part for part in names if part) for names in failing]


def run_matrix(mutations: Sequence[Mutation], targets: Sequence[str], expected: int) -> int:
    """Run every mutation and return how many did not behave as predicted."""
    mismatches = 0

    baseline, ran, _ = run_tests(REPO, targets, expected)
    print(f"baseline: {baseline}, ran={ran}")
    if baseline != "GREEN":
        raise SystemExit("the unmodified tree is not green; nothing below would mean anything")

    for name, relative, old, new, predicted in mutations:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(REPO, root, ignore=IGNORED)
            target = root / relative
            text = target.read_text(encoding="utf-8")

            hits = text.count(old)
            if hits != 1:
                print(f"{name}: ANCHOR MATCHED {hits} TIMES, mutation not applied")
                mismatches += 1
                continue

            target.write_text(text.replace(old, new), encoding="utf-8")
            print(
                f"{name}: {old.splitlines()[0][:58]!r} -> "
                f"{(new or '<deleted>').splitlines()[0][:58]!r}"
            )

            verdict, ran, failing = run_tests(root, targets, expected)
            ok = verdict == predicted
            mismatches += 0 if ok else 1
            print(
                f"   {'as predicted' if ok else 'MISMATCH'}: {verdict} "
                f"(predicted {predicted}), ran={ran} failing={failing}"
            )

    print(f"\nMISMATCHES: {mismatches} of {len(mutations)}")
    return mismatches


def main(mutations: Sequence[Mutation], targets: Sequence[str]) -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <expected test count>")
    raise SystemExit(1 if run_matrix(mutations, targets, int(sys.argv[1])) else 0)
