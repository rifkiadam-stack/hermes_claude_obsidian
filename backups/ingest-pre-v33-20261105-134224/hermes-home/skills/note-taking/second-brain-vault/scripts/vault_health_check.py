#!/usr/bin/env python3
"""Probe vault health for the Hermes claude-obsidian port (read-only).

Checks: env vars, sentinel, guard import, lint blocking categories, BM25
index freshness. Exits 0 when healthy, 1 otherwise. Never writes anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

VAULT = Path(os.environ.get("HERMES_OBSIDIAN_VAULT", "G:/My Drive/hermes_obsidian"))
CORE = Path(
    os.environ.get(
        "HERMES_CLAUDE_OBSIDIAN_CORE",
        r"C:/Users/rahmazaki.adam/AppData/Local/hermes/components/claude-obsidian-core",
    )
)
BLOCKING = (
    "dead_links",
    "ambiguous_targets",
    "missing_frontmatter",
    "stale_index_entries",
    "read_errors",
    "configuration_errors",
    "provenance_errors",
)

problems: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        problems.append(name)


def main() -> int:
    print(f"vault: {VAULT}")
    print(f"core:  {CORE}")
    check("vault exists", VAULT.is_dir(), "HERMES_OBSIDIAN_VAULT missing")
    check("sentinel", (VAULT / ".claude-obsidian.json").is_file() or (VAULT / ".obsidian").is_dir())
    check("wiki dir", (VAULT / "wiki").is_dir())

    sys.path.insert(0, str(CORE))
    try:
        from claude_obsidian.hermes_windows_write import inspect_operation  # noqa: F401

        check("guard importable", True)
    except Exception as exc:  # noqa: BLE001
        check("guard importable", False, str(exc))

    lock = VAULT / ".vault-meta" / "hermes-windows" / "write.lock"
    check("no held write.lock", not lock.exists(), "a guard operation is in flight")

    lint = subprocess.run(
        [sys.executable, "-B", str(CORE / "scripts" / "claude-obsidian.py"),
         "lint", "--vault", str(VAULT), "--format", "json"],
        capture_output=True,
        text=True,
    )
    if lint.returncode != 0:
        check("lint runs", False, lint.stderr[-200:])
    else:
        report = json.loads(lint.stdout)
        blocking = {c: len(report.get(c, [])) for c in BLOCKING}
        check("lint blocking clean", all(v == 0 for v in blocking.values()), json.dumps(blocking))
        print(f"  info: issues_found={report.get('summary', {}).get('issues_found')}")

    index = VAULT / ".vault-meta" / "bm25" / "index.json"
    if index.is_file():
        try:
            doc_count = json.loads(index.read_text(encoding="utf-8")).get("doc_count", 0)
            check("bm25 index fresh", doc_count > 0, "doc_count=0")
        except (json.JSONDecodeError, OSError) as exc:
            check("bm25 index fresh", False, str(exc))
    else:
        check("bm25 index fresh", False, "index.json missing (run chunk build first)")

    print("RESULT:", "HEALTHY" if not problems else f"{len(problems)} problem(s): {problems}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
