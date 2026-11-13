"""Synthetic-only cleanup provenance regressions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('staging_cleanup', ROOT / 'scripts/second_brain_staging_cleanup.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        self.payload = b'Synthetic source body.\n'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.sources = {}
        self.manifest = {}

    def put(self, rel, data):
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)

    def candidate(self, name='a', page=None, legacy=False):
        raw = f'.raw/{name}.md'
        page_rel = f'wiki/{name}.md'
        sid = cleanup.stable_source_id('file', raw, self.digest)
        self.put(raw, self.payload)
        self.put(page_rel, page if page is not None else f'Sumber arsip: [[{raw}]]\n\n' + self.payload.decode())
        self.sources[sid] = {'content_sha256': self.digest, 'origin': {'kind': 'file', 'locator': raw}, 'pages': [page_rel]}
        self.manifest[raw if legacy else sid] = ({'pages_created': [page_rel]} if legacy else {'path': raw, 'sha256': self.digest})
        self.put('wiki/meta/ledgers/source-ledger.json', json.dumps({'sources': self.sources}))
        self.put('.raw/.manifest.json', json.dumps({'sources': self.manifest}))
        return sid

    def test_hidden_declarations_cannot_authorize_cleanup(self):
        self.put('inbox/source.md', self.payload)
        declaration = 'Sumber arsip: [[.raw/a.md]]'
        for wrapper in ('<!--\n%s\n-->\n', '%%\n%s\n%%\n', '---\n%s\n---\n'):
            with self.subTest(wrapper=wrapper):
                self.candidate(page=wrapper.replace('%s', declaration) + self.payload.decode())
                found = cleanup.discover(self.vault)
                self.assertEqual(found['verified'], [])
                self.assertEqual(len(found['blocked']), 1)


    def test_rejected_later_candidate_preserves_selected_proofs(self):
        self.put('inbox/source.md', self.payload)
        sid = self.candidate()
        self.candidate('b', page='No source declaration.\n')
        found = cleanup.discover(self.vault)
        self.assertEqual(found['verified'], [{'path': 'inbox/source.md', 'sha256': self.digest,
                         'source_id': sid, 'raw_path': '.raw/a.md', 'pages': ['wiki/a.md']}])
        self.assertIn('.raw/a.md', found['proof_hashes'])
        self.assertNotIn('.raw/b.md', found['proof_hashes'])
        self.assertIn('wiki/a.md', found['proof_hashes'])
        self.assertNotIn('wiki/b.md', found['proof_hashes'])


    def test_standalone_link_does_not_excuse_body_mismatch(self):
        self.put('inbox/source.md', self.payload)
        self.candidate(page='Sumber arsip: [[.raw/a.md]]\n\nChanged body.\n')
        found = cleanup.discover(self.vault)
        self.assertEqual(found['verified'], [])
        self.assertEqual(len(found['blocked']), 1)


    def test_apply_deletes_only_verified_source_with_current_and_legacy_manifest(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.setUp()
                self.put('inbox/verified.md', self.payload)
                self.candidate(legacy=legacy)
                self.payload = b'Blocked synthetic payload.\n'
                self.digest = hashlib.sha256(self.payload).hexdigest()
                self.put('Clippings/blocked.md', self.payload)
                self.candidate('b', page='Sumber arsip: [[.raw/b.md]]\n\nIncomplete.\n', legacy=legacy)
                preserved = {rel: (self.vault / rel).read_bytes() for rel in
                             ('.raw/a.md', '.raw/b.md', 'wiki/a.md', 'wiki/b.md', 'Clippings/blocked.md')}
                with patch.object(cleanup, 'capture_bytes', wraps=cleanup.capture_bytes) as captures, \
                     patch.object(cleanup, 'inspect_operation', wraps=cleanup.inspect_operation) as inspected:
                    result = cleanup.apply(self.vault, 'synthetic-cleanup')
                self.assertEqual(result['deleted_paths'], ['inbox/verified.md'])
                self.assertFalse((self.vault / 'inbox/verified.md').exists())
                self.assertEqual([item['path'] for item in result['blocked']], ['Clippings/blocked.md'])
                for rel, data in preserved.items():
                    self.assertEqual((self.vault / rel).read_bytes(), data)
                preconditions = inspected.call_args.args[1]['read_preconditions']
                for rel in ('.raw/a.md', 'wiki/a.md', '.raw/.manifest.json', 'wiki/meta/ledgers/source-ledger.json'):
                    self.assertEqual(preconditions[rel], 'sha256:' + hashlib.sha256((self.vault / rel).read_bytes()).hexdigest())
                    self.assertEqual(sum(call.args[0] == self.vault / rel for call in captures.call_args_list), 1)
                self.assertNotIn('.raw/b.md', preconditions)
                self.assertNotIn('wiki/b.md', preconditions)

    def test_selected_raw_drift_blocks_apply_after_rejected_candidate(self):
        self.put('inbox/source.md', self.payload)
        self.candidate()
        self.candidate('b', page='Rejected page.\n')
        inspect = cleanup.inspect_operation
        def drift(vault, operation):
            self.put('.raw/a.md', b'Changed after capture.\n')
            return inspect(vault, operation)
        from claude_obsidian.hermes_windows_write import ConcurrentDriftError
        with patch.object(cleanup, 'inspect_operation', side_effect=drift):
            with self.assertRaises(ConcurrentDriftError):
                cleanup.apply(self.vault, 'synthetic-drift')
        self.assertTrue((self.vault / 'inbox/source.md').exists())
        self.assertTrue((self.vault / 'wiki/a.md').exists())

    def test_exact_suffix_hidden_in_code_or_comment_is_blocked(self):
        self.put('inbox/source.md', self.payload)
        for prefix in ('```markdown\n', '~~~\n', '<!--\n', '%%\n', '---\n'):
            with self.subTest(prefix=prefix):
                self.candidate(page=prefix + 'Sumber arsip: [[.raw/a.md]]\n\n' + self.payload.decode())
                self.assertEqual(cleanup.discover(self.vault)['verified'], [])

    def test_earlier_visible_link_cannot_launder_hidden_exact_suffix(self):
        self.put('inbox/source.md', self.payload)
        self.candidate(page='Sumber arsip: [[.raw/a.md]]\n\n<!--\nSumber arsip: [[.raw/a.md]]\n\n' + self.payload.decode())
        self.assertEqual(cleanup.discover(self.vault)['verified'], [])

    def test_capture_enforces_byte_bound(self):
        self.put('proof.md', b'12345')
        with patch.object(cleanup, 'MAX_PROOF_BYTES', 4):
            with self.assertRaises(cleanup.CleanupError):
                cleanup.capture_bytes(self.vault / 'proof.md')


if __name__ == '__main__':
    unittest.main()
