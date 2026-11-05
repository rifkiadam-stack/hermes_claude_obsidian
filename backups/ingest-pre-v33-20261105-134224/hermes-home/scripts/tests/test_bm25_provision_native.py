from __future__ import annotations

import json
import importlib.util
import subprocess
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(r"C:\Users\rahmazaki.adam\AppData\Local\hermes\components\claude-obsidian-core")
sys.path.insert(0, str(CORE))

SCRIPT = Path(__file__).resolve().parents[1] / "bm25_provision_native.py"
STAGING = Path(r"C:\Users\rahmazaki.adam\AppData\Local\hermes\staging")


def load_adapter():
    spec = importlib.util.spec_from_file_location("bm25_provision_native_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Bm25ProvisionNativeTests(unittest.TestCase):
    def run_adapter(self, vault: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(vault)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_removed_page_prunes_stale_chunk_and_index_record(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            (vault / ".claude-obsidian.json").write_text(
                '{"schema":"claude-obsidian.config.v1"}\n', encoding="utf-8"
            )
            (wiki / "keep.md").write_text(
                "---\ntitle: Keep\n---\n\n# Keep\n\nPersistent BM25 content.\n",
                encoding="utf-8",
            )
            obsolete = wiki / "obsolete.md"
            obsolete.write_text(
                "---\ntitle: Obsolete\n---\n\n# Obsolete\n\nStale BM25 content.\n",
                encoding="utf-8",
            )

            first = self.run_adapter(vault)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            stale_records = []
            for path in (vault / ".vault-meta/chunks").glob("*/chunk-*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("page_path") == "wiki\\obsolete.md" or record.get(
                    "page_path"
                ) == "wiki/obsolete.md":
                    stale_records.append(path)
            self.assertTrue(stale_records)

            obsolete.unlink()
            time.sleep(1.1)
            second = self.run_adapter(vault)
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertIn("deleted=", second.stdout)
            self.assertTrue(all(not path.exists() for path in stale_records))

            index = json.loads(
                (vault / ".vault-meta/bm25/index.json").read_text(encoding="utf-8")
            )
            indexed_chunk_paths = {
                str(doc.get("path", "")).replace("\\", "/")
                for doc in index.get("docs", {}).values()
                if isinstance(doc, dict)
            }
            stale_relatives = {
                path.relative_to(vault).as_posix() for path in stale_records
            }
            self.assertTrue(stale_relatives.isdisjoint(indexed_chunk_paths))

            third = self.run_adapter(vault)
            self.assertEqual(2, third.returncode, third.stdout + third.stderr)
            self.assertIn("UNCHANGED", third.stdout)
            self.assertFalse(
                (vault / ".vault-meta/hermes-windows/write.lock").exists()
            )

    def test_address_collision_fails_in_preflight(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            for name in ("first", "second"):
                (wiki / f"{name}.md").write_text(
                    "---\ntitle: Collision\naddress: l-123456\n---\n\n# Same\n\nText.\n",
                    encoding="utf-8",
                    newline="\n",
                )

            adapter = load_adapter()
            with self.assertRaisesRegex(RuntimeError, "address collision"):
                adapter.generate_chunk_mutations(vault, False)

    def test_rename_with_stable_address_updates_chunk_page_path(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            old_page = wiki / "old.md"
            old_page.write_text(
                "---\ntitle: Stable\naddress: l-123456\n---\n\n# Stable\n\nSame text.\n",
                encoding="utf-8",
                newline="\n",
            )
            first = self.run_adapter(vault)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            new_page = wiki / "new.md"
            old_page.rename(new_page)
            time.sleep(1.1)

            second = self.run_adapter(vault)

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            chunk = json.loads(
                (vault / ".vault-meta/chunks/l-123456/chunk-000.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                chunk["page_path"].replace("\\", "/"),
                {"wiki/new.md"},
            )

    def test_retry_rebuilds_index_when_chunks_are_newer(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            page = wiki / "term.md"
            page.write_text("# Term\n\nolduniqueterm\n", encoding="utf-8")
            first = self.run_adapter(vault)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)

            page.write_text("# Term\n\nnewuniqueterm\n", encoding="utf-8")
            adapter = load_adapter()
            (
                writes,
                deletes,
                _total,
                _skipped,
                _records,
                _source_hashes,
            ) = adapter.generate_chunk_mutations(vault, False)
            self.assertTrue(writes)
            operation = adapter.make_op(
                "simulate-chunks-committed-index-failed", writes, vault, deletes
            )
            adapter.apply_guard(vault, operation)

            retry = self.run_adapter(vault)

            self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
            index = json.loads(
                (vault / ".vault-meta/bm25/index.json").read_text(encoding="utf-8")
            )
            self.assertIn("newuniqueterm", index["vocab"])
            self.assertNotIn("olduniqueterm", index["vocab"])

    def test_stale_four_digit_chunk_is_deleted(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            page = wiki / "page.md"
            page.write_text("# Page\n\nText.\n", encoding="utf-8")
            first = self.run_adapter(vault)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            chunk_dir = next((vault / ".vault-meta/chunks").iterdir())
            stale = chunk_dir / "chunk-1000.json"
            stale.write_text(
                json.dumps(
                    {
                        "page_path": "wiki/missing.md",
                        "page_address": chunk_dir.name,
                        "chunk_index": 1000,
                        "raw_text": "stale",
                        "contextualized_text": "stale",
                        "body_hash": "sha256:" + "0" * 64,
                        "page_body_hash": "sha256:" + "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            time.sleep(1.1)

            second = self.run_adapter(vault)

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertFalse(stale.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_chunk_address_junction_is_rejected_before_inventory(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            root = Path(directory)
            vault = root / "vault"
            (vault / "wiki").mkdir(parents=True)
            chunks = vault / ".vault-meta/chunks"
            chunks.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (outside / "chunk-000.json").write_text("outside", encoding="utf-8")
            junction = chunks / "l-123456"
            linked = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if linked.returncode != 0:
                self.skipTest("mklink /J unavailable")
            adapter = load_adapter()

            with self.assertRaisesRegex(RuntimeError, "unsafe chunk address directory"):
                adapter.generate_chunk_mutations(vault, False)

    def test_every_chunk_prefix_receives_original_page_content(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            (wiki / "multi.md").write_text(
                "# Multi\n\nORIGINAL_PAGE_CONTENT\n", encoding="utf-8"
            )
            adapter = load_adapter()
            seen_page_contents = []

            def capture_prefix(_tier, _fm, page_content, _raw):
                seen_page_contents.append(page_content)
                return "prefix", "synthetic"

            with patch.object(adapter.cp, "chunk_body", return_value=["one", "two"]), patch.object(
                adapter.cp, "generate_prefix", side_effect=capture_prefix
            ):
                adapter.generate_chunk_mutations(vault, False)

            self.assertEqual(2, len(seen_page_contents))
            self.assertEqual(seen_page_contents[0], seen_page_contents[1])
            self.assertIn("ORIGINAL_PAGE_CONTENT", seen_page_contents[0])

    def test_empty_address_directories_count_toward_inventory_bound(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            (vault / "wiki").mkdir(parents=True)
            (vault / ".vault-meta/chunks/l-123456").mkdir(parents=True)
            adapter = load_adapter()

            with patch.object(adapter, "MAX_CHUNK_INVENTORY_ENTRIES", 0):
                with self.assertRaisesRegex(RuntimeError, "inventory exceeds"):
                    adapter.generate_chunk_mutations(vault, False)

    def test_index_builder_uses_in_memory_records_not_disk_builder(self) -> None:
        adapter = load_adapter()
        record = {
            "page_address": "l-123456",
            "chunk_index": 0,
            "contextualized_text": "bounded snapshot text",
            "raw_text": "bounded snapshot text",
            "body_hash": "sha256:" + "1" * 64,
            "page_body_hash": "sha256:" + "2" * 64,
        }
        records = [
            (
                "l-123456:0",
                ".vault-meta/chunks/l-123456/chunk-000.json",
                record,
            )
        ]

        with patch.object(
            adapter.bm, "build_index", side_effect=AssertionError("disk builder called")
        ):
            index = adapter.build_index_from_records(records)

        self.assertEqual(1, index["doc_count"])
        self.assertIn("bounded", index["vocab"])

    def test_status_rejects_oversized_index_with_bounded_error(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            (vault / "wiki").mkdir(parents=True)
            index_path = vault / ".vault-meta/bm25/index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--vault", str(vault), "--status"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("ERR status index", result.stdout)

    def test_existing_windows_page_path_format_remains_idempotent(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            (wiki / "page.md").write_text("# Page\n\nText.\n", encoding="utf-8")
            adapter = load_adapter()
            writes, _deletes, _total, _skipped, _records, _sources = (
                adapter.generate_chunk_mutations(vault, False)
            )
            self.assertEqual(1, len(writes))
            legacy = json.loads(writes[0]["content"])
            legacy["page_path"] = legacy["page_path"].replace("/", "\\")
            target = vault / writes[0]["path"]
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")

            second_writes, *_rest = adapter.generate_chunk_mutations(vault, False)

            self.assertEqual([], second_writes)

    def test_adapter_recovers_from_stale_lock_left_by_dead_owner(self) -> None:
        from claude_obsidian.hermes_windows_write import (
            apply_prepared_operation,
            inspect_operation,
            prepare_operation,
        )

        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            page = wiki / "page.md"
            page.write_text("# Page\n\none\n", encoding="utf-8")
            first = self.run_adapter(vault)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)

            page.write_text("# Page\n\ntwo\n", encoding="utf-8")
            time.sleep(1.1)
            adapter = load_adapter()
            writes, deletes, _total, _skipped, _records, _sources = (
                adapter.generate_chunk_mutations(vault, False)
            )
            self.assertTrue(writes)
            operation = adapter.make_op("stale-crash-op", writes, vault, deletes)
            approval = inspect_operation(str(vault), operation)["approval_sha256"]
            prepare_operation(str(vault), operation, approval)
            apply_prepared_operation(str(vault), operation, approval)
            owner_path = vault / ".vault-meta/hermes-windows/write.lock/owner.json"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["pid"] = 2_147_483_647
            owner_path.write_text(json.dumps(owner), encoding="utf-8")

            second = self.run_adapter(vault)

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertFalse(
                (vault / ".vault-meta/hermes-windows/write.lock").exists()
            )

    def test_recovery_refuses_stale_lock_without_owner(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=STAGING) as directory:
            vault = Path(directory) / "vault"
            wiki = vault / "wiki"
            wiki.mkdir(parents=True)
            (wiki / "page.md").write_text("# Page\n\nText.\n", encoding="utf-8")
            lock_dir = vault / ".vault-meta/hermes-windows/write.lock"
            lock_dir.mkdir(parents=True)
            adapter = load_adapter()
            writes, deletes, *_ = adapter.generate_chunk_mutations(vault, False)
            operation = adapter.make_op("stale-no-owner", writes, vault, deletes)

            with self.assertRaisesRegex(
                Exception, "stale write.lock"
            ):
                adapter.apply_guard(vault, operation)


if __name__ == "__main__":
    unittest.main()
