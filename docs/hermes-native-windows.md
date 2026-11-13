# Hermes native Windows adapter

The native adapter supports a single Hermes orchestrator on a locally accessible Windows vault without WSL. It provides **reduced guarantees**, not the POSIX descriptor-pinned transaction guarantee.

## Write lifecycle

1. Read each target and retain its exact bytes/hash or verified absence.
2. Build one `hermes-native-windows-reduced-v1` operation with inline content, expected hashes, and any read preconditions.
3. Call `inspect_operation(vault, operation)` and inspect its complete changed-path list and `approval_sha256`.
4. Call `execute_operation(vault, operation, approval_sha256)`. This owns prepare, apply, and verify; success is `state: complete` after the cooperative lock is released.
5. Verify source/raw/page/provenance as applicable, then run read-only lint.

Do not manually write the vault using generic file tools between prepare and verify. Do not call the POSIX transaction apply command on native Windows.

## Safety boundary

The guard provides bounded vault-relative paths and payloads, expected-content checks, checkpoint before-images, post-write verification, protected runtime namespaces, alias/junction checks, and authority-bound rollback. It does **not** provide a truly atomic multi-file commit or protection from non-cooperating writers.

Obsidian, other agents, and cloud-sync clients do not automatically honor Hermes locks. Keep managed files locally available, serialize automated writers, and avoid concurrent edits/sync conflicts during apply. Cloud-backed paths are not a guarantee of cross-machine locking. Do not relocate an existing user vault merely to install this package.

Use `recover_prepared_operation` only with original operation authority, a dead local owner, and an exact fully-applied state. Partial state or unexplained drift requires safe rollback/investigation. Never manually delete a lock to force progress.

## Product and vault selection

The product is this checkout; it is not the user's vault. Pass the vault explicitly through `--vault`, or use the existing supported runtime vault configuration. Machine-local configuration and credentials are not distributed by this repository.

The distributed native scripts resolve the product relative to their own location. No personal home directory, mounted drive, account, or live vault contents are required or included.

## Native BM25 provisioning

```bash
python -B scripts/bm25_provision_native.py --vault <VAULT>
python -B scripts/retrieve.py --vault <VAULT> "search terms" --top 5 --no-rerank --explain
```

The adapter creates synthetic local prefixes without LLM/network egress, reconciles changed/surplus chunks through the guard, and publishes the index through `hermes_windows_bm25`.

The large-index writer is narrowly limited to `.vault-meta/bm25/index.json`; it is not a general way to bypass transaction payload limits. Chunk mutation and index publication are distinct recoverable lifecycles. Verify the final index and retrieval result, not only the chunk-write message. Exit code `2` from provisioning means unchanged, not failure.

## Verified staging cleanup

```bash
python -B scripts/second_brain_staging_cleanup.py --vault <VAULT>
```

Run discovery first; inspect CLI help before applying. The adapter accepts legacy/current manifest forms and proves raw hash, ledger identity, page association, an operative archive declaration outside comments/code/metadata, and an exact page-body/raw-byte relationship before deleting an eligible direct child of `inbox/` or `Clippings/`. Accepted-candidate proof hashes are retained together and bound as read preconditions. Until a transformation-specific proof is available, summaries or edited representations remain blocked even when an archive link is present. An explicit ingest request authorizes cleanup of only that verified source. Blocked candidates stay in place; `.raw/` is never a cleanup target.

## Runtime artifacts and privacy

Locks, checkpoints, operations, chunks, and indexes belong to the selected vault's ignored `.vault-meta/` namespace. They may contain private data and must not be published. Checkpoints are recovery aids, not a substitute for independent backups. Git for user vaults is optional and never enabled automatically.

See [current implementation reference](current-implementation.md) for lint and retrieval boundaries, including the not-yet-implemented `Sesi/` design.
