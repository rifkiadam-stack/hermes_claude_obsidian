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
from .paths import assert_unaliased_directory, is_name_surrogate, is_same_object, read_open_flags
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


def bounded_target_bytes(
    vault_root: str | Path, relative: str
) -> bytes | None:
    """Read one confined regular target with the transaction file-size bound."""

    vault = Path(vault_root).resolve(strict=True)
    target = _bounded_target(vault, relative)
    if not target.exists():
        return None
    return _bounded_file_bytes(
        target, limit=MAX_TRANSACTION_FILE_BYTES, label="target"
    )


def bounded_target_hash(vault_root: str | Path, relative: str) -> str | None:
    """Hash one confined target without following an unsafe parent chain."""

    data = bounded_target_bytes(vault_root, relative)
    return sha256_bytes(data) if data is not None else None


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


def _validated_delete_parts(vault: Path, relative: str) -> tuple[str, ...]:
    """Confine deletes to staging files or generated BM25 chunk records."""

    normalized = PurePosixPath(relative.replace("\\", "/"))
    parts = normalized.parts
    staging_delete = (
        len(parts) == 2
        and parts[0] in {"inbox", "Clippings"}
        and normalized.name != ".gitkeep"
    )
    bm25_chunk_delete = (
        len(parts) == 4
        and parts[:2] == (".vault-meta", "chunks")
        and bool(parts[2])
        and re.fullmatch(r"chunk-\d{3,9}\.json", parts[3]) is not None
    )
    if not staging_delete and not bm25_chunk_delete:
        raise OperationValidationError(f"delete path is outside allowed scope: {relative}")
    try:
        assert_unaliased_directory(vault)
        current = vault
        for part in parts[:-1]:
            current /= part
            assert_unaliased_directory(current)
    except OSError as exc:
        raise OperationValidationError(
            f"delete parent path is aliased: {relative}: {exc}"
        ) from exc
    return parts


def inspect_operation(vault_root: str | Path, operation: dict[str, Any]) -> dict[str, Any]:
    """Validate scope/preconditions and return a review-bound reduced plan."""

    vault = Path(vault_root)
    if not vault.is_dir():
        raise OperationValidationError(f"vault is not a directory: {vault}")
    if operation.get("schema") != OPERATION_SCHEMA:
        raise OperationValidationError("unsupported Hermes Windows operation schema")
    operation_id = _validated_operation_id(operation.get("operation_id"))
    expected = operation.get("expected_hashes")
    read_preconditions = operation.get("read_preconditions", {})
    writes = operation.get("writes", [])
    deletes = operation.get("deletes", [])
    if not isinstance(expected, dict) or not isinstance(read_preconditions, dict) or not isinstance(writes, list) or not isinstance(deletes, list):
        raise OperationValidationError("expected_hashes, read_preconditions, writes, and deletes must have valid types")
    if not writes and not deletes:
        raise OperationValidationError("operation requires at least one write or delete")
    if len(writes) + len(deletes) > MAX_TRANSACTION_WRITES:
        raise OperationValidationError("operation contains too many mutations")
    if any(not isinstance(path, str) for path in expected):
        raise OperationValidationError("expected hash paths must be strings")
    if len(read_preconditions) > MAX_TRANSACTION_WRITES or any(not isinstance(path, str) for path in read_preconditions):
        raise OperationValidationError("invalid or excessive read preconditions")
    mutation_key_set: set[tuple[str, ...]] = set()
    for path in list(expected):
        mutation_key_set.add(_portable_path_key(vault, path))
    for path, expected_hash in read_preconditions.items():
        key = _portable_path_key(vault, path)
        if key in mutation_key_set:
            raise OperationValidationError(f"read precondition overlaps mutation path: {path}")
        if not isinstance(expected_hash, str) or _HASH_RE.fullmatch(expected_hash) is None:
            raise OperationValidationError(f"invalid read precondition hash: {path}")
        current = _current_hash(_bounded_target(vault, path))
        if current != expected_hash:
            raise ConcurrentDriftError(f"read precondition changed: {path}; expected {expected_hash}, found {current}")

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

    for relative in deletes:
        if not isinstance(relative, str):
            raise OperationValidationError("each delete path must be a string")
        _validated_delete_parts(vault, relative)
        portable_key = _portable_path_key(vault, relative)
        if portable_key in seen:
            raise OperationValidationError(f"duplicate mutation path: {relative}")
        seen.add(portable_key)
        if relative not in expected:
            raise OperationValidationError(f"missing expected hash: {relative}")
        expected_hash = expected[relative]
        if not isinstance(expected_hash, str) or _HASH_RE.fullmatch(expected_hash) is None:
            raise OperationValidationError(f"delete requires existing expected hash: {relative}")
        current = _current_hash(_bounded_target(vault, relative))
        if current != expected_hash:
            raise ConcurrentDriftError(
                f"delete target changed: {relative}; expected {expected_hash}, found {current}"
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
    mutation_paths = {write["path"] for write in writes} | set(deletes)
    extra = set(expected_keys) - {_portable_path_key(vault, path) for path in mutation_paths}
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


def _release_lock(
    lock: Path, *, expected_owner: dict[str, Any] | None = None
) -> None:
    """Retire a cooperative lock without recursive deletion."""

    retired = lock.with_name(f".released-{os.getpid()}-{time.time_ns()}")
    try:
        os.replace(lock, retired)
    except OSError as exc:
        raise CooperativeLockError(f"cannot retire write.lock: {exc}") from exc
    try:
        metadata = retired.lstat()
        if is_name_surrogate(metadata):
            if expected_owner is not None:
                raise CooperativeLockError(
                    "retired write.lock is a name surrogate; owner cannot be bound"
                )
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
            if expected_owner is not None and _load_json(owner) != expected_owner:
                raise CooperativeLockError("write.lock owner changed before release")
            owner.unlink()
        elif expected_owner is not None:
            raise CooperativeLockError("write.lock owner changed before release")
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
    expected_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original = dict(manifest)
    updated = dict(manifest)
    updated["state"] = state
    updated[epoch_field] = time.time()
    _atomic_json(manifest_path, updated)
    try:
        _release_lock(lock, expected_owner=expected_owner)
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
        mutations = [
            {"path": write["path"], "kind": "write", "content": write["content"]}
            for write in operation.get("writes", [])
        ] + [
            {"path": relative, "kind": "delete"}
            for relative in operation.get("deletes", [])
        ]
        for mutation in mutations:
            relative = mutation["path"]
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
                    "after_sha256": (
                        sha256_bytes(mutation["content"].encode("utf-8"))
                        if mutation["kind"] == "write"
                        else None
                    ),
                    "mutation_kind": mutation["kind"],
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
        owner = {
            "schema": OPERATION_SCHEMA,
            "operation_id": operation_id,
            "approval_sha256": approved_plan_sha256,
            "operation_sha256": sha256_bytes(_canonical_operation(operation)),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_epoch": time.time(),
        }
        _atomic_json(lock / "owner.json", owner)
        return {
            "state": "prepared",
            "operation_id": operation_id,
            "approval_sha256": approved_plan_sha256,
            "checkpoint": str(operation_root),
            "changed_paths": plan["changed_paths"],
            "owner": owner,
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
) -> tuple[Path, Path, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
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

    writes = operation.get("writes", [])
    deletes = operation.get("deletes", [])
    expected_hashes = operation.get("expected_hashes")
    targets = manifest.get("targets")
    if not isinstance(writes, list) or not isinstance(deletes, list) or (not writes and not deletes):
        raise OperationValidationError("checkpoint mutations are invalid")
    if not isinstance(expected_hashes, dict) or not isinstance(targets, list):
        raise OperationValidationError("checkpoint targets are invalid")
    mutations = [
        {"path": write.get("path"), "kind": "write", "content": write.get("content")}
        for write in writes if isinstance(write, dict)
    ] + [
        {"path": relative, "kind": "delete"}
        for relative in deletes
    ]
    if len(targets) != len(mutations):
        raise OperationValidationError("manifest target count does not match operation")

    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for mutation, target_record in zip(mutations, targets):
        if not isinstance(mutation, dict) or not isinstance(target_record, dict):
            raise OperationValidationError("invalid checkpoint target record")
        relative = mutation.get("path")
        kind = mutation.get("kind")
        content = mutation.get("content")
        if not isinstance(relative, str) or kind not in {"write", "delete"}:
            raise OperationValidationError("invalid checkpoint mutation")
        if kind == "write" and not isinstance(content, str):
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
            "after_sha256": (
                sha256_bytes(content.encode("utf-8")) if kind == "write" else None
            ),
            "mutation_kind": kind,
        }
        if target_record != expected_record:
            raise OperationValidationError(
                f"manifest target does not match operation: {relative}"
            )
        _bounded_target(vault, relative)
        validated.append(target_record)
    mutation_paths = {write["path"] for write in writes} | set(deletes)
    if set(expected_hashes) != mutation_paths:
        raise OperationValidationError("checkpoint expected_hashes do not match mutations")
    return lock, manifest_path, manifest, validated, owner


def _safe_delete_quarantine(operation_root: Path, relative: str) -> Path:
    """Create and validate the operation-local delete quarantine chain."""
    parts = PurePosixPath(relative).parts
    deleted_root = operation_root / "deleted"
    if deleted_root.exists():
        try:
            assert_unaliased_directory(deleted_root)
        except OSError as exc:
            raise OperationValidationError(f"delete quarantine is aliased: {exc}") from exc
    else:
        deleted_root.mkdir()
        assert_unaliased_directory(deleted_root)
    parent = deleted_root
    for part in parts[:-1]:
        parent /= part
        if parent.exists():
            try:
                assert_unaliased_directory(parent)
            except OSError as exc:
                raise OperationValidationError(
                    f"delete quarantine parent is aliased: {exc}"
                ) from exc
        else:
            parent.mkdir()
            assert_unaliased_directory(parent)
    return parent / parts[-1]


def apply_prepared_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Apply authority-bound writes/deletes while retaining deleted payloads."""
    vault = Path(vault_root).resolve(strict=True)
    _lock, manifest_path, _manifest, targets, _owner = _load_prepared_state(
        vault, authority_operation, approved_plan_sha256
    )
    operation_root = manifest_path.parent
    try:
        assert_unaliased_directory(vault)
        assert_unaliased_directory(vault / ".vault-meta")
        assert_unaliased_directory(vault / ".vault-meta" / "hermes-windows")
        assert_unaliased_directory(vault / ".vault-meta" / "hermes-windows" / "operations")
        assert_unaliased_directory(operation_root)
    except OSError as exc:
        raise OperationValidationError(f"delete runtime path is aliased: {exc}") from exc
    writes_by_path = {
        item["path"]: item["content"] for item in authority_operation.get("writes", [])
    }
    for relative, expected_hash in authority_operation.get("read_preconditions", {}).items():
        current = _current_hash(_bounded_target(vault, relative))
        if current != expected_hash:
            raise ConcurrentDriftError(
                f"read precondition changed before guarded apply: {relative}; expected {expected_hash}, found {current}"
            )
    written: list[str] = []
    deleted: list[str] = []
    for target_record in targets:
        relative = target_record["path"]
        target = _bounded_target(vault, relative)
        before_hash = target_record["before_sha256"]
        current = _current_hash(target)
        if current not in {before_hash, target_record["after_sha256"]}:
            raise ConcurrentDriftError(f"target changed before guarded apply: {relative}")
        if target_record["mutation_kind"] == "write":
            if current != target_record["after_sha256"]:
                _atomic_bytes(target, writes_by_path[relative].encode("utf-8"))
            written.append(relative)
        else:
            if current is None:
                deleted.append(relative)
                continue
            if current != before_hash:
                raise ConcurrentDriftError(f"delete target changed before guarded apply: {relative}")
            retired = _safe_delete_quarantine(operation_root, relative)
            if retired.exists():
                raise OperationValidationError(f"delete checkpoint already exists: {relative}")
            os.replace(target, retired)
            if _current_hash(retired) != before_hash or target.exists():
                raise OperationValidationError(f"delete move verification failed: {relative}")
            deleted.append(relative)
    return {
        "state": "applied",
        "operation_id": authority_operation["operation_id"],
        "written_paths": written,
        "deleted_paths": deleted,
    }


def execute_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Prepare, apply, and verify one reviewed operation without lifecycle gaps.

    Apply failures deliberately preserve the prepared checkpoint and lock so the
    caller can inspect, retry, recover, or roll back without hiding partial state.
    """

    prepared = prepare_operation(
        vault_root, authority_operation, approved_plan_sha256
    )
    apply_prepared_operation(
        vault_root, authority_operation, approved_plan_sha256
    )
    return verify_operation(
        vault_root,
        authority_operation,
        approved_plan_sha256,
        expected_owner=prepared["owner"],
    )


def _pid_is_running(pid: int) -> bool:
    """Probe a local owner PID without signalling it."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise OperationValidationError("write.lock owner pid is invalid")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        process_query_limited_information = 0x1000
        still_active = 259
        handle = open_process(process_query_limited_information, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
                return False
            if error == 5:  # ERROR_ACCESS_DENIED: fail closed as live.
                return True
            raise CooperativeLockError(
                f"cannot determine write.lock owner state: Windows error {error}"
            )
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                error = ctypes.get_last_error()
                raise CooperativeLockError(
                    f"cannot query write.lock owner state: Windows error {error}"
                )
            return exit_code.value == still_active
        finally:
            close_handle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        raise CooperativeLockError(f"cannot determine write.lock owner state: {exc}") from exc
    return True


def recover_prepared_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
) -> dict[str, Any]:
    """Finalize a fully-applied prepared operation whose local owner is dead.

    Verification remains authority-bound and checks every target against its
    expected after-image. Partial or drifted operations retain the lock and
    prepared state for explicit retry or rollback.
    """

    vault = Path(vault_root).resolve(strict=True)
    _lock, _manifest_path, _manifest, _targets, owner = _load_prepared_state(
        vault, authority_operation, approved_plan_sha256
    )
    if owner.get("host") != socket.gethostname():
        raise CooperativeLockError("cannot recover write.lock owned by another host")
    pid = owner.get("pid")
    if _pid_is_running(pid):
        raise CooperativeLockError("write.lock owner process is still running")
    return verify_operation(
        vault,
        authority_operation,
        approved_plan_sha256,
        expected_owner=owner,
    )


def verify_operation(
    vault_root: str | Path,
    authority_operation: dict[str, Any],
    approved_plan_sha256: str,
    *,
    expected_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify externally applied writes and complete the cooperative operation."""

    vault = Path(vault_root).resolve(strict=True)
    lock, manifest_path, manifest, targets, loaded_owner = _load_prepared_state(
        vault, authority_operation, approved_plan_sha256
    )
    if expected_owner is not None and loaded_owner != expected_owner:
        raise CooperativeLockError("write.lock owner changed before verification")
    operation_id = _validated_operation_id(authority_operation.get("operation_id"))
    for target_record in targets:
        relative = target_record.get("path")
        expected_after = target_record.get("after_sha256")
        kind = target_record.get("mutation_kind")
        if not isinstance(relative, str) or kind not in {"write", "delete"}:
            raise OperationValidationError("invalid target path/kind in manifest")
        if kind == "write" and not isinstance(expected_after, str):
            raise OperationValidationError("invalid write hash in manifest")
        if kind == "delete" and expected_after is not None:
            raise OperationValidationError("delete target must have null after hash")
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
        expected_owner=loaded_owner,
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
    lock, manifest_path, manifest, targets, loaded_owner = _load_prepared_state(
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
        kind = target_record.get("mutation_kind")
        if not isinstance(relative, str) or kind not in {"write", "delete"}:
            raise OperationValidationError("invalid rollback target record")
        if kind == "write" and not isinstance(after_hash, str):
            raise OperationValidationError("invalid rollback write hash")
        if kind == "delete" and after_hash is not None:
            raise OperationValidationError("invalid rollback delete hash")
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
        expected_owner=loaded_owner,
    )
    return {
        "state": "rolled-back",
        "operation_id": operation_id,
        "restored_paths": restored,
    }
