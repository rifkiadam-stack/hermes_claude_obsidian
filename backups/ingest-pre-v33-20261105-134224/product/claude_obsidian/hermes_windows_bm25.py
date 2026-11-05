"""Index-only native Windows publisher for a large, disposable BM25 cache.

This is deliberately NOT a general transaction writer. It has one fixed target,
uses the same cooperative Hermes lock as canonical writes, and publishes one
bounded derived file by atomic replacement. Windows path checks are point-in-
time, not POSIX directory-descriptor confinement. A crash may leave a staged
file/lock; recovery may restore only this disposable index from a hash-checked
before-image, never canonical files.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import time
import uuid
from pathlib import Path
from typing import Any

from .hermes_windows_write import (
    ConcurrentDriftError,
    CooperativeLockError,
    OperationValidationError,
    _atomic_json,
    _bounded_file_bytes,
    _bounded_target,
    _current_hash,
    _load_json,
    _pid_is_running,
    _portable_path_key,
    _release_lock,
    bounded_target_hash,
    sha256_bytes,
)
from .paths import assert_unaliased_directory, is_name_surrogate
from .transaction import MAX_TRANSACTION_FILE_BYTES, MAX_TRANSACTION_WRITES, TransactionValidationError, _safe_directory

INDEX_REL = ".vault-meta/bm25/index.json"
SCHEMA = "hermes-windows-bm25-index-v1"


def _vault(root: str | Path) -> Path:
    vault = Path(root).resolve(strict=True)
    try:
        assert_unaliased_directory(vault)
    except OSError as exc:
        raise OperationValidationError(f"unsafe vault directory: {exc}") from exc
    return vault


def _metadata(vault: Path, data: bytes, expected_hash: str | None,
              preconditions: dict[str, str]) -> dict[str, Any]:
    if not isinstance(data, bytes) or len(data) > MAX_TRANSACTION_FILE_BYTES:
        raise OperationValidationError("BM25 index must be bounded bytes")
    if expected_hash is not None and (not isinstance(expected_hash, str) or
                                      len(expected_hash) != 71 or not expected_hash.startswith("sha256:") or
                                      any(ch not in "0123456789abcdef" for ch in expected_hash[7:])):
        raise OperationValidationError("invalid expected BM25 index hash")
    if not isinstance(preconditions, dict) or len(preconditions) > MAX_TRANSACTION_WRITES:
        raise OperationValidationError("invalid BM25 read preconditions")
    seen = {_portable_path_key(vault, INDEX_REL)}
    for relative, expected in preconditions.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or len(expected) != 71 or not expected.startswith("sha256:") or any(ch not in "0123456789abcdef" for ch in expected[7:]):
            raise OperationValidationError("invalid BM25 read precondition")
        key = _portable_path_key(vault, relative)
        if key in seen:
            raise OperationValidationError("BM25 read preconditions overlap or alias")
        seen.add(key)
        _bounded_target(vault, relative)
    return {"schema": SCHEMA, "target": INDEX_REL,
            "before_sha256": expected_hash, "after_sha256": sha256_bytes(data),
            "length": len(data), "read_preconditions": dict(preconditions)}


def _approval(vault: Path, metadata: dict[str, Any]) -> str:
    raw = json.dumps({"vault": str(vault), "metadata": metadata},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    return sha256_bytes(raw)


def _check_state(vault: Path, metadata: dict[str, Any]) -> None:
    current = _current_hash(_bounded_target(vault, INDEX_REL))
    if current != metadata["before_sha256"]:
        raise ConcurrentDriftError("BM25 index changed since review")
    for relative, expected in metadata["read_preconditions"].items():
        if bounded_target_hash(vault, relative) != expected:
            raise ConcurrentDriftError(f"BM25 source/chunk changed: {relative}")


def inspect_large_index(vault_root: str | Path, data: bytes,
                        expected_hash: str | None,
                        read_preconditions: dict[str, str]) -> dict[str, Any]:
    """Review exact bytes, target hash and source snapshot without writing."""
    vault = _vault(vault_root)
    metadata = _metadata(vault, data, expected_hash, read_preconditions)
    _check_state(vault, metadata)
    return {"target": INDEX_REL, "after_sha256": metadata["after_sha256"],
            "approval_sha256": _approval(vault, metadata),
            "guarantee_level": "reduced-single-derived-file"}


def _stage_index(parent: Path, name: str, data: bytes) -> Path:
    """Exclusive, bounded stage in the index directory (never the vault root)."""
    staged = parent / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(staged, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            view = memoryview(data)
            for start in range(0, len(view), 1024 * 1024):
                stream.write(view[start:start + 1024 * 1024])
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except Exception:
        # Assignment at the caller has not happened yet; clean our own partial
        # stage here. A real process crash is handled by dead-owner recovery.
        _remove_stage(staged)
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def _remove_stage(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_name_surrogate(info) or not stat.S_ISREG(info.st_mode):
        raise CooperativeLockError(f"unexpected BM25 stage object: {path}")
    path.unlink()


def _restore_before(vault: Path, backup: Path, before_hash: str | None) -> None:
    target = _bounded_target(vault, INDEX_REL)
    if before_hash is None:
        _remove_stage(target)
    else:
        data = _bounded_file_bytes(backup, limit=MAX_TRANSACTION_FILE_BYTES,
                                   label="BM25 before-image")
        if sha256_bytes(data) != before_hash:
            raise OperationValidationError("BM25 before-image hash mismatch")
        os.replace(backup, target)
    if _current_hash(_bounded_target(vault, INDEX_REL)) != before_hash:
        raise ConcurrentDriftError("BM25 before-image restore failed")


def publish_large_index(vault_root: str | Path, data: bytes,
                        expected_hash: str | None,
                        read_preconditions: dict[str, str],
                        approved_plan_sha256: str) -> dict[str, Any]:
    """Publish only the reviewed BM25 index under the shared Hermes lock."""
    vault = _vault(vault_root)
    metadata = _metadata(vault, data, expected_hash, read_preconditions)
    if approved_plan_sha256 != _approval(vault, metadata):
        raise OperationValidationError("BM25 index approval does not match exact bytes")
    _check_state(vault, metadata)
    try:
        runtime = _safe_directory(vault, ".vault-meta/hermes-windows", create=True)
        parent = _safe_directory(vault, ".vault-meta/bm25", create=True)
    except (TransactionValidationError, OSError) as exc:
        raise OperationValidationError(f"unsafe BM25 runtime directory: {exc}") from exc
    lock = runtime / "write.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise CooperativeLockError("another Hermes writer holds write.lock") from exc
    operation_id = uuid.uuid4().hex[:12]
    stage_name = f".index-{operation_id}.tmp"
    backup_name = f".index-{operation_id}.before"
    owner = {"schema": SCHEMA, "operation_id": operation_id,
             "approval_sha256": approved_plan_sha256, "metadata": metadata,
             "stage_name": stage_name, "backup_name": backup_name,
             "pid": os.getpid(), "host": socket.gethostname(),
             "started_epoch": time.time()}
    staged: Path | None = None
    backup: Path | None = None
    committed = False
    try:
        try:
            _atomic_json(lock / "owner.json", owner)
        except Exception:
            # The shared JSON helper can fail after creating its temporary
            # file. Remove only its known regular stage before retiring lock.
            _remove_stage(lock / f".owner.json.{os.getpid()}.tmp")
            raise
        _check_state(vault, metadata)
        before = (_bounded_file_bytes(_bounded_target(vault, INDEX_REL),
                                      limit=MAX_TRANSACTION_FILE_BYTES,
                                      label="BM25 before-image")
                  if expected_hash is not None else b"")
        if expected_hash is not None and sha256_bytes(before) != expected_hash:
            raise ConcurrentDriftError("BM25 before-image changed")
        backup = _stage_index(parent, backup_name, before)
        if expected_hash is not None and sha256_bytes(_bounded_file_bytes(
                backup, limit=MAX_TRANSACTION_FILE_BYTES,
                label="BM25 staged before-image")) != expected_hash:
            raise OperationValidationError("BM25 staged before-image mismatch")
        _check_state(vault, metadata)
        staged = _stage_index(parent, stage_name, data)
        if sha256_bytes(_bounded_file_bytes(staged, limit=MAX_TRANSACTION_FILE_BYTES, label="staged BM25 index")) != metadata["after_sha256"]:
            raise OperationValidationError("staged BM25 index hash mismatch")
        _check_state(vault, metadata)
        _safe_directory(vault, ".vault-meta/bm25", create=False)
        os.replace(staged, _bounded_target(vault, INDEX_REL))
        committed = True
        if _current_hash(_bounded_target(vault, INDEX_REL)) != metadata["after_sha256"]:
            # A pathname stage may have changed after verification. Restore the
            # recoverable before-image instead of leaving unapproved bytes live.
            _restore_before(vault, backup, expected_hash)
            _remove_stage(backup)
            _release_lock(lock, expected_owner=owner)
            raise ConcurrentDriftError("published BM25 index differed; old index restored")
        _remove_stage(backup)
        _release_lock(lock, expected_owner=owner)
        return {"state": "complete", "target": INDEX_REL,
                "after_sha256": metadata["after_sha256"], "operation_id": operation_id}
    except Exception:
        # A pre-replace failure leaves the old target untouched. After replace,
        # retain lock/backup for dead-owner recovery if restoration did not finish.
        if not committed:
            if staged is not None:
                _remove_stage(staged)
            if backup is not None:
                _remove_stage(backup)
            if lock.exists():
                _release_lock(lock, expected_owner=owner if (lock / "owner.json").exists() else None)
        raise


def recover_large_index_lock(vault_root: str | Path) -> dict[str, Any]:
    """Retire a dead dedicated owner only if the index is old OR fully new."""
    vault = _vault(vault_root)
    try:
        lock = _safe_directory(vault, ".vault-meta/hermes-windows/write.lock", create=False)
        owner = _load_json(lock / "owner.json")
        parent = _safe_directory(vault, ".vault-meta/bm25", create=False)
    except (TransactionValidationError, OSError) as exc:
        raise CooperativeLockError(f"unsafe BM25 recovery state: {exc}") from exc
    metadata = owner.get("metadata")
    opid = owner.get("operation_id")
    if owner.get("schema") != SCHEMA or not isinstance(metadata, dict) or metadata.get("schema") != SCHEMA or metadata.get("target") != INDEX_REL or not isinstance(opid, str) or len(opid) != 12 or any(c not in "0123456789abcdef" for c in opid):
        raise CooperativeLockError("invalid BM25 lock authority")
    if owner.get("approval_sha256") != _approval(vault, metadata):
        raise CooperativeLockError("BM25 lock approval differs from metadata")
    if owner.get("host") != socket.gethostname() or _pid_is_running(owner.get("pid")):
        raise CooperativeLockError("BM25 lock owner is remote or still active")
    if owner.get("stage_name") != f".index-{opid}.tmp" or owner.get("backup_name") != f".index-{opid}.before":
        raise CooperativeLockError("invalid BM25 stage/backup names")
    staged = parent / owner["stage_name"]
    backup = parent / owner["backup_name"]
    current = _current_hash(_bounded_target(vault, INDEX_REL))
    if current not in {metadata.get("before_sha256"), metadata.get("after_sha256")}:
        # A missing candidate stage and a hash-verified before-image indicate
        # interruption after replacement. Unknown external drift otherwise
        # remains fail-closed; never silently bless an unapproved index.
        if staged.exists():
            raise ConcurrentDriftError("BM25 index drifted before publication")
        try:
            before_bytes = _bounded_file_bytes(backup, limit=MAX_TRANSACTION_FILE_BYTES,
                                               label="BM25 recovery before-image")
        except OperationValidationError as exc:
            raise CooperativeLockError(f"BM25 recovery backup missing/unsafe: {exc}") from exc
        expected = metadata.get("before_sha256")
        if (expected is None and before_bytes != b"") or (expected is not None and sha256_bytes(before_bytes) != expected):
            raise CooperativeLockError("BM25 recovery before-image hash mismatch")
        _restore_before(vault, backup, expected)
        current = expected
    _remove_stage(staged)
    _remove_stage(backup)
    _release_lock(lock, expected_owner=owner)
    return {"state": "recovered", "index_sha256": current}
