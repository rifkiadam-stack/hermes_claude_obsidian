"""Reduced-guarantee guard for Hermes-managed writes on native Windows.

This module does not claim equivalence with the POSIX descriptor-pinned
transaction engine.  It provides bounded paths, expected-content checks, and a
review hash for a single Hermes orchestrator.  Non-cooperating writers such as
Obsidian do not honor its cooperative policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import stat
import time
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .json_utils import strict_json_loads
from .paths import is_name_surrogate, is_same_object, read_open_flags
from .transaction import (
    MAX_TRANSACTION_FILE_BYTES,
    MAX_TRANSACTION_RUNTIME_JSON_BYTES,
    MAX_TRANSACTION_TOTAL_BYTES,
    MAX_TRANSACTION_WRITES,
    TransactionValidationError,
    _assert_portable_write_path,
    _assert_no_existing_portable_alias,
    _portable_name_key,
    _safe_directory,
    _safe_vault_path,
)

OPERATION_SCHEMA = "hermes-native-windows-reduced-v1"
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class HermesWindowsWriteError(RuntimeError):
    """Base error for the reduced-guarantee write guard."""


class OperationValidationError(HermesWindowsWriteError):
    """The requested operation is malformed or outside the selected vault."""


class ConcurrentDriftError(HermesWindowsWriteError):
    """A target changed after the orchestrator recorded its expected content."""


class CooperativeLockError(HermesWindowsWriteError):
    """Another Hermes writer owns the cooperative vault lock."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _bounded_file_bytes(path: Path, *, limit: int, label: str) -> bytes:
    """Read one stable regular file without allocating beyond ``limit``."""

    try:
        before = path.lstat()
        if is_name_surrogate(before) or not stat.S_ISREG(before.st_mode):
            raise OperationValidationError(f"{label} is not a regular file: {path}")
        if before.st_size > limit:
            raise OperationValidationError(f"{label} exceeds byte limit: {path}")
        descriptor = os.open(path, read_open_flags())
    except OperationValidationError:
        raise
    except OSError as exc:
        raise OperationValidationError(f"cannot open {label}: {path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not is_same_object(before, opened)
            or opened.st_size > limit
        ):
            raise OperationValidationError(f"{label} changed before read: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > limit:
                raise OperationValidationError(f"{label} exceeds byte limit: {path}")
        after = os.fstat(descriptor)
        if not is_same_object(opened, after) or after.st_size != total:
            raise OperationValidationError(f"{label} changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validated_operation_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is None
        or value in {".", ".."}
    ):
        raise OperationValidationError("operation_id is not a portable runtime name")
    try:
        _assert_portable_write_path(value)
    except TransactionValidationError as exc:
        raise OperationValidationError(
            f"operation_id is not a portable runtime name: {exc}"
        ) from exc
    return value


def _bounded_target(vault: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise OperationValidationError("write path must be a non-empty string")
    try:
        normalized, target = _safe_vault_path(vault, relative)
        _assert_portable_write_path(normalized)
        _assert_no_existing_portable_alias(vault, normalized)
    except TransactionValidationError as exc:
        raise OperationValidationError(f"unsafe write path: {relative}: {exc}") from exc
    parts = tuple(_portable_name_key(part) for part in PurePosixPath(normalized).parts)
    if parts and parts[0] == _portable_name_key(".git"):
        raise OperationValidationError(f"protected Git namespace: {relative}")
    runtime_prefix = (
        _portable_name_key(".vault-meta"),
        _portable_name_key("hermes-windows"),
    )
    if parts[:2] == runtime_prefix:
        raise OperationValidationError(f"protected Hermes runtime namespace: {relative}")
    return target


def _portable_path_key(vault: Path, relative: str) -> tuple[str, ...]:
    try:
        normalized, _target = _safe_vault_path(vault, relative)
    except TransactionValidationError as exc:
        raise OperationValidationError(f"unsafe write path: {relative}: {exc}") from exc
    return tuple(_portable_name_key(part) for part in PurePosixPath(normalized).parts)


def _current_hash(target: Path) -> str | None:
    if not target.exists():
        return None
    return sha256_bytes(
        _bounded_file_bytes(
            target, limit=MAX_TRANSACTION_FILE_BYTES, label="target"
        )
    )


def _canonical_operation(operation: dict[str, Any]) -> bytes:
    return json.dumps(
        operation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _approval_sha256(vault: Path, operation: dict[str, Any]) -> str:
    payload = {
        "vault": str(vault.resolve(strict=True)),
        "operation": operation,
        "guarantee_level": "reduced",
    }
    return sha256_bytes(_canonical_operation(payload))


def inspect_operation(vault_root: str | Path, operation: dict[str, Any]) -> dict[str, Any]:
    """Validate scope/preconditions and return a review-bound reduced plan."""

    vault = Path(vault_root)
    if not vault.is_dir():
        raise OperationValidationError(f"vault is not a directory: {vault}")
    if operation.get("schema") != OPERATION_SCHEMA:
        raise OperationValidationError("unsupported Hermes Windows operation schema")
    operation_id = _validated_operation_id(operation.get("operation_id"))
    expected = operation.get("expected_hashes")
    writes = operation.get("writes")
    if not isinstance(expected, dict) or not isinstance(writes, list) or not writes:
        raise OperationValidationError("expected_hashes and non-empty writes are required")
    if len(writes) > MAX_TRANSACTION_WRITES:
        raise OperationValidationError("operation contains too many writes")
    if any(not isinstance(path, str) for path in expected):
        raise OperationValidationError("expected hash paths must be strings")

    changed_paths: list[str] = []
    seen: set[tuple[str, ...]] = set()
    total_content_bytes = 0
    for write in writes:
        if not isinstance(write, dict):
            raise OperationValidationError("each write must be an object")
        relative = write.get("path")
        content = write.get("content")
        if not isinstance(relative, str) or not isinstance(content, str):
            raise OperationValidationError("each write needs string path and content")
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_TRANSACTION_FILE_BYTES:
            raise OperationValidationError(f"write content is too large: {relative}")
        total_content_bytes += len(content_bytes)
        if total_content_bytes > MAX_TRANSACTION_TOTAL_BYTES:
            raise OperationValidationError("operation content exceeds total byte limit")
        portable_key = _portable_path_key(vault, relative)
        if portable_key in seen:
            raise OperationValidationError(f"duplicate write path: {relative}")
        seen.add(portable_key)
        if relative not in expected:
            raise OperationValidationError(f"missing expected hash: {relative}")
        expected_hash = expected[relative]
        if expected_hash is not None and not (
            isinstance(expected_hash, str) and _HASH_RE.fullmatch(expected_hash)
        ):
            raise OperationValidationError(f"invalid expected hash: {relative}")
        current = _current_hash(_bounded_target(vault, relative))
        if current != expected_hash:
            raise ConcurrentDriftError(
                f"target changed: {relative}; expected {expected_hash}, found {current}"
            )
        changed_paths.append(relative)

    expected_keys: dict[tuple[str, ...], str] = {}
    for path in expected:
        key = _portable_path_key(vault, path)
        if key in expected_keys:
            raise OperationValidationError(
                f"expected_hashes contains portable path aliases: "
                f"{expected_keys[key]} and {path}"
            )
        expected_keys[key] = path
    extra = set(expected_keys) - seen
    if extra:
        raise OperationValidationError(
            "expected_hashes contains paths not written: "
            + ", ".join(sorted(expected_keys[key] for key in extra))
        )

    try:
        operation_bytes = _canonical_operation(operation)
    except (TypeError, ValueError) as exc:
        raise OperationValidationError(f"operation is not strict JSON: {exc}") from exc
    if len(operation_bytes) > MAX_TRANSACTION_RUNTIME_JSON_BYTES:
        raise OperationValidationError("operation JSON exceeds runtime byte limit")
    approval = _approval_sha256(vault, operation)
    return {
        "valid": True,
        "schema": OPERATION_SCHEMA,
        "operation_id": operation_id,
        "changed_paths": changed_paths,
        "approval_sha256": approval,
        "guarantee_level": "reduced",
        "upstream_transaction_equivalent": False,
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _release_lock(lock: Path) -> None:
    """Retire a cooperative lock without recursive deletion."""

    retired = lock.with_name(f".released-{os.getpid()}-{time.time_ns()}")
    try:
        os.replace(lock, retired)
    except OSError as exc:
        raise CooperativeLockError(f"cannot retire write.lock: {exc}") from exc
    try:
        metadata = retired.lstat()
        if is_name_surrogate(metadata):
            retired.rmdir()
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise CooperativeLockError("retired write.lock is not a directory")
        owner_seen = False
        for entry in retired.iterdir():
            if entry.name != "owner.json" or owner_seen:
                raise CooperativeLockError("write.lock contains unexpected entries")
            owner_seen = True
        owner = retired / "owner.json"
        if owner.exists():
            if owner.is_symlink() or not owner.is_file():
                raise CooperativeLockError("write.lock owner is not a regular file")
            owner.unlink()
        retired.rmdir()
    except Exception:
        if retired.exists() and not lock.exists():
            try:
                os.replace(retired, lock)
            except OSError:
                pass
        raise


def _finalize_manifest_state(
    manifest_path: Path,
    manifest: dict[str, Any],
    lock: Path,
    *,
    state: str,
    epoch_field: str,
) -> dict[str, Any]:
    original = dict(manifest)
    updated = dict(manifest)
    updated["state"] = state
    updated[epoch_field] = time.time()
    _atomic_json(manifest_path, updated)
    try:
        _release_lock(lock)
    except Exception:
        _atomic_json(manifest_path, original)
        raise
    return updated


def prepare_operation(
    vault_root: str | Path,
    operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Recheck a reviewed operation and checkpoint targets under a cooperative lock."""

    vault = Path(vault_root).resolve(strict=True)
    plan = inspect_operation(vault, operation)
    if approved_plan_sha256 != plan["approval_sha256"]:
        raise ConcurrentDriftError("reviewed plan no longer matches this operation")
    operation_id = _validated_operation_id(plan["operation_id"])

    try:
        runtime = _safe_directory(
            vault, ".vault-meta/hermes-windows", create=True
        )
    except TransactionValidationError as exc:
        raise OperationValidationError(f"unsafe Hermes runtime path: {exc}") from exc
    lock = runtime / "write.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise CooperativeLockError("another Hermes writer holds write.lock") from exc

    try:
        operations_root = _safe_directory(
            vault, ".vault-meta/hermes-windows/operations", create=True
        )
    except TransactionValidationError as exc:
        if lock.exists():
            _release_lock(lock)
        raise OperationValidationError(f"unsafe operations runtime path: {exc}") from exc

    operation_root = operations_root / operation_id
    try:
        if operation_root.exists():
            raise OperationValidationError(
                f"operation checkpoint already exists: {operation_id}"
            )
        try:
            operation_root = _safe_directory(
                vault,
                f".vault-meta/hermes-windows/operations/{operation_id}",
                create=True,
            )
        except TransactionValidationError as exc:
            raise OperationValidationError(
                f"unsafe operation runtime path: {exc}"
            ) from exc
        before_root = operation_root / "before"
        manifest_targets: list[dict[str, Any]] = []
        total_checkpoint_bytes = 0
        for write in operation["writes"]:
            relative = write["path"]
            target = _bounded_target(vault, relative)
            current = _current_hash(target)
            expected = operation["expected_hashes"][relative]
            if current != expected:
                raise ConcurrentDriftError(
                    f"target changed while preparing: {relative}"
                )
            existed = current is not None
            if existed:
                source_size = target.stat().st_size
                if source_size > MAX_TRANSACTION_FILE_BYTES:
                    raise OperationValidationError(
                        f"checkpoint source exceeds per-file limit: {relative}"
                    )
                if total_checkpoint_bytes + source_size > MAX_TRANSACTION_TOTAL_BYTES:
                    raise OperationValidationError(
                        "checkpoint exceeds total byte limit"
                    )
                backup = before_root / Path(relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, backup)
                checkpoint_data = _bounded_file_bytes(
                    backup,
                    limit=MAX_TRANSACTION_FILE_BYTES,
                    label="completed checkpoint",
                )
                total_checkpoint_bytes += len(checkpoint_data)
                if total_checkpoint_bytes > MAX_TRANSACTION_TOTAL_BYTES:
                    raise OperationValidationError(
                        "completed checkpoints exceed total byte limit"
                    )
                if sha256_bytes(checkpoint_data) != current:
                    raise OperationValidationError(
                        f"checkpoint copy hash mismatch: {relative}"
                    )
                if _current_hash(target) != current:
                    raise ConcurrentDriftError(
                        f"target changed while checkpointing: {relative}"
                    )
            manifest_targets.append(
                {
                    "path": relative,
                    "before_exists": existed,
                    "before_sha256": current,
                    "after_sha256": sha256_bytes(write["content"].encode("utf-8")),
                }
            )
        manifest = {
            "schema": OPERATION_SCHEMA,
            "operation_id": operation_id,
            "state": "prepared",
            "approval_sha256": approved_plan_sha256,
            "guarantee_level": "reduced",
            "targets": manifest_targets,
        }
        _atomic_json(operation_root / "manifest.json", manifest)
        _atomic_json(operation_root / "operation.json", operation)
        _atomic_json(
            lock / "owner.json",
            {
                "schema": OPERATION_SCHEMA,
                "operation_id": operation_id,
                "approval_sha256": approved_plan_sha256,
                "operation_sha256": sha256_bytes(_canonical_operation(operation)),
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started_epoch": time.time(),
            },
        )
        return {
            "state": "prepared",
            "operation_id": operation_id,
            "approval_sha256": approved_plan_sha256,
            "checkpoint": str(operation_root),
            "changed_paths": plan["changed_paths"],
        }
    except Exception:
        if lock.exists():
            _release_lock(lock)
        raise


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = _bounded_file_bytes(
            path,
            limit=MAX_TRANSACTION_RUNTIME_JSON_BYTES,
            label="runtime state",
        )
        value = strict_json_loads(raw)
    except (OSError, ValueError) as exc:
        raise OperationValidationError(
            f"cannot read runtime state {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise OperationValidationError(f"runtime state is not an object: {path}")
    return value


def _runtime_paths(vault: Path, operation_id: str) -> tuple[Path, Path, Path]:
    try:
        runtime = _safe_directory(vault, ".vault-meta/hermes-windows", create=False)
        lock = _safe_directory(
            vault, ".vault-meta/hermes-windows/write.lock", create=False
        )
        operation_root = _safe_directory(
            vault,
            f".vault-meta/hermes-windows/operations/{operation_id}",
            create=False,
        )
    except TransactionValidationError as exc:
        raise OperationValidationError(f"unsafe Hermes runtime path: {exc}") from exc
    return runtime, lock, operation_root


def _load_prepared_state(
    vault: Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> tuple[Path, Path, dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(authority_operation, dict):
        raise OperationValidationError("authority operation must be an object")
    operation_id = _validated_operation_id(authority_operation.get("operation_id"))
    authority_approval = _approval_sha256(vault, authority_operation)
    if approved_plan_sha256 != authority_approval:
        raise OperationValidationError("authority approval does not match operation")
    _runtime, lock, operation_root = _runtime_paths(vault, operation_id)
    owner = _load_json(lock / "owner.json")
    manifest_path = operation_root / "manifest.json"
    manifest = _load_json(manifest_path)
    operation = _load_json(operation_root / "operation.json")
    if operation != authority_operation:
        raise OperationValidationError("checkpoint operation differs from authority input")

    if owner.get("schema") != OPERATION_SCHEMA:
        raise OperationValidationError("write.lock owner schema is invalid")
    if owner.get("operation_id") != operation_id:
        raise CooperativeLockError("write.lock belongs to another operation")
    if manifest.get("schema") != OPERATION_SCHEMA:
        raise OperationValidationError("manifest schema is invalid")
    if manifest.get("operation_id") != operation_id:
        raise OperationValidationError("manifest operation_id is invalid")
    if manifest.get("state") != "prepared":
        raise OperationValidationError("operation is not in prepared state")
    if operation.get("schema") != OPERATION_SCHEMA:
        raise OperationValidationError("checkpoint operation schema is invalid")
    if _validated_operation_id(operation.get("operation_id")) != operation_id:
        raise OperationValidationError("checkpoint operation_id is invalid")

    approval = _approval_sha256(vault, operation)
    operation_hash = sha256_bytes(_canonical_operation(operation))
    if manifest.get("approval_sha256") != approval:
        raise OperationValidationError("manifest approval does not match operation")
    if owner.get("approval_sha256") != approval:
        raise OperationValidationError("lock approval does not match operation")
    if owner.get("operation_sha256") != operation_hash:
        raise OperationValidationError("lock operation hash does not match operation")

    writes = operation.get("writes")
    expected_hashes = operation.get("expected_hashes")
    targets = manifest.get("targets")
    if not isinstance(writes, list) or not writes:
        raise OperationValidationError("checkpoint writes are invalid")
    if not isinstance(expected_hashes, dict) or not isinstance(targets, list):
        raise OperationValidationError("checkpoint targets are invalid")
    if len(targets) != len(writes):
        raise OperationValidationError("manifest target count does not match operation")

    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for write, target_record in zip(writes, targets):
        if not isinstance(write, dict) or not isinstance(target_record, dict):
            raise OperationValidationError("invalid checkpoint target record")
        relative = write.get("path")
        content = write.get("content")
        if not isinstance(relative, str) or not isinstance(content, str):
            raise OperationValidationError("invalid checkpoint write")
        key = _portable_path_key(vault, relative)
        if key in seen:
            raise OperationValidationError("checkpoint contains portable path aliases")
        seen.add(key)
        before_hash = expected_hashes.get(relative)
        expected_record = {
            "path": relative,
            "before_exists": before_hash is not None,
            "before_sha256": before_hash,
            "after_sha256": sha256_bytes(content.encode("utf-8")),
        }
        if target_record != expected_record:
            raise OperationValidationError(
                f"manifest target does not match operation: {relative}"
            )
        _bounded_target(vault, relative)
        validated.append(target_record)
    if set(expected_hashes) != {write["path"] for write in writes}:
        raise OperationValidationError("checkpoint expected_hashes do not match writes")
    return lock, manifest_path, manifest, validated


def verify_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Verify externally applied writes and complete the cooperative operation."""

    vault = Path(vault_root).resolve(strict=True)
    lock, manifest_path, manifest, targets = _load_prepared_state(
        vault, authority_operation, approved_plan_sha256
    )
    operation_id = _validated_operation_id(authority_operation.get("operation_id"))
    for target_record in targets:
        relative = target_record.get("path")
        expected_after = target_record.get("after_sha256")
        if not isinstance(relative, str) or not isinstance(expected_after, str):
            raise OperationValidationError("invalid target path/hash in manifest")
        current = _current_hash(_bounded_target(vault, relative))
        if current != expected_after:
            raise ConcurrentDriftError(
                f"written target failed verification: {relative}; "
                f"expected {expected_after}, found {current}"
            )
    manifest = _finalize_manifest_state(
        manifest_path,
        manifest,
        lock,
        state="complete",
        epoch_field="verified_epoch",
    )
    return {
        "state": "complete",
        "operation_id": operation_id,
        "changed_paths": [item["path"] for item in manifest["targets"]],
    }


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def rollback_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Restore a prepared operation when targets have no unexplained drift."""

    vault = Path(vault_root).resolve(strict=True)
    lock, manifest_path, manifest, targets = _load_prepared_state(
        vault, authority_operation, approved_plan_sha256
    )
    operation_id = _validated_operation_id(authority_operation.get("operation_id"))
    operation_root = manifest_path.parent
    backup_data: dict[str, bytes] = {}
    total_backup_bytes = 0
    for target_record in targets:
        if not isinstance(target_record, dict):
            raise OperationValidationError("invalid target record in manifest")
        relative = target_record.get("path")
        before_hash = target_record.get("before_sha256")
        after_hash = target_record.get("after_sha256")
        if not isinstance(relative, str) or not isinstance(after_hash, str):
            raise OperationValidationError("invalid rollback target record")
        current = _current_hash(_bounded_target(vault, relative))
        if current not in {before_hash, after_hash}:
            raise ConcurrentDriftError(
                f"rollback refuses unexplained drift: {relative}; found {current}"
            )
        if target_record.get("before_exists"):
            backup = operation_root / "before" / Path(relative)
            if backup.is_symlink() or not backup.is_file():
                raise OperationValidationError(
                    f"checkpoint is not a regular file: {relative}"
                )
            backup_size = backup.stat().st_size
            if backup_size > MAX_TRANSACTION_FILE_BYTES:
                raise OperationValidationError(
                    f"checkpoint exceeds per-file limit: {relative}"
                )
            if total_backup_bytes + backup_size > MAX_TRANSACTION_TOTAL_BYTES:
                raise OperationValidationError(
                    "checkpoint exceeds aggregate backup limit"
                )
            data = _bounded_file_bytes(
                backup,
                limit=MAX_TRANSACTION_FILE_BYTES,
                label="rollback checkpoint",
            )
            total_backup_bytes += len(data)
            if total_backup_bytes > MAX_TRANSACTION_TOTAL_BYTES:
                raise OperationValidationError(
                    "checkpoint exceeds aggregate backup limit"
                )
            if sha256_bytes(data) != before_hash:
                raise OperationValidationError(
                    f"checkpoint hash mismatch during rollback: {relative}"
                )
            backup_data[relative] = data

    restored: list[str] = []
    for target_record in reversed(targets):
        relative = target_record["path"]
        target = _bounded_target(vault, relative)
        if target_record.get("before_exists"):
            _atomic_bytes(target, backup_data[relative])
        elif target.exists():
            if not target.is_file() or target.is_symlink():
                raise OperationValidationError(
                    f"rollback target is not a regular file: {relative}"
                )
            target.unlink()
        restored.append(relative)

    manifest = _finalize_manifest_state(
        manifest_path,
        manifest,
        lock,
        state="rolled-back",
        epoch_field="rolled_back_epoch",
    )
    return {
        "state": "rolled-back",
        "operation_id": operation_id,
        "restored_paths": restored,
    }
