#!/usr/bin/env python3
"""Behavioral tests for the reduced-guarantee Hermes Windows write guard."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claude_obsidian.hermes_windows_write import (
    CooperativeLockError,
    OPERATION_SCHEMA,
    OperationValidationError,
    inspect_operation,
    prepare_operation,
    rollback_operation,
    verify_operation,
)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class HermesWindowsWriteGuardTests(unittest.TestCase):
    def make_vault(self, base: str) -> Path:
        vault = Path(base) / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "wiki").mkdir()
        return vault

    def test_inspect_accepts_bounded_operation_and_binds_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            existing = vault / "wiki" / "Existing.md"
            existing.write_bytes(b"# Existing\r\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "save-001",
                "expected_hashes": {
                    "wiki/Existing.md": digest(b"# Existing\r\n"),
                    "wiki/New.md": None,
                },
                "writes": [
                    {"path": "wiki/Existing.md", "content": "# Updated\n"},
                    {"path": "wiki/New.md", "content": "# New\n"},
                ],
            }

            plan = inspect_operation(vault, operation)

            self.assertTrue(plan["valid"])
            self.assertEqual(
                ["wiki/Existing.md", "wiki/New.md"], plan["changed_paths"]
            )
            self.assertRegex(plan["approval_sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual("reduced", plan["guarantee_level"])
            self.assertFalse(plan["upstream_transaction_equivalent"])

    def test_prepare_rechecks_and_creates_checkpoint_under_cooperative_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            existing = vault / "wiki" / "Existing.md"
            existing.write_bytes(b"before\r\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "save-002",
                "expected_hashes": {
                    "wiki/Existing.md": digest(b"before\r\n"),
                    "wiki/New.md": None,
                },
                "writes": [
                    {"path": "wiki/Existing.md", "content": "after\n"},
                    {"path": "wiki/New.md", "content": "new\n"},
                ],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]

            prepared = prepare_operation(vault, operation, approval)

            runtime = vault / ".vault-meta" / "hermes-windows"
            self.assertEqual("prepared", prepared["state"])
            self.assertTrue((runtime / "write.lock").is_dir())
            self.assertTrue(
                (runtime / "operations" / "save-002" / "manifest.json").is_file()
            )
            self.assertEqual(
                b"before\r\n",
                (
                    runtime
                    / "operations"
                    / "save-002"
                    / "before"
                    / "wiki"
                    / "Existing.md"
                ).read_bytes(),
            )
            self.assertFalse(
                (
                    runtime
                    / "operations"
                    / "save-002"
                    / "before"
                    / "wiki"
                    / "New.md"
                ).exists()
            )

    def test_verify_confirms_external_writes_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / "wiki" / "Result.md"
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "save-003",
                "expected_hashes": {"wiki/Result.md": None},
                "writes": [{"path": "wiki/Result.md", "content": "result\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            target.write_text("result\n", encoding="utf-8", newline="\n")

            result = verify_operation(vault, operation, approval)

            runtime = vault / ".vault-meta" / "hermes-windows"
            self.assertEqual("complete", result["state"])
            self.assertFalse((runtime / "write.lock").exists())
            manifest = (
                runtime / "operations" / "save-003" / "manifest.json"
            ).read_text(encoding="utf-8")
            self.assertIn('"state": "complete"', manifest)

    def test_rollback_restores_before_images_and_removes_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            existing = vault / "wiki" / "Existing.md"
            created = vault / "wiki" / "Created.md"
            existing.write_bytes(b"original\r\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "save-004",
                "expected_hashes": {
                    "wiki/Existing.md": digest(b"original\r\n"),
                    "wiki/Created.md": None,
                },
                "writes": [
                    {"path": "wiki/Existing.md", "content": "changed\n"},
                    {"path": "wiki/Created.md", "content": "created\n"},
                ],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            existing.write_text("changed\n", encoding="utf-8", newline="\n")
            created.write_text("created\n", encoding="utf-8", newline="\n")

            result = rollback_operation(vault, operation, approval)

            runtime = vault / ".vault-meta" / "hermes-windows"
            self.assertEqual("rolled-back", result["state"])
            self.assertEqual(b"original\r\n", existing.read_bytes())
            self.assertFalse(created.exists())
            self.assertFalse((runtime / "write.lock").exists())

    def test_inspect_reuses_upstream_portable_write_path_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            for unsafe in (
                "wiki/CON.md",
                "wiki/alternate:stream.md",
                "wiki/trailing./note.md",
                "../outside.md",
            ):
                operation = {
                    "schema": OPERATION_SCHEMA,
                    "operation_id": "unsafe-path",
                    "expected_hashes": {unsafe: None},
                    "writes": [{"path": unsafe, "content": "x"}],
                }
                with self.subTest(path=unsafe):
                    with self.assertRaises(OperationValidationError):
                        inspect_operation(vault, operation)

    def test_prepare_rejects_unsafe_runtime_path_before_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "unsafe-runtime",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            (vault / ".vault-meta").write_text("not a directory", encoding="utf-8")

            with self.assertRaises(OperationValidationError):
                prepare_operation(vault, operation, approval)

            self.assertFalse((vault / "wiki" / "New.md").exists())

    def test_reused_operation_id_never_deletes_existing_audit_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / "wiki" / "Result.md"
            first = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "immutable-id",
                "expected_hashes": {"wiki/Result.md": None},
                "writes": [{"path": "wiki/Result.md", "content": "first\n"}],
            }
            approval = inspect_operation(vault, first)["approval_sha256"]
            prepare_operation(vault, first, approval)
            target.write_text("first\n", encoding="utf-8", newline="\n")
            verify_operation(vault, first, approval)
            manifest = (
                vault
                / ".vault-meta"
                / "hermes-windows"
                / "operations"
                / "immutable-id"
                / "manifest.json"
            )
            before = manifest.read_bytes()
            second = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "immutable-id",
                "expected_hashes": {"wiki/Result.md": digest(b"first\n")},
                "writes": [{"path": "wiki/Result.md", "content": "second\n"}],
            }
            second_approval = inspect_operation(vault, second)["approval_sha256"]

            with self.assertRaises(OperationValidationError):
                prepare_operation(vault, second, second_approval)

            self.assertTrue(manifest.is_file())
            self.assertEqual(before, manifest.read_bytes())

    def test_runtime_manifest_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "strict-json",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            manifest = (
                vault
                / ".vault-meta"
                / "hermes-windows"
                / "operations"
                / "strict-json"
                / "manifest.json"
            )
            text = manifest.read_text(encoding="utf-8").replace(
                '"state": "prepared"',
                '"state": "complete",\n  "state": "prepared"',
            )
            manifest.write_text(text, encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(OperationValidationError, "duplicate"):
                verify_operation(vault, operation, approval)

    def test_inspect_rejects_nonportable_operation_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            for operation_id in (".", "..", "CON", "trailing."):
                operation = {
                    "schema": OPERATION_SCHEMA,
                    "operation_id": operation_id,
                    "expected_hashes": {"wiki/New.md": None},
                    "writes": [{"path": "wiki/New.md", "content": "new\n"}],
                }
                with self.subTest(operation_id=operation_id):
                    with self.assertRaises(OperationValidationError):
                        inspect_operation(vault, operation)

    def test_inspect_rejects_protected_and_casefold_colliding_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            for relative in (
                ".git/hooks/post-checkout",
                ".vault-meta/hermes-windows/write.lock/owner.json",
            ):
                operation = {
                    "schema": OPERATION_SCHEMA,
                    "operation_id": "protected",
                    "expected_hashes": {relative: None},
                    "writes": [{"path": relative, "content": "x\n"}],
                }
                with self.subTest(relative=relative):
                    with self.assertRaises(OperationValidationError):
                        inspect_operation(vault, operation)

            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "aliases",
                "expected_hashes": {"wiki/A.md": None, "wiki/a.md": None},
                "writes": [
                    {"path": "wiki/A.md", "content": "A\n"},
                    {"path": "wiki/a.md", "content": "a\n"},
                ],
            }
            with self.assertRaises(OperationValidationError):
                inspect_operation(vault, operation)

    def test_verify_revalidates_runtime_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "runtime-swap",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            meta = vault / ".vault-meta"
            meta.rename(vault / ".vault-meta-old")
            meta.write_text("unsafe replacement", encoding="utf-8")

            with self.assertRaises(OperationValidationError):
                verify_operation(vault, operation, approval)

    def test_verify_rejects_manifest_target_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "tampered-manifest",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            manifest_path = vault / ".vault-meta/hermes-windows/operations/tampered-manifest/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["targets"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(OperationValidationError):
                verify_operation(vault, operation, approval)

    def test_prepare_rejects_corrupt_completed_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / "wiki" / "Old.md"
            target.write_text("old\n", encoding="utf-8", newline="\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "bad-copy",
                "expected_hashes": {"wiki/Old.md": digest(b"old\n")},
                "writes": [{"path": "wiki/Old.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]

            def corrupt_copy(_source: Path, destination: Path) -> None:
                Path(destination).write_bytes(b"corrupt\n")

            with patch("claude_obsidian.hermes_windows_write.shutil.copyfile", corrupt_copy):
                with self.assertRaises(OperationValidationError):
                    prepare_operation(vault, operation, approval)

    def test_rollback_preflights_all_backups_before_any_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            first = vault / "wiki" / "First.md"
            second = vault / "wiki" / "Second.md"
            first.write_text("first-old\n", encoding="utf-8", newline="\n")
            second.write_text("second-old\n", encoding="utf-8", newline="\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "rollback-preflight",
                "expected_hashes": {
                    "wiki/First.md": digest(b"first-old\n"),
                    "wiki/Second.md": digest(b"second-old\n"),
                },
                "writes": [
                    {"path": "wiki/First.md", "content": "first-new\n"},
                    {"path": "wiki/Second.md", "content": "second-new\n"},
                ],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            first.write_text("first-new\n", encoding="utf-8", newline="\n")
            second.write_text("second-new\n", encoding="utf-8", newline="\n")
            backup = vault / ".vault-meta/hermes-windows/operations/rollback-preflight/before/wiki/First.md"
            backup.write_bytes(b"corrupt\n")

            with self.assertRaises(OperationValidationError):
                rollback_operation(vault, operation, approval)

            self.assertEqual(b"first-new\n", first.read_bytes())
            self.assertEqual(b"second-new\n", second.read_bytes())

    def test_runtime_operation_cannot_replace_orchestrator_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "authority",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            operation_path = vault / ".vault-meta/hermes-windows/operations/authority/operation.json"
            tampered = dict(operation)
            tampered["writes"] = [{"path": "wiki/New.md", "content": "evil\n"}]
            operation_path.write_text(json.dumps(tampered), encoding="utf-8")

            with self.assertRaises(OperationValidationError):
                verify_operation(vault, operation, approval)

    def test_inspect_enforces_resource_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "bounded",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "0123456789"}],
            }
            with patch(
                "claude_obsidian.hermes_windows_write.MAX_TRANSACTION_FILE_BYTES",
                4,
            ):
                with self.assertRaises(OperationValidationError):
                    inspect_operation(vault, operation)

    def test_expected_hash_aliases_are_rejected_during_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "expected-alias",
                "expected_hashes": {"wiki/A.md": None, "wiki/a.md": None},
                "writes": [{"path": "wiki/A.md", "content": "A\n"}],
            }
            with self.assertRaises(OperationValidationError):
                inspect_operation(vault, operation)

    def test_nonfinite_operation_is_rejected_before_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "nan",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
                "untrusted": float("nan"),
            }
            with self.assertRaises(OperationValidationError):
                inspect_operation(vault, operation)

    def test_release_failure_keeps_prepared_state_retriable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "release-retry",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            (vault / "wiki/New.md").write_text("new\n", encoding="utf-8", newline="\n")
            lock = vault / ".vault-meta/hermes-windows/write.lock"
            unexpected = lock / "unexpected.txt"
            unexpected.write_text("x", encoding="utf-8")

            with self.assertRaises(CooperativeLockError):
                verify_operation(vault, operation, approval)

            manifest_path = vault / ".vault-meta/hermes-windows/operations/release-retry/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("prepared", manifest["state"])
            unexpected.unlink()
            self.assertEqual(
                "complete", verify_operation(vault, operation, approval)["state"]
            )

    def test_rollback_rejects_oversize_backup_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / "wiki/Old.md"
            target.write_text("old\n", encoding="utf-8", newline="\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "backup-limit",
                "expected_hashes": {"wiki/Old.md": digest(b"old\n")},
                "writes": [{"path": "wiki/Old.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            target.write_text("new\n", encoding="utf-8", newline="\n")
            with patch(
                "claude_obsidian.hermes_windows_write.MAX_TRANSACTION_FILE_BYTES",
                3,
            ):
                with self.assertRaisesRegex(OperationValidationError, "limit"):
                    rollback_operation(vault, operation, approval)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_prepare_rejects_operations_junction(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            runtime = vault / ".vault-meta/hermes-windows"
            runtime.mkdir(parents=True)
            outside = Path(directory) / "outside"
            outside.mkdir()
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(runtime / "operations"), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest("junction creation unavailable")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "junction",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            with self.assertRaises(OperationValidationError):
                prepare_operation(vault, operation, approval)
            self.assertFalse((outside / "junction/manifest.json").exists())

    def test_prepare_bounds_completed_checkpoint_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            target = vault / "wiki/Old.md"
            target.write_text("old\n", encoding="utf-8", newline="\n")
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "grown-copy",
                "expected_hashes": {"wiki/Old.md": digest(b"old\n")},
                "writes": [{"path": "wiki/Old.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]

            def growing_copy(_source: Path, destination: Path) -> None:
                Path(destination).write_bytes(b"12345")

            with patch(
                "claude_obsidian.hermes_windows_write.shutil.copyfile", growing_copy
            ), patch(
                "claude_obsidian.hermes_windows_write.MAX_TRANSACTION_FILE_BYTES",
                4,
            ):
                with self.assertRaisesRegex(OperationValidationError, "limit"):
                    prepare_operation(vault, operation, approval)

    def test_lock_enumeration_rejects_first_unexpected_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = self.make_vault(directory)
            operation = {
                "schema": OPERATION_SCHEMA,
                "operation_id": "bounded-lock",
                "expected_hashes": {"wiki/New.md": None},
                "writes": [{"path": "wiki/New.md", "content": "new\n"}],
            }
            approval = inspect_operation(vault, operation)["approval_sha256"]
            prepare_operation(vault, operation, approval)
            (vault / "wiki/New.md").write_text("new\n", encoding="utf-8", newline="\n")
            consumed = {"count": 0}

            def many_entries(path: Path):
                for index in range(5001):
                    consumed["count"] += 1
                    yield path / f"unexpected-{index}"

            with patch.object(Path, "iterdir", many_entries):
                with self.assertRaises(CooperativeLockError):
                    verify_operation(vault, operation, approval)

            self.assertEqual(1, consumed["count"])
            self.assertEqual(
                "complete", verify_operation(vault, operation, approval)["state"]
            )


if __name__ == "__main__":
    unittest.main()
