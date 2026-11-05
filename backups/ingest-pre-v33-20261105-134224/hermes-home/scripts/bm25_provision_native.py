#!/usr/bin/env python3
"""bm25_provision_native.py — BM25 provisioning adapter untuk native Windows.

Menggantikan `bm25-index.py build` (yang menolak native Windows karena
MutationLock POSIX). Alur:

1. Scan semua halaman wiki, generate chunk records (tier-3 synthetic prefix,
   TANPA LLM/egress) memakai logika `contextual-prefix.py` (read-only).
2. Rekonsiliasi chunk files di `.vault-meta/chunks/<address>/chunk-<idx>.json`
   lewat write guard `hermes_windows_write` (write + stale delete dalam satu
   bundle transaksi).
3. Build BM25 index dari snapshot record yang terverifikasi terhadap chunk disk,
   lalu tulis `.vault-meta/bm25/index.json` via writer khusus indeks besar.

Idempotent: chunk yang isinya identik dengan file yang ada TIDAK ditulis ulang;
chunk surplus dari halaman yang dihapus/dipendekkan dihapus secara guarded;
index hanya ditulis bila konten semantiknya berubah atau index belum ada.
Lock mati dipulihkan sebelum jalur no-op; lock hidup/ambigu menyebabkan gagal.

Usage:
  python bm25_provision_native.py --vault "G:/My Drive/hermes_obsidian" [--force]
  python bm25_provision_native.py --vault ... --status

Exit codes: 0 ok / 1 error / 2 unchanged (tidak ada yang ditulis).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

CORE = Path(r"C:\Users\rahmazaki.adam\AppData\Local\hermes\components\claude-obsidian-core")
SCRIPTS = CORE / "scripts"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SCRIPTS))

from claude_obsidian.hermes_windows_write import (  # noqa: E402
    CooperativeLockError,
    bounded_target_bytes,
    bounded_target_hash,
    execute_operation,
    inspect_operation,
    recover_prepared_operation,
    rollback_operation,
    _load_json,
)
from claude_obsidian.transaction import _safe_directory, TransactionValidationError  # noqa: E402
from claude_obsidian.paths import assert_unaliased_directory  # noqa: E402
from claude_obsidian.hermes_windows_bm25 import (  # noqa: E402
    SCHEMA as LARGE_INDEX_SCHEMA,
    inspect_large_index,
    publish_large_index,
    recover_large_index_lock,
)


CHUNK_FILENAME_RE = re.compile(r"^chunk-\d{3,9}\.json$")
PAGE_ADDRESS_RE = re.compile(r"^(?:[cl]-\d{6}|syn-[0-9a-f]{64})$")
MAX_CHUNK_INVENTORY_ENTRIES = 100_000
OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cp = load_module("contextual_prefix", SCRIPTS / "contextual-prefix.py")
bm = load_module("bm25_index", SCRIPTS / "bm25-index.py")


def generate_chunk_mutations(vault: Path, force: bool):
    """Generate desired chunk records and identify stale records.

    Return: (writes, deletes, total_chunks, skipped, records, source_hashes)
    writes = [{path, content}] — hanya chunk yang berubah/belum ada.
    deletes = [path] — chunk existing yang tidak ada di desired set.
    """
    cp.configure_vault(str(vault))
    pages = cp.collect_pages(None)  # semua halaman wiki
    writes = []
    desired_records = []
    source_hashes: dict[str, str] = {}
    seen_addresses: dict[str, str] = {}
    desired_paths: set[str] = set()
    total_chunks = 0
    skipped = 0
    tier = cp.pick_prefix_tier(force_synthetic=True, allow_egress=False)

    for page_path in pages:
        page_relative = page_path.relative_to(vault)
        page_rel = page_relative.as_posix()
        record_page_path = str(page_relative)
        body_bytes = bounded_target_bytes(vault, page_rel)
        if body_bytes is None:
            raise RuntimeError(f"source page disappeared: {page_rel}")
        source_hashes[page_rel] = "sha256:" + hashlib.sha256(body_bytes).hexdigest()
        body = body_bytes.decode("utf-8", errors="replace")
        fm, page_content = cp.parse_frontmatter(body)
        address = fm.get("address") or cp.derive_synthetic_address(page_path)
        if PAGE_ADDRESS_RE.fullmatch(address) is None:
            raise RuntimeError(f"invalid page address: {address}")
        prior = seen_addresses.get(address)
        if prior is not None:
            raise RuntimeError(
                f"address collision: {address}: {prior} and {page_rel}"
            )
        seen_addresses[address] = page_rel
        page_body_hash = cp.sha256(body)
        chunks = cp.chunk_body(page_content)

        for idx, raw in enumerate(chunks):
            body_hash = cp.sha256(raw)
            prefix, prefix_source = cp.generate_prefix(
                tier, fm, page_content, raw
            )
            prefix = (prefix or "").strip()[: cp.CONTEXT_PREFIX_MAX_CHARS].rstrip()
            contextualized = f"{prefix}\n\n{raw}" if prefix else raw
            record = {
                "schema_version": 1,
                "page_path": record_page_path,
                "page_address": address,
                "chunk_index": idx,
                "raw_text": raw,
                "contextualized_text": contextualized,
                "prefix": prefix or "",
                "prefix_source": prefix_source,
                "char_count": len(raw),
                "body_hash": body_hash,
                "page_body_hash": page_body_hash,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            total_chunks += 1
            rel = f".vault-meta/chunks/{address}/chunk-{idx:03d}.json"
            desired_paths.add(rel)
            chunk_id = f"{address}:{idx}"
            desired_records.append((chunk_id, rel, record))
            serialized_record = json.dumps(record, ensure_ascii=False, indent=2)

            if not force:
                try:
                    existing_bytes = bounded_target_bytes(vault, rel)
                    existing = (
                        json.loads(existing_bytes.decode("utf-8"))
                        if existing_bytes is not None
                        else None
                    )
                    same = (
                        all(
                            existing.get(key) == value
                            for key, value in record.items()
                            if key != "created_at"
                        )
                        if isinstance(existing, dict)
                        else False
                    )
                    if same:
                        skipped += 1
                        continue
                except (OSError, UnicodeError, ValueError):
                    pass
            writes.append({"path": rel, "content": serialized_record})

    chunks_root = vault / ".vault-meta" / "chunks"
    existing_paths: set[str] = set()
    try:
        chunks_root.lstat()
    except FileNotFoundError:
        pass
    else:
        try:
            assert_unaliased_directory(vault)
            assert_unaliased_directory(vault / ".vault-meta")
            assert_unaliased_directory(chunks_root)
        except OSError as exc:
            raise RuntimeError(f"unsafe chunk inventory root: {exc}") from exc
        entries_seen = 0
        for address_dir in chunks_root.iterdir():
            entries_seen += 1
            if entries_seen > MAX_CHUNK_INVENTORY_ENTRIES:
                raise RuntimeError("chunk inventory exceeds safety bound")
            try:
                assert_unaliased_directory(address_dir)
            except OSError as exc:
                raise RuntimeError(
                    f"unsafe chunk address directory: {address_dir}: {exc}"
                ) from exc
            for chunk_path in address_dir.iterdir():
                entries_seen += 1
                if entries_seen > MAX_CHUNK_INVENTORY_ENTRIES:
                    raise RuntimeError("chunk inventory exceeds safety bound")
                if CHUNK_FILENAME_RE.fullmatch(chunk_path.name) is None:
                    continue
                rel = chunk_path.relative_to(vault).as_posix()
                if bounded_target_hash(vault, rel) is not None:
                    existing_paths.add(rel)
    deletes = sorted(existing_paths - desired_paths)
    return (
        writes,
        deletes,
        total_chunks,
        skipped,
        desired_records,
        source_hashes,
    )


def build_index_from_records(records: list[tuple[str, str, dict]]) -> dict:
    """Build the BM25 index from the bounded in-memory desired snapshot."""

    docs = {}
    df: Counter[str] = Counter()
    postings = defaultdict(list)
    for chunk_id, rel_path, record in records:
        if chunk_id in docs:
            raise RuntimeError(f"duplicate chunk id: {chunk_id}")
        text = record.get("contextualized_text") or record.get("raw_text", "")
        try:
            tokens = bm.tokenize(text)
        except bm.TokenGrowthLimitError as exc:
            raise RuntimeError(f"token growth limit: {rel_path}: {exc}") from exc
        tf = Counter(tokens)
        docs[chunk_id] = {
            "path": str(Path(rel_path)),
            "dl": len(tokens),
            "body_hash": record.get("body_hash"),
            "page_body_hash": record.get("page_body_hash"),
        }
        for term, count in tf.items():
            df[term] += 1
            postings[term].append([chunk_id, count])
    avg_dl = (
        sum(document["dl"] for document in docs.values()) / len(docs)
        if docs
        else 0.0
    )
    vocab = {
        term: {"df": df[term], "postings": postings[term]}
        for term in sorted(df)
    }
    return {
        "schema_version": bm.INDEX_SCHEMA_VERSION,
        "params": {"k1": bm.K1, "b": bm.B},
        "doc_count": len(docs),
        "avg_dl": avg_dl,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vocab": vocab,
        "docs": docs,
    }


def index_semantically_equal(existing: dict, candidate: dict) -> bool:
    """Compare index content while ignoring its build timestamp."""

    left = dict(existing)
    right = dict(candidate)
    left.pop("updated_at", None)
    right.pop("updated_at", None)
    return left == right


def new_operation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def apply_guard(vault: Path, operation: dict) -> str:
    """Inspect, then run the closed prepare/apply/verify lifecycle."""
    insp = inspect_operation(str(vault), operation)
    sha = insp["approval_sha256"]
    try:
        execute_operation(str(vault), operation, sha)
    except CooperativeLockError:
        _recover_stale_lock(vault)
        execute_operation(str(vault), operation, sha)
    return sha

def verified_chunk_preconditions(vault: Path, records: list[tuple[str, str, dict]]) -> dict[str, str]:
    """Bind the index to bytes proven to match its generated record snapshot."""
    result = {}
    for _chunk_id, relative, generated in records:
        current_bytes = bounded_target_bytes(vault, relative)
        if current_bytes is None:
            raise RuntimeError(f"desired chunk missing before index operation: {relative}")
        try:
            current_record = json.loads(current_bytes.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError(f"desired chunk is invalid: {relative}") from exc
        if (not isinstance(current_record, dict)
                or current_record.keys() != generated.keys()
                or any(current_record[key] != value for key, value in generated.items() if key != "created_at")):
            raise RuntimeError(f"desired chunk changed since index generation: {relative}")
        result[relative] = "sha256:" + hashlib.sha256(current_bytes).hexdigest()
    return result

def apply_large_index(vault: Path, index_json: str, preconditions: dict[str, str]) -> dict:
    """Publish only the BM25 index through its bounded single-file guard."""
    index_rel = ".vault-meta/bm25/index.json"
    data = index_json.encode("utf-8")
    before = bounded_target_hash(vault, index_rel)
    approval = inspect_large_index(vault, data, before, preconditions)["approval_sha256"]
    try:
        return publish_large_index(vault, data, before, preconditions, approval)
    except CooperativeLockError:
        _recover_stale_lock(vault)
        return publish_large_index(vault, data, before, preconditions, approval)




def _recover_stale_lock(vault: Path) -> None:
    """Recover a write.lock left behind by a dead owner, then let it release."""

    lock_dir = vault / ".vault-meta" / "hermes-windows" / "write.lock"
    try:
        lock_dir.lstat()
    except FileNotFoundError:
        return
    try:
        assert_unaliased_directory(vault)
        _safe_directory(vault, ".vault-meta/hermes-windows/write.lock", create=False)
    except (OSError, TransactionValidationError) as exc:
        raise CooperativeLockError(f"unsafe stale write.lock: {exc}") from exc
    owner = _load_json(lock_dir / "owner.json")
    if owner.get("schema") == LARGE_INDEX_SCHEMA:
        recover_large_index_lock(vault)
        return
    operation_id = owner.get("operation_id")
    approval = owner.get("approval_sha256")
    if (
        not isinstance(operation_id, str)
        or OPERATION_ID_RE.fullmatch(operation_id) is None
        or not isinstance(approval, str)
        or not approval.startswith("sha256:")
    ):
        raise CooperativeLockError("stale write.lock owner is invalid")
    try:
        op_root = _safe_directory(
            vault,
            f".vault-meta/hermes-windows/operations/{operation_id}",
            create=False,
        )
    except (OSError, TransactionValidationError) as exc:
        raise CooperativeLockError(f"unsafe stale checkpoint: {exc}") from exc
    authority = _load_json(op_root / "operation.json")
    try:
        recover_prepared_operation(str(vault), authority, approval)
    except CooperativeLockError:
        raise
    except Exception:
        rollback_operation(str(vault), authority, approval)


def make_op(
    operation_id: str,
    writes: list,
    vault: Path,
    deletes: list[str] | None = None,
    read_preconditions: dict[str, str] | None = None,
) -> dict:
    deletes = deletes or []
    expected = {}
    for w in writes:
        expected[w["path"]] = bounded_target_hash(vault, w["path"])
    for relative in deletes:
        current = bounded_target_hash(vault, relative)
        if current is None:
            raise RuntimeError(f"delete target disappeared before operation: {relative}")
        expected[relative] = current
    return {
        "schema": "hermes-native-windows-reduced-v1",
        "operation_id": operation_id,
        "expected_hashes": expected,
        "writes": writes,
        "deletes": deletes,
        "read_preconditions": read_preconditions or {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="BM25 provisioning native Windows")
    ap.add_argument("--vault", required=True, help="Vault root")
    ap.add_argument("--force", action="store_true", help="Tulis ulang semua chunk")
    ap.add_argument("--status", action="store_true", help="Cetak status index saja")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"ERR: vault tidak ditemukan: {vault}")
        return 1

    index_rel = ".vault-meta/bm25/index.json"

    if args.status:
        try:
            index_bytes = bounded_target_bytes(vault, index_rel)
            if index_bytes is None:
                print("index MISSING")
                return 2
            idx = json.loads(index_bytes.decode("utf-8"))
            print(
                f"index OK docs={idx.get('doc_count')} vocab={len(idx.get('vocab', {}))} "
                f"updated={idx.get('updated_at')}"
            )
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"ERR status index: {exc}")
            return 1

    # Even an unchanged index must not mask a dead (or live) shared writer.
    # Recover only a verifiably dead owner; otherwise fail instead of no-op.
    try:
        _recover_stale_lock(vault)
    except (CooperativeLockError, OSError, ValueError) as exc:
        print(f"ERR stale write.lock: {exc}")
        return 1

    # --- 1) generate chunks ---
    try:
        (
            writes,
            deletes,
            total_chunks,
            skipped,
            desired_records,
            source_hashes,
        ) = generate_chunk_mutations(vault, args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"ERR generate chunks: {exc}")
        return 1

    changed = len(writes)
    deleted = len(deletes)
    print(
        f"chunks: total={total_chunks} changed={changed} deleted={deleted} "
        f"skipped={skipped} "
        f"index_exist={bounded_target_hash(vault, index_rel) is not None}"
    )

    # --- 2) tulis chunk via guard ---
    if writes or deletes:
        op = make_op(
            new_operation_id("bm25-chunks"),
            writes,
            vault,
            deletes,
            source_hashes,
        )
        try:
            apply_guard(vault, op)
        except CooperativeLockError as exc:
            print(f"ERR chunk apply (lock tidak bisa dipulihkan): {exc}")
            return 1
        print(f"chunk mutations applied: changed={changed} deleted={deleted}")

    # --- 3) build candidate index dan tulis hanya jika berbeda ---
    index = build_index_from_records(desired_records)
    if not index.get("docs"):
        print("WARN: tidak ada chunk ter-index; index kosong tetap ditulis.")
    existing_index = None
    try:
        existing_index_bytes = bounded_target_bytes(vault, index_rel)
        if existing_index_bytes is not None:
            existing_index = json.loads(existing_index_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        pass
    index_changed = not (
        isinstance(existing_index, dict)
        and index_semantically_equal(existing_index, index)
    )
    if index_changed:
        index_json = json.dumps(
            index, ensure_ascii=False, separators=(",", ":")
        )
        chunk_preconditions = verified_chunk_preconditions(vault, desired_records)
        index_preconditions = {**source_hashes, **chunk_preconditions}
        result = apply_large_index(vault, index_json, index_preconditions)
        if result.get("state") != "complete":
            raise RuntimeError("BM25 index publication did not complete")
        print(
            f"index written: docs={index['doc_count']} vocab={len(index['vocab'])} "
            f"avg_dl={index['avg_dl']:.1f}"
        )
    else:
        print("index current: semantic content unchanged")

    if changed == 0 and deleted == 0 and not index_changed:
        print("UNCHANGED: chunk dan index sudah sinkron.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
