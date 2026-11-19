"""Concurrent first-use must not reject a vault that another writer initialised."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(sys.executable)

CHILD = r'''
import json, sys, time
from claude_obsidian.memori_guard_mcp import MemoryGuard
vault, start_at, tag = sys.argv[1], float(sys.argv[2]), sys.argv[3]
delay = start_at - time.time()
if delay > 0:
    time.sleep(delay)
try:
    guard = MemoryGuard(vault, 4096)
    runtime = guard._runtime()
    print(json.dumps({"tag": tag, "ok": True, "runtime": str(runtime)}))
except Exception as exc:
    print(json.dumps({"tag": tag, "ok": False, "error": type(exc).__name__, "detail": str(exc)}))
'''


@unittest.skipUnless(os.name == 'nt', 'native Windows guard semantics')
class RuntimeCreationConcurrencyTests(unittest.TestCase):
    def _vault(self, root: Path) -> Path:
        vault = root / 'vault'
        for folder in ('wiki/sesi', 'wiki/profil', 'sesi-log'):
            (vault / folder).mkdir(parents=True)
        return vault

    def test_concurrent_first_use_creates_runtime_once_without_false_rejection(self):
        """Regression: T8 pattern A - a valid request was denied while the runtime
        directory was being created by another process."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for round_index in range(2):
                vault = self._vault(root / f'round-{round_index}')
                start_at = time.time() + 1.5
                workers = 16
                procs = [subprocess.Popen(
                    [str(PYTHON), '-B', '-c', CHILD, str(vault), str(start_at), str(index)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(ROOT))
                    for index in range(workers)]
                outcomes = []
                for proc in procs:
                    stdout, stderr = proc.communicate(timeout=180)
                    line = stdout.strip().splitlines()
                    self.assertEqual(proc.returncode, 0, stderr)
                    self.assertTrue(line, stderr)
                    outcomes.append(json.loads(line[-1]))
                failures = [outcome for outcome in outcomes if not outcome['ok']]
                self.assertEqual(failures, [], 'concurrent runtime creation was rejected')
                self.assertTrue((vault / '.vault-meta/memori-guard').is_dir())

    def test_runtime_junction_escape_is_still_rejected(self):
        """The concurrency retry must not loosen alias or junction rejection."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self._vault(root)
            outside = root / 'outside'
            outside.mkdir()
            (vault / '.vault-meta').mkdir()
            junction = vault / '.vault-meta/memori-guard'
            made = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)],
                                  capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            try:
                from claude_obsidian.memori_guard_mcp import MemoryGuard
                from claude_obsidian.memori_validasi import MemoryValidationError
                with self.assertRaises((MemoryValidationError, ValueError)):
                    MemoryGuard(vault, 4096)._runtime()
                self.assertEqual(list(outside.iterdir()), [], 'nothing may be created outside the vault')
            finally:
                junction.rmdir()


if __name__ == '__main__':
    unittest.main()
