# Native Windows pasted-text ingest: guard and provenance checks

This supplements `second-brain-ingest-operations` for pasted text captured into an Obsidian vault on native Windows. It records a verified variant of the existing class-level workflow, not a separate task skill.

## Source and synthesis

- Use the exact source supplied by the user; exclude only the user's operational instruction (for example, “ingest ini”). Do not fetch external sources unless the user separately authorizes them.
- Check the source archive, source ledger, manifest, target date page, and relevant navigation for duplicates before mutation.
- Preserve raw source bytes create-only. For market updates, summarize only durable/useful content and retain a direct raw link. Keep forecasts, realized outcomes, different instruments, and distinct market-session snapshots separate.
- For yield tables, reproduce all reported values exactly. Independently calculate (end yield - start yield) × 100 bps; flag mismatches in the note, never replace the reported value. Preserve source sign conventions, flow windows, and units. Mark claims unverified if no external checking was requested/performed.

## Guarded lifecycle

For native Windows, the low-level helper accepts a reviewed operation with schema `hermes-native-windows-reduced-v1`:

1. Assemble one operation containing raw archive, canonical note, source ledger, raw manifest, relevant existing MOC, hot cache, and log updates. Use a unique operation ID and one write per path.
2. Set `expected_hashes` for every mutation path. Existing targets require `sha256:<64 lowercase hex>`; create-only paths require `null`. The raw source stable ID is `stable_source_id("file", raw_locator, raw_sha256)`; ledger `origin.locator`, `content_sha256`, and `pages`, plus manifest `path` and `sha256`, must all agree with the actual raw archive.
3. Call `inspect_operation(vault, operation)`. Inspect the exact changed paths and rendered content, not just the returned approval hash. Review its `approval_sha256` against the operation that will be applied.
4. Call `execute_operation(vault, operation, approval_sha256)` once. It performs prepare/apply/verify. Report the actual `guarantee_level` as reduced; do not describe this as upstream transaction equivalence.
5. If a post-apply lint issue is caused by operation metadata, create a distinct repair operation with fresh hashes, inspect and execute it through the same helper. Never repair by direct file writing.

When the native helper is used, `.raw/.manifest.json` can be included as a path in the reviewed native operation. Do not infer that this licenses direct writes outside that helper or in a POSIX transaction.

## Date fields

Keep the following concepts separate:

- Source date: in filename/date/title for a dated Market Update.
- Actual local ingest date: note `created`/`updated`, source `ingested_at`, manifest `archived_at`, and the ingest log heading.
- Ledger `generated_at`: a canonical UTC timestamp exactly `YYYY-MM-DDTHH:MM:SSZ`, not a date-only string. Verify against the live lint engine; a date-only value produces a provenance error.

## Read-back and retrieval

After a `complete` operation:

1. Hash the actual raw archive bytes; require exact equality with both the manifest and ledger content hash. Check the ledger raw locator/page link and the exact standalone note line `Sumber arsip: [[.raw/<filename>]]`.
2. Check canonical page, intended MOC/hot/log changes, and that the native write lock is absent.
3. Run the vault lint command and require zero findings (or precisely distinguish pre-existing issues from new ones).
4. Rebuild the native BM25 index and perform a focused retrieval query. Verify `page_path` in the returned result; a hot-cache hit alone does not prove the target note is indexed.
5. Report the raw/note paths, whether hash/provenance checks matched, lint outcome, and the actual retrieval result. Do not say the ingest is complete while any verification is pending.

This is a bounded record of the Windows pasted-text workflow. Continue to follow the parent skill's scope, compilation-value gate, source trust, and user-ownership rules. For existing inbox/Clippings files, use their separate archival and cleanup workflow; pasted chat text has no user-owned staging file to delete.
