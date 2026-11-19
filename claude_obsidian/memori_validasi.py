"""Shared, read-only memory validation for Hermes and the future MCP adapter.

This layer narrows the existing native guard; it is not a write entry point.
All eventual writes must still pass inspect_operation/execute_operation.
"""
from pathlib import Path, PurePosixPath
import unicodedata
import argparse
import json
import re
import sys

from .hermes_windows_write import (
    MAX_TRANSACTION_FILE_BYTES, OperationValidationError, _bounded_target,
    bounded_target_bytes,
)
from .paths import assert_unaliased_directory


class MemoryValidationError(ValueError):
    """Memory scope or append-only policy was violated."""


_WRITE_ROOTS = {('wiki', 'sesi'), ('wiki', 'profil'), ('sesi-log',)}
_READ_ONLY = {'_konvensi-memori.md', '_template-sesi.md', '_template-sesi-log.md'}


def _has_dot_component(path: str) -> bool:
    return any(part.startswith('.') for part in path.split('/'))


def validate_path(vault: str | Path, path: str, *, write: bool) -> None:
    """Reject noncanonical or out-of-scope paths, aliases and junction chains.

    Reads additionally cover every ``wiki/**/*.md`` page (read-only knowledge
    lookup).  Dot-prefixed components are rejected in every scope: a dotted
    folder such as ``.vault-meta`` or a dotted file such as
    ``wiki/sesi/.tersembunyi.md`` is never a memory or knowledge target.
    """
    if (not isinstance(path, str) or not path or len(path) > 1024
            or '\\' in path or ':' in path or '\x00' in path
            or path != unicodedata.normalize('NFC', path)):
        raise MemoryValidationError('path must be canonical vault-relative POSIX text')
    parts = path.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise MemoryValidationError('empty, dot and parent path components are forbidden')
    if _has_dot_component(path):
        raise MemoryValidationError('dot-prefixed path components are forbidden')
    suffix = PurePosixPath(path).suffix
    writable = any(tuple(parts[:len(root)]) == root and len(parts) > len(root)
                   for root in _WRITE_ROOTS)
    readable_page = (not write and len(parts) > 1 and parts[0] == 'wiki'
                     and suffix == '.md')
    if not ((writable and suffix == '.md')
            or readable_page
            or (not write and path in _READ_ONLY)):
        raise MemoryValidationError('path is outside memory scope or is read-only')
    try:
        root = Path(vault).absolute()
        assert_unaliased_directory(root)
        _bounded_target(root, path)
    except (OperationValidationError, OSError, ValueError) as exc:
        raise MemoryValidationError(str(exc)) from exc


def next_log_continuation(vault: str | Path, path: str) -> str:
    """Return the first continuation Log path in this chain that does not exist.

    ``sesi-log/uji-log.md`` yields ``sesi-log/uji-log-2.md`` when that file is
    absent, otherwise ``-log-3.md`` and so on. The returned value is a canonical
    vault-relative POSIX path inside the same folder as ``path``.
    """
    pure = PurePosixPath(path)
    folder = pure.parent.as_posix()
    stem = re.sub(r'(-log)(?:-(?:[2-9]|[1-9][0-9]+))?$', r'\1', pure.stem)
    prefix = '' if folder in ('', '.') else folder + '/'
    root = Path(vault)
    for index in range(2, 1000):
        candidate = f'{prefix}{stem}-{index}.md'
        try:
            if not (root / candidate).exists():
                return candidate
        except OSError:
            return candidate
    return f'{prefix}{stem}-1000.md'


def validate_content(vault: str | Path, path: str, content: str, *, max_file_bytes: int = MAX_TRANSACTION_FILE_BYTES) -> bytes | None:
    """Return bounded old bytes after scope, size and append-only checks.

    This is a snapshot, not authorization to write: the caller must bind its
    hash into the guard operation and revalidate before execution.
    """
    validate_path(vault, path, write=True)
    if not isinstance(content, str):
        raise MemoryValidationError('content must be bounded UTF-8 text')
    if path.startswith('sesi-log/'):
        size_message = ('Log exceeds guard byte limit; create continuation file '
                        + next_log_continuation(vault, path))
    else:
        size_message = 'content exceeds guard byte limit'
    if len(content) > max_file_bytes:
        raise MemoryValidationError(size_message)
    try:
        new = content.encode('utf-8', errors='strict')
        if len(new) > max_file_bytes:
            raise MemoryValidationError(size_message)
        old = bounded_target_bytes(vault, path)
    except (UnicodeError, OperationValidationError) as exc:
        raise MemoryValidationError(str(exc)) from exc
    if path.startswith('sesi-log/') and old is not None and not new.startswith(old):
        raise MemoryValidationError('existing Log bytes must remain an exact prefix')
    return old


def validate_operation(vault: str | Path, operation: dict, *, max_file_bytes: int = MAX_TRANSACTION_FILE_BYTES,
                       max_operation_bytes: int = 8 * 1024 * 1024) -> list[str]:
    """Validate all memory targets; existing Log byte prefixes are mandatory."""
    reasons: list[str] = []
    if not isinstance(operation, dict):
        return ['operation must be a JSON object']
    changes = operation.get('perubahan')
    logs = operation.get('tambahan_log')
    if not isinstance(changes, list) or not isinstance(logs, list):
        return ['perubahan and tambahan_log must be arrays']
    if len(changes) > 10 or len(logs) > 10:
        return ['at most 10 perubahan and 10 tambahan_log items are permitted']
    if not changes and not logs:
        return ['operation must contain a perubahan or tambahan_log item']
    if not isinstance(operation.get('kunci_operasi'), str) or not operation['kunci_operasi'].strip():
        return ['kunci_operasi must be nonempty text']
    keys = {operation['kunci_operasi']}
    for item in logs:
        if isinstance(item, dict) and isinstance(item.get('kunci'), str):
            keys.add(item['kunci'])
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        return ['operation identity keys must be nonempty text']
    total_bytes = 0
    assembled_logs: dict[str, str] = {}
    oversized: set[str] = set()
    for item in changes:
        try:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise MemoryValidationError('invalid perubahan item')
            path = item['path']
            if path.startswith('sesi-log/'):
                if bounded_target_bytes(vault, path) is not None:
                    raise MemoryValidationError('perubahan to an existing Log is forbidden; use tambahan_log')
            validate_content(vault, path, item.get('isi_baru'), max_file_bytes=max_file_bytes)
            total_bytes += len(item['isi_baru'].encode('utf-8'))
        except (MemoryValidationError, OperationValidationError, OSError, ValueError) as exc:
            reasons.append(str(exc))
    for item in logs:
        try:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise MemoryValidationError('invalid tambahan_log item')
            path = item['path']
            if not path.startswith('sesi-log/'):
                raise MemoryValidationError('tambahan_log path must be in sesi-log')
            if _has_dot_component(path):
                raise MemoryValidationError('dot-prefixed path components are forbidden')
            old = bounded_target_bytes(vault, path)
            if old is None:
                raise MemoryValidationError('tambahan_log requires an existing sesi-log file')
            if not isinstance(item.get('teks'), str):
                raise MemoryValidationError('teks must be text')
            if not isinstance(item.get('kunci'), str) or not item['kunci'].strip():
                raise MemoryValidationError('kunci must be nonempty text')
            if re.search(r'(?m)^' + re.escape(item['kunci']) + r'\r?$', item['teks']) is None:
                raise MemoryValidationError('kunci must appear as an exact line in teks')
            try:
                base = assembled_logs.get(path)
                if base is None:
                    base = old.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise MemoryValidationError('existing Log is not UTF-8 text') from exc
            assembled = base + item['teks']
            if len(assembled.encode('utf-8', errors='strict')) > max_file_bytes:
                # Report the oversize Log exactly once per path, naming the real
                # continuation file; the final-size pass below must not repeat it.
                if path not in oversized:
                    oversized.add(path)
                    reasons.append('Log exceeds guard byte limit; create continuation file '
                                   + next_log_continuation(vault, path))
                continue
            assembled_logs[path] = assembled
            total_bytes += len(item['teks'].encode('utf-8'))
        except (MemoryValidationError, OperationValidationError, OSError, ValueError, UnicodeError) as exc:
            reasons.append(str(exc))
    # Validate the projected final size of each Log once, after every append for
    # that path is accumulated; per-item checks alone miss an over-limit final file.
    for path, assembled in assembled_logs.items():
        try:
            validate_content(vault, path, assembled, max_file_bytes=max_file_bytes)
        except (MemoryValidationError, OperationValidationError, OSError, ValueError, UnicodeError) as exc:
            reasons.append(str(exc))
    if total_bytes > max_operation_bytes:
        reasons.append('operation exceeds 8 MiB aggregate byte limit')
    return reasons


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--periksa', action='store_true')
    parser.add_argument('--vault')
    parser.add_argument('--batas-byte', type=int, default=MAX_TRANSACTION_FILE_BYTES)
    args = parser.parse_args(argv)
    reasons = []
    if not args.periksa:
        reasons.append('--periksa is required')
    if not args.vault:
        reasons.append('explicit --vault is required; vault environment is not consulted')
    try:
        if not 1 <= args.batas_byte <= MAX_TRANSACTION_FILE_BYTES:
            raise ValueError('--batas-byte is outside allowed range')
        raw_parts = []
        total = 0
        reader = getattr(sys.stdin.buffer, 'read1', sys.stdin.buffer.read)
        while True:
            chunk = reader(min(65536, 8 * 1024 * 1024 + 1 - total))
            if not chunk:
                break
            raw_parts.append(chunk)
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                raise ValueError('stdin exceeds bounded operation limit')
        raw = b''.join(raw_parts)
        operation = json.loads(raw.decode('utf-8'))
    except (ValueError, OSError, UnicodeError) as exc:
        operation = None
        reasons.append('invalid JSON input: ' + str(exc))
    if args.vault and operation is not None:
        reasons.extend(validate_operation(args.vault, operation, max_file_bytes=args.batas_byte))
    print(json.dumps({'lolos': not reasons, 'alasan': reasons}, ensure_ascii=False))
    return 0 if not reasons else 1


if __name__ == '__main__':
    raise SystemExit(main())
