import hashlib,json,sys,tempfile,unittest
from pathlib import Path
SCRIPTS=Path(r'C:\Users\rahmazaki.adam\AppData\Local\hermes\scripts'); CORE=Path(r'C:\Users\rahmazaki.adam\AppData\Local\hermes\components\claude-obsidian-core'); sys.path[:0]=[str(SCRIPTS),str(CORE)]
from second_brain_staging_cleanup import discover,apply
from claude_obsidian.ledgers import stable_source_id

def digest(data): return hashlib.sha256(data).hexdigest()
class RunnerV2Tests(unittest.TestCase):
 def make(self,root):
  v=Path(root)/'vault'
  for d in ['.obsidian','inbox','Clippings','.raw','wiki/x','wiki/meta/ledgers']:(v/d).mkdir(parents=True,exist_ok=True)
  data=b'hello'; rel='.raw/a.md'; page='wiki/x/a.md'; (v/'inbox/a.md').write_bytes(data); (v/rel).write_bytes(data); (v/page).write_text('Sumber: [['+rel+']]\n',encoding='utf-8'); sid=stable_source_id('file',rel,digest(data)); record={'origin':{'kind':'file','locator':rel},'content_sha256':digest(data),'pages':[page]}; (v/'wiki/meta/ledgers/source-ledger.json').write_text(json.dumps({'sources':{sid:record}}),encoding='utf-8'); (v/'.raw/.manifest.json').write_text(json.dumps({'sources':{sid:{'path':rel,'sha256':digest(data)}}}),encoding='utf-8'); return v
 def test_fence_marker_with_trailing_text_is_not_a_close(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d); page=v/'wiki/x/a.md'; page.write_text('```md\n```not-a-close\nSumber: [[.raw/a.md]]\n```\n',encoding='utf-8')
   result=discover(v); self.assertEqual([],result['verified']); self.assertEqual('inbox/a.md',result['blocked'][0]['path'])
 def test_shorter_backtick_run_does_not_close_outer_fence(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d); page=v/'wiki/x/a.md'; page.write_text('````md\n```\nSumber: [[.raw/a.md]]\n````\n',encoding='utf-8')
   result=discover(v); self.assertEqual([],result['verified']); self.assertEqual('inbox/a.md',result['blocked'][0]['path'])
 def test_metadata_changed_after_parse_cannot_become_new_snapshot(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d)
   import second_brain_staging_cleanup as runner
   original=runner.capture_json
   calls={'n':0}
   def capture_then_tamper(path):
    value,proof=original(path); calls['n']+=1
    if path.name=='source-ledger.json': path.write_text(json.dumps({'sources':{}}),encoding='utf-8')
    return value,proof
   from unittest.mock import patch
   with patch.object(runner,'capture_json',side_effect=capture_then_tamper):
    with self.assertRaises(Exception): runner.apply(v,'runner-v2-metadata-race')
   self.assertTrue((v/'inbox/a.md').exists())
 def test_apply_binds_discovery_snapshot_not_later_raw_state(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d)
   import second_brain_staging_cleanup as runner
   original=runner.discover
   def discover_then_tamper(vault):
    result=original(vault); (vault/'.raw/a.md').write_bytes(b'tampered'); return result
   from unittest.mock import patch
   with patch.object(runner,'discover',side_effect=discover_then_tamper):
    with self.assertRaises(Exception): runner.apply(v,'runner-v2-toctou')
   self.assertTrue((v/'inbox/a.md').exists())
 def test_fenced_source_link_is_not_provenance(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d); page=v/'wiki/x/a.md'; page.write_text('```md\nSumber: [[.raw/a.md]]\n```\n',encoding='utf-8')
   result=discover(v); self.assertEqual([],result['verified']); self.assertEqual('inbox/a.md',result['blocked'][0]['path'])
 def test_discover_proves_complete_chain(self):
  with tempfile.TemporaryDirectory() as d:
   result=discover(self.make(d)); self.assertEqual(['inbox/a.md'],[x['path'] for x in result['verified']]); self.assertEqual([],result['blocked'])
 def test_apply_uses_core_guard_and_preserves_raw(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d); result=apply(v,'runner-v2-apply'); self.assertEqual('complete',result['state']); self.assertFalse((v/'inbox/a.md').exists()); self.assertEqual(b'hello',(v/'.raw/a.md').read_bytes()); self.assertTrue((v/'.vault-meta/hermes-windows/operations/runner-v2-apply/before/inbox/a.md').is_file())
 def test_bad_stable_source_id_is_blocked_and_not_deleted(self):
  with tempfile.TemporaryDirectory() as d:
   v=self.make(d); ledger=json.loads((v/'wiki/meta/ledgers/source-ledger.json').read_text()); rec=next(iter(ledger['sources'].values())); (v/'wiki/meta/ledgers/source-ledger.json').write_text(json.dumps({'sources':{'src-tampered':rec}}),encoding='utf-8'); result=apply(v,'runner-v2-block'); self.assertEqual('no-op',result['state']); self.assertTrue((v/'inbox/a.md').exists())
if __name__=='__main__': unittest.main()