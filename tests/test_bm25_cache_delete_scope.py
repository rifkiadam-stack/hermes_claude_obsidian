from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claude_obsidian.hermes_windows_write import (
    OPERATION_SCHEMA,
    OperationValidationError,
    execute_operation,
    inspect_operation,
)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Bm25CacheDeleteScopeTests(unittest.TestCase):
    def make_vault(self, base: str) -> Path:
        vault = Path(base) / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "wiki").mkdir()
        return vault

    def test_guard_deletes_only_well_formed_bm25_chunk_file(self) -> None:
        for index, filename in enumerate(("chunk-000.json", "chunk-1000.json")):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                vault = self.make_vault(directory)
                relative = f".vault-meta/chunks/wiki--ndf/{filename}"
                target = vault / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(b'{"page":"wiki/ndf.md"}\n')
                operation = {
                    "schema": OPERATION_SCHEMA,
                    "operation_id": f"bm25-cache-delete-{index}",
                    "expected_hashes": {relative: digest(target.read_bytes())},
                    "writes": [],
                    "deletes": [relative],
                }

                approval = inspect_operation(vault, operation)["approval_sha256"]
                result = execute_operation(vault, operation, approval)

                self.assertEqual("complete", result["state"])
                self.assertFalse(target.exists())
                self.assertFalse(
                    (vault / ".vault-meta/hermes-windows/write.lock").exists()
                )

    def test_guard_rejects_nearby_metadata_delete_paths(self) -> None:
        rejected = [
            ".vault-meta/index/bm25.json",
            ".vault-meta/chunks/wiki--ndf/not-a-chunk.json",
            ".vault-meta/chunks/wiki--ndf/chunk-1.json",
            ".vault-meta/chunks/chunk-000.json",
            ".vault-meta/chunks/wiki--ndf/nested/chunk-000.json",
        ]
        for index, relative in enumerate(rejected):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                vault = self.make_vault(directory)
                target = vault / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"data")
                operation = {
                    "schema": OPERATION_SCHEMA,
                    "operation_id": f"reject-bm25-nearby-{index}",
                    "expected_hashes": {relative: digest(b"data")},
                    "writes": [],
                    "deletes": [relative],
                }

                with self.assertRaises(OperationValidationError):
                    inspect_operation(vault, operation)
                self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
