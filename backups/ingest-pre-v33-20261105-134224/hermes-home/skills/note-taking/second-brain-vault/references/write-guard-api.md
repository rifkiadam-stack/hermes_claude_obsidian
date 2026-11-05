# Hermes native-Windows write guard — API reference

Module: `claude_obsidian/hermes_windows_write.py` in the product core
(`$HERMES_CLAUDE_OBSIDIAN_CORE`).

## Purpose

The upstream POSIX transaction engine (directory-descriptor confinement,
`fcntl.flock`, atomic replacement) refuses mutation on native Windows with
`UNSUPPORTED_PLATFORM`. The guard is the **reduced-guarantee** replacement for
a single Hermes orchestrator writing to a local NTFS vault. It is NOT
equivalent to the upstream engine; it is honest about that (operation schema
`hermes-native-windows-reduced-v1`).

## Operation shape

```python
operation = {
    "schema": "hermes-native-windows-reduced-v1",
    "operation_id": "slug-001",            # [A-Za-z0-9._-]{1,128}, not "."/"..", portable name
    "expected_hashes": {"wiki/New.md": None, "wiki/Old.md": "sha256:<64 hex>"},
    "writes": [{"path": "wiki/New.md", "content": "..."}],
}
```

- `expected_hashes`: current SHA-256 for existing targets, `None` for files
  that must not exist yet. Guard rejects drift (target changed vs expected).
- Writes are strings; content written with `newline="\n"` on Windows.
- Extra keys are tolerated by inspect but non-finite values (NaN) are rejected
  (strict JSON; `allow_nan=False`).

## Lifecycle

```text
plan = inspect_operation(vault, operation)          # approval = hash(vault, operation, "reduced")
prepare_operation(vault, operation, plan["approval_sha256"])   # recheck + before-images + write.lock
# orchestrator writes files (Hermes write_file/patch or pathlib with newline="\n")
verify_operation(vault, operation, approval)        # after-hash verify, marks complete, releases lock
rollback_operation(vault, operation, approval)      # restores before-images in reverse order
```

- `verify`/`rollback` take the **original operation + approval as authority
  inputs** (not just the id) — runtime JSON under `.vault-meta` is untrusted
  and cross-validated against them.
- Approval binding: `approval_sha256` must equal the hash of the exact
  operation; reuse the emitted value unchanged.

## Runtime layout

```text
.vault-meta/hermes-windows/
├── write.lock/owner.json        # cooperative single-writer lock (dir-lock)
└── operations/<operation_id>/
    ├── manifest.json            # schema, state: prepared|complete|rolled-back
    ├── operation.json           # the exact reviewed operation
    └── before/                  # byte-for-byte before-images
```

Lock release is atomic: rename `write.lock` → `.released-*`, verify only
`owner.json` present, unlink, rmdir — never recursive delete (junction-safe).
If release fails, the manifest state is reverted to `prepared` so the
operation stays retriable.

## Rollback semantics (critical)

Rollback restores a target ONLY when its current content equals
`before_sha256` or `after_sha256`. Any other content → `ConcurrentDriftError`,
lock retained, manifest stays `prepared`. This is by design ("refuses
unexplained drift"). To roll back after a bad external write: first restore the
file to the known `after` content, then rollback succeeds.

## Init / adopt plan conversion (the convergence trick)

`python -B scripts/claude-obsidian.py init|adopt <vault> --generated-at <ISO>
--operation-id <id>` prints a dry-run plan whose `operation` field is already a
transaction-shaped object:

```json
{"schema": "claude-obsidian.transaction.v1", "operation_type": "setup|migration",
 "operation_id": "...", "expected_hashes": {...},
 "writes": [{"content": "...", "mode": "create", "path": "...", "sha256": "..."}]}
```

Convert to a guard operation by keeping `path` + `content` (drop `mode` and
`sha256`), then guard-apply. The upstream reviewed plan hash is NOT the guard
approval — treat them as separate review artifacts.

## Errors

- `OperationValidationError` — malformed op, unsafe/aliased/protected path
  (`.git`, `.vault-meta/hermes-windows`), bad JSON, size limits.
- `ConcurrentDriftError` — target content differs from expected/after.
- `CooperativeLockError` — another Hermes writer holds `write.lock`.

## Hardening notes (from review rounds)

- Path confinement reuses upstream validators (`_safe_vault_path`,
  `_assert_portable_write_path`, `_assert_no_existing_portable_alias`,
  `_safe_directory`); every lifecycle entry point revalidates the runtime
  chain (junction swaps are rejected).
- Reads use bounded descriptor helpers (`lstat`/`os.open`/`fstat` + identity
  check + chunked read) for targets, runtime JSON, and checkpoints.
- Resource limits reuse upstream constants: file 64 MiB, total 128 MiB, writes
  1024, runtime JSON 8 MiB.
