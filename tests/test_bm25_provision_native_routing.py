"""Adapter route for a large BM25 index must not enter the generic JSON guard."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("bm25_provision_native", HERE.parent / "scripts" / "bm25_provision_native.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class IndexRoutingTests(unittest.TestCase):
    def test_index_route_uses_index_only_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            with patch.object(adapter, "inspect_large_index", return_value={"approval_sha256": "approved"}) as inspect, \
                 patch.object(adapter, "publish_large_index", return_value={"state": "complete"}) as publish, \
                 patch.object(adapter, "inspect_operation", side_effect=AssertionError("generic guard called")):
                result = adapter.apply_large_index(vault, '{"vocab":{}}', {"wiki/a.md": "sha256:" + "a" * 64})
            self.assertEqual("complete", result["state"])
            inspect.assert_called_once()
            publish.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_stale_lock_recovery_rejects_junction_before_owner_read(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            runtime = vault / ".vault-meta/hermes-windows"
            runtime.mkdir(parents=True)
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "owner.json").write_text('{"schema":"fake"}', encoding="utf-8")
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(runtime / "write.lock"), str(outside)], capture_output=True, text=True)
            if result.returncode:
                self.skipTest("mklink /J unavailable")
            with patch.object(adapter, "_load_json", side_effect=AssertionError("outside owner read")):
                with self.assertRaises(adapter.CooperativeLockError):
                    adapter._recover_stale_lock(vault)
            self.assertTrue((outside / "owner.json").exists())

    def test_generated_chunk_snapshot_rejects_changed_record(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            rel = ".vault-meta/chunks/c-000001/chunk-000.json"
            target = vault / rel
            target.parent.mkdir(parents=True)
            generated = {"contextualized_text": "original", "created_at": "now"}
            target.write_text('{"contextualized_text":"tampered","created_at":"old"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                adapter.verified_chunk_preconditions(vault, [("c-000001:0", rel, generated)])

    def test_generated_chunk_snapshot_accepts_timestamp_only_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            rel = ".vault-meta/chunks/c-000001/chunk-000.json"
            target = vault / rel
            target.parent.mkdir(parents=True)
            generated = {"contextualized_text": "original", "created_at": "now"}
            target.write_text('{"contextualized_text":"original","created_at":"old"}', encoding="utf-8")
            result = adapter.verified_chunk_preconditions(vault, [("c-000001:0", rel, generated)])
            self.assertEqual(adapter.bounded_target_hash(vault, rel), result[rel])

    def test_noop_refuses_to_report_synced_when_lock_recovery_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            vault.mkdir()
            candidate = {"docs": {"one": {}}, "vocab": {}, "doc_count": 1}
            with patch.object(sys, "argv", ["bm25_provision_native.py", "--vault", str(vault)]), \
                 patch.object(adapter, "_recover_stale_lock", side_effect=adapter.CooperativeLockError("live owner")) as recover, \
                 patch.object(adapter, "generate_chunk_mutations", return_value=([], [], 0, 0, [], {})), \
                 patch.object(adapter, "build_index_from_records", return_value=candidate), \
                 patch.object(adapter, "bounded_target_hash", return_value="sha256:" + "a" * 64), \
                 patch.object(adapter, "bounded_target_bytes", return_value=adapter.json.dumps(candidate).encode("utf-8")):
                self.assertEqual(1, adapter.main())
            recover.assert_called_once_with(vault)

    def test_noop_recovers_dead_index_owner_after_publish(self):
        from claude_obsidian import hermes_windows_bm25 as writer
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            (vault / ".vault-meta/bm25").mkdir(parents=True)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            candidate = {"docs": {"one": {}}, "vocab": {}, "doc_count": 1}
            data = adapter.json.dumps(candidate, separators=(",", ":")).encode("utf-8")
            before = adapter.bounded_target_hash(vault, ".vault-meta/bm25/index.json")
            approval = writer.inspect_large_index(vault, data, before, {})["approval_sha256"]
            with patch.object(writer, "_release_lock", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    writer.publish_large_index(vault, data, before, {}, approval)
            self.assertTrue((vault / ".vault-meta/hermes-windows/write.lock").exists())
            with patch.object(sys, "argv", ["bm25_provision_native.py", "--vault", str(vault)]), \
                 patch.object(writer, "_pid_is_running", return_value=False), \
                 patch.object(adapter, "generate_chunk_mutations", return_value=([], [], 0, 0, [], {})), \
                 patch.object(adapter, "build_index_from_records", return_value=candidate):
                self.assertEqual(2, adapter.main())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())
            self.assertEqual(data, target.read_bytes())
