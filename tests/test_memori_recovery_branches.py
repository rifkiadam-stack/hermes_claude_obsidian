"""Both lawful --pulihkan outcomes, each forced by a real crashed process."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(sys.executable)
CAP = 4096

RUNNER = r'''
import json, sys
from claude_obsidian.memori_guard_mcp import MemoryGuard
print(json.dumps(MemoryGuard(sys.argv[1], int(sys.argv[3])).tulis(**json.loads(sys.argv[2]))))
'''


def make_vault(root: Path) -> Path:
    vault = root / 'vault'
    for folder in ('wiki/sesi', 'wiki/profil', 'sesi-log'):
        (vault / folder).mkdir(parents=True)
    (vault / 'sesi-log/profil-log.md').write_bytes(b'---\ntype: sesi-log\n---\nold\n')
    return vault


def request(key, paths):
    return {
        'kunci_operasi': key,
        'perubahan': [{'path': p, 'isi_baru': 'new-' + Path(p).stem, 'hash_lama': None} for p in paths],
        'tambahan_log': [],
        'alasan': 'recovery branch coverage',
    }


def run_write(vault: Path, payload: dict, fault: str | None = None):
    env = {k: v for k, v in os.environ.items() if k not in ('MEMORI_GUARD_TEST', 'MEMORI_GUARD_FAULT')}
    if fault:
        env.update(MEMORI_GUARD_TEST='1', MEMORI_GUARD_FAULT=fault)
    return subprocess.run([str(PYTHON), '-B', '-c', RUNNER, str(vault), json.dumps(payload), str(CAP)],
                          capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)


def records(vault: Path):
    return [json.loads(p.read_text(encoding='utf-8'))
            for p in (vault / '.vault-meta/memori-guard').glob('*.json')]


def manifest_of(vault: Path, operation_id: str):
    path = vault / '.vault-meta/hermes-windows/operations' / operation_id / 'manifest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def recover(vault: Path, operation_id: str):
    return subprocess.run([str(PYTHON), '-B', '-m', 'claude_obsidian.memori_guard_mcp', '--vault', str(vault),
                           '--batas-byte', str(CAP), '--pulihkan', operation_id],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=120)


@unittest.skipUnless(os.name == 'nt', 'native Windows guard semantics')
class RecoveryBranchTests(unittest.TestCase):
    def test_recovery_returns_dikembalikan_and_retry_runs_as_new_attempt(self):
        """No checkpoint yet: --pulihkan cancels, frees the key, retry executes."""
        with tempfile.TemporaryDirectory() as directory:
            vault = make_vault(Path(directory))
            payload = request('ingest: branch-rollback', ['wiki/sesi/pulih.md'])
            crashed = run_write(vault, payload, 'henti_setelah_catat_berjalan')
            self.assertNotEqual(crashed.returncode, 0, crashed.stdout)
            self.assertEqual(crashed.stdout.strip(), '')
            saved = records(vault)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['status'], 'berjalan')
            operation_id = saved[0]['operation']['operation_id']
            self.assertIsNone(manifest_of(vault, operation_id))
            self.assertFalse((vault / 'wiki/sesi/pulih.md').exists())

            result = recover(vault, operation_id)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {'operation_id': operation_id, 'hasil': 'dikembalikan',
                              'paths': ['wiki/sesi/pulih.md']})
            self.assertFalse((vault / 'wiki/sesi/pulih.md').exists())
            self.assertEqual(records(vault), [], 'cancelled attempt must release its operation key')

            retry = run_write(vault, payload)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)['status'], 'selesai')
            self.assertEqual((vault / 'wiki/sesi/pulih.md').read_text(encoding='utf-8'), 'new-pulih')

    def test_recovery_rolls_forward_diselesaikan_then_retry_is_sudah_ada(self):
        """Existing prepared checkpoint with one applied target: --pulihkan finishes it."""
        with tempfile.TemporaryDirectory() as directory:
            vault = make_vault(Path(directory))
            paths = ['wiki/sesi/pulih-a.md', 'wiki/sesi/pulih-b.md']
            payload = request('ingest: branch-rollforward', paths)
            crashed = run_write(vault, payload, 'henti_setelah_target_pertama')
            self.assertNotEqual(crashed.returncode, 0, crashed.stdout)
            saved = records(vault)
            self.assertEqual(saved[0]['status'], 'berjalan')
            operation_id = saved[0]['operation']['operation_id']
            self.assertEqual(manifest_of(vault, operation_id)['state'], 'prepared')

            result = recover(vault, operation_id)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {'operation_id': operation_id, 'hasil': 'diselesaikan', 'paths': paths})
            for path in paths:
                self.assertEqual((vault / path).read_text(encoding='utf-8'),
                                 'new-' + Path(path).stem)

            retry = run_write(vault, payload)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)['status'], 'sudah_ada')

    def test_recovery_failure_is_json_and_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = make_vault(Path(directory))
            result = recover(vault, 'missing-operation')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['status'], 'gagal')
            self.assertNotIn('hasil', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
