# Staging cleanup guard: validated pattern

Use this reference for both interactive and cron ingest completion.

## Lifecycle

1. Discover only direct child files of `inbox/` and `Clippings/`; exclude `.gitkeep`.
2. Prove exactly one source-ledger record with supported `origin.kind`, stable source ID, `.raw` locator, matching content hash, manifest record, existing raw payload, and at least one valid wiki page.
3. Require a structured source line such as `Sumber: [[.raw/name]]` or `Sumber arsip: [[.raw/name]]`. Ignore fenced code blocks, including nested/shorter marker runs and fence-like lines with trailing text.
4. Capture ledger, manifest, raw, and page bytes once; derive parsing and SHA-256 proof from the same bytes. Bind those proof hashes as read-only preconditions to the guarded delete operation.
5. Apply only through the native Windows guard. Delete targets are direct children of the two staging roots only. Preserve `.raw/` and `.gitkeep`.
6. Validate vault/runtime/quarantine ancestors immediately before movement; reject junctions/reparse aliases. Keep before-images and quarantine copies for rollback/recovery.
7. Post-check staging state, raw hashes, checkpoint contents, and lint. Compare lint with the pre-ingest baseline so unrelated legacy findings are reported, not silently repaired.

## Important ledger detail

Use a validator-supported `content_kind` (for textual clips/threads, normally
`document`). Do not introduce an unrecognized enum such as `clipping`; encode
that distinction in title, tags, or log metadata.

## Safety outcomes

- `verified > 0` and `blocked == 0`: guarded apply is allowed.
- Any blocked proof or changed read precondition: preserve staging and report it.
- No staging files: discovery/apply is a no-op; do not delete chat source files outside the vault.
