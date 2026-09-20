# ShyFerry Phase 1 (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `shyferry` that transfers a complete file tree between two
providers, verifies every byte, and recycles verified sources - proven end to
end with the `local` provider, with the cloud providers plugging into the same
seam in Phase 2 and Phase 3.

**Architecture:** One `StorageProvider` protocol; `core` never imports a
provider. Bytes stream source to destination in bounded chunks through a
multi-hasher, so verification happens in flight. An append-only JSONL manifest
is the worklist, never the authority. Fifteen invariants (INV-1 to INV-15) are
mechanical, each owned by exactly one story and each proven by a mutation.

**Tech Stack:** Python 3.12 (floor 3.11), `uv`, `httpx`, `typer`, `rich`,
`pydantic`, `keyring`, `platformdirs`, `pytest`, `hypothesis`, `ruff`,
`mypy --strict`, `mutmut`.

**Spec:** `docs/superpowers/specs/2026-09-20-shyferry-design.md` - the plan
argues from the spec and does not restate it. Executors read both.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include
this section.

- `requires-python = ">=3.11"`, tested on 3.11, 3.12, 3.13 across Linux, macOS
  and Windows.
- No permanent deletion exists anywhere: `StorageProvider` has no method for
  it, and INV-1's guard derives the banned set from the vendors' own
  machine-readable API surfaces.
- Personal accounts only. An account type outside the supported set is refused
  at authentication (INV-14).
- Chunk size defaults to 7.5 MiB, the sixth multiple of the 1.25 MiB lowest
  common multiple of Graph's 320 KiB and Drive's 256 KiB requirements.
  Granularity is a provider capability, not a constant.
- The failing test precedes the implementation, for every task.
- Every guard is mutation-verified in both directions: red when the control is
  removed, green on the unmodified tree.
- Comment stripping in any source-text guard uses Python's `tokenize`.
- No credential material reaches logs, error output or reports (INV-10).

---

## Note on this plan's granularity

The spec is 953 lines and already fixes the interfaces, the invariants and
their mutations. Transcribing every implementation body into the plan as well
would write the product twice and put the authoritative copy in the document
rather than the repository. So each task below gives: the exact files, the
interfaces it consumes and produces, the test names that must exist and fail
first, the mutation that proves each guard, and the commit. Implementation
bodies belong in the repository, under the tests named here.

---

## File structure

```
pyproject.toml                  project, deps, ruff, mypy, pytest config
.github/workflows/ci.yml        lint, types, tests, guards, matrix
.github/dependabot.yml          pip + github-actions, target develop
src/shyferry/
  core/models.py                RemoteItem, UploadTarget, TransferPlan,
                                ManifestRecord, Verification, Quota, AccountInfo
  core/provider.py              StorageProvider protocol, ProviderCapabilities
  core/registry.py              entry-point discovery
  core/config.py                layered config, locator parsing
  core/naming.py                sanitisation, collisions, Unicode normalisation
  core/hashing.py               multi-hasher, quickXorHash
  core/planner.py               enumeration, filters, exclusions (INV-7, INV-13)
  core/preflight.py             quota, containment refusal (INV-12)
  core/engine.py                streaming, concurrency, retry (INV-15)
  core/verify.py                algorithm negotiation, unverifiable states
  core/manifest.py              append-only JSONL, resume
  core/purge.py                 recycle gate (INV-1..6, INV-9)
  core/logging.py               redacting formatter (INV-10)
  core/errors.py                exception hierarchy
  providers/local/              filesystem provider
  cli/main.py                   typer app
tests/unit/                     per-module
tests/conformance/              one suite, every provider
tests/guards/                   INV-1 deny-list, source-text, dependency direction
tests/mutations/                mutation matrices per guard
```

---

## Task 1: Repository bootstrap (S-01)

**Files:** `pyproject.toml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`,
`LICENSE`, `README.md`, `CLAUDE.md`, `tests/guards/test_supply_chain.py`,
`docs/superpowers/specs/spec_check.py` wired into CI.

**Interfaces produced:** `uv run shyferry` entry point; `uv run pytest` green.

- [ ] **Step 1: Write the failing supply-chain guard** - `tests/guards/test_supply_chain.py`
      asserting, with comments stripped via `tokenize` for Python and a YAML
      comment stripper for workflows: every `uses:` is a 40-hex SHA with a
      trailing `# vX.Y.Z`; `dependabot.yml` declares `pip` and `github-actions`;
      both carry `target-branch: develop`; any same-repo sub-path group sits
      above a catch-all group.
- [ ] **Step 2: Run it and watch it fail** - no files exist yet.
- [ ] **Step 3: Write `pyproject.toml`** - Apache-2.0, `requires-python = ">=3.11"`,
      deps as listed, ruff and mypy strict config, pytest paths.
- [ ] **Step 4: Write `.github/dependabot.yml` and `ci.yml`** with SHA-pinned actions.
- [ ] **Step 5: Run the guard and watch it pass.**
- [ ] **Step 6: Mutation-verify** - unpin one action to a tag; the guard must go
      red naming that action. Restore; green.
- [ ] **Step 7: Add `LICENSE`, `README.md` (limitations section from spec 13),
      `CLAUDE.md`** carrying the spec's hard rules.
- [ ] **Step 8: Commit** - `feat(S-01): repository bootstrap, CI and supply-chain guards`.

---

## Task 2: Models and configuration (S-02)

**Files:** `src/shyferry/core/models.py`, `core/config.py`, `core/errors.py`,
`tests/unit/test_models.py`, `tests/unit/test_config.py`.

**Interfaces produced:**
`RemoteItem(id, path: PurePosixPath, size, modified, hashes: Mapping[str,str],
mime, is_folder, is_native, revision: str)`;
`UploadTarget(path, size, modified, collision: CollisionPolicy)`;
`Locator(provider: str, account: str | None, path: PurePosixPath)` with
`Locator.parse("gdrive@work:/Archive")`;
`Config.load(layers)` returning a frozen model.

- [ ] **Step 1: Write failing tests** - `test_locator_parses_provider_account_and_path`,
      `test_a_bare_path_means_local`, `test_a_locator_without_account_is_resolved_later`,
      `test_config_layers_override_in_order`, `test_credentials_are_never_read_from_config`,
      `test_chunk_default_is_a_multiple_of_both_providers_granularities`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement** the models and the four-layer loader.
- [ ] **Step 4: Run and watch them pass.**
- [ ] **Step 5: Mutation-verify** the chunk-granularity test: set the default to
      8 MiB; it must go red reporting 25.6.
- [ ] **Step 6: Commit** - `feat(S-02): core models, locators and layered configuration`.

---

## Task 3: Provider protocol, registry, conformance suite, local provider (S-03)

**Files:** `core/provider.py`, `core/registry.py`, `providers/local/`,
`tests/conformance/suite.py` (exported as a pytest plugin), `tests/unit/test_registry.py`,
`tests/guards/test_dependency_direction.py`.

**Interfaces consumed:** Task 2's models.
**Interfaces produced:** the `StorageProvider` protocol exactly as spec 3.2
defines it, including `recycle(item, *, expected_revision: str)`;
`registry.load()` discovering the `shyferry.providers` entry-point group;
`conformance_suite(provider_factory)`.

- [ ] **Step 1: Write the failing conformance suite** - round-trip a file and
      compare bytes; round-trip a zero-byte file and record whether a hash is
      reported; enumerate a nested tree; create and detect empty folders; race
      N workers at one folder path and assert a single identifier; reject
      forbidden names per declared capabilities; hashes match locally computed
      values; recycle removes from the listing; a stale `expected_revision` is
      refused; declared-unsupported operations are refused.
- [ ] **Step 2: Run it and watch every case fail.**
- [ ] **Step 3: Write the protocol and `ProviderCapabilities`.**
- [ ] **Step 4: Write the `local` provider** - revision token is size plus
      modification time; `.shyferry-trash` at the transfer root, excluded from
      its own enumeration unconditionally.
- [ ] **Step 5: Run the suite against `local` and watch it pass.**
- [ ] **Step 6: Write the dependency-direction guard** - `core` must not import
      `providers`; mutation: add such an import, guard goes red.
- [ ] **Step 7: Mutation-verify the trash exclusion** - remove it; the
      second-run test must go red showing recycled files ferried back.
- [ ] **Step 8: Commit** - `feat(S-03): provider protocol, registry, conformance suite and local provider`.

---

## Task 4: Hashing (S-04, partial - quickXorHash lands in Phase 3)

**Files:** `core/hashing.py`, `tests/unit/test_hashing.py`.

**Interfaces produced:** `MultiHasher(algorithms: Iterable[str])` with
`update(chunk)` and `digests() -> dict[str, str]`; algorithm set derived from
provider capabilities, never a constant.

- [ ] **Step 1: Write failing tests** - `test_it_computes_every_requested_algorithm`,
      `test_the_algorithm_set_comes_from_capabilities_not_a_constant`,
      `test_an_empty_input_still_produces_digests`.
- [ ] **Step 2: Run and watch fail.**
- [ ] **Step 3: Implement** over `hashlib`, with a registry that Phase 3's
      quickXorHash joins without touching this module's callers.
- [ ] **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify** - hardcode the algorithm list; the
      capabilities test must go red.
- [ ] **Step 6: Commit** - `feat(S-04): streaming multi-hasher driven by provider capabilities`.

---

## Task 5: Planner and naming (S-09, INV-7, INV-13)

**Files:** `core/planner.py`, `core/naming.py`, `tests/unit/test_planner.py`,
`tests/unit/test_naming.py`.

**Interfaces produced:** `plan(source, destination, config) -> TransferPlan`.

- [ ] **Step 1: Write failing tests** - trashed items never appear in a plan
      (INV-7); items the user does not own never appear (INV-13); filters by
      glob, size and modified time; forbidden characters and reserved names
      sanitised per capabilities; NFC and NFD compare equal but original bytes
      are preserved (R-03); duplicate names in one source folder resolve under
      the collision policy (R-02); Hypothesis property test over round-tripping
      names.
- [ ] **Step 2: Run and watch fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify INV-7 and INV-13** - remove each exclusion in
      turn; the matching test must go red and no other.
- [ ] **Step 6: Commit** - `feat(S-09): planner with trashed and non-owned exclusions`.

---

## Task 6: Pre-flight (S-15, INV-12)

**Files:** `core/preflight.py`, `tests/unit/test_preflight.py`.

**Interfaces produced:** `preflight(plan, source, destination) -> PreflightResult`.

- [ ] **Step 1: Write failing tests** - a destination inside its own source on
      the same account is refused before any byte moves (INV-12); the same path
      on a different account is allowed; planned bytes against destination free
      space, accounting for content already present and for conversion size
      changes.
- [ ] **Step 2: Run and watch fail.** **Step 3: Implement.** **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify INV-12** - remove the containment check; the
      nested-destination test goes red.
- [ ] **Step 6: Commit** - `feat(S-15): pre-flight quota and nested-destination refusal`.

---

## Task 7: Manifest and resume (S-11)

**Files:** `core/manifest.py`, `tests/unit/test_manifest.py`.

**Interfaces produced:** `Manifest.open(run_id)`, `.record(state, item, **fields)`,
`.replay()`, `.effective_config`.

- [ ] **Step 1: Write failing tests** - the first record is the run's effective
      configuration and is never rewritten; every state in the spec's list is
      accepted and no other; a record that fails to parse is refused and
      reported, never skipped; owner-only permissions; resume plans under the
      recorded configuration and declines when today's differs, naming the keys;
      an item verified but not recycled is not finished.
- [ ] **Step 2: Run and watch fail.** **Step 3: Implement.** **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify** - make an unparseable record skip silently;
      the refusal test goes red.
- [ ] **Step 6: Commit** - `feat(S-11): append-only manifest with configuration pinning and resume`.

---

## Task 8: Verification (S-12)

**Files:** `core/verify.py`, `tests/unit/test_verify.py`.

**Interfaces produced:** `verify(local_digests, source, destination) -> Verification`
with states `verified` and `unverifiable`.

- [ ] **Step 1: Write failing tests** - read integrity and write integrity each
      compare against the locally computed value; no cross-algorithm comparison
      is ever attempted; each `unverifiable` cause from spec 5.3 produces that
      state; a zero-byte file with no reported hash is unverifiable, not failed;
      a failure re-transfers within the retry budget by overwriting the same
      path, then records `failed`.
- [ ] **Step 2: Run and watch fail.** **Step 3: Implement.** **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify** - let a converted item report `verified`;
      the unverifiable test goes red.
- [ ] **Step 6: Commit** - `feat(S-12): in-flight verification and the unverifiable state`.

---

## Task 9: Engine (S-10, INV-15)

**Files:** `core/engine.py`, `core/logging.py`, `tests/unit/test_engine.py`.

**Interfaces produced:** `run(plan, source, destination, manifest, config) -> RunResult`.

- [ ] **Step 1: Write failing tests** - bytes stream in bounded chunks with no
      temporary file; peak buffer is chunk times workers; folder creation is
      single-flight so N workers at one path produce one identifier; folders
      before contents; empty folders transferred; 401 and 403 refresh and retry
      once, 412 is a refusal, 429 honours `Retry-After`, other 4xx is permanent
      for that item and never fails the run; a vanished source item records
      `vanished`; an interrupt flushes the manifest and abandons one chunk;
      `recycle` is never called on the destination (INV-15); dry run and real
      run produce an identical plan (INV-6).
- [ ] **Step 2: Run and watch fail.** **Step 3: Implement.** **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify INV-15 and INV-6** - clean up a failed upload by
      recycling it at the destination, and diverge the dry-run path; each goes red.
- [ ] **Step 6: Commit** - `feat(S-10): transfer engine with bounded streaming and single-flight folders`.

---

## Task 10: Purge (S-14, INV-1 to INV-6, INV-9)

**Files:** `core/purge.py`, `tests/guards/test_no_destructive_api.py`,
`tests/unit/test_purge.py`, `tests/mutations/purge_matrix.py`.

**Interfaces produced:** `purge(run_id, source, destination, *, confirmation) -> PurgeResult`.

- [ ] **Step 1: Write the failing INV-1 guard** - download Drive's discovery
      document and Graph's metadata, derive the set of operations whose own
      description denotes permanent deletion, and assert none appears in our
      source with comments stripped by `tokenize`. The derived set must contain
      `files.delete` and `files.emptyTrash` as its positive control.
- [ ] **Step 2: Write the remaining failing tests** - the protocol exposes no
      permanent-delete method (INV-2); nothing is recycled without a live
      destination check at the moment of deletion (INV-3); an `unverifiable`
      item can never be recycled (INV-4); purge never runs implicitly and a
      confirmation naming a different run is refused (INV-5); a source changed
      since transfer is refused (INV-9); a folder is recycled only when empty
      and everything it held was transferred, verified and recycled.
- [ ] **Step 3: Run and watch every one fail.** **Step 4: Implement.**
      **Step 5: Run and watch them pass.**
- [ ] **Step 6: Run the mutation matrix** - one mutant per invariant, each
      changing the implementation rather than the input, each asserting its
      anchor matched exactly once and printing the changed text.
- [ ] **Step 7: Commit** - `feat(S-14): purge with seven mechanical safety invariants`.

---

## Task 11: CLI (S-16, INV-8, INV-10)

**Files:** `cli/main.py`, `tests/unit/test_cli.py`.

**Interfaces produced:** every command in spec section 9.

- [ ] **Step 1: Write failing tests** - each command exists with its documented
      arguments; exit codes 0, 1, 2, 3 as specified, including a successful run
      that declined to purge exiting 0; `--json` on stdout with everything else
      on stderr; progress degrades off-TTY; `NO_COLOR` honoured; `plan` is
      `run --dry-run` on the same code path; the host recorder sees only hosts
      the loaded providers declare, with a control request proving the recorder
      is attached (INV-8); tokens, client secrets and signed upload URLs pushed
      through every reporting surface appear nowhere (INV-10).
- [ ] **Step 2: Run and watch fail.** **Step 3: Implement.** **Step 4: Run and watch pass.**
- [ ] **Step 5: Mutation-verify INV-8 and INV-10** - add a call to an unrelated
      host, detach the recorder, and log a raw token; each goes red.
- [ ] **Step 6: Commit** - `feat(S-16): command-line surface with redacting output`.

---

## Task 12: Phase 1 end-to-end journey

**Files:** `tests/journeys/test_local_to_local.py`.

- [ ] **Step 1: Write the failing journey** - build a fixture tree including an
      empty folder, a zero-byte file, a name needing sanitisation and a nested
      path; plan; dry run; run; verify; purge with confirmation; assert the
      destination matches the source, the source files are in `.shyferry-trash`,
      and the manifest tells the same story.
- [ ] **Step 2: Run and watch it fail.** **Step 3: Fix whatever it finds.**
      **Step 4: Run and watch it pass.**
- [ ] **Step 5: Write the evidence page** for the phase and request sign-off.
- [ ] **Step 6: Commit and open the PR into `develop`.**

---

## Phases that follow

Each gets its own plan, written when the previous one ships, because each
produces working software on its own.

- **Phase 2 - Google Drive** (S-05, S-06, S-07, S-13, SPIKE-01): OAuth2 PKCE and
  device code, keyring storage, single-flight refresh, account-type gate, the
  bring-your-own credential wizard, the Drive provider, native document export
  policy, and the measurement of whether `files.download` lifts the 10 MB
  export ceiling.
- **Phase 3 - OneDrive** (S-04 completion, S-08): quickXorHash written from
  Microsoft's published algorithm description and oracled against live Graph
  values, then the OneDrive provider.
- **Phase 4 - Release** (S-17, S-18): documentation, real-account journeys on
  both providers in both directions, the release workflow and PyPI publication.
