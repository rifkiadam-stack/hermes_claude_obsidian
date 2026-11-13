"""Authority-bound cleanup of verified Second Brain staging sources.

This orchestrator proves provenance, then delegates all destructive mutation to
the reviewed native-Windows guard delete primitive. `.raw/` is never targeted.
"""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from datetime import datetime
from pathlib import Path,PurePosixPath
CORE=Path(__file__).resolve().parents[1]
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
 # Mask non-operative text without changing declaration offsets.
 mask=lambda value: re.sub(r'[^\r\n]', ' ', value)
 text=re.sub(r'\A---[^\S\n]*\r?\n.*?(?:(?:\r?\n)(?:---|\.\.\.)[^\S\n]*(?:\r?\n|\Z)|\Z)', lambda match: mask(match.group()), text, flags=re.S)
 text=re.sub(r'<!--.*?(?:-->|\Z)|%%.*?(?:%%|\Z)', lambda match: mask(match.group()), text, flags=re.S)
 out=[]; fence_char=None; fence_length=0
 for line in text.splitlines(keepends=True):
  match=re.match(r'^\s*(`{3,}|~{3,})(.*)$',line)
  if match:
   run=match.group(1); suffix=match.group(2); marker=run[0]
   if fence_char is None: fence_char=marker; fence_length=len(run)
   elif fence_char==marker and len(run)>=fence_length and suffix.strip()=='': fence_char=None; fence_length=0
   out.append(mask(line)); continue
  out.append(line if fence_char is None else mask(line))
 return ''.join(out)

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
     if not isinstance(mr,dict):
      mr=manifest.get('sources',{}).get(raw_rel)
     if isinstance(mr,dict):
      manifest_path=mr.get('path',raw_rel if mr.get('pages_created') else None)
      manifest_sha=mr.get('sha256')
      if manifest_sha is None and mr.get('pages_created'):
       manifest_sha=digest
     else:
      # Legacy manifest format maps raw locator to metadata.
      mr=manifest.get('sources',{}).get(raw_rel,{})
      manifest_path=raw_rel
      manifest_sha=mr.get('sha256') if isinstance(mr,dict) else None
     if manifest_path!=raw_rel or manifest_sha!=digest: continue
     raw=vault/Path(raw_rel)
     if not raw.is_file(): continue
     raw_bytes,raw_proof=capture_bytes(raw)
     if raw_proof!='sha256:'+digest: continue
     pages=record.get('pages');
     if not isinstance(pages,list) or not pages: continue
     ok=True; candidate_page_proofs={}
     for page_rel in pages:
      try: page_rel=valid_rel(page_rel,'wiki')
      except CleanupError: ok=False; break
      page=vault/Path(page_rel)
      if not page.is_file(): ok=False; break
      page_bytes,page_proof=capture_bytes(page)
      # No transformation mode is proven: require exact verbatim bytes, even
      # when a normal archive link exists. Validate and hash one capture only.
      header=('Sumber arsip: [['+raw_rel+']]'+chr(10)+chr(10)).encode('utf-8')
      if not page_bytes.endswith(header+raw_bytes): ok=False; break
      prefix=page_bytes[:-len(raw_bytes)] if raw_bytes else page_bytes
      prefix_text=prefix.decode('utf-8')
      text=strip_fenced_code(prefix_text)
      link_pattern=r'(?m)^Sumber arsip: \[\['+re.escape(raw_rel)+r'\]\][ \t]*$'
      declaration_offset=len(prefix_text)-len(header.decode('utf-8'))
      if not any(match.start()==declaration_offset for match in re.finditer(link_pattern,text)): ok=False; break
      candidate_page_proofs[page_rel]=page_proof
     if ok: matches.append((sid,raw_rel,pages,raw_proof,candidate_page_proofs))
    if len(matches)!=1: raise CleanupError(f'expected one complete provenance chain, found {len(matches)}')
    matched_sid,raw_rel,pages,raw_proof,matched_page_proofs=matches[0]
    verified.append({'path':rel,'sha256':digest,'source_id':matched_sid,'raw_path':raw_rel,'pages':pages})
    proof_hashes[raw_rel]=raw_proof
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
