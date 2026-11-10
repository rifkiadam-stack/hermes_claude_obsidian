"""Explicit per-input persisted-chat runner. No CURRENT, discovery, or vault writes.
prepare --selection FILE --work-root DIR --page-path PATH --date INGEST-YYYY-MM-DD
        --title TITLE --route-id ID --query TEXT
The date is generated-envelope/ingest date, NOT the source's publication date.
Source dates remain unchanged in source bytes and caller-selected page path.
Navigation is strictly additions-only; a native plan rewriting old lines HOLDS.
apply|verify|index --workdir DIR. Completed content is NEVER replayed.
All vault mutation uses installed native request/guard APIs; cleanup is OFF.
"""
from pathlib import Path
import sys,json,copy,uuid,datetime,importlib.util,hashlib,argparse
H=Path('C:/Users/rahmazaki.adam/AppData/Local/hermes');C=H/'components/claude-obsidian-ingest-v34';PRODUCT=C/'product'
sys.path[:0]=[str(PRODUCT),str(H/'scripts')]
import claude_obsidian
assert Path(claude_obsidian.__file__).resolve().is_relative_to(PRODUCT.resolve())
from capture_hermes_message import read_source
from claude_obsidian import hermes_windows_write as native
from claude_obsidian.hermes_ingest_buffer_context import consume_persisted_buffer
from claude_obsidian.hermes_ingest_request import RequestDependencies,IngestRequest,prepare_request
from claude_obsidian.hermes_ingest_route_config import bind_staged_route,APPROVED_STAGING_MAP_SHA256
from claude_obsidian import hermes_ingest_execute as coordinator


def sha(data): return hashlib.sha256(data).hexdigest()
def readj(path): return json.loads(Path(path).read_bytes())
def save(path,value):
    with Path(path).open('xb') as f: f.write(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'))
def canonical(value): return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def initialize(*,selection,source,work_root,page_path,date,title,route_id,query):
    datetime.date.fromisoformat(date)
    if not all(isinstance(x,str) and x.strip() for x in (page_path,title,route_id,query)):
        raise ValueError('explicit page/title/route/query required')
    key=sha(canonical(selection).encode())
    root=Path(work_root).absolute();vault=Path(readj(C/'setup-registry.json')['vault_path']).resolve()
    if root.resolve().is_relative_to(vault): raise ValueError('work root must be outside vault')
    root.mkdir(parents=True,exist_ok=True)
    out=root/('message-'+str(selection['message_id'])+'-'+key[:16])
    if out.exists(): raise ValueError('input workdir already exists; do not replay; use verify/index for completed content')
    out.mkdir()
    raw=source['source_bytes']
    if sha(raw)!=source['source_sha256'] or len(raw)!=source['source_length']: raise ValueError('source baseline mismatch')
    proof={k:v for k,v in source.items() if k!='source_bytes'}
    now=datetime.datetime.now(datetime.timezone.utc)
    settings=dict(operation_id='ingest-'+uuid.uuid4().hex[:12],page_path=page_path,date=date,title=title,route_id=route_id,query=query,generated_at=now.strftime('%Y-%m-%dT%H:%M:%SZ'),registry_sha256=sha((C/'setup-registry.json').read_bytes()),selection_sha256=key,source_sha256=sha(raw),source_length=len(raw))
    save(out/'SELECTION.json',selection);save(out/'SOURCE.json',proof);save(out/'REQUEST-SETTINGS.json',settings)
    with (out/'source.txt').open('xb') as f: f.write(raw)
    return out


def context(out):
    selection=readj(out/'SELECTION.json');settings=readj(out/'REQUEST-SETTINGS.json')
    if sha(canonical(selection).encode())!=settings['selection_sha256']: raise ValueError('selection changed')
    source=read_source(**selection);raw=source.pop('source_bytes')
    if raw!=(out/'source.txt').read_bytes() or source!=readj(out/'SOURCE.json') or sha(raw)!=settings['source_sha256']: raise ValueError('source/proof changed')
    registry=readj(C/'setup-registry.json')
    if sha((C/'setup-registry.json').read_bytes())!=settings['registry_sha256']: raise ValueError('registry changed')
    if sha((H/'scripts/capture_hermes_message.py').read_bytes())!=registry['observed_components']['persisted_user_message_capture']['reader_sha256']: raise ValueError('capture reader changed')
    local=copy.deepcopy(registry);opid=settings['operation_id']
    prefixes=registry['path_budget']['checkpoint_prefixes']
    if any('{' in x.replace('{operation_id}','') or '}' in x.replace('{operation_id}','') for x in prefixes): raise ValueError('unknown checkpoint placeholder')
    local['path_budget']['checkpoint_prefixes']=[x.replace('{operation_id}',opid) for x in prefixes]
    v=Path(local['vault_path'])
    if (v/'.vault-meta/hermes-windows/write.lock').exists(): raise ValueError('native lock present; inspect original authority')
    policy=load('installed_scope_policy',C/'helpers/scope_plan.py')
    if sha((C/'helpers/scope_plan.py').read_bytes())!=registry['observed_components']['installed_scope_policy']['sha256']: raise ValueError('installed policy changed')
    helper=load('installed_reading_helper',H/'skills/second-brain/ingest-verbatim/scripts/reading_page.py')
    buffer=consume_persisted_buffer(source_reader=lambda:read_source(**selection))
    if buffer.source.source_bytes!=raw or buffer.source_origin!='hermes_persisted_user_message': raise ValueError('buffer mismatch')
    route=bind_staged_route(approved_map_bytes=(H/'docs/ingest-native-v34-work/route-map.approved-for-staging.json').read_bytes(),approved_map_sha256=APPROVED_STAGING_MAP_SHA256,registry=local,route_id=settings['route_id'],runtime_identity=local['runtime_identity'],vault_path=local['vault_path'],core_path=local['registered_paths']['INGEST_CORE_PATH'],registry_path=local['registered_paths']['INGEST_REGISTRY_PATH'],supported_native_contract=local['native_contract'])
    selected=[r for r in local['domain_routes']['routes'] if r['id']==settings['route_id'] and r['approved'] and r['enabled']]
    if len(selected)!=1 or not settings['page_path'].startswith(selected[0]['folder']): raise ValueError('page outside approved route')
    nav=selected[0]['navigation']
    deps=RequestDependencies(policy=policy,reading_helper=helper,registry=local,runtime_identity=local['runtime_identity'],vault_path=local['vault_path'],core_path=local['registered_paths']['INGEST_CORE_PATH'],registry_path=local['registered_paths']['INGEST_REGISTRY_PATH'],supported_native_contract=local['native_contract'],trusted_route_config=route,trusted_buffer_context=buffer,trusted_mutation_targets=(settings['page_path'],nav,'.raw/','.raw/.manifest.json','wiki/meta/ledgers/source-ledger.json','.vault-meta/address-counter.txt','wiki/log.md','wiki/hot.md'))
    req=IngestRequest(command=buffer.command_bytes.decode(),origin='manual',source=buffer.source,retained_input_identity=buffer.source.input_identity,current_message_identity=buffer.source.message_identity,selected_route_id=settings['route_id'],page_path=settings['page_path'],title=settings['title'],date=settings['date'],operation_id=opid,generated_at=settings['generated_at'],path_prefixes=tuple(local['path_budget']['checkpoint_prefixes']),max_path_units=local['path_budget']['absolute_path_max'])
    return v,deps,req,raw


def validate_navigation(before,after):
    import difflib
    if any(line.startswith('- ') for line in difflib.ndiff(before.splitlines(),after.splitlines())):
        raise ValueError('approved navigation must be additions-only; no rewriting/backdating existing lines')


def validate_plan(v,deps,plan):
    operation=plan['operation'];allowed=set(deps.trusted_mutation_targets)
    if operation.get('deletes'): raise ValueError('retention prohibits deletes')
    for write in operation['writes']:
        path=write['path']
        if path not in allowed and path!=plan['artifact']['raw_path']: raise ValueError('out-of-scope target')
        if path.startswith('wiki/') and path.endswith('.md') and path!=plan['artifact']['page_path']:
            before=native.bounded_target_bytes(v,path)
            validate_navigation(before.decode('utf-8'),write['content'])


def prepare(out):
    v,deps,req,raw=context(out);prep=prepare_request(req,dependencies=deps)
    if prep.disposition!='PREPARED': raise ValueError(str(prep))
    plan=prep.plan
    if plan['operation'].get('deletes') or sha(raw)!=plan['artifact']['source_sha256']: raise ValueError('invalid retention plan')
    validate_plan(v,deps,plan)
    inspection=native.inspect_operation(v,plan['operation'])
    save(out/'PREPARED.json',{'plan':plan,'bindings':prep.bindings});save(out/'INSPECT.json',inspection)
    return {'state':'PREPARED_NO_CONTENT_MUTATION','workdir':str(out),'operation_id':req.operation_id,'approval_sha256':inspection['approval_sha256'],'writes':[w['path'] for w in plan['operation']['writes']],'artifact':plan['artifact']}


def apply(out):
    if any((out/x).exists() for x in ('RESULT.json','retained','retained.custody','APPLY-ATTEMPT.json')): raise ValueError('already attempted/completed; no content replay; use verify/index or original-authority recovery')
    v,deps,req,raw=context(out);prep=prepare_request(req,dependencies=deps)
    original=readj(out/'PREPARED.json')
    if prep.disposition!='PREPARED' or canonical({'plan':prep.plan,'bindings':prep.bindings})!=canonical(original): raise ValueError('preparation changed; do not replay')
    validate_plan(v,deps,prep.plan)
    inspection=native.inspect_operation(v,prep.plan['operation'])
    if canonical(inspection)!=canonical(readj(out/'INSPECT.json')): raise ValueError('inspection changed')
    save(out/'APPLY-ATTEMPT.json',{'operation_id':req.operation_id,'approval_sha256':inspection['approval_sha256']})
    result=coordinator.execute_request(req,dependencies=deps,private_directory=out/'retained',expected_preparation_sha256='sha256:'+sha(canonical(original).encode('utf-8')))
    save(out/'RESULT.json',result)
    if read_source(**readj(out/'SELECTION.json'))['source_bytes']!=raw: raise ValueError('canonical source changed')
    return result


def verify(out):
    result=readj(out/'RESULT.json');settings=readj(out/'REQUEST-SETTINGS.json');registry=readj(C/'setup-registry.json')
    if sha((C/'setup-registry.json').read_bytes())!=settings['registry_sha256']:
        # Only completed read-only verification may use an explicitly retained,
        # hash-exact historical registry. Preparation/apply/index remain live-bound.
        snapshot=registry.get('historical_readonly_registries',{}).get(settings['registry_sha256'])
        if not snapshot: raise ValueError('registry changed')
        frozen=Path(snapshot).read_bytes()
        if sha(frozen)!=settings['registry_sha256']: raise ValueError('historical registry changed')
        historical=json.loads(frozen)
        if Path(historical['vault_path']).resolve()!=Path(registry['vault_path']).resolve(): raise ValueError('historical registry vault changed')
    # Completed native validity is not proof that a record belongs to this input.
    # Resolve only this workdir's retained authorities, never a RESULT redirect.
    if Path(result['record_path']).resolve()!=(out/'retained/record.json').resolve(): raise ValueError('record not bound to input workdir')
    if Path(result['custody_path']).resolve()!=(out/'retained.custody/custody.json').resolve(): raise ValueError('custody not bound to input workdir')
    prepared=readj(out/'PREPARED.json');plan=prepared['plan'];bindings=prepared['bindings']
    record=readj(result['record_path']);custody=readj(result['custody_path']);inspection=readj(out/'INSPECT.json')
    if (json.loads(record['operation_json'])!=plan['operation'] or record['artifact']!=plan['artifact']
            or record['retention_authority']!=plan['retention_authority']
            or bindings['retention_authority']!=plan['retention_authority']
            or record['approval_sha256']!=inspection['approval_sha256']
            or custody['approval_sha256']!=inspection['approval_sha256']
            or custody['bindings']!=bindings): raise ValueError('record/custody not bound to frozen preparation')
    for key in ('operation_id','page_path','title','date','generated_at','route_id','source_sha256'):
        if bindings[key]!=settings[key]: raise ValueError('prepared input settings mismatch: '+key)
    if (plan['operation']['operation_id']!=settings['operation_id']
            or plan['artifact']['page_path']!=settings['page_path']
            or plan['artifact']['source_sha256']!=settings['source_sha256']
            or plan['route_authority']!=bindings['route_authority']
            or plan['route_authority']['route_id']!=settings['route_id']): raise ValueError('prepared operation/artifact input mismatch')
    selection=readj(out/'SELECTION.json')
    if sha(canonical(selection).encode('utf-8'))!=settings['selection_sha256']: raise ValueError('selection changed')
    source=read_source(**selection);raw=source['source_bytes']
    if (raw!=(out/'source.txt').read_bytes() or sha(raw)!=settings['source_sha256']
            or len(raw)!=settings['source_length']
            or {k:v for k,v in source.items() if k!='source_bytes'}!=readj(out/'SOURCE.json')): raise ValueError('source/proof changed')
    buffer=consume_persisted_buffer(source_reader=lambda:read_source(**selection))
    from claude_obsidian.hermes_ingest_buffer_context import validate_buffer_context
    input_binding=validate_buffer_context(buffer,source=buffer.source,retained_input_identity=bindings['input_identity'],current_message_identity=bindings['message_identity'],command=bindings['command'])
    if (input_binding!=plan['retention_authority']['input_binding']
            or buffer.payload_sha256!=plan['retention_authority']['source_sha256']): raise ValueError('prepared input/message binding mismatch')
    v=Path(registry['vault_path']);verified=coordinator.verify_completed(v,result['record_path'],result['record_sha256'])
    if verified.get('state')!='complete': raise ValueError(str(verified))
    if read_source(**readj(out/'SELECTION.json'))['source_bytes']!=(out/'source.txt').read_bytes(): raise ValueError('source drift')
    if (v/'.vault-meta/hermes-windows/write.lock').exists(): raise ValueError('native lock remains')
    return verified


def index(out):
    """Index-only resume: generous bounded subprocess, never content execution.
    External per-attempt evidence remains create-only; failed index is retryable.
    """
    import subprocess,os
    verified=verify(out)
    settings=readj(out/'REQUEST-SETTINGS.json')
    if sha((C/'setup-registry.json').read_bytes())!=settings['registry_sha256']: raise ValueError('registry changed')
    result=readj(out/'RESULT.json')
    if result.get('lint')!='PASS': raise ValueError('native content lint must PASS before indexing')
    settings=readj(out/'REQUEST-SETTINGS.json');registry=readj(C/'setup-registry.json');v=Path(registry['vault_path'])
    record=readj(result['record_path']);art=record['artifact']
    raw=native.bounded_target_bytes(v,art['raw_path']);page=native.bounded_target_bytes(v,art['page_path'])
    if raw!=(out/'source.txt').read_bytes() or sha(raw)!=art['source_sha256'] or sha(page)!=art['page_sha256']: raise ValueError('readback digest mismatch')
    attempt=out/('index-'+uuid.uuid4().hex[:12]);attempt.mkdir()
    env=dict(os.environ,PYTHONPATH=str(PRODUCT))
    def invoke(label,script,arguments,timeout):
        command=[sys.executable,'-B',str(script),*arguments]
        save(attempt/(label+'-invocation.json'),{'command':command,'script_sha256':sha(Path(script).read_bytes()),'page_path':art['page_path'],'page_sha256':sha(page)})
        r=subprocess.run(command,capture_output=True,timeout=timeout,env=env)
        for suffix,data in (('.stdout',r.stdout),('.stderr',r.stderr),('.exit',str(r.returncode).encode())):
            with (attempt/(label+suffix)).open('xb') as f: f.write(data)
        return r
    built=invoke('provision',C/'helpers/bm25_provision_native.py',['--vault',str(v)],900)
    if built.returncode not in (0,2): raise ValueError('index provision failed; see '+str(attempt))
    queried=invoke('retrieve',PRODUCT/'scripts/retrieve.py',['--vault',str(v),'--no-rerank','--explain',settings['query']],120)
    if queried.returncode!=0: raise ValueError('retrieval failed; see '+str(attempt))
    retrieval=json.loads(queried.stdout);canon=lambda x:str(x).replace('\\','/').casefold()
    if retrieval['explain']['stale_candidates_skipped']!=0 or not any(canon(c['page_path'])==canon(art['page_path']) for c in retrieval['candidates']): raise ValueError('retrieval missing exact page or stale')
    verified=verify(out)
    if native.bounded_target_bytes(v,art['raw_path'])!=raw or native.bounded_target_bytes(v,art['page_path'])!=page: raise ValueError('post-index drift')
    nav=next(r['navigation'] for r in registry['domain_routes']['routes'] if r['id']==settings['route_id'])
    moc=native.bounded_target_bytes(v,nav)
    if ('[['+art['page_path'][:-3]+'|'+settings['title']+']]').encode() not in moc: raise ValueError('approved MOC link missing')
    snapshot=out/('review-'+uuid.uuid4().hex[:12]);snapshot.mkdir()
    hashes={}
    for filename,data,original in [('PERSISTED-RAW.txt',raw,art['raw_path']),('PERSISTED-PAGE.md',page,art['page_path']),('PERSISTED-MOC.md',moc,nav),('SOURCE.txt',(out/'source.txt').read_bytes(),readj(out/'SOURCE.json')['locator'])]:
        with (snapshot/filename).open('xb') as f: f.write(data)
        hashes[filename]={'sha256':sha(data),'bytes':len(data),'persisted_path':original}
    manifest=dict(source_sha256=sha(raw),page_sha256=sha(page),moc_sha256=sha(moc),snapshots=hashes,source_proof=readj(out/'SOURCE.json'),vault=str(v),page_path=art['page_path'],raw_path=art['raw_path'],moc_path=nav,approved_route_id=settings['route_id'],runtime_identity=registry['runtime_identity'],native_state=verified['state'],lint=result['lint'],lint_report_path=result['lint_report_path'],indexing='PASS',retrieval_evidence=str(attempt/'retrieve.stdout'),retrieval_sha256=sha(queried.stdout),retrieval_stale=0,retrieval_target_found=True,record_path=result['record_path'],record_sha256=result['record_sha256'],verbatim_artifact=art,cleanup='OFF: content-retention',post_review='PENDING independent whole-source and persisted-page AI review by parent; not a self-review PASS',gui='No new per-input GUI proof recorded by runner')
    save(snapshot/'REVIEW-MANIFEST.json',manifest)
    save(attempt/'POST-INDEX-VERIFY.json',verified)
    evidence={'state':'CONTENT_COMPLETE_INDEXED_REVIEW_PENDING','provision_exit':built.returncode,'retrieval_target_found':True,'retrieval_stale':0,'review_manifest':str(snapshot/'REVIEW-MANIFEST.json'),'evidence_directory':str(attempt),'source_sha256':sha(raw),'page_sha256':sha(page)}
    save(attempt/'RESULT.json',evidence)
    return evidence


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare')
    for arg in ('selection','work-root','page-path','date','title','route-id','query'): p.add_argument('--'+arg,required=True)
    for action in ('apply','verify','index'):
        sub.add_parser(action).add_argument('--workdir',required=True)
    args=ap.parse_args()
    if args.action=='prepare':
        selection=readj(args.selection);registry=readj(C/'setup-registry.json')
        if Path(selection['db_path']).resolve()!= (H/'state.db').resolve(): raise ValueError('canonical default-profile state.db required')
        if sha((H/'scripts/capture_hermes_message.py').read_bytes())!=registry['observed_components']['persisted_user_message_capture']['reader_sha256']: raise ValueError('reader hash mismatch')
        source=read_source(**selection)
        out=initialize(selection=selection,source=source,work_root=Path(args.work_root),page_path=args.page_path,date=args.date,title=args.title,route_id=args.route_id,query=args.query)
        result=prepare(out)
    else:
        out=Path(args.workdir).resolve(strict=True);result={'apply':apply,'verify':verify,'index':index}[args.action](out)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
