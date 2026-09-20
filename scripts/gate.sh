#!/usr/bin/env bash
# Everything CI will run, in one command, so that "I ran the checks" cannot
# quietly mean "I ran some of them, before my last edit".
#
#     ./scripts/gate.sh            checks and tests
#     ./scripts/gate.sh --mutate   the above, plus every mutation matrix
#
# Twice now a late edit went out untested because the gate had been run
# earlier in the session and the edit came after it. One command, run last,
# is the fix.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "== ruff lint =="
uv run ruff check .

echo "== ruff format =="
uv run ruff format --check .

echo "== mypy --strict =="
uv run mypy

echo "== tests =="
uv run pytest

echo "== specification integrity =="
uv run python docs/superpowers/specs/spec_check.py

if [[ "${1:-}" == "--mutate" ]]; then
  # Each matrix is told how many tests its own targets have, so a denominator
  # that moves is caught rather than read as a pass.
  count() {
    uv run pytest "$@" -o addopts= -q --tb=no -p no:cacheprovider \
      | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+'
  }

  echo "== mutation: supply chain =="
  uv run python tests/mutations/supply_chain_matrix.py \
    "$(count tests/guards/test_supply_chain.py)"

  echo "== mutation: provider seam =="
  uv run python tests/mutations/provider_matrix.py \
    "$(count tests/conformance tests/unit/test_local_provider.py tests/guards)"

  echo "== mutation: core =="
  uv run python tests/mutations/core_matrix.py \
    "$(count tests/unit/test_hashing.py tests/unit/test_models.py)"
fi

echo
echo "gate: all green"
