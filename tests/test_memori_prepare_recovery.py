"""Real-process and cross-version regressions for authenticated prepare recovery."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(sys.executable)
sys.path.insert(0, str(ROOT))
from claude_obsidian import hermes_windows_write as new_guard



def operation_for(vault: Path, operation_id: str):
    before = b"before"
    (vault / "target.md").write_bytes(before)
    return {
        "schema": new_guard.OPERATION_SCHEMA,
        "operation_id": operation_id,
        "expected_hashes": {"target.md": new_guard.sha256_bytes(before)},
        "writes": [{"path": "target.md", "content": "after"}],
        "deletes": [],
    }


def prepare_crash(vault: Path, operation, stage="after_operation_dir"):
    script = r'''
import os, sys
from pathlib import Path
from claude_obsidian import hermes_windows_write as g
vault, raw, stage = sys.argv[1:]
op = g.strict_json_loads(raw.encode())
plan = g.inspect_operation(vault, op)
original_dir = g._safe_directory
original_json = g._atomic_json
def crash_dir(root, relative, *, create=False):
    if stage == 'before_operations_dir' and relative == '.vault-meta/hermes-windows/operations':
        os._exit(88)
    result = original_dir(root, relative, create=create)
    if stage == 'after_operation_dir' and relative == '.vault-meta/hermes-windows/operations/' + op['operation_id']:
        os._exit(88)
    return result
def crash_json(path, value):
    if stage == 'after_before_copy' and Path(path).name == 'manifest.json':
        os._exit(88)
    if stage == 'after_manifest' and Path(path).name == 'operation.json':
        os._exit(88)
    return original_json(path, value)
g._safe_directory = crash_dir
g._atomic_json = crash_json
g.prepare_operation(vault, op, plan['approval_sha256'])
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    run = subprocess.run(
        [str(PYTHON), "-B", "-c", script, str(vault), json.dumps(operation), stage],
        env=env, cwd=ROOT, capture_output=True, text=True,
    )
    if run.returncode != 88:
        raise AssertionError(f"crash child exit={run.returncode}: {run.stderr}")
    plan = new_guard.inspect_operation(vault, operation)
    return plan["approval_sha256"]


class PrepareRecoveryTests(unittest.TestCase):
    def test_real_crash_authenticated_recovery_then_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            op = operation_for(vault, "crash-retry")
            approval = prepare_crash(vault, op)
            lock = vault / ".vault-meta/hermes-windows/write.lock"
            self.assertTrue((lock / "owner.json").is_file())
            self.assertEqual((vault / "target.md").read_bytes(), b"before")
            result = new_guard.recover_interrupted_preparation(vault, op, approval)
            self.assertEqual(result, {"state": "cancelled", "operation_id": op["operation_id"]})
            self.assertFalse(lock.exists())
            self.assertTrue((vault / ".vault-meta/hermes-windows/operations" / op["operation_id"]).is_dir())
            retry = dict(op, operation_id="crash-retry-again")
            retry_plan = new_guard.inspect_operation(vault, retry)
            new_guard.execute_operation(vault, retry, retry_plan["approval_sha256"])
            self.assertEqual((vault / "target.md").read_bytes(), b"after")

    def test_all_pre_execute_crash_windows_abort_and_retry_without_deleting_diagnostics(self):
        for stage in ("before_operations_dir", "after_before_copy", "after_manifest"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp)
                op = operation_for(vault, "window-" + stage)
                approval = prepare_crash(vault, op, stage)
                operations = vault / ".vault-meta/hermes-windows/operations"
                operation_root = operations / op["operation_id"]
                before_image = operation_root / "before/target.md"
                if stage == "before_operations_dir":
                    self.assertFalse(operations.exists())
                elif stage == "after_before_copy":
                    self.assertEqual(before_image.read_bytes(), b"before")
                else:
                    self.assertTrue((operation_root / "manifest.json").is_file())
                new_guard.recover_interrupted_preparation(vault, op, approval)
                self.assertFalse((vault / ".vault-meta/hermes-windows/write.lock").exists())
                if before_image.exists():
                    self.assertEqual(before_image.read_bytes(), b"before")
                retry = dict(op, operation_id="retry-" + stage)
                retry_plan = new_guard.inspect_operation(vault, retry)
                new_guard.execute_operation(vault, retry, retry_plan["approval_sha256"])
                self.assertEqual((vault / "target.md").read_bytes(), b"after")

    def test_incomplete_checkpoint_metadata_must_match_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            op = operation_for(vault, "bad-partial-manifest")
            approval = prepare_crash(vault, op, "after_manifest")
            manifest_path = vault / ".vault-meta/hermes-windows/operations" / op["operation_id"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["approval_sha256"] = "sha256:" + "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(new_guard.OperationValidationError):
                new_guard.recover_interrupted_preparation(vault, op, approval)
            self.assertTrue((vault / ".vault-meta/hermes-windows/write.lock/owner.json").is_file())

    def test_valid_complete_checkpoint_is_reserved_to_prepared_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            op = operation_for(vault, "complete-checkpoint")
            approval = new_guard.inspect_operation(vault, op)["approval_sha256"]
            new_guard.prepare_operation(vault, op, approval)
            with mock.patch.object(new_guard, "_pid_is_running", return_value=False):
                with self.assertRaises(new_guard.OperationValidationError):
                    new_guard.recover_interrupted_preparation(vault, op, approval)

    def test_recovery_refuses_live_remote_tampered_drift_and_ownerless_claims(self):
        cases = ("live", "remote", "tampered", "drift", "ownerless")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp)
                op = operation_for(vault, "refuse-" + case)
                approval = prepare_crash(vault, op)
                owner_path = vault / ".vault-meta/hermes-windows/write.lock/owner.json"
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                if case == "live":
                    owner["pid"] = os.getpid()
                    owner["host"] = socket.gethostname()
                    owner_path.write_text(json.dumps(owner), encoding="utf-8")
                elif case == "remote":
                    owner["host"] = "not-this-host.invalid"
                    owner_path.write_text(json.dumps(owner), encoding="utf-8")
                elif case == "tampered":
                    owner["approval_sha256"] = "sha256:" + "0" * 64
                    owner_path.write_text(json.dumps(owner), encoding="utf-8")
                elif case == "drift":
                    (vault / "target.md").write_bytes(b"unexpected")
                elif case == "ownerless":
                    owner_path.unlink()
                with self.assertRaises((new_guard.CooperativeLockError,
                                        new_guard.ConcurrentDriftError,
                                        new_guard.OperationValidationError)):
                    new_guard.recover_interrupted_preparation(vault, op, approval)
                self.assertTrue((vault / ".vault-meta/hermes-windows/write.lock").exists())

    def test_recovery_refuses_tampered_runtime_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            op = operation_for(vault, "runtime-chain")
            approval = prepare_crash(vault, op)
            runtime = vault / ".vault-meta/hermes-windows"
            operations = runtime / "operations"
            parked = runtime / "operations.saved"
            operations.rename(parked)
            operations.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(new_guard.OperationValidationError):
                new_guard.recover_interrupted_preparation(vault, op, approval)
            self.assertTrue((parked / op["operation_id"]).is_dir())
            self.assertTrue((runtime / "write.lock/owner.json").is_file())

    @unittest.skip("Cross-version comparison needs an external baseline snapshot; intentionally excluded from public tests.")
    def test_original_and_new_guards_mutually_exclude_in_shared_lock_namespace(self):
        self.fail("baseline snapshot is not bundled")


if __name__ == "__main__":
    unittest.main()
