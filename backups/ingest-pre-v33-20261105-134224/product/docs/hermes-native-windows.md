# Hermes native Windows adapter

This adapter lets one Hermes orchestrator manage a local NTFS Obsidian vault without WSL. It is a **reduced-guarantee** workflow and is **not equivalent** to the upstream POSIX descriptor-pinned transaction engine.

## Guarantee boundary

The adapter provides:

- bounded vault-relative paths;
- expected SHA-256 or verified absence for every target;
- approval hash bound to the selected vault and exact operation;
- cooperative single-writer lock for Hermes writers;
- byte-for-byte before-image checkpoint;
- post-write hash verification;
- guarded rollback when targets have no unexplained drift.
- protected `.git` and Hermes runtime namespaces;
- portable case-fold/Unicode collision rejection;
- bounded write, checkpoint, and runtime-state sizes.
- strict finite JSON for operation and runtime authority records.
- bounded descriptor-based reads for targets, runtime JSON, and checkpoints;
- streaming cooperative-lock inspection with immediate rejection of unexpected entries.

It does not provide:

- protection from non-cooperating writers such as Obsidian or another program;
- POSIX directory-descriptor pinning;
- a truly atomic multi-file commit;
- automatic stale-lock reaping;
- upstream transaction equivalence.

Keep the vault on local NTFS. Do not use this adapter for a shared/network vault or concurrent automated writers.

## Required workflow

Only a **single orchestrator** may perform canonical writes. `delegate_task` workers remain read-only and return drafts/evidence.

1. Read every target and record its exact SHA-256 or verified absence.
2. Build one `hermes-native-windows-reduced-v1` operation.
3. Call `inspect_operation(vault, operation)` and review the complete changed-path list.
4. Call `prepare_operation(vault, operation, approved_plan_sha256)` immediately before writing. This rechecks targets, creates before-images, and acquires the cooperative lock.
5. Apply only the reviewed content through Hermes `write_file` or `patch`. Do not run unrelated writes while the lock exists.
6. Call `verify_operation(vault, operation, approved_plan_sha256)` with the original authority inputs to verify every after hash and release the lock.
7. Run deterministic wiki lint after verification while all writers are idle.
8. If writing or verification fails, call `rollback_operation(vault, operation, approved_plan_sha256)` with the same original authority inputs. Rollback preflights every before-image and refuses unexplained drift instead of overwriting it.

## Runtime environment

The Hermes profile `.env` (under the Hermes home directory) supplies two
variables:

```text
HERMES_OBSIDIAN_VAULT=<path-to-your-obsidian-vault>
HERMES_CLAUDE_OBSIDIAN_CORE=C:/Users/<user>/AppData/Local/hermes/components/claude-obsidian-core
```

- `HERMES_OBSIDIAN_VAULT` is the explicit managed vault path (legacy alias
  `CLAUDE_OBSIDIAN_VAULT` remains accepted by the core scripts).
- `HERMES_CLAUDE_OBSIDIAN_CORE` is the installed product root the skills use to
  resolve `scripts/claude-obsidian.py`. Skills never hard-code machine-local
  paths; the invoking agent reads this variable.

Use forward slashes in `.env` values so no shell or dotenv parser interprets a
backslash escape. Windows `pathlib` and the write guard accept both separators.

## Concurrent Obsidian edits

Obsidian does not honor the cooperative Hermes lock. Adam should avoid editing target notes during a Hermes write. `prepare_operation` catches changes made before preparation; `verify_operation` catches unexpected final bytes. A small race remains between the final recheck and the external file-tool write, which is why this mode is explicitly reduced-guarantee.

## Runtime state

The adapter stores ignored operational state under:

```text
.vault-meta/hermes-windows/
├── write.lock/
└── operations/<operation-id>/
    ├── manifest.json
    ├── operation.json
    └── before/
```

Do not treat this runtime state as canonical knowledge. Keep normal external backups or local Git in addition to per-operation before-images.

Runtime JSON is untrusted state. Verification and rollback revalidate its directory chain and compare it with the original operation and approval hash retained by the orchestrator.

## Failure handling

- Expected hash mismatch: abort and rebuild the draft from current files.
- Existing cooperative lock: stop; do not delete it automatically.
- Verification mismatch: keep checkpoint and lock, investigate, then rollback if targets still match known before/after hashes.
- Lock-release failure: terminal manifest state is reverted to `prepared`; remove only the unexpected cooperative-lock entry after review, then retry verification or rollback.
- Rollback drift: stop and ask for manual review; never force overwrite.
- Completed operation: preserve its manifest for audit; cleanup policy is a separate maintenance decision.
