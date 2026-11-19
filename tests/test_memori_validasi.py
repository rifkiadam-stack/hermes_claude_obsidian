"""Memory-specific validation; fixtures never use the configured live vault."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MemoryPathTests(unittest.TestCase):
    def test_confined_memory_paths_and_read_only_templates(self):
        try:
            helper = importlib.import_module('claude_obsidian.memori_validasi')
        except ModuleNotFoundError:
            self.fail('shared memory validation helper is not implemented')
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            for folder in ('wiki/sesi', 'wiki/profil', 'sesi-log'):
                (vault / folder).mkdir(parents=True, exist_ok=True)
            for path in ('wiki/sesi/topik.md', 'wiki/profil/profil.md', 'sesi-log/topik-log.md'):
                helper.validate_path(vault, path, write=True)
            for path in ('_konvensi-memori.md', '_template-sesi.md', '_template-sesi-log.md'):
                helper.validate_path(vault, path, write=False)
                with self.assertRaises(helper.MemoryValidationError):
                    helper.validate_path(vault, path, write=True)
            for path in ('wiki/index.md', '../outside.md', '/wiki/sesi/a.md',
                         'C:/wiki/sesi/a.md', 'wiki/sesi/../profil/a.md',
                         'wiki//sesi/a.md', 'wiki/sesi/./a.md',
                         'wiki\\sesi\\a.md', 'Wiki/sesi/a.md',
                         'wiki/sesi/a.MD', 'wiki/sesi/a.md.',
                         'wiki/sesi/a.md:stream', 'wiki/sesi/NUL.md',
                         'wiki/sesi/a.txt', 'wiki/sesi/a\x00.md'):
                with self.subTest(path=path):
                    with self.assertRaises(helper.MemoryValidationError):
                        helper.validate_path(vault, path, write=True)
            (vault / 'wiki/sesi/Existing.md').write_bytes(b'old')
            with self.assertRaises(helper.MemoryValidationError):
                helper.validate_path(vault, 'wiki/sesi/existing.md', write=True)

    def test_log_validation_preserves_existing_bytes(self):
        helper = importlib.import_module('claude_obsidian.memori_validasi')
        self.assertTrue(hasattr(helper, 'validate_content'), 'append-only validator is not implemented')
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / 'sesi-log').mkdir()
            path = 'sesi-log/topik-log.md'
            old = b'---\r\ntype: sesi-log\r\n---\r\nold\r\n'
            (vault / path).write_bytes(old)
            new = old + b'\r\nnew\r\n'
            self.assertEqual(helper.validate_content(vault, path, new.decode('utf-8')), old)
            with self.assertRaises(helper.MemoryValidationError):
                helper.validate_content(vault, path, old.decode().replace('\r\n', '\n') + '\nnew\n')
            with self.assertRaises(helper.MemoryValidationError):
                helper.validate_content(vault, path, 'replacement')
            self.assertEqual((vault / path).read_bytes(), old)
            with self.assertRaises(helper.MemoryValidationError):
                helper.validate_content(vault, path, 'x' * (helper.MAX_TRANSACTION_FILE_BYTES + 1))
            self.assertIsNone(helper.validate_content(vault, 'sesi-log/new-log.md', 'new'))

    @unittest.skipUnless(os.name == 'nt', 'requires Windows junctions')
    def test_real_junction_parent_is_rejected(self):
        try:
            helper = importlib.import_module('claude_obsidian.memori_validasi')
        except ModuleNotFoundError:
            self.fail('shared memory validation helper is not implemented')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / 'vault'
            (vault / 'wiki').mkdir(parents=True)
            outside = root / 'outside'
            outside.mkdir()
            junction = vault / 'wiki/sesi'
            result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                with self.assertRaises(helper.MemoryValidationError):
                    helper.validate_path(vault, 'wiki/sesi/escape.md', write=True)
            finally:
                junction.rmdir()
            self.assertEqual(list(outside.iterdir()), [])


    def test_oversize_log_names_next_nonexistent_continuation(self):
        helper = importlib.import_module('claude_obsidian.memori_validasi')
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / 'sesi-log').mkdir()
            old = b'---\ntype: sesi-log\n---\nold\n'
            (vault / 'sesi-log/uji-besar-log.md').write_bytes(old)
            with self.assertRaises(helper.MemoryValidationError) as first:
                helper.validate_content(vault, 'sesi-log/uji-besar-log.md', old.decode() + 'x' * 64,
                                        max_file_bytes=32)
            self.assertIn('sesi-log/uji-besar-log-2.md', str(first.exception))
            self.assertNotIn('<topik>', str(first.exception))
            (vault / 'sesi-log/uji-besar-log-2.md').write_bytes(b'second\n')
            with self.assertRaises(helper.MemoryValidationError) as second:
                helper.validate_content(vault, 'sesi-log/uji-besar-log.md', old.decode() + 'x' * 64,
                                        max_file_bytes=32)
            self.assertIn('sesi-log/uji-besar-log-3.md', str(second.exception))
            # One rejection for the whole assembled request, not a repeated sentence.
            reasons = helper.validate_operation(vault, {
                'kunci_operasi': 'ingest: big',
                'perubahan': [],
                'tambahan_log': [{'path': 'sesi-log/uji-besar-log.md', 'kunci': 'id: big',
                                  'teks': '\nid: big\n' + 'y' * 64}],
            }, max_file_bytes=32)
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn('sesi-log/uji-besar-log-3.md', reasons[0])
            self.assertEqual(reasons[0].count('exceeds guard byte limit'), 1)
            # Chains already numbered continue from the same base stem.
            self.assertEqual(helper.next_log_continuation(vault, 'sesi-log/uji-besar-log-2.md'),
                             'sesi-log/uji-besar-log-3.md')
            self.assertEqual(helper.next_log_continuation(vault, 'sesi-log/uji-besar-log.md'),
                             'sesi-log/uji-besar-log-3.md')


if __name__ == '__main__':
    unittest.main()
