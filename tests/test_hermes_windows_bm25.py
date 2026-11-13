"""Index-only native Windows writer: bounded atomic derived-state publication."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_obsidian.hermes_windows_bm25 import (
    CooperativeLockError,
    ConcurrentDriftError,
    OperationValidationError,
    inspect_large_index,
    publish_large_index,
    recover_large_index_lock,
)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class LargeBm25IndexTests(unittest.TestCase):
    def make_vault(self, root: str) -> Path:
        vault = Path(root) / "vault"
        (vault / "wiki").mkdir(parents=True)
        (vault / ".vault-meta" / "bm25").mkdir(parents=True)
        return vault

    def test_large_index_publishes_without_widening_generic_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta" / "bm25" / "index.json"
            target.write_bytes(b"old")
            page = vault / "wiki" / "source.md"
            page.write_bytes(b"source")
            candidate = b'{"padding":"' + b"x" * (9 * 1024 * 1024) + b'"}'
            preconditions = {"wiki/source.md": digest(b"source")}
            plan = inspect_large_index(vault, candidate, digest(b"old"), preconditions)
            result = publish_large_index(vault, candidate, digest(b"old"), preconditions, plan["approval_sha256"])
            self.assertEqual("complete", result["state"])
            self.assertEqual(digest(candidate), digest(target.read_bytes()))
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())

    def test_changed_source_is_rejected_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            page = vault / "wiki/source.md"
            page.write_bytes(b"source")
            preconditions = {"wiki/source.md": digest(b"source")}
            candidate = b'{}'
            approval = inspect_large_index(vault, candidate, digest(b"old"), preconditions)["approval_sha256"]
            page.write_bytes(b"changed")
            with self.assertRaises(ConcurrentDriftError):
                publish_large_index(vault, candidate, digest(b"old"), preconditions, approval)
            self.assertEqual(b"old", target.read_bytes())

    def test_wrong_approval_is_rejected_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            with self.assertRaises(OperationValidationError):
                publish_large_index(vault, b'{}', digest(b"old"), {}, digest(b"not approved"))
            self.assertEqual(b"old", target.read_bytes())

    def test_drift_while_staging_preserves_old_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            candidate = b'{"new":1}'
            approval = inspect_large_index(vault, candidate, digest(b"old"), {})["approval_sha256"]
            from claude_obsidian import hermes_windows_bm25 as mod
            real = mod._stage_index
            def stage_and_drift(*args, **kwargs):
                staged = real(*args, **kwargs)
                target.write_bytes(b"external")
                return staged
            with patch.object(mod, "_stage_index", side_effect=stage_and_drift):
                with self.assertRaises(ConcurrentDriftError):
                    publish_large_index(vault, candidate, digest(b"old"), {}, approval)
            self.assertEqual(b"external", target.read_bytes())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())

    def test_caller_mutation_cannot_drop_reviewed_read_preconditions(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            page = vault / "wiki/source.md"
            page.write_bytes(b"before")
            reads = {"wiki/source.md": digest(b"before")}
            candidate = b'{"new":1}'
            approval = inspect_large_index(vault, candidate, digest(b"old"), reads)["approval_sha256"]
            original = mod._stage_index
            def stage_and_mutate(*args, **kwargs):
                staged = original(*args, **kwargs)
                reads.clear()
                page.write_bytes(b"after")
                return staged
            with patch.object(mod, "_stage_index", side_effect=stage_and_mutate):
                with self.assertRaises(ConcurrentDriftError):
                    publish_large_index(vault, candidate, digest(b"old"), reads, approval)
            self.assertEqual(b"old", target.read_bytes())

    def test_interrupted_after_replace_can_recover_derived_index(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            candidate = b'{"new":1}'
            approval = inspect_large_index(vault, candidate, digest(b"old"), {})["approval_sha256"]
            with patch.object(mod, "_release_lock", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    publish_large_index(vault, candidate, digest(b"old"), {}, approval)
            self.assertEqual(candidate, target.read_bytes())
            self.assertTrue((vault / ".vault-meta/hermes-windows/write.lock").exists())
            with patch.object(mod, "_pid_is_running", return_value=False):
                result = recover_large_index_lock(vault)
            self.assertEqual("recovered", result["state"])
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_index_parent_junction_cannot_redirect_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            (vault / "wiki").mkdir(parents=True)
            (vault / ".vault-meta").mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            junction = vault / ".vault-meta/bm25"
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True)
            if result.returncode:
                self.skipTest("mklink /J unavailable")
            with self.assertRaises(OperationValidationError):
                inspect_large_index(vault, b'{}', None, {})
            self.assertEqual([], list(outside.iterdir()))

    def test_shared_hermes_lock_blocks_index_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            data = b'{"new":1}'
            approval = inspect_large_index(vault, data, digest(b"old"), {})["approval_sha256"]
            lock = vault / ".vault-meta/hermes-windows/write.lock"
            lock.mkdir(parents=True)
            with self.assertRaises(CooperativeLockError):
                publish_large_index(vault, data, digest(b"old"), {}, approval)
            self.assertEqual(b"old", target.read_bytes())

    def test_staged_bytes_swapped_before_replace_restore_old_index(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            candidate = b'{"new":1}'
            approval = inspect_large_index(vault, candidate, digest(b"old"), {})["approval_sha256"]
            real_replace = os.replace
            def swap_stage(source, destination):
                if Path(destination).name == "index.json" and Path(source).name.startswith(".index-") and Path(source).name.endswith(".tmp"):
                    Path(source).write_bytes(b'{"unapproved":true}')
                return real_replace(source, destination)
            with patch.object(mod.os, "replace", side_effect=swap_stage):
                with self.assertRaises(ConcurrentDriftError):
                    publish_large_index(vault, candidate, digest(b"old"), {}, approval)
            self.assertEqual(b"old", target.read_bytes())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())
            self.assertEqual([], list(target.parent.glob(".index-*")))

    def test_stage_fsync_failure_leaves_no_payload_or_lock(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            data = b'{"new":1}'
            approval = inspect_large_index(vault, data, digest(b"old"), {})["approval_sha256"]
            with patch.object(mod.os, "fsync", side_effect=OSError("injected fsync")):
                with self.assertRaises(OSError):
                    publish_large_index(vault, data, digest(b"old"), {}, approval)
            self.assertEqual(b"old", target.read_bytes())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())
            self.assertEqual([], list(target.parent.glob(".index-*")))

    def test_crash_after_unapproved_replace_recovers_old_derived_index(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            data = b'{"new":1}'
            approval = inspect_large_index(vault, data, digest(b"old"), {})["approval_sha256"]
            real_replace = os.replace
            def replace_then_crash(source, destination):
                if Path(destination).name == "index.json" and Path(source).name.endswith(".tmp"):
                    Path(source).write_bytes(b'{"unapproved":true}')
                    real_replace(source, destination)
                    raise SystemExit("simulated crash")
                return real_replace(source, destination)
            with patch.object(mod.os, "replace", side_effect=replace_then_crash):
                with self.assertRaises(SystemExit):
                    publish_large_index(vault, data, digest(b"old"), {}, approval)
            with patch.object(mod, "_pid_is_running", return_value=False):
                result = recover_large_index_lock(vault)
            self.assertEqual("recovered", result["state"])
            self.assertEqual(b"old", target.read_bytes())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())

    def test_partial_owner_write_cleans_temp_and_lock(self) -> None:
        from claude_obsidian import hermes_windows_bm25 as mod
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / ".vault-meta/bm25/index.json"
            target.write_bytes(b"old")
            data = b'{"new":1}'
            approval = inspect_large_index(vault, data, digest(b"old"), {})["approval_sha256"]
            def partial_owner(path, owner):
                tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
                tmp.write_text("partial", encoding="utf-8")
                raise OSError("injected owner write failure")
            with patch.object(mod, "_atomic_json", side_effect=partial_owner):
                with self.assertRaises(OSError):
                    publish_large_index(vault, data, digest(b"old"), {}, approval)
            self.assertEqual(b"old", target.read_bytes())
            self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())
