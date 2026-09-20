# Project Context: ShyFerry

ShyFerry moves an entire cloud storage library from one provider to another,
verifies every byte arrived, and - only on request, and only for files it has
proven arrived - moves the originals to the source provider's recycle bin.

**The design is the authority**, not this file:
`docs/superpowers/specs/2026-09-20-shyferry-design.md`. It carries fifteen
numbered invariants, their enforcement and the mutation that proves each one is
alive. `docs/superpowers/plans/` carries the phase plans. Read the spec before
changing behaviour; it is checked in CI by `docs/superpowers/specs/spec_check.py`.

## Hard guardrails

- **Nothing is ever deleted permanently.** `StorageProvider` has no method that
  could express it. Both clouds expose permanent deletion within the exact
  scopes ShyFerry must hold to upload anything, so the guarantee rests entirely
  on this codebase - which is why INV-1 derives the banned set from the
  vendors' own machine-readable API surfaces rather than a hand-written list.
- **Nothing is deleted that could not be verified.** Unverifiable is not a
  failure; what it forfeits is eligibility for deletion, permanently and
  without an override.
- **`recycle` is only ever called on the source** (INV-15). A failed upload
  leaves a bad file at the destination; report it and leave it.
- **Zero cost.** Every dependency, service and test account must be free,
  permanently, with no trial expiry and no payment details anywhere. Users
  bring their own OAuth client, which is why there are no verification fees.
- **Personal accounts only** until a free business test tenant exists. An
  unsupported account type is refused at authentication rather than
  half-supported (INV-14): a run that silently misses every Shared Drive and
  then reports success is worse than one that fails.

## How work is done here

- Test-driven, always. The failing test precedes the implementation, and you
  watch it fail before you write the code.
- Every guard is mutation-verified **in both directions**: red when the control
  it protects is removed, green on the unmodified tree. A guard nobody has seen
  fail is not evidence. The matrices live in `tests/mutations/`.
- Every guard that reads a file's own text strips comments first, with Python's
  `tokenize` for Python and a YAML parser for YAML. A guard matched against raw
  text is satisfied by the file's own documentation.
- Derive populations from the filesystem or from the vendor's published
  surface, never from a list typed into a test. A sweep driven by a
  hand-written list covers what its author remembered.
- Every assertion over a population found at runtime carries a liveness
  control. An empty population passes everything while asserting nothing - the
  version-comment guard here examined zero lines and passed, until a mutation
  caught it.
- Branches: `main` and `develop`. Nothing merges to `main` directly. Every
  ticket gets a branch, which merges to `develop`.
- A story merges into `develop` when CI is green **read job by job** and its
  mutation matrix is clean (D9). One evidence page then covers every story and
  is signed off before anything is published. A green pipeline is a
  precondition for that sign-off, never a substitute for it.
- **Run `./scripts/gate.sh` last, immediately before committing.** Running the
  checks earlier in a session and then editing is how two commits have already
  reached CI red while the local tree was believed green.

## Commands

```console
uv sync --group dev          # install, hash-verified from the lockfile
./scripts/gate.sh            # everything CI runs: lint, format, types, tests, spec
./scripts/gate.sh --mutate   # the above, plus every mutation matrix
uv run pytest                # tests alone, while iterating
```

Each matrix is given the number of tests its own targets have, so a moving
denominator is caught rather than read as a pass. `gate.sh --mutate` counts
them for you.
