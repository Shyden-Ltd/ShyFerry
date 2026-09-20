# ShyFerry - Design Specification

- Status: DRAFT, awaiting operator approval
- Date: 2026-09-20
- Owner: Shyden Ltd
- Supersedes: nothing (first specification for this product)

ShyFerry moves an entire cloud storage library from one provider to another,
verifies that every byte arrived intact, and - only on request, and only for
files it has proven arrived - moves the originals to the source provider's
recycle bin.

---

## 1. Purpose and scope

### 1.1 In scope for MVP

- Transfer of a complete file tree between two cloud storage providers.
- Providers shipped in MVP: Google Drive (personal) and OneDrive (personal),
  usable as either source or destination, in both directions.
- A third provider, `local`, backed by the local filesystem. It is a real
  provider, not a test double (see section 11.2).
- Conversion of Google Workspace native documents on the way out, under a
  policy the user chooses (section 7).
- Verification of every transferred file by checksum (section 5).
- Optional deletion of verified source files to the source provider's recycle
  bin, in either of two timings (section 6).
- Resumable runs backed by an append-only manifest (section 10.3).
- Customisation through a layered configuration file (section 8).
- A pre-flight check that the destination has room, before any byte moves.
- Run history that can be listed and pruned, under a default retention
  window (section 10.3).
- Extension to further providers by third parties, without modifying this
  codebase (section 3.3).

### 1.2 Explicitly out of scope for MVP

Each of these will be stated as a non-feature in the README, because users
will otherwise assume it is covered.

- Business and enterprise tiers: OneDrive for Business, SharePoint document
  libraries, Google Shared Drives, Google Workspace, admin consent flows.
  Deferred solely because no permanently free test tenant exists for either
  vendor, and untestable code must not be claimed as supported
  (operator decision, 2026-09-20; see section 2).
- Sharing permissions, link grants and access control lists.
- Comments, suggestions and revision history.
- Files in Google Drive's "Shared with me" that the user does not own.
- Two-way synchronisation, continuous synchronisation, or scheduling.
- Any graphical or web interface.
- Any hosted or server-side component. ShyFerry runs on the user's machine
  and nowhere else.

### 1.3 Non-negotiable constraints

- **Zero cost.** Every dependency, service and test account used to build,
  test, release and run ShyFerry must be free, permanently, with no trial
  expiry and no payment details held anywhere.
- **No permanent deletion, ever.** See section 6.
- **No telemetry.** ShyFerry makes network calls to the configured providers
  and to nothing else. This is asserted by a test, not promised in prose.

---

## 2. Decisions already taken

These were decided by the operator and are not open for re-litigation during
implementation. Changing one is a new decision, recorded here.

| # | Decision | Date |
|---|---|---|
| D1 | Product name: ShyFerry. Package and CLI: `shyferry` | 2026-09-20 |
| D2 | Public repository, `Shyden-Ltd/ShyFerry`, Apache-2.0 | 2026-09-20 |
| D3 | Language: Python | 2026-09-20 |
| D4 | Users bring their own OAuth client credentials. ShyFerry ships no client ID and operates no service | 2026-09-20 |
| D5 | Deletion goes to the recycle bin only. Permanent deletion is not offered under any flag, key or environment variable | 2026-09-20 |
| D6 | Two deletion timings are offered: a separate verified pass (default), and per-file after each verified upload | 2026-09-20 |
| D7 | Google native file handling is the user's choice, with the reasoning surfaced in the tool itself | 2026-09-20 |
| D8 | MVP covers personal accounts only. Business tiers deferred until a free test tenant exists | 2026-09-20 |

D4 costs the user a one-off registration in Google Cloud and Microsoft Entra.
In exchange: no verification fee, no annual CASA security assessment, no
shared rate limits, and no circumstance in which Shyden Ltd holds or is
perceived to hold anyone's files or tokens.

D8 follows from the zero-cost constraint. Google Workspace has no permanently
free tier (14-day trial, then USD 7.00 per user per month). Microsoft's free
E5 developer sandbox is restricted to Visual Studio Professional or
Enterprise subscribers and members of qualifying programmes.

---

## 3. Architecture

### 3.1 Module layout

```
shyferry/
  core/
    models.py       RemoteItem, UploadTarget, TransferPlan, ManifestRecord,
                    Verification, Quota, AccountInfo
    provider.py     StorageProvider protocol and ProviderCapabilities
    registry.py     entry-point discovery of providers
    planner.py      enumeration, filtering, naming, collision resolution
    preflight.py    destination quota and capability checks, before any byte moves
    engine.py       execution: streaming, concurrency, retry, progress
    hashing.py      streaming multi-hasher, including quickXorHash
    verify.py       hash algorithm negotiation and comparison
    purge.py        recycle-bin deletion, gated on live re-verification
    manifest.py     append-only JSONL journal, resume support
    config.py       layered configuration and validation
    naming.py       filename sanitisation and portability rules
    errors.py       exception hierarchy
  providers/
    local/          filesystem provider
    gdrive/         Google Drive v3
    onedrive/       Microsoft Graph
  auth/
    oauth.py        OAuth2 PKCE loopback and device-code flows
    store.py        keyring-backed token storage, single-flight refresh
  cli/
    main.py         command-line surface
```

`core` never imports from `providers`. Providers never import each other.
The dependency direction is enforced by a test (section 11.5).

### 3.2 The StorageProvider protocol

The protocol is the only seam in the system. Every capability difference
between clouds is expressed through it, so `core` contains no provider name
and no conditional on one.

```python
class StorageProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def account_info(self) -> AccountInfo: ...
    def quota(self) -> Quota: ...
    def iter_items(self, root: PurePosixPath, *, recursive: bool) -> Iterator[RemoteItem]: ...
    def open_read(self, item: RemoteItem) -> ContextManager[BinaryIO]: ...
    def export(self, item: RemoteItem, target_mime: str) -> ContextManager[BinaryIO]: ...
    def ensure_folder(self, path: PurePosixPath) -> RemoteItem: ...
    def upload(self, stream: BinaryIO, dest: UploadTarget) -> RemoteItem: ...
    def stat(self, path: PurePosixPath) -> RemoteItem | None: ...
    def recycle(self, item: RemoteItem, *, expected_revision: str) -> None: ...
```

`RemoteItem` carries the provider's own identifier, the path, size, modified
time, the hashes the provider reports, the MIME type, whether the item is a
folder or a native document, and a **revision token**: an opaque,
provider-defined string that changes whenever the item's content changes.
That is Graph's eTag and Drive's `headRevisionId`. The token is captured at
transfer time, persisted in the manifest, and handed back to `recycle` as
`expected_revision`.

That keyword argument is not decoration. `recycle` must compare the
**recorded** revision, and an implementation that simply stats the item and
compares the result with itself would satisfy the signature, satisfy INV-9's
description, and check nothing whatsoever. Requiring the caller to supply the
transfer-time value makes that mistake impossible to write by accident: the
provider has no other way to obtain it.

`UploadTarget` carries the destination path, the declared byte length, the
modified time to preserve, and the collision policy for this item. Paths are
`PurePosixPath` throughout the protocol, including on Windows, because the
subject is a remote namespace and not the local filesystem.

`ProviderCapabilities` declares what the planner must adapt to: the hash
algorithms the provider reports, maximum file size, maximum path length,
forbidden filename characters, reserved names, whether names are
case-sensitive, whether duplicate names may exist in one folder, and whether
the provider has native document types requiring export.

OneDrive's naming rules are richer than a character blacklist and are
declared in full: the characters `" * : < > ? / \ |`, no leading or trailing
space, the reserved names `.lock`, `CON`, `PRN`, `AUX`, `NUL`, `COM0` to
`COM9`, `LPT0` to `LPT9`, `_vti_` and `desktop.ini`, no name beginning `~$`,
no folder named `forms` at a library root, and two specific characters barred
as the first character of a folder name. Microsoft publishes **no single
maximum path length**, noting instead that different applications and Office
versions impose different limits, so the capability carries a conservative
configured value rather than a fabricated authoritative one.

**The protocol has no method that deletes permanently.** There is no
`delete`, no `erase`, no `purge`, and no boolean argument on `recycle` that
would change its behaviour. This is the primary structural expression of D5:
the capability is not withheld by policy, it is absent from the interface.

### 3.3 Extensibility

Providers are discovered through the `shyferry.providers` entry-point group.
A third party ships a provider as a separate package on PyPI; ShyFerry finds
it at runtime and it becomes usable as a source or destination with no change
to this codebase. The conformance suite (section 11.3) is exported as a
pytest plugin so an external provider can prove itself against the same tests
the built-in providers pass.

---

## 4. Transfer pipeline

There is no server-to-server transfer path between Google Drive and OneDrive.
Neither API accepts a foreign URL as a source. Every byte therefore passes
through the machine running ShyFerry.

Bytes are streamed source to destination in bounded chunks. No temporary file
is written and no file is buffered whole: peak memory is `chunk_size` times
`worker_count`, both configurable, and a user with 20 GB of free disk must be
able to move a library far larger than that.

- Files below the provider's simple-upload threshold are uploaded in one
  request.
- Larger files use each provider's resumable upload session, with chunk
  boundaries aligned to the destination's required multiple.
- Each chunk is fed to the multi-hasher (section 5) as it passes.
- Folders are created before their contents. Empty folders are transferred:
  an empty folder is content.
- Folder creation is single-flight, cached by destination path. Google Drive
  permits two folders with the same name in the same parent, so two workers
  creating the same path concurrently would produce two folders and silently
  split the tree beneath them. One creation per path, shared by all workers,
  is therefore a correctness requirement and not an optimisation. Proven by a
  conformance test that races N workers at one nested path and asserts a
  single folder identifier results. See R-02.
- Transport is `httpx` with an async, bounded worker pool.
- Defaults are stated rather than left to emerge: 8 MiB chunks and 4 workers,
  giving a documented peak transfer buffer of 32 MiB. "Bounded by
  configuration" is not a bound until the configuration has a number in it.

---

## 5. Verification

### 5.1 The problem

The two clouds report incompatible hashes and cannot be compared to each
other:

- Google Drive reports `md5Checksum`, `sha1Checksum` and `sha256Checksum`,
  and only for files with binary content stored in Drive. Native documents
  and shortcuts have none.
- OneDrive reports `quickXorHash`, `crc32Hash` and `sha1Hash`. Microsoft's
  v1.0 reference states that `sha256Hash` "isn't supported, don't use", and
  that `quickXorHash` is the only value guaranteed to be available for both
  OneDrive personal and OneDrive for work or school.

### 5.2 The mechanism

As each chunk passes through the pipeline, a multi-hasher computes every
algorithm either side may report. Two comparisons are then made, both against
the value computed locally in flight:

1. **Read integrity**: the source's reported hash equals the locally computed
   value for the same algorithm. Proves the bytes were read correctly.
2. **Write integrity**: the destination's reported hash equals the locally
   computed value for the same algorithm. Proves the bytes landed intact.

Because both comparisons are made against the same local computation, no
cross-algorithm comparison is ever needed.

Which algorithms the multi-hasher runs is **derived from the two providers'
declared capabilities**, not fixed in code. A provider that reports only
`crc32Hash` for a given file would otherwise be unverifiable purely because
nobody remembered to add CRC32 to a list, and an item that cannot be
verified cannot be deleted - so a stale list would quietly cost users the
feature they came for.

A file that fails either comparison is re-transferred, within the item's
retry budget, by overwriting the same destination path. If the budget is
exhausted the item is recorded `failed` and named in the report, and the
partial or mismatched copy is **left where it is**: see INV-15.

`quickXorHash` is implemented in this repository. It is not optional and not
deferrable: it is the only hash guaranteed present on personal OneDrive, so
without it no OneDrive file can be verified, and therefore no OneDrive file
can ever be deleted.

Microsoft publishes an algorithm description and a C# reference
implementation, but **no known-answer test vectors**. A port checked only
against a transcription of that sample proves the transcription, not the
hash. The oracle is therefore the live service: upload known content to a
real personal OneDrive account and assert our computed value equals the
`quickXorHash` that Graph reports for it. Vectors obtained that way are then
frozen into the unit suite, so the fast tests need no network afterwards.

The implementation is written from Microsoft's published algorithm
description, which is prose and pseudocode, and **not transcribed from their
C# sample**. That keeps an Apache-2.0 repository clear of a licensing
question over vendor sample code, and it is the better engineering choice
anyway: the description is the specification, while the sample is one
implementation of it, complete with its own architecture-dependent caveats.

### 5.3 When verification is impossible

Microsoft's documentation states that not all services provide a value for
all hash properties. Google's states that checksums are absent for native
documents. A file may therefore arrive intact and still be unverifiable.

An item is marked `unverifiable` when: neither side reports any algorithm the
other side's bytes were hashed with; the destination reports no hash at all;
the content was converted in transit (section 7), so source and destination
bytes legitimately differ; or the item could not be exported at all.

Empty files are the awkward boundary case: providers vary in whether they
report a hash for zero bytes at all. A zero-byte file whose destination
reports no hash is unverifiable by the rule above, and therefore not
deletable, which would be a surprising outcome for the simplest possible
file. The conformance suite covers empty files explicitly on every provider
so the behaviour is known rather than discovered.

**Unverifiable is not a failure.** The transfer is reported as completed, and
the item is recorded as present at the destination. What it forfeits is
eligibility for deletion, permanently and without an override.

---

## 6. Deletion

### 6.1 What both clouds actually expose

Both providers offer permanent deletion, and both do so within the exact
OAuth scopes ShyFerry must hold in order to upload anything:

| Provider | Permanent deletion | Notes |
|---|---|---|
| Google Drive | `files.delete` | "Permanently deletes a file owned by the user without moving it to the trash." |
| Google Drive | `files.emptyTrash` | "Permanently deletes all of the user's trashed files." Blast radius extends beyond this run to anything the user trashed previously. |
| Microsoft Graph | `POST /drives/{drive-id}/items/{item-id}/permanentDelete` | v1.0, permission `Files.ReadWrite`. Titled "Permanently delete a file or folder". |

No part of ShyFerry's guarantee rests on these being unavailable. They are
available. The guarantee rests entirely on this codebase, which is why the
enforcement in section 6.4 is mechanical rather than editorial.

### 6.2 What ShyFerry does instead

- Google Drive: `files.update` with `trashed=true`.
- OneDrive: `DELETE /me/drive/items/{item-id}`. Microsoft's v1.0 reference
  states that deleting by this method "moves the items to the recycle bin
  instead of permanently deleting the item".
- `local`: moves the file into a `.shyferry-trash` directory at the root of
  the transfer, preserving relative path. The local provider does not use the
  desktop trash, because that behaviour differs per platform and cannot be
  asserted identically across the CI matrix. The provider excludes that
  directory from its own enumeration unconditionally; leaving it to a
  user-supplied filter would mean a second run over the same root ferries
  previously recycled files back again. Its revision token, which INV-9
  requires of every provider, is the file's size and modification time -
  what a filesystem offers - so the conformance suite's stale-revision test
  runs against `local` exactly as it does against the clouds.

Both cloud recycle bins retain items for a provider-defined period, during
which the user can restore them without ShyFerry. The exact period varies by
provider and account, so ShyFerry states it nowhere and relies on it for
nothing; recoverability is a property of the user's account, not a promise
this tool is in a position to make.

The two providers differ in how a deletion can be made conditional, and the
difference is load-bearing for INV-9. Graph accepts an `if-match` header on
delete: "if the eTag (or cTag) provided doesn't match the current tag on the
item, a `412 Precondition Failed` response is returned and the item isn't
deleted". That makes the invariant **atomic on OneDrive** - the server, not
ShyFerry, refuses a stale deletion. Drive v3 offers no equivalent: neither
`files.update` nor `files.delete` accepts any precondition parameter, so the
Drive path must read `headRevisionId`, compare, then trash, leaving a narrow
window between the two (R-06).

### 6.3 The two timings (D6)

- `shyferry purge-source RUN_ID` (default): a separate command, run after a
  transfer. It reads the manifest as a worklist, re-checks each item against
  the live destination, confirms the source is unchanged since transfer
  (INV-9), and recycles only those that pass both.
- `shyferry run --delete-after-each` (opt-in): recycles each source file
  immediately after that file's own upload has been verified. Intended for
  users whose source account is too full to complete a transfer otherwise.
  Subject to identical verification; only the timing differs.

Confirmation is specified rather than left to the implementation, because an
under-specified confirmation becomes a blanket `--yes` the first time
somebody scripts it. Interactively, the user types the run identifier.
Non-interactively, `--confirm RUN_ID` must match the run being purged. The
token is therefore never reusable: a command copied from a previous run, a
shell history entry or a README cannot authorise a deletion it was not
written for, and there is no flag that means "whatever run this is".

Both timings perform an **independent** existence and hash check against the
destination after the upload completes, never reusing the upload response. A
provider that acknowledges an upload it did not persist must not be able to
authorise the deletion of the original, and an invariant satisfied by reading
back the same response that claimed success is satisfied in name only.

Folders need their own rule, and it is the part of "remove everything from
the source" that a file-by-file rule cannot cover. A source folder is
recycled only when it is empty **at the moment of the check** and every item
it ever held was transferred, verified and recycled. A folder still holding
anything - an unverifiable file, an item the user does not own, something
added after the run began - is left in place and reported. Recycling a
folder because our records say it ought to be empty deletes whatever is
actually inside it, which is the one mistake in this design that the recycle
bin would not fully undo: the user would have to notice it had happened.

Neither can reach a permanent delete, because no code path can express one.

### 6.4 Safety invariants

Each invariant states its enforcement and the mutation that proves the
enforcement is alive. A guard that has never been observed failing is not
evidence of anything.

Every entry in the mutation column changes the **implementation**, never the
input. A test that merely exercises the hazard shows the behaviour is right
today; only removing the control shows that the test would notice if it
stopped being right.

| ID | Invariant | Enforcement | Mutation |
|---|---|---|---|
| INV-1 | No destructive provider API is referenced anywhere in the source | A CI guard downloads Google's Drive v3 discovery document and Microsoft Graph's metadata, **derives** the set of operations whose own description contains permanent deletion, and asserts none appears in our source with comments stripped | Introduce a `files.delete` call; guard must go red |
| INV-2 | `StorageProvider` exposes no permanent-delete method | Conformance test asserts the protocol's method set exactly | Add `delete_forever` to the protocol; test must go red |
| INV-3 | Nothing is recycled without a live destination check at the moment of deletion | Unit tests plus a journey that removes a file from the destination after transfer and asserts purge refuses it | Make purge trust the manifest record; tests must go red |
| INV-4 | An `unverifiable` item can never be recycled | Purge filters on verification state; property test over generated manifests | Mark an unverifiable item eligible; test must go red |
| INV-5 | Purge never runs implicitly as part of a transfer, and always requires a confirmation naming the specific run | CLI tests assert that `run` without `--delete-after-each` deletes nothing, that a purge with no confirmation deletes nothing, and that a confirmation quoting a *different* run identifier is refused | Accept any non-empty confirmation value; the wrong-run test must go red |
| INV-6 | Dry run and real run produce an identical plan and share one code path | Test compares plans; effects are gated at a single boundary | Diverge the dry-run path; test must go red |
| INV-7 | Items already in the source's trash are never enumerated, transferred or counted | Planner query asserts `trashed=false` on Drive and the equivalent on Graph; integration test trashes a file and asserts it is absent from the plan | Remove the filter; test must go red |
| INV-8 | ShyFerry contacts the configured providers and nothing else | A request recorder asserts every host contacted is one the active providers declare in their capabilities. The allowed set is **derived** from the loaded providers, never hand-listed. The test carries a liveness control: a deliberate request to a known host must be observed by the recorder in the same test, so a recorder that is not wired up fails rather than reporting an empty set | Add a call to an unrelated host; test must go red. Separately, detach the recorder; the liveness control must go red |
| INV-15 | `recycle` is only ever called on the source provider, never on the destination | The engine holds the destination behind a handle offering no `recycle`, and a test asserts the destination provider's `recycle` is never invoked across a full run including failed and mismatched transfers | Call `recycle` on the destination when cleaning up a failed upload; test must go red |
| INV-14 | An account type outside the supported set is refused at authentication, never partially supported | `account_info()` reports the account type, and anything outside the set stops with an explanation naming the limitation | Accept an unsupported account type; the refusal test must go red |
| INV-13 | Only items the user owns are enumerated, transferred or recycled | The Drive query carries `'me' in owners` beside `trashed=false`. An integration test places a shared-with-me file within the transfer root and asserts it is absent from the plan | Remove the ownership term from the query; the shared-with-me test must go red |
| INV-12 | A transfer whose destination lies inside its own source, on the same account, is refused before any byte moves | Pre-flight compares account identity and tests path containment in both directions | Remove the containment check from pre-flight; the nested-destination test must go red |
| INV-10 | No credential material reaches logs, error output or reports | A redacting formatter is the only logging path. Tests push access tokens, client secrets and signed resumable-upload URLs through every reporting surface and assert none appears | Log a raw token; test must go red |
| INV-11 | No OAuth client identifier or secret is embedded in the distributed package (D4) | A test scans the built wheel and source distribution for anything matching either provider's credential format | Embed a client ID in the source; test must go red |
| INV-9 | Nothing is recycled whose source has changed since it was transferred (R-04) | OneDrive: the recorded eTag is sent as `if-match`, so the server refuses a stale deletion with 412 and the check is atomic. Drive: `headRevisionId` is re-read and compared immediately before trashing, since Drive accepts no precondition (R-06) | Remove the `if-match` header from the Graph path and skip the `headRevisionId` comparison on the Drive path; the source-changed test must go red for each |

Ownership: INV-1 to INV-6 and INV-9 belong to S-14, INV-7 to S-09, INV-8 and
INV-10 to S-16, INV-11 to S-05, INV-12 to S-15, INV-13 to S-09, INV-14 to
S-05, and INV-15 to S-10. An invariant with no owning story is an intention
rather than a control.

INV-15 protects the destination from ShyFerry itself. A failed or mismatched
upload leaves a bad file at the destination, and the obvious tidy-up is to
delete it - which is a deletion this tool has no business performing, on a
provider whose contents it did not inventory, in a place where a name
collision with the user's own data is entirely possible. The mess is
reported and left; the user decides.

INV-14 guards the worst shape a deferred scope can take: not failure, but
partial success. A business account would authenticate, and most of the tool
would work - until enumeration missed every Shared Drive and SharePoint
library, and the run reported completion over an incomplete set. An account
we have not tested is refused with an explanation, because "it mostly
worked" is the outcome that loses data when a purge follows.

INV-13 is INV-7's twin. Section 1.2 puts "Shared with me" content out of
scope, and a scope statement enforces nothing: Drive's `files.list` returns
everything the user can see, not everything they own, so without an
ownership term the tool would ferry other people's files and then attempt to
recycle originals that were never the user's to delete.

INV-12 exists because a transfer that writes inside the tree it is reading
grows without limit: each file copied becomes a new file to copy. It is the
same defect as copying a directory into itself, and on metered cloud storage
it is considerably more expensive.

The derived deny-list in INV-1 is deliberate. A hand-written list of banned
method names would not have caught `files.emptyTrash`, which was missed in
the first draft of this design, and would not catch whatever either vendor
ships next year.

---

## 7. Google Workspace native documents

Google Docs, Sheets, Slides and Drawings have no bytes to download.
`files.get` with `alt=media` does not apply to them; they exist only as
server-side objects and must be converted through `files.export`.

Policy is set per type in configuration (D7), with these values:

| Policy | Behaviour | Why a user would choose it |
|---|---|---|
| `office` (default) | Docs to `.docx`, Sheets to `.xlsx`, Slides to `.pptx`, Drawings to `.png` | Keeps documents editable at the destination, which is usually the entire point of migrating |
| `pdf` | Every native type to PDF | Exact visual fidelity, at the cost of editability |
| `both` | The Office file and a PDF alongside | For irreplaceable documents; doubles the file count, and the source item counts as transferred only when both outputs exist |
| `skip` | Left in place, reported | No conversion risk; the user moves them by hand |

`shyferry explain native-files` prints this table with its trade-offs, and
the first interactive run shows it before asking. The default is applied
without prompting in non-interactive use.

`both` is the one policy where a single source item produces two destination
files, so the manifest holds one record per output sharing a source
identifier, and the item is transferred only once every one of its outputs
is present. A model that assumed one destination per source would report
success with the PDF written and the `.docx` missing.

Conversion means the destination's bytes differ from the source's by design,
so converted items are `unverifiable` in the sense of section 5.3 and are
never eligible for deletion. This is stated in the tool's output at the point
of choice, not only in documentation.

Types with no export path at all - Forms, Jamboard, Sites - and shortcuts
are reported, left untouched, and are likewise never eligible for deletion.

Files going the other way are never converted: a `.docx` uploaded to Google
Drive stays a `.docx`. Converting on upload would create a native document
with no checksum, making every uploaded file unverifiable.

---

## 8. Configuration

Layers, each overriding the one before:

1. Built-in defaults
2. A configuration file at the location `platformdirs` resolves for this
   application on the running platform, which is `~/.config/shyferry/` on
   Linux and different elsewhere. The path is reported by
   `shyferry auth status` rather than assumed by the user
3. Environment variables
4. Command-line flags

Customisable: include and exclude globs, minimum and maximum size, modified
before or after, MIME type filters, the native export map of section 7,
collision policy, concurrency, chunk size, retry and backoff policy, and
output format.

Credentials are never stored in the configuration file. Client IDs and
secrets, refresh tokens and access tokens live in the OS keyring. Google
desktop-client secrets are not secret in the cryptographic sense, but they
are still not written to a file that users paste into issue reports.

Collision policy at the destination, when a name already exists:
`skip-if-identical` (default, by hash), `rename`, `overwrite`, or `fail`.

`skip-if-identical` cannot use a hash for items converted under section 7,
because a converted file legitimately differs from its source and the
destination's hash is meaningless for comparison. Identity for those items is
the recorded tuple of destination name, size and source revision identifier.
Without this rule a second run cannot recognise its own previous output, and
every Google document is either duplicated or overwritten on every run.

---

## 9. Command-line surface

```
shyferry auth setup <provider>      register credentials, guided
shyferry auth login <provider>      run the OAuth flow
shyferry auth status                accounts, scopes, token expiry
shyferry plan <src> <dst>           enumerate and report, change nothing
shyferry run <src> <dst>            transfer, with --dry-run and --resume
shyferry verify <run-id>            re-check a completed run
shyferry purge-source <run-id>      recycle verified source files
                                    (--confirm <run-id> when non-interactive)
shyferry explain native-files       the table in section 7
shyferry report <run-id>            human or JSON output
shyferry runs list                  past runs and their outcomes
shyferry runs prune                 discard manifests past the retention window
```

Source and destination are written as `<provider>:<path>` - `gdrive:/`,
`onedrive:/Photos`, `local:~/Backup`. The prefix is the name the provider
registers under, so a third-party provider is addressed exactly like a
built-in one, and a bare path with no prefix means `local:`. A locator parses
to a provider, an account and a path, which is precisely the triple INV-12
compares for containment.

Exit codes are meaningful and documented: 0 success, 1 partial with
failures, 2 configuration or credential error, 3 refused by a safety gate.
A run that completes but leaves items unpurged for safety reasons is a
success and exits 0, with every refusal itemised in the report: those
refusals are the tool working, not failing. Exit 3 is for a gate that
refused the whole operation. `--json` produces machine-readable output on
every command that reports.

Output conventions: machine-readable output goes to stdout and everything
else to stderr, so `--json` stays parseable when piped. Progress rendering
degrades to plain lines when stdout is not a terminal. `NO_COLOR` is
honoured, and colour is never the only carrier of meaning.

---

## 10. Errors, retries and resumability

### 10.1 Retry policy

Retries apply to transport failures and to documented throttling responses
only. A 4xx that is not a throttle is a permanent failure for that item and
is recorded; it never fails the whole run. Graph 429 responses honour
`Retry-After`. Drive rate-limit responses use exponential backoff with
jitter. Retry budgets are per item and per run, both configurable.

Three conditions are not retryable and are handled as expected events rather
than as crashes. **Revoked authorisation** mid-run - the user withdrew
consent, or an administrator did - stops the run cleanly with a message
naming the re-authentication command, and the manifest is left resumable.
**A source item that has vanished** between planning and transfer is
recorded as `vanished` and reported, never as a failure: the user deleted
their own file, and treating that as an error trains people to ignore the
error count. **An interrupt** flushes the manifest, abandons the in-flight
chunk and exits with a resumable state, so that the difference between a
clean exit and a hard kill is one chunk of repeated work rather than a
corrupt journal.

### 10.2 Token refresh

Access tokens are refreshed through a single-flight lock: concurrent workers
observing an expired token produce exactly one refresh call. This matters
beyond correctness. Google documents a limit of 100 refresh tokens per Google
account per OAuth client ID, and a naive implementation issuing one refresh
per worker walks toward that ceiling. Google also expires refresh tokens
after seven days while a client's publishing status is "Testing", and after
six months of disuse; both are handled as expected conditions with actionable
messages, not stack traces.

### 10.3 The manifest

An append-only JSONL journal per run, at the platform state directory, one
record per state transition: `planned`, `transferred`, `verified`,
`unverifiable`, `failed`, `skipped`, `vanished`, `recycled`. Each record
carries the source and destination identifiers, the size, the hashes
computed and reported, and the **source revision token** captured at
transfer time, without which INV-9 cannot be evaluated at purge time.

A manifest is an inventory of the user's entire file tree in plain text:
names, paths, sizes and hashes. That is sensitive on its own, independently
of the files it describes. It is written with owner-only permissions, its
location and contents are documented in `SECURITY.md` rather than left for a
user to discover, `shyferry report` can redact paths, and
`shyferry runs prune` removes old manifests. Runs are retained for 90 days
by default rather than forever.

**The manifest is a worklist. It is never the authority.** Purge re-reads the
live destination and re-compares hashes at the moment of deletion. A record
that fails to parse is refused and reported; it is never skipped silently. A
manifest that has been edited, truncated or copied between machines can
therefore cause a purge to do less, and can never cause it to do more.

### 10.4 Resume

`--resume RUN_ID` replays the manifest, skips the transfer of items already
verified, and re-plans the remainder. An item that is verified but not yet
recycled is not finished: under `--delete-after-each`, an interruption
between verification and deletion leaves work outstanding, and resume
completes the deletion rather than skipping the item as done. Resumption is asymmetric, deliberately. An interrupted upload continues from
the last chunk the destination confirmed, where the provider permits it. The
**source is always re-read from the beginning**, because verification hashes
the whole file in flight (section 5.2) and a hash computed over the tail of
a file is not a hash of that file. Seeking the source instead would save
reading bytes that are comparatively cheap, and would forfeit the
verification that licenses deletion. On the asymmetric connections most
people have, the upload is the bottleneck, so resuming the upload while
re-reading the source recovers nearly all of the cost. This is also why
`open_read` needs no range parameter: nothing in ShyFerry ever reads part of
a file.

Provider upload sessions expire; an expired session is a normal condition
and is re-established.

---

## 11. Testing

Test-driven throughout: the failing test precedes the implementation, for
every story.

### 11.1 Layers

- Unit tests over pure logic: planner, naming, collision resolution, filters,
  hashing, manifest state machine, configuration layering.
- Property-based tests (Hypothesis) over filename sanitisation, path
  portability and manifest replay, including both Unicode normalisation
  forms (R-03).
- Conformance tests: one suite, run against every provider.
- Integration journeys against real accounts.
- Mutation testing over every module that carries an invariant from section
  6.4 - today `verify`, `purge`, `hashing`, `manifest`, `preflight`,
  `planner`, `auth` and the CLI reporting path. The scope is **derived from
  the invariant table's ownership**, not kept as a separate list beside it. A
  hand-maintained list would have covered four modules while six of the
  fourteen invariants lived elsewhere, and nothing would have said so.

### 11.2 The local provider is not a mock

`local` is a genuine `StorageProvider` over a real filesystem, shipped to
users as a supported target. It is not a stub and contains no test-only
branch. It means the conformance suite exercises real bytes, real directory
structures and real failure modes without a network, and it forces the
abstraction to be honest: anything the protocol cannot express, `local`
cannot implement either.

### 11.3 The conformance suite

Every provider passes the same suite: round-trip a file and compare bytes,
round-trip a zero-byte file and record whether a hash is reported at all
(section 5.3), enumerate a nested tree, create and detect folders including
empty ones, race N workers at one folder path and assert a single identifier,
reject forbidden names according to declared capabilities, report hashes
matching locally computed values, recycle an item and confirm it leaves the
listing, refuse a recycle whose `expected_revision` is stale, and refuse
operations the provider declares it cannot do.

### 11.4 Journeys against real accounts

Two providers in MVP, a personal account on each: Google Drive and OneDrive.
Both directions. ("Account type" is reserved for the personal-against-
business distinction INV-14 enforces, and is not used loosely here.) Credentials come from CI secrets; a missing credential produces
an itemised, loud skip naming each journey not run. A silent pass is a
failure of the harness.

Journeys: first-run credential setup; plan and dry run; full transfer; native
document conversion under each policy; verification; purge by separate pass;
purge by `--delete-after-each`; interrupted transfer and resume; a file
modified at source mid-run; a file modified between transfer and purge; a
destination nested inside its source; a shared-with-me file inside the
transfer root; an unsupported account type; destination quota exhaustion
(R-05); throttling.

Free-tier storage ceilings (5 GB OneDrive, 15 GB Drive) bound these fixtures.
Large-file and resume journeys therefore target the mechanism - chunk
boundary resumption, expired upload sessions, mid-file interruption - rather
than attempting to provoke failure through sheer volume. "Survives a 500 GB
migration" is consequently an untested claim and will not be made.

### 11.5 Structural guards

- Module dependency direction: `core` must not import `providers`.
- Comment stripping for every source-text guard uses Python's own `tokenize`
  module, which yields exact COMMENT and STRING tokens from the real grammar.
  A regular expression cannot distinguish a call from the same text inside a
  docstring, and the guards in section 6.4 are worthless if it cannot.
- Every guard is mutation-verified in both directions before it is trusted,
  and the two directions are stated rather than implied: the guard goes
  **red** when the control it protects is removed, and **green** on the
  unmodified tree. A guard proven only in the first direction may be failing
  for an unrelated reason; one proven only in the second may be asserting
  nothing at all.

### 11.6 Platform matrix

Linux, macOS and Windows, on Python 3.11, 3.12 and 3.13. Keyring backends,
path semantics and filesystem case sensitivity differ per platform, and all
three are load-bearing for this product.

---

## 12. Repository, CI and supply chain

- Public, Apache-2.0, `Shyden-Ltd/ShyFerry` (D1, D2).
- Every ticket carries an evidence page recording what was run and what was
  observed, and the operator signs it off before the branch merges. A green
  pipeline is a precondition for that sign-off, never a substitute for it.
- Installs in CI are hash-verified from the lockfile. A tool that handles
  other people's credentials does not resolve dependencies loosely.
- The specification's own integrity checker runs in CI beside the test
  suite. It found a command documented nowhere and five decisions cited
  nowhere while this design was being written; a document that drifts out of
  agreement with itself misleads exactly the people it was written for.
- Branches: `main` and `develop`. Nothing merges to `main` directly. Every
  ticket gets a branch, which merges to `develop`.
- `uv` for environment and lockfile (D3). Python 3.12 pinned for development;
  `requires-python = ">=3.11"` declared in the package metadata, matching the
  tested matrix exactly. A package installable on a version nothing tests is
  a defect waiting for a bug report.
- `ruff` for lint and format, `mypy --strict`, `pytest`, coverage gate.
- `.github/dependabot.yml` covering `pip` and `github-actions`, both with
  `target-branch: develop`. Same-repository sub-path actions are grouped
  above any catch-all group, because Dependabot assigns to the first matching
  group and stops.
- Every third-party action pinned to a full 40-character commit SHA with a
  trailing version comment. Asserted by a test that strips comments first.
- Dependabot alerts and security updates enabled explicitly on the repository
  and then re-read, because an organisation default does not apply to a
  repository created through the API.
- Required status checks are added to branch protection after the first merge
  to `develop`, then re-read. A job that is not in `required_status_checks`
  is not a gate, however green it looks.
- `SECURITY.md`, `CONTRIBUTING.md` and a code of conduct, as a public
  repository handling other people's credentials requires.

---

## 13. Known limitations, to be published

1. Personal accounts only. Business and enterprise tiers are not supported.
2. Sharing permissions, comments and revision history do not transfer.
3. Google native documents are converted, and converted files cannot be
   checksum-verified, so they are never eligible for deletion.
4. Google's export endpoint is limited to 10 MB; larger native documents
   cannot currently be transferred (see SPIKE-01).
5. Forms, Jamboard, Sites and shortcuts cannot be transferred at all.
6. Deletion is to the recycle bin only, by design. ShyFerry cannot free
   quota instantly and will not.
7. Tested up to free-tier storage limits; very large migrations are untested.
8. A run resumed after an interruption re-reads the source file from the
   beginning. Only the upload resumes, so resuming costs download bandwidth
   again; this is what keeps verification honest (section 10.4).
9. A file whose source has changed since it was transferred is left in place
   rather than deleted, and reported. That is deliberate, not a failure.

---

## 14. Risks and open questions

Each risk names the story that owns it, so no risk is recorded without a
place where it is actually discharged.

| ID | Question | How it will be settled | Owner |
|---|---|---|---|
| SPIKE-01 | Can Google native documents over 10 MB be exported through `files.download`, the long-running operation whose docs are silent on size and documented only for Google Vids? | Create a >10 MB Google Doc on a real account, attempt both paths, measure. Until measured, such files are non-transferable and therefore never deletable | SPIKE-01, then S-13 |
| R-02 | Google Drive permits duplicate filenames in one folder; OneDrive does not, and is case-insensitive where Drive is case-sensitive | Treated as an assumption, proven by integration test, not asserted as fact. Collision policy in section 8 is the handling, and the folder single-flight rule in section 4 is its consequence | S-09 |
| R-03 | Unicode normalisation differs between platforms and providers (NFC against NFD), producing false name mismatches | Normalise for comparison, preserve original bytes for display; property test over both forms | S-09 |
| R-04 | A file modified at the source between planning and transfer, or between transfer and purge | The first is detected by hash mismatch at verification. The second is INV-9 in section 6.4, which is the case that could otherwise lose data | S-12, S-14 |
| R-05 | Destination quota exhausted mid-run | Pre-flight comparison of planned bytes against destination free space in `preflight.py`, accounting for content already present when resuming and for conversions changing size, plus graceful handling and resume | S-15 |
| R-06 | Google Drive accepts no precondition on delete or update, so INV-9 on the Drive side is a read-then-act with a narrow race window, where the OneDrive side is atomic via `if-match` | Re-read `headRevisionId` immediately before trashing, keeping the window minimal. The residual risk is bounded by D5: the worst outcome of losing that race is an item in the user's own trash, recoverable by them, because ShyFerry cannot permanently delete anything | S-14 |

---

## 15. Story breakdown

Eighteen stories and one spike. Each gets a branch, full acceptance criteria
written before implementation begins, and a failing test before production
code.

| ID | Story |
|---|---|
| S-01 | Repository bootstrap: uv, ruff, mypy, pytest, CI matrix, Dependabot, branch protection, licence, project CLAUDE.md |
| S-02 | Core models and layered configuration |
| S-03 | `StorageProvider` protocol, capabilities, entry-point registry, conformance suite exported as a pytest plugin, `local` provider |
| S-04 | quickXorHash, oracled against live Graph values (no published vectors exist) |
| S-05 | OAuth2 PKCE and device-code flows, keyring storage, single-flight refresh |
| S-06 | Bring-your-own credential setup wizard and provider registration guides |
| S-07 | Google Drive provider, personal accounts |
| S-08 | OneDrive provider, personal accounts |
| S-09 | Planner: enumeration, trashed-item exclusion, filters, naming, collisions |
| S-10 | Transfer engine: streaming, chunking, concurrency, retry and backoff |
| S-11 | Manifest and resume |
| S-12 | Verification and hash negotiation, including the unverifiable state |
| S-13 | Native document export policy and the `explain` command |
| S-14 | Purge: both timings, INV-1 to INV-6 and INV-9, mutation proofs |
| S-15 | Destination quota pre-flight |
| S-16 | CLI surface, dry-run parity, JSON reporting, exit codes |
| S-17 | Documentation: README with limitations, SECURITY.md including the manifest's contents and location, CONTRIBUTING, CoC |
| S-18 | Real-account journeys, release workflow, PyPI publication |
| SPIKE-01 | Google native export above 10 MB |

Build order is constrained by S-04: quickXorHash blocks any verified OneDrive
transfer, and therefore blocks deletion entirely on that side.

---

## Appendix A: verified facts and their sources

Every load-bearing claim below was read from the vendor's own published
source on 2026-09-20, not from recollection.

| Claim | Source |
|---|---|
| `drive.files.delete` permanently deletes without trashing | Drive v3 discovery document, method description |
| `drive.files.emptyTrash` permanently deletes all of the user's trashed files | Drive v3 discovery document, method description |
| Drive checksums exist only for files with binary content | Drive v3 discovery document, `File.md5Checksum` and `File.sha256Checksum` |
| `supportsAllDrives` is a parameter on `files.list` and `files.delete` | Drive v3 discovery document |
| Google export is limited to 10 MB | `files.export` reference and the download guide |
| `files.download` is a long-running operation valid for 24 hours, documented for Google Vids, silent on size | Drive v3 discovery document and the download guide |
| Graph exposes `POST /drives/{drive-id}/items/{item-id}/permanentDelete` at v1.0 under `Files.ReadWrite` | Microsoft Learn, "Permanently delete a file or folder", graph-rest-1.0 |
| Graph `sha256Hash` "isn't supported, don't use" | Microsoft Learn, hashes resource type, v1.0 |
| `quickXorHash` is the only hash guaranteed on both OneDrive personal and work or school | Microsoft Learn, hashes resource type, v1.0 |
| Google refresh tokens expire in seven days while publishing status is "Testing" | Google Identity, Using OAuth 2.0 |
| Limit of 100 refresh tokens per Google account per OAuth client ID | Google Identity, Using OAuth 2.0 |
| Google Workspace has no permanently free tier; 14-day trial, then USD 7.00 per user per month | Google Workspace pricing |
| The free Microsoft 365 E5 developer sandbox requires a Visual Studio Professional or Enterprise subscription, or membership of a qualifying programme | Microsoft 365 Developer Program |
| Graph delete "moves the items to the recycle bin instead of permanently deleting the item" | Microsoft Learn, "Delete a file or folder", graph-rest-1.0 |
| Graph delete accepts `if-match`, returning 412 and not deleting when the tag differs | Microsoft Learn, "Delete a file or folder", request headers |
| Drive `files.update` and `files.delete` accept no precondition parameter; `File` exposes `headRevisionId` and `version` | Drive v3 discovery document, method parameters and `File` schema |
| Microsoft publishes a quickXorHash algorithm description and C# reference implementation, but no known-answer test vectors | Microsoft Learn, QuickXOR Hash Sample |
| OneDrive forbids nine characters (quotation mark, asterisk, colon, both angle brackets, question mark, both slashes, vertical bar), leading and trailing spaces, and a documented set of reserved names; no single maximum path length is published | Microsoft Support, invalid file names and file types |
