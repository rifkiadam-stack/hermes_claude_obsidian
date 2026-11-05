"""Authority-bound cleanup of verified Second Brain staging sources.

This orchestrator proves provenance, then delegates all destructive mutation to
the reviewed native-Windows guard delete primitive. `.raw/` is never targeted.
"""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from datetime import datetime
from pathlib import Path,PurePosixPath
CORE=Path(r'C:\Users\rahmazaki.adam\AppData\Local\hermes\components\claude-obsidian-core')
sys.path.insert(0,str(CORE))
from claude_obsidian.hermes_windows_write import OPERATION_SCHEMA,execute_operation,inspect_operation
from claude_obsidian.ledgers import stable_source_id

class CleanupError(RuntimeError): pass

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()

MAX_PROOF_BYTES=32*1024*1024

def capture_bytes(path:Path)->tuple[bytes,str]:
 size=path.stat().st_size
 if size>MAX_PROOF_BYTES: raise CleanupError(f'proof file too large: {path}')
 data=path.read_bytes()
 if len(data)!=size: raise CleanupError(f'proof file changed during capture: {path}')
 return data,'sha256:'+hashlib.sha256(data).hexdigest()

def capture_json(path:Path)->tuple[dict,str]:
 data,proof=capture_bytes(path)
 value=json.loads(data.decode('utf-8'))
 if not isinstance(value,dict): raise CleanupError(f'invalid metadata: {path}')
 return value,proof

def capture_text(path:Path)->tuple[str,str]:
 data,proof=capture_bytes(path)
 return data.decode('utf-8'),proof

def load(path:Path)->dict:
 return capture_json(path)[0]

def valid_rel(value:str,root:str)->str:
 p=PurePosixPath(value.replace('\\','/'))
 if p.is_absolute() or '..' in p.parts or len(p.parts)<2 or p.parts[0]!=root: raise CleanupError(f'unsafe path: {value}')
 return p.as_posix()

def strip_fenced_code(text:str)->str:
 out=[]; fence_char=None; fence_length=0
 for line in text.splitlines():
  match=re.match(r'^\s*(`{3,}|~{3,})(.*)$',line)
  if match:
   run=match.group(1); suffix=match.group(2); marker=run[0]
   if fence_char is None: fence_char=marker; fence_length=len(run)
   elif fence_char==marker and len(run)>=fence_length and suffix.strip()=='': fence_char=None; fence_length=0
   continue
  if fence_char is None: out.append(line)
 return '\n'.join(out)

def discover(vault:Path)->dict:
 ledger_path=vault/'wiki/meta/ledgers/source-ledger.json'; manifest_path=vault/'.raw/.manifest.json'
 ledger,ledger_proof=capture_json(ledger_path); manifest,manifest_proof=capture_json(manifest_path); verified=[]; blocked=[]
 proof_hashes={'wiki/meta/ledgers/source-ledger.json':ledger_proof,'.raw/.manifest.json':manifest_proof}
 for folder in ('inbox','Clippings'):
  root=vault/folder
  if not root.exists(): continue
  for source in sorted(root.iterdir(),key=lambda p:p.name.casefold()):
   if not source.is_file() or source.name=='.gitkeep': continue
   rel=f'{folder}/{source.name}'
   try:
    digest=sha(source); matches=[]
    for sid,record in ledger.get('sources',{}).items():
     if not isinstance(record,dict) or record.get('content_sha256')!=digest: continue
     origin=record.get('origin',{}); locator=origin.get('locator') if isinstance(origin,dict) else None
     if not isinstance(locator,str) or origin.get('kind')!='file': continue
     raw_rel=valid_rel(locator,'.raw'); expected_sid=stable_source_id('file',raw_rel,digest)
     if sid!=expected_sid: continue
     mr=manifest.get('sources',{}).get(sid)
     if not isinstance(mr,dict) or mr.get('path')!=raw_rel or mr.get('sha256')!=digest: continue
     raw=vault/Path(raw_rel)
     if not raw.is_file() or sha(raw)!=digest: continue
     pages=record.get('pages');
     if not isinstance(pages,list) or not pages: continue
     ok=True; candidate_page_proofs={}
     for page_rel in pages:
      try: page_rel=valid_rel(page_rel,'wiki')
      except CleanupError: ok=False; break
      page=vault/Path(page_rel)
      if not page.is_file(): ok=False; break
      captured_text,page_proof=capture_text(page)
      text=strip_fenced_code(captured_text)
      link_pattern=r'(?m)^Sumber(?: arsip)?:\s*\[\['+re.escape(raw_rel)+r'\]\]\s*$'
      if re.search(link_pattern,text) is None: ok=False; break
      candidate_page_proofs[page_rel]=page_proof
     if ok: matches.append((sid,candidate_page_proofs))
    if len(matches)!=1: raise CleanupError(f'expected one complete provenance chain, found {len(matches)}')
    matched_sid,matched_page_proofs=matches[0]
    verified.append({'path':rel,'sha256':digest,'source_id':matched_sid,'raw_path':raw_rel,'pages':pages})
    proof_hashes[raw_rel]='sha256:'+digest
    proof_hashes.update(matched_page_proofs)
   except Exception as exc: blocked.append({'path':rel,'reason':str(exc)})
 return {'verified':verified,'blocked':blocked,'proof_hashes':proof_hashes}

def apply(vault:Path,operation_id:str)->dict:
 found=discover(vault)
 if not found['verified']: return {'state':'no-op','verified':0,'blocked':found['blocked']}
 expected={item['path']:'sha256:'+item['sha256'] for item in found['verified']}
 read_preconditions=dict(found['proof_hashes'])
 operation={'schema':OPERATION_SCHEMA,'operation_id':operation_id,'expected_hashes':expected,'read_preconditions':read_preconditions,'writes':[],'deletes':[item['path'] for item in found['verified']]}
 plan=inspect_operation(vault,operation); approval=plan['approval_sha256']
 complete=execute_operation(vault,operation,approval)
 return {**complete,'deleted_paths':complete['changed_paths'],'blocked':found['blocked'],'approval_sha256':approval}

if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--vault',required=True); p.add_argument('--discover',action='store_true'); p.add_argument('--apply-verified',action='store_true'); p.add_argument('--operation-id'); args=p.parse_args(); vault=Path(args.vault).resolve(strict=True)
 try:
  result=discover(vault) if args.discover or not args.apply_verified else apply(vault,args.operation_id or 'cleanup-staging-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
  print(json.dumps(result,ensure_ascii=False,indent=2))
 except Exception as exc:
  print(json.dumps({'state':'error','error':str(exc)},ensure_ascii=False)); raise SystemExit(1)
