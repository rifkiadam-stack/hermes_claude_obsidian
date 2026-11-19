"""Read-only BM25 retrieval adapter for the memori-guard ``cari`` tool.

This module never writes and never takes ``write.lock``.  It loads one bounded
snapshot of the derived BM25 index, scores it with the existing retrieval
implementation, and resolves the scored chunks back to their wiki pages under
the same read rules used by ``baca``.

Deliberate limits:

- the index is derived state, so a missing or internally inconsistent snapshot
  is reported as unavailable instead of being repaired here;
- chunks and pages are read with bounded, identity-checked reads;
- a page whose chunk/index/page hashes disagree is treated as stale, never as
  evidence;
- freshness is conservative: any unreadable part marks the result ``basi``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hermes_windows_write import OperationValidationError, _bounded_target
from .memori_validasi import MemoryValidationError, validate_path
from .paths import is_name_surrogate

INDEX_REL = ".vault-meta/bm25/index.json"
PAGE_LIMIT = 1_048_576
DERIVED_INDEX_LIMIT = 64 * 1024 * 1024
SNIPPET_MAX = 500
CANDIDATE_TARGET = 200
RETRY_SLEEP_S = 0.02
INDEX_DEADLINE_S = 2.0
FILE_DEADLINE_S = 0.25
FUTURE_TOLERANCE_S = 1.0

_bm25_module = None


class RetrievalUnavailable(Exception):
    """The derived BM25 index cannot be read safely right now."""


def _bm25():
    """Load the existing retrieval script once (its filename is not importable)."""
    global _bm25_module
    if _bm25_module is None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "bm25-index.py"
        spec = importlib.util.spec_from_file_location("_memori_guard_bm25_index", path)
        if spec is None or spec.loader is None:
            raise RetrievalUnavailable("modul BM25 tidak dapat dimuat")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _bm25_module = module
    return _bm25_module


def _refresh_hint(vault: Path) -> str:
    provision = Path(__file__).resolve().parents[1] / "scripts" / "bm25_provision_native.py"
    return (f'Jalankan lewat Hermes: python -B "{provision.as_posix()}" '
            f'--vault "{Path(vault).as_posix()}"')


def _read_bytes_share_delete(path: Path, limit: int) -> bytes:
    """Read a file while allowing concurrent replace/delete on Windows.

    CPython's ``open`` does not request ``FILE_SHARE_DELETE``, so a publisher's
    ``os.replace`` or a user's ``unlink`` fails with WinError 5/32 while the
    handle is open.  Opening with all three share flags keeps readers
    non-blocking.  The handle is closed before this function returns.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        generic_read = 0x80000000
        share_all = 0x1 | 0x2 | 0x4
        open_existing = 3
        file_attribute_normal = 0x80
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ]
        kernel32.ReadFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateFileW(
            str(path), generic_read, share_all, None, open_existing,
            file_attribute_normal, None)
        invalid = ctypes.c_void_p(-1).value
        if not handle or handle == invalid:
            error = ctypes.get_last_error()
            raise OSError(error, f"CreateFileW failed for {path.name}: {error}")
        try:
            buffer = ctypes.create_string_buffer(1024 * 1024)
            chunks: list[bytes] = []
            total = 0
            read = wintypes.DWORD(0)
            while True:
                if not kernel32.ReadFile(handle, buffer, len(buffer),
                                         ctypes.byref(read), None):
                    error = ctypes.get_last_error()
                    raise OSError(error, f"ReadFile failed for {path.name}: {error}")
                if read.value == 0:
                    break
                total += read.value
                if total > limit:
                    raise ValueError(f"file exceeds byte limit: {path.name}")
                chunks.append(buffer.raw[:read.value])
            return b"".join(chunks)
        finally:
            kernel32.CloseHandle(handle)
    with open(path, "rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file exceeds byte limit: {path.name}")
    return data


def _read_once(vault: Path, relative: str, limit: int) -> bytes | None:
    """Bounded, alias-checked read that never keeps a handle open."""
    target = _bounded_target(vault, relative)
    try:
        before = target.lstat()
    except OSError:
        return None
    if is_name_surrogate(before) or not stat.S_ISREG(before.st_mode):
        raise OperationValidationError(f"not a regular file: {relative}")
    data = _read_bytes_share_delete(target, limit)
    try:
        after = target.lstat()
    except OSError:
        raise OperationValidationError(f"file replaced during read: {relative}")
    if after.st_size != len(data):
        raise OperationValidationError(f"file changed during read: {relative}")
    return data


def _read_with_retry(vault: Path, relative: str, limit: int, *, required: bool,
                     deadline: float) -> bytes | None:
    """Retry transient metadata/replace races; VFS lag on G: is expected."""
    started = time.monotonic()
    last_error: Exception | None = None
    while True:
        try:
            data = _read_once(vault, relative, limit)
            if data is not None or not required:
                return data
            last_error = FileNotFoundError(relative)
        except (OperationValidationError, OSError, ValueError) as exc:
            last_error = exc
        if time.monotonic() - started >= deadline:
            if required:
                raise OperationValidationError(str(last_error)) from last_error
            return None
        time.sleep(RETRY_SLEEP_S)


def load_snapshot(vault: str | Path) -> dict[str, Any]:
    """Return one bounded, validated index snapshot plus its hash."""
    vault = Path(vault)
    bm = _bm25()
    try:
        data = _read_with_retry(vault, INDEX_REL, DERIVED_INDEX_LIMIT,
                                required=True, deadline=INDEX_DEADLINE_S)
    except (OperationValidationError, OSError, ValueError) as exc:
        raise RetrievalUnavailable(
            "indeks BM25 belum ada atau sedang dipublikasikan ulang. "
            + _refresh_hint(vault)) from exc
    if data is None:  # defensive; required=True never returns None
        raise RetrievalUnavailable("indeks BM25 belum ada. " + _refresh_hint(vault))
    try:
        index = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetrievalUnavailable(
            "indeks BM25 tidak terbaca (bukan JSON UTF-8 yang sah). "
            + _refresh_hint(vault)) from exc
    try:
        index = bm.validate_index(index)
    except Exception as exc:  # IndexValidationError and shape errors
        raise RetrievalUnavailable(
            f"indeks BM25 tidak konsisten: {exc}. " + _refresh_hint(vault)) from exc
    return {
        "index": index,
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def score(snapshot: dict[str, Any], kueri: str, top_k: int = CANDIDATE_TARGET) -> list[dict]:
    """Score the snapshot with the existing BM25 implementation."""
    bm = _bm25()
    return bm.score_index(snapshot["index"], kueri, top_k=top_k)


def _frontmatter_field(text: str, field: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    block = text[3:end]
    match = re.search(rf"(?m)^{re.escape(field)}\s*:\s*(.+?)\s*$", block)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value or None


def page_title(text: str, page_rel: str) -> str:
    """Frontmatter ``title``, else first H1, else the file stem."""
    title = _frontmatter_field(text, "title")
    if title:
        return title
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return Path(page_rel).stem


def page_type(text: str) -> str | None:
    """Frontmatter ``type`` or ``None``; the key is always present in results."""
    return _frontmatter_field(text, "type")


def _page_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_page(vault: Path, page_rel: str) -> str | None:
    data = _read_with_retry(vault, page_rel, PAGE_LIMIT, required=False,
                            deadline=FILE_DEADLINE_S)
    if data is None:
        return None
    return data.decode("utf-8", errors="replace")


def _snippet_from_page(page_text: str, raw_text: str) -> str:
    """Return a literal, whitespace-normalised window of the page itself.

    The chunk's raw text is used only as an anchor.  The window always comes
    from the page content, so it can never contain the synthetic context
    prefix that the index sees.
    """
    page_norm = " ".join(page_text.split())
    chunk_norm = " ".join(str(raw_text).split())
    position = -1
    for width in (120, 60, 40, 20):
        if len(chunk_norm) < width:
            continue
        position = page_norm.find(chunk_norm[:width])
        if position >= 0:
            break
    if position < 0:
        return page_norm[:SNIPPET_MAX]
    return page_norm[position:position + SNIPPET_MAX]


def page_results(vault: str | Path, snapshot: dict[str, Any],
                 hits: list[dict], jumlah: int) -> tuple[list[dict], bool]:
    """Resolve chunk hits to one result per page, best score wins.

    Returns ``(results, stale)`` where ``stale`` is true when any candidate was
    discarded because its chunk or page no longer matches the index.
    """
    vault = Path(vault)
    best: dict[str, dict[str, Any]] = {}
    page_cache: dict[str, str | None] = {}
    stale = False

    for hit in hits:
        chunk_rel = str(hit.get("path") or "").replace("\\", "/")
        if not chunk_rel.startswith(".vault-meta/chunks/"):
            stale = True
            continue
        try:
            raw = _read_with_retry(vault, chunk_rel, DERIVED_INDEX_LIMIT,
                                   required=False, deadline=FILE_DEADLINE_S)
        except (OperationValidationError, OSError, ValueError):
            stale = True
            continue
        if raw is None:
            stale = True
            continue
        try:
            chunk = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            stale = True
            continue
        if not isinstance(chunk, dict):
            stale = True
            continue
        if chunk.get("body_hash") != hit.get("body_hash"):
            stale = True
            continue
        if chunk.get("page_body_hash") != hit.get("page_body_hash"):
            stale = True
            continue

        page_rel = str(chunk.get("page_path") or "").replace("\\", "/")
        if not page_rel.startswith("wiki/"):
            stale = True
            continue
        try:
            validate_path(vault, page_rel, write=False)
        except MemoryValidationError:
            stale = True
            continue

        if page_rel not in page_cache:
            try:
                page_cache[page_rel] = _read_page(vault, page_rel)
            except (OperationValidationError, OSError, ValueError):
                page_cache[page_rel] = None
        text = page_cache[page_rel]
        if text is None or _page_hash(text) != chunk.get("page_body_hash"):
            stale = True
            continue

        score_value = float(hit.get("score") or 0.0)
        if score_value <= 0.0:
            continue
        current = best.get(page_rel)
        if current is None or score_value > current["skor"]:
            raw_text = chunk.get("raw_text")
            if not isinstance(raw_text, str):
                stale = True
                continue
            best[page_rel] = {
                "path": page_rel,
                "judul": page_title(text, page_rel),
                "type": page_type(text),
                "skor": score_value,
                "cuplikan": _snippet_from_page(text, raw_text),
            }

    results = sorted(best.values(), key=lambda item: (-item["skor"], item["path"]))
    return results[:jumlah], stale


def _parse_updated(value: Any) -> float | None:
    """Parse an ISO 8601 UTC timestamp ending in ``Z`` (fraction optional)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.endswith("Z"):
        return None
    body = text[:-1]
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(body, pattern).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def index_is_stale(vault: str | Path, snapshot: dict[str, Any]) -> bool:
    """Conservative freshness check: timestamp, page inventory, readability."""
    index = snapshot["index"]
    updated = _parse_updated(index.get("updated_at"))
    if updated is None:
        return True

    newest: float | None = None
    count = 0
    try:
        for current, dirs, files in os.walk(Path(vault) / "wiki"):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            for name in files:
                if name.startswith(".") or not name.endswith(".md"):
                    continue
                stat = os.stat(os.path.join(current, name))
                count += 1
                if newest is None or stat.st_mtime > newest:
                    newest = stat.st_mtime
    except (OSError, ValueError):
        return True

    indexed_pages = {str(chunk_id).split(":", 1)[0] for chunk_id in index["docs"]}
    if count != len(indexed_pages):
        return True
    if newest is not None and newest > updated + FUTURE_TOLERANCE_S:
        return True
    return False


def search(vault: str | Path, kueri: str, jumlah: int) -> dict[str, Any]:
    """Execute the read-only search pipeline in the contracted order."""
    if not isinstance(kueri, str):
        return {"status": "ditolak", "pesan": "kueri harus teks 1–500 karakter"}
    text = kueri.strip()
    if not 1 <= len(text) <= 500:
        return {"status": "ditolak", "pesan": "kueri harus teks 1–500 karakter setelah spasi tepi dibuang"}
    if isinstance(jumlah, bool) or not isinstance(jumlah, int) or not 1 <= jumlah <= 10:
        return {"status": "ditolak", "pesan": "jumlah harus bilangan bulat 1–10"}

    vault = Path(vault)
    try:
        snapshot = load_snapshot(vault)
    except RetrievalUnavailable as exc:
        return {"status": "gagal", "pesan": str(exc)}

    try:
        hits = score(snapshot, text, top_k=CANDIDATE_TARGET)
    except Exception as exc:  # QueryTooLargeError and defensive failures
        return {"status": "ditolak", "pesan": f"kueri ditolak: {exc}"}

    results, stale = page_results(vault, snapshot, hits, jumlah)
    basi = stale or index_is_stale(vault, snapshot)
    return {
        "status": "selesai",
        "indeks": {"dibangun": snapshot["index"]["updated_at"], "basi": bool(basi)},
        "hasil": results,
    }
