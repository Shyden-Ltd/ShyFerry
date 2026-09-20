# ShyFerry

Move an entire cloud storage library from one provider to another, verify that
every byte arrived intact, and — only if you ask — move the originals to the
source provider's recycle bin.

```console
$ shyferry run gdrive:/ onedrive:/FromDrive
$ shyferry purge-source 2026-09-20-a3f1
```

ShyFerry is free, open source, and runs entirely on your machine. There is no
hosted service, no account to create with us, and nothing about your files ever
reaches Shyden Ltd.

## What it will not do

Take these seriously before pointing it at anything you care about.

- **It never deletes permanently.** Deletion means the provider's recycle bin,
  always. There is no flag, no configuration key and no environment variable
  that changes this — the capability is absent from the code, not withheld by
  policy.
- **It never deletes anything it could not verify.** A file whose checksum
  cannot be compared on both sides is transferred and reported, and then stays
  where it is, permanently and without an override.
- **Personal accounts only, for now.** OneDrive for Business, SharePoint,
  Google Shared Drives and Google Workspace are not supported, and an account
  of an unsupported type is refused at sign-in rather than half-handled.
- **Sharing permissions, comments and revision history do not transfer.** Only
  the files do.
- **Google Docs, Sheets and Slides are converted**, because they have no bytes
  to download. You choose the format. Converted files cannot be checksummed
  against their originals, so they are never eligible for deletion.
- **Files over Google's 10 MB export limit, plus Forms, Jamboard and Sites,
  cannot be transferred at all.** They are reported and left alone.
- **Tested up to free-tier storage limits.** Very large migrations are
  untested, and we will not claim otherwise.

## Bring your own credentials

You register your own OAuth application with Google and Microsoft — a one-off
of about ten minutes, guided by `shyferry auth setup`. That is why ShyFerry
costs nothing to run: no verification fees, no annual security assessment, no
shared rate limits, and no third party holding a token that can read your
files.

## Status

Early development. The design is settled and public:
[`docs/superpowers/specs/2026-09-20-shyferry-design.md`](docs/superpowers/specs/2026-09-20-shyferry-design.md).

## Licence

Apache-2.0. Copyright Shyden Ltd.
