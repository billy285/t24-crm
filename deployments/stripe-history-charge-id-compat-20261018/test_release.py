"""Scoped backend release guards; no Docker, public writes or production DB."""
import copy,io,json,sqlite3,subprocess,tarfile,types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

def load(path,name):
    module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__);return module

r=load(Path(__file__).with_name('release.py'),'account_release')
actual_verify_secret_mount=r.verify_secret_mount
actual_next_nginx=r.next_nginx
actual_verify_public=r.verify_public
actual_stage_public=r.stage_public
actual_new_static_boundary=r.new_static_boundary
old=load(Path(__file__).parents[1]/'sales-dossier-20261016/release.py','retained_release')

@pytest.fixture(autouse=True)
def no_real_actions(monkeypatch):
    monkeypatch.setattr(r,'credential_boundary',lambda:r.CREDENTIAL_EXPECTED);monkeypatch.setattr(r,'verify_secret_mount',Mock());monkeypatch.setattr(r,'SOURCE','a'*40);monkeypatch.setattr(r,'LIVE_PREFLIGHT_SHA','5'*64)
    nginx_body=('server { root '+str(r.PUBLIC)+'; }\n').encode();monkeypatch.setattr(r,'NGINX',SimpleNamespace(read_bytes=lambda:nginx_body));monkeypatch.setattr(r,'NGINX_SHA',r.H(nginx_body))
    monkeypatch.setattr(old,'reload_nginx',Mock());monkeypatch.setattr(r,'cleanup_nginx_temp',Mock());monkeypatch.setattr(r,'replace_nginx',Mock())
    monkeypatch.setattr(r,'BUSINESS',SimpleNamespace(stat=lambda:SimpleNamespace(st_dev=r.BUSINESS_IDENTITY[0],st_ino=r.BUSINESS_IDENTITY[1])))
    def forbid(*args,**kwargs):raise AssertionError('No real process, Docker or public write allowed')
    monkeypatch.setattr(subprocess,'run',forbid);monkeypatch.setattr(subprocess,'check_output',forbid)
    monkeypatch.setattr(old,'docker_request',forbid);monkeypatch.setattr(r,'retained',lambda:old)

def original_info():
    return {'Id':r.OLD_ID,'Image':r.BASE_IMAGE,'State':{'Running':True,'StartedAt':'2026-10-16T00:00:00Z'},
        'RestartCount':0,'Name':'/t24-crm','Config':{'Image':r.BASE_IMAGE,'Hostname':'original','Labels':{'old':'preserved'},
        'Env':['PRIVATE_KEY=synthetic-only','DATABASE_SCHEMA_MODE=verify'],'Cmd':['python','-m','main']},
        'HostConfig':{'AutoRemove':False,'NetworkMode':'none','RestartPolicy':{'Name':'unless-stopped'},'Binds':['/data:/app/backend/data:rw',str(r.SECRET_HOST)+':'+r.SECRET_TARGET+':ro']},
        'Mounts':[{'Type':'bind','Source':'/data','Destination':'/app/backend/data','RW':True,'Propagation':'rprivate'},{'Type':'bind','Source':str(r.SECRET_HOST),'Destination':r.SECRET_TARGET,'Mode':'ro','RW':False,'Propagation':'rprivate'}],
        'NetworkSettings':{'Networks':{}}}

def manifest():
    return {'source_sha':r.SOURCE,'baseline_source_sha':r.BASELINE,'baseline_application_source':r.BASELINE_APPLICATION_SOURCE,
        'frontend_version':r.FRONTEND_VERSION,'baseline_frontend_version':r.BASELINE_FRONTEND,'schema_revision':r.REVISION,'payload_sha256':'payload',
        'credentials_included':False,'preserved':r.PRESERVED,'backend_only':False,'static_transition':True,
        'backend_before':dict.fromkeys(r.BACKEND,'1'*64),'backend_after':dict.fromkeys(r.BACKEND,'2'*64),
        'files':{**{'backend/'+path:'2'*64 for path in r.BACKEND},'static/index.html':'2'*64,'static/app-version.json':'2'*64},'live_preflight_sha256':r.LIVE_PREFLIGHT_SHA,
        'baseline_backend_inventory_sha256':r.BASE_BACKEND_SHA,'changed_source_files':sorted({'app/backend/'+p for p in r.BACKEND}|{'app/frontend/src/'+p for p in r.FRONTEND}|r.TESTS)}

def read_manifest(monkeypatch,value):
    monkeypatch.setattr(r,'read',lambda path,*args:json.dumps(value).encode() if path.name=='manifest.json' else b'payload')

def args():return SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload',preflight_sha256='preflight',review_sha256='review')

def test_exact_single_service_manifest_accepted(monkeypatch,tmp_path):
    value=manifest();read_manifest(monkeypatch,value);assert r.checked_manifest(tmp_path,args())==value

@pytest.mark.parametrize('field,value',[('source_sha','0'*40),('baseline_source_sha','0'*40),
    ('baseline_application_source','0'*40),('frontend_version','0'*12),('schema_revision','other'),
    ('credentials_included',True),('backend_only',True),('static_transition',False),('baseline_frontend_version','wrong'),('preserved',{'schema':True}),
    ('backend_before',{}),('backend_after',{}),('files',{}),
    ('files',{'backend/routers/payments.py':'2'*64}),('files',{'static/index.html':'2'*64}),
    ('files',{'backend/../crm.env':'2'*64})])
def test_manifest_fails_closed_for_any_pin_or_scope_drift(monkeypatch,tmp_path,field,value):
    selected=manifest();selected[field]=value;read_manifest(monkeypatch,selected)
    with pytest.raises(RuntimeError):r.checked_manifest(tmp_path,args())

@pytest.mark.parametrize('source',['PENDING_SOURCE','0'*39,'0'*41,'G'*40])
def test_unfrozen_helper_source_cannot_prepare(monkeypatch,tmp_path,source):
    monkeypatch.setattr(r,'SOURCE',source);read_manifest(monkeypatch,manifest())
    with pytest.raises(RuntimeError,match='FROZEN_SOURCE_REQUIRED'):r.checked_manifest(tmp_path,args())

def test_manifest_requires_matching_content_hashes(monkeypatch,tmp_path):
    value=manifest();value['files']['backend/services/stripe_history_reconciliation.py']='3'*64;read_manifest(monkeypatch,value)
    with pytest.raises(RuntimeError,match='BACKEND_HASH_IDENTITY_DRIFT'):r.checked_manifest(tmp_path,args())

def test_clone_preserves_environment_command_hostconfig_networks_and_mounts():
    original=original_info();before=copy.deepcopy(original);image='sha256:'+'9'*64
    config=r.clone_config(image,original)
    assert original==before
    assert config['Env']==original['Config']['Env'] and config['Cmd']==original['Config']['Cmd']
    assert config['HostConfig']==original['HostConfig']
    candidate=copy.deepcopy(original);candidate['Image']=image
    candidate['Config']={key:value for key,value in config.items() if key not in {'HostConfig','NetworkingConfig'}}
    candidate['Config']['Hostname']='new-generated'
    r.verify_clone(candidate,original)

@pytest.mark.parametrize('change',[
    lambda value:value['Config']['Env'].reverse(),lambda value:value['Config']['Cmd'].reverse(),
    lambda value:value['Mounts'][0].update(RW=False),lambda value:value['Mounts'].append(copy.deepcopy(value['Mounts'][0])),
    lambda value:value['HostConfig'].update(Privileged=True),lambda value:value['Config']['Labels'].update(extra='unreviewed')])
def test_clone_rejects_configuration_or_complete_mount_record_changes(change):
    original=original_info();candidate=copy.deepcopy(original);candidate['Config']['Labels']=r.expected_labels(original)
    change(candidate)
    with pytest.raises(RuntimeError):r.verify_clone(candidate,original)

@pytest.mark.parametrize('field,value',[('Id','unknown'),('Image','sha256:'+'0'*64),('Running',False),('configuration',True)])
def test_unknown_live_identity_or_configuration_blocks_boundary(monkeypatch,field,value):
    original=original_info();monkeypatch.setattr(r,'OLD_CONFIG',r.runtime(original)['config'])
    if field=='Running':original['State']['Running']=value
    elif field=='configuration':original['Config']['Env'].append('UNREVIEWED=1')
    else:original[field]=value
    monkeypatch.setattr(r,'private_boundary',Mock());monkeypatch.setattr(r,'schema_boundary',lambda:'schema')
    monkeypatch.setattr(r,'static_boundary',lambda:'static');monkeypatch.setattr(r,'inspect',lambda name:original)
    with pytest.raises(RuntimeError):r.boundary({})

@pytest.mark.parametrize('component',['private_boundary','schema_boundary','static_boundary'])
def test_private_schema_or_static_drift_stops_before_container_action(monkeypatch,component):
    for name in ('private_boundary','schema_boundary','static_boundary'):monkeypatch.setattr(r,name,Mock(return_value='pin'))
    monkeypatch.setattr(r,component,Mock(side_effect=RuntimeError('BOUNDARY_DRIFT')))
    inspect=Mock(side_effect=AssertionError('must not touch a container'));monkeypatch.setattr(r,'inspect',inspect)
    with pytest.raises(RuntimeError,match='BOUNDARY_DRIFT'):r.boundary({})
    inspect.assert_not_called()

def test_schema_guard_includes_indexes_triggers_and_views_without_writing_data(tmp_path):
    path=tmp_path/'crm.db'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE alembic_version(version_num TEXT);INSERT INTO alembic_version VALUES ('d1a5b9e7f234');CREATE TABLE payments(id INTEGER PRIMARY KEY,amount REAL);INSERT INTO payments VALUES(1,123.45);")
    first=r.schema_signature(path)
    with sqlite3.connect(path) as db:db.execute('CREATE INDEX new_index ON payments(amount)')
    assert r.schema_signature(path)!=first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM payments').fetchall()==[(1,123.45)]
        db.execute("UPDATE alembic_version SET version_num='wrong'")
    with pytest.raises(RuntimeError,match='SCHEMA_REVISION_DRIFT'):r.schema_signature(path)

@pytest.mark.parametrize('running,wrong_id,wrong_image',[(True,False,False),(False,True,False),(False,False,True)])
def test_stop_must_be_verified_before_snapshot_or_swap(monkeypatch,tmp_path,running,wrong_id,wrong_image):
    original=original_info();receipt={'candidate_image':'sha256:'+'9'*64,'old_crm':r.runtime(original),'schema_sha256':'schema','old_static_sha256':'static','public_inventory_sha256':'newstatic','nginx_next_sha256':r.H(r.next_nginx(r.NGINX.read_bytes()))}
    monkeypatch.setattr(r,'reviewed_receipt',lambda *a:(receipt,original,{},{}))
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(original,'schema','static'));monkeypatch.setattr(r,'inventory',lambda name:{})
    stopped=copy.deepcopy(original);stopped.update(Id='unknown' if wrong_id else r.OLD_ID,Image='wrong' if wrong_image else r.BASE_IMAGE)
    stopped['State']['Running']=running
    monkeypatch.setattr(r,'inspect',lambda name:stopped);monkeypatch.setattr(r,'write',Mock())
    run=Mock();backup=Mock(side_effect=AssertionError('must not snapshot before verified stop'))
    monkeypatch.setattr(r,'run',run);monkeypatch.setattr(r,'backup',backup);monkeypatch.setattr(r,'rollback',Mock())
    with pytest.raises(RuntimeError,match='CRM_NOT_STOPPED'):r.activate(tmp_path,args(),manifest(),{})
    backup.assert_not_called();assert run.call_args_list[0].args[0]==['docker','stop','-t','30',r.OLD_ID]
    assert run.call_count==1

def test_forward_recovery_only_uses_new_candidate_and_never_old_build_or_database_restore(monkeypatch,tmp_path):
    original=original_info();original['State']['Running']=False
    candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64)
    candidate['Config']['Labels']=r.expected_labels(original)
    receipt={'candidate_image':candidate['Image'],'old_crm':r.runtime(original),'schema_sha256':'schema','old_static_sha256':'static','public_inventory_sha256':'newstatic','nginx_next_sha256':r.H(r.next_nginx(r.NGINX.read_bytes())),'manifest_sha256':'manifest'}
    monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'tree',lambda root:{});monkeypatch.setattr(r,'STATIC_SHA',r.digest({}));monkeypatch.setattr(r,'verify_public',lambda *a:'newstatic');monkeypatch.setattr(r,'private_boundary',Mock())
    monkeypatch.setattr(r,'inspect_optional',lambda name:candidate);monkeypatch.setattr(r,'inspect',lambda name:candidate)
    monkeypatch.setattr(r,'read',lambda path,*args:json.dumps({'backend_after':{'service':'new'}}).encode() if path.name=='manifest.json' else json.dumps({str(i):'row' for i in range(111)}).encode() if path.name=='production-before-rows.json' else r.NGINX.read_bytes());monkeypatch.setattr(r,'sql_snapshot',lambda *a:{str(i):'row' for i in range(111)})
    monkeypatch.setattr(r,'inventory',lambda name:{'service':'new'});monkeypatch.setattr(r,'ready',Mock());monkeypatch.setattr(r,'write',Mock())
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(candidate,'schema','static'))
    (tmp_path/'production-before-rows.json').write_text('{}')
    monkeypatch.setattr(r,'schema_signature',lambda *a:'schema')
    run=Mock(return_value=json.dumps({'version':r.FRONTEND_VERSION}).encode());monkeypatch.setattr(r,'run',run);monkeypatch.setattr(r,'backup',Mock())
    result=r.rollback(tmp_path,receipt,original,{'service':'old'},{},'TEST')
    assert result['stage']=='STRIPE_HISTORY_CHARGE_ID_COMPAT_FORWARD_RECOVERED' and result['old_crm_build_started'] is False
    assert ['docker','start','candidate'] in [c.args[0] for c in run.call_args_list]
    assert not any(call.args[0]==['docker','start',r.OLD_ID] for call in run.call_args_list)

@pytest.mark.parametrize('kind',['schema','static','unknown_active'])
def test_forward_recovery_fails_closed_before_actions_on_unknown_state(monkeypatch,tmp_path,kind):
    original=original_info();receipt={'candidate_image':'sha256:'+'9'*64,'schema_sha256':'schema','old_static_sha256':'static','public_inventory_sha256':'newstatic','nginx_next_sha256':r.H(r.next_nginx(r.NGINX.read_bytes()))}
    monkeypatch.setattr(r,'schema_boundary',lambda:'bad' if kind=='schema' else 'schema')
    monkeypatch.setattr(r,'static_boundary',lambda:'bad' if kind=='static' else 'static');monkeypatch.setattr(r,'private_boundary',Mock())
    monkeypatch.setattr(r,'inspect_optional',lambda name:{'Id':'unknown','Image':'wrong','Config':{'Labels':{}}})
    run=Mock();monkeypatch.setattr(r,'run',run)
    with pytest.raises(RuntimeError):r.rollback(tmp_path,receipt,original,{}, {},'TEST')
    run.assert_not_called()

def test_recovery_cannot_undo_a_successful_release_without_new_review(monkeypatch,tmp_path):
    (tmp_path/'deployed.json').write_text('{}')
    monkeypatch.setattr(r,'reviewed_receipt',lambda *a:({}, {}, {}, {}))
    rollback=Mock(side_effect=AssertionError('successful release requires explicit new review'));monkeypatch.setattr(r,'rollback',rollback)
    with pytest.raises(RuntimeError,match='SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW'):r.recover(tmp_path,args(),manifest(),{})
    rollback.assert_not_called()

def test_builder_scope_and_no_migration_with_only_reviewed_component_payload_contract():
    builder=load(Path(__file__).with_name('build_payload.py'),'account_builder')
    assert builder.BASE==r.BASELINE and builder.BACKEND==r.BACKEND
    assert r.BACKEND=={'services/stripe_history_reconciliation.py'}
    code=Path(__file__).with_name('release.py').read_text()
    assert 'MIGRATE=' not in code and 'sqlite3.connect' in code and '?mode=ro' in code
    assert r.FRONTEND=={'components/StripeHistoryReconciliation.tsx'} and len(r.TESTS)==2
    assert 'database_migration' in code and 'next_nginx' in code

@pytest.mark.parametrize('name',['crm.env','business-before.db','probe-data/crm_prod.db','private/data.db','static/index.html','backend/.env','backend/routers/payments.py'])
def test_build_context_reincludes_only_the_single_approved_service(name):
    includes=[line[1:] for line in r.DOCKERIGNORE.decode().splitlines() if line.startswith('!')]
    assert name not in includes
    assert set(includes)=={'Dockerfile','backend','backend/services',*{'backend/'+path for path in r.BACKEND}}


@pytest.mark.parametrize('drift',[None,'rows','schema','protected_source'])
def test_offline_candidate_must_preserve_database_schema_and_every_other_backend_file(monkeypatch,tmp_path,drift):
    for name in ('release.py','manifest.json','payload.tar.gz'):(tmp_path/name).write_bytes(b'staged')
    original=original_info();selected=manifest();before={**selected['backend_before'],'services/finance.py':'protected'}
    monkeypatch.setattr(r,'BASE_BACKEND_SHA',r.digest(before))
    after={**before,**selected['backend_after']}
    if drift=='protected_source':after['services/finance.py']='changed'
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(original,'schema','static'))
    monkeypatch.setattr(r,'inventory',Mock(side_effect=[before,after]))
    monkeypatch.setattr(r,'extract',Mock());monkeypatch.setattr(old,'environment_file',Mock())
    monkeypatch.setattr(r,'build_image',lambda *a:'sha256:'+'9'*64);monkeypatch.setattr(r,'backup',Mock())
    monkeypatch.setattr(r,'offline_args',lambda *a:['docker','run','--rm','--network=none','image'])
    monkeypatch.setattr(r,'schema_signature',Mock(side_effect=['schema','changed' if drift=='schema' else 'schema']))
    monkeypatch.setattr(r,'sql_snapshot',Mock(side_effect=[{str(i):'before' for i in range(111)},{str(i):'changed' if drift=='rows' else 'before' for i in range(111)}]))
    monkeypatch.setattr(r,'stage_public',lambda *a:(r.public_root(),'newstatic'))
    monkeypatch.setattr(r,'ready',Mock());monkeypatch.setattr(r,'inspect',lambda *a:{});write=Mock(return_value='hash');monkeypatch.setattr(r,'write',write)
    run=Mock();monkeypatch.setattr(r,'run',run)
    if drift:
        with pytest.raises(RuntimeError):r.prepare(tmp_path,args(),selected,{})
        assert not any(call.args[0].name=='prepared.json' for call in write.call_args_list)
    else:
        r.prepare(tmp_path,args(),selected,{})
        receipt=next(call.args[1] for call in write.call_args_list if call.args[0].name=='prepared.json')
        assert receipt['offline_business_rows_unchanged'] and receipt['offline_schema_unchanged']
        assert receipt['database_migration'] is False and receipt['database_restored'] is False
    assert not any(r.OLD_ID in call.args[0] or 't24-private-api' in call.args[0] for call in run.call_args_list)
    assert ['docker','stop','-t','20','t24-stripe-history-charge-id-compat-probe-'+r.SOURCE[:12]] in [call.args[0] for call in run.call_args_list]


def test_generated_commands_are_hash_pinned_scoped_python(monkeypatch,tmp_path):
    generator=load(Path(__file__).with_name('make_commands.py'),'account_commands')
    package=tmp_path/'package';(package/'artifacts').mkdir(parents=True)
    selected=manifest();(package/'release.py').write_bytes(b'approved helper')
    (package/'artifacts/manifest.json').write_text(json.dumps(selected));(package/'artifacts/payload.tar.gz').write_bytes(b'payload')
    proof=tmp_path/'preflight.json';proof.write_bytes(b'{}\n');proofsha=r.H(proof.read_bytes())
    output=tmp_path/'commands';monkeypatch.setattr(generator,'DIRECTORY',str(package))
    monkeypatch.setattr(generator,'__file__',str(package/'make_commands.py'))
    monkeypatch.setattr('sys.argv',['commands','--carrier','4'*40,'--preflight','/opt/t24-crm/releases/preflight.json',
        '--preflight-sha256',proofsha,'--preflight-receipt',str(proof),'--out',str(output)])
    generator.main()
    script=(output/'prepare-command.sh').read_text();embedded=script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    compile(embedded,'generated_prepare','exec')
    assert 'SOURCE_SCOPE_DRIFT' in script and 'schema_revision' in script
    assert 'CARRIER_MEMBER_HASH_DRIFT' in script and 'IMMUTABLE_SOURCE_REQUIRED' in script
    assert 'stripe-history-charge-id-compat-' in script and "namespace['main']()" in script
    pins=json.loads((output/'package-pins.json').read_text())
    assert pins['source']==r.SOURCE and len(pins['files'])==3


def test_current_preflight_gate_rejects_wronghash_stage_runtime_and_dirty_receipt(monkeypatch,tmp_path):
    p={'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_READ_ONLY_PREFLIGHT','baseline_carrier':r.BASELINE,'crm':{'id':r.OLD_ID,'image':r.BASE_IMAGE,'config':r.OLD_CONFIG},
     'schema_revision':r.REVISION,'schema_sha256':r.SCHEMA_SHA,'business_table_count':111,'backend_inventory_sha256':r.BASE_BACKEND_SHA,
     'frontend_version':r.BASELINE_FRONTEND,'public_inventory_sha256':r.STATIC_SHA,'nginx_sha256':r.NGINX_SHA,'public_root':str(r.PUBLIC),
     'business_identity':{'device':r.BUSINESS_IDENTITY[0],'inode':r.BUSINESS_IDENTITY[1]},'readonly':True,'private_boundary_verified':True,
     'database_modified':False,'services_modified':False,'files_written':False,'provider_requests':False}
    monkeypatch.setattr(r,'read',lambda *a:json.dumps(p).encode());assert r.checked_live_preflight(tmp_path/'p',r.LIVE_PREFLIGHT_SHA)==p
    with pytest.raises(RuntimeError,match='EXACT_LIVE_PREFLIGHT_REQUIRED'):r.checked_live_preflight(tmp_path/'p','0'*64)
    for key,value in [('business_table_count',110),('readonly',False),('database_modified',True),('stage','OLD'),('public_root','/wrong')]:
     changed={**p,key:value};monkeypatch.setattr(r,'read',lambda *a,changed=changed:json.dumps(changed).encode())
     with pytest.raises(RuntimeError):r.checked_live_preflight(tmp_path/'p',r.LIVE_PREFLIGHT_SHA)


def test_forward_recovery_stops_original_but_only_starts_pinned_new_image(monkeypatch,tmp_path):
    original=original_info();candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64);candidate['Config']['Labels']=r.expected_labels(original)
    stopped=copy.deepcopy(original);stopped['State']['Running']=False
    receipt={'candidate_image':candidate['Image'],'schema_sha256':'schema','old_static_sha256':'static','public_inventory_sha256':'newstatic','nginx_next_sha256':r.H(r.next_nginx(r.NGINX.read_bytes())),'manifest_sha256':'manifest'}
    monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'tree',lambda root:{});monkeypatch.setattr(r,'STATIC_SHA',r.digest({}));monkeypatch.setattr(r,'verify_public',lambda *a:'newstatic');monkeypatch.setattr(r,'private_boundary',Mock())
    monkeypatch.setattr(r,'OLD_CONFIG',r.runtime(original)['config']);monkeypatch.setattr(r,'inspect_optional',lambda n:original)
    monkeypatch.setattr(r,'inspect',lambda n:stopped);monkeypatch.setattr(r,'docker_create',lambda *a:'candidate')
    monkeypatch.setattr(r,'read',lambda path,*a:json.dumps({'backend_after':{'service':'new'}}).encode() if path.name=='manifest.json' else json.dumps({str(i):'row' for i in range(111)}).encode() if path.name=='production-before-rows.json' else r.NGINX.read_bytes());monkeypatch.setattr(r,'sql_snapshot',lambda *a:{str(i):'row' for i in range(111)});monkeypatch.setattr(r,'inventory',lambda n:{'service':'new'})
    monkeypatch.setattr(r,'ready',Mock());monkeypatch.setattr(r,'write',Mock());monkeypatch.setattr(r,'boundary',lambda *a,**k:(candidate,'schema','static'))
    (tmp_path/'production-before-rows.json').write_text('{}');monkeypatch.setattr(r,'schema_signature',lambda *a:'schema');monkeypatch.setattr(r,'backup',Mock())
    run=Mock(return_value=json.dumps({'version':r.FRONTEND_VERSION}).encode());monkeypatch.setattr(r,'run',run);result=r.rollback(tmp_path,receipt,original,{'service':'old'},{},'TEST')
    commands=[c.args[0] for c in run.call_args_list];assert commands[0]==['docker','stop','-t','30',r.OLD_ID]
    assert ['docker','start',r.OLD_ID] not in commands and ['docker','start','candidate'] in commands
    assert result['old_crm_build_started'] is False and result['database_restored'] is False


def test_manifest_rejects_extra_test_frontend_or_unrelated_source(monkeypatch,tmp_path):
    for extra in ('app/backend/tests/test_other.py','app/frontend/src/pages/Dashboard.tsx','app/backend/services/finance.py'):
     selected=manifest();selected['changed_source_files'].append(extra);read_manifest(monkeypatch,selected)
     with pytest.raises(RuntimeError,match='EXACT_SOURCE_SCOPE_REQUIRED'):r.checked_manifest(tmp_path,args())


def test_proof_installer_is_exact_protected_file_only():
    generator=load(Path(__file__).with_name('make_commands.py'),'current_period_proof_installer')
    script=generator.receipt_installer('/opt/t24-crm/releases/current-period-proof.json',b'{}\n','5'*64)
    compile(script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0],'installer','exec')
    assert all(x in script for x in ('O_EXCL','O_NOFOLLOW','0o600','info.st_nlink==1','EXISTING_PROOF_HASH_DRIFT'))
    assert all(x not in script for x in ('sqlite3','docker','urllib','crm_prod.db','webhook-secret'))


@pytest.mark.parametrize('drift',['write','source','target','duplicate','mode'])
def test_existing_approved_readonly_key_mount_cannot_change(drift):
    info=original_info();actual_verify_secret_mount(info)
    if drift=='write':info['Mounts'][-1]['RW']=True
    if drift=='source':info['Mounts'][-1]['Source']='/wrong/key'
    if drift=='target':info['Mounts'][-1]['Destination']='/wrong/target'
    if drift=='duplicate':info['Mounts'].append(copy.deepcopy(info['Mounts'][-1]))
    if drift=='mode':info['Mounts'][-1]['Mode']='rw'
    with pytest.raises(RuntimeError):actual_verify_secret_mount(info)


def test_filled_history_tables_are_in_full_snapshot_and_never_forced_empty(tmp_path):
    path=tmp_path/'filled.db'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE stripe_history_bindings(id INTEGER PRIMARY KEY,snapshot JSON);INSERT INTO stripe_history_bindings VALUES(1,'{\"synthetic\":true}');CREATE TABLE stripe_history_invoice_reviews(id INTEGER PRIMARY KEY,status TEXT);INSERT INTO stripe_history_invoice_reviews VALUES(1,'exception');")
    before=r.sql_snapshot(path)
    assert before['stripe_history_bindings']['count']==1 and before['stripe_history_invoice_reviews']['count']==1
    assert r.sql_snapshot(path)==before
    with sqlite3.connect(path) as db:db.execute("UPDATE stripe_history_invoice_reviews SET status='pending_review'")
    assert r.sql_snapshot(path)!=before
    source=Path(__file__).with_name('release.py').read_text()
    assert 'new_tables_empty' not in source and 'pristine' not in source and 'NEW_TABLES' not in source

@pytest.mark.parametrize('name',['../crm.env','assets/../../private.key','.env','assets/chunk.js.map','assets/.secret.js','uploads/private.db'])
def test_public_manifest_rejects_sensitive_traversal_and_unpublished_paths(name):
    assert not r.static_path(name)


def test_nginx_changes_only_one_exact_public_root_and_keeps_private_routes():
    body=('server {\n root '+str(r.PUBLIC)+';\n location /private { proxy_pass http://private; }\n ssl_certificate /protected/path;\n}\n').encode()
    before=r.NGINX_SHA;r.NGINX_SHA=r.H(body)
    try:
        updated=actual_next_nginx(body)
        assert updated.replace(str(r.public_root()).encode(),str(r.PUBLIC).encode())==body
        assert b'location /private { proxy_pass http://private; }' in updated
    finally:r.NGINX_SHA=before


@pytest.mark.parametrize('kind',['duplicate_old','missing_old','new_already_present'])
def test_nginx_baseline_ambiguity_cannot_publish(monkeypatch,kind):
    old=('root '+str(r.PUBLIC)+';').encode();new=('root '+str(r.public_root())+';').encode()
    body=old+old if kind=='duplicate_old' else b'no root' if kind=='missing_old' else old+new
    monkeypatch.setattr(r,'NGINX_SHA',r.H(body))
    with pytest.raises(RuntimeError):actual_next_nginx(body)


def static_fixture(monkeypatch,tmp_path):
    baseline=tmp_path/'baseline';baseline.mkdir();(baseline/'assets').mkdir()
    (baseline/'app-version.json').write_text(json.dumps({'version':r.BASELINE_FRONTEND}))
    (baseline/'index.html').write_text('old index');(baseline/'assets/old.js').write_text('old immutable module')
    staged=tmp_path/'staging';(staged/'static/assets').mkdir(parents=True)
    files={'index.html':b'new index','app-version.json':json.dumps({'version':r.FRONTEND_VERSION}).encode(),'assets/new.js':b'new immutable module'}
    for name,body in files.items():(staged/'static'/name).write_bytes(body)
    selected=manifest();selected['files']={**{'backend/'+p:'2'*64 for p in r.BACKEND},**{'static/'+name:r.H(body) for name,body in files.items()}}
    target=tmp_path/'candidate';monkeypatch.setattr(r,'PUBLIC',baseline);monkeypatch.setattr(r,'public_root',lambda:target)
    monkeypatch.setattr(r,'read',lambda path,*a:Path(path).read_bytes());monkeypatch.setattr(r,'STATIC_SHA',r.digest(r.tree(baseline)))
    return baseline,staged,target,selected


def test_static_staging_is_unserved_exact_union_and_keeps_old_cached_assets(monkeypatch,tmp_path):
    baseline,staged,target,selected=static_fixture(monkeypatch,tmp_path);before=r.tree(baseline)
    root,digest=actual_stage_public(staged,selected)
    assert root==target and r.tree(baseline)==before and digest==r.digest(r.tree(target))
    assert (target/'assets/old.js').read_bytes()==(baseline/'assets/old.js').read_bytes()
    assert actual_verify_public(target,selected)==digest
    with pytest.raises(RuntimeError,match='FRESH_STATIC_ROOT_REQUIRED'):actual_stage_public(staged,selected)


@pytest.mark.parametrize('kind',['extra','missing','mutated'])
def test_staged_public_inventory_rejects_every_unreviewed_file_change(monkeypatch,tmp_path,kind):
    baseline,staged,target,selected=static_fixture(monkeypatch,tmp_path);actual_stage_public(staged,selected)
    if kind=='extra':(target/'assets/injected.js').write_text('unreviewed')
    if kind=='missing':(target/'assets/new.js').unlink()
    if kind=='mutated':(target/'index.html').write_text('changed')
    with pytest.raises(RuntimeError,match='EXACT_PUBLIC_FILE_DRIFT'):actual_verify_public(target,selected)


def test_static_asset_collision_never_overwrites_baseline_module(monkeypatch,tmp_path):
    baseline,staged,target,selected=static_fixture(monkeypatch,tmp_path)
    (staged/'static/assets/old.js').write_bytes(b'collision');selected['files']['static/assets/old.js']=r.H(b'collision')
    with pytest.raises(RuntimeError,match='STATIC_ASSET_COLLISION'):actual_stage_public(staged,selected)
    assert (baseline/'assets/old.js').read_text()=='old immutable module'


@pytest.mark.parametrize('kind',[None,'old_tree','new_tree','nginx'])
def test_published_static_boundary_checks_both_old_new_and_exact_nginx(monkeypatch,tmp_path,kind):
    baseline,staged,target,selected=static_fixture(monkeypatch,tmp_path);_,digest=actual_stage_public(staged,selected)
    nginx=tmp_path/'nginx.conf';body=('root '+str(target)+';').encode();nginx.write_bytes(body);monkeypatch.setattr(r,'NGINX',nginx)
    receipt={'public_root':str(target),'public_inventory_sha256':digest,'nginx_next_sha256':r.H(body)}
    if kind=='old_tree':(baseline/'index.html').write_text('changed old')
    if kind=='new_tree':(target/'index.html').write_text('changed new')
    if kind=='nginx':nginx.write_bytes(body+b' altered config')
    if kind:
        with pytest.raises(RuntimeError):actual_new_static_boundary(receipt)
    else:assert actual_new_static_boundary(receipt)==digest


def test_forward_recovery_refuses_filled_row_changes_before_public_switch(monkeypatch,tmp_path):
    original=original_info();candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64);candidate['Config']['Labels']=r.expected_labels(original)
    receipt={'candidate_image':candidate['Image'],'schema_sha256':'schema','public_inventory_sha256':'public','manifest_sha256':'manifest'}
    monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'tree',lambda *a:{});monkeypatch.setattr(r,'STATIC_SHA',r.digest({}));monkeypatch.setattr(r,'verify_public',lambda *a:'public');monkeypatch.setattr(r,'private_boundary',Mock())
    monkeypatch.setattr(r,'inspect_optional',lambda *a:candidate);monkeypatch.setattr(r,'ready',Mock());monkeypatch.setattr(r,'inventory',lambda *a:{'service':'new'})
    monkeypatch.setattr(r,'read',lambda path,*a:json.dumps({'backend_after':{'service':'new'}}).encode() if path.name=='manifest.json' else json.dumps({str(i):'before' for i in range(111)}).encode())
    monkeypatch.setattr(r,'sql_snapshot',lambda *a:{str(i):'changed' for i in range(111)});run=Mock();monkeypatch.setattr(r,'run',run)
    (tmp_path/'production-before-rows.json').write_text('{}')
    with pytest.raises(RuntimeError,match='FORWARD_FILLED_ROWS_CHANGED'):r.rollback(tmp_path,receipt,original,{'service':'old'},{},'TEST')
    assert run.call_count==0
    r.replace_nginx.assert_not_called();old.reload_nginx.assert_not_called()


def setup_forward_state(monkeypatch,tmp_path,active_kind='old',baseline_exists=False):
    original=original_info();stopped=copy.deepcopy(original);stopped['State']['Running']=False
    candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64);candidate['Config']['Labels']=r.expected_labels(original)
    active={'old':original,'candidate':candidate,'missing':None,'unknown':{'Id':'foreign','Image':'foreign','Config':{'Labels':{}}}}[active_kind]
    rows={str(i):'original filled row digest' for i in range(111)};events=[]
    if baseline_exists:(tmp_path/'production-before-rows.json').write_text(json.dumps(rows))
    (tmp_path/'nginx-before.conf').write_bytes(r.NGINX.read_bytes())
    receipt={'candidate_image':candidate['Image'],'schema_sha256':'schema','manifest_sha256':'manifest','public_inventory_sha256':'public'}
    monkeypatch.setattr(r,'OLD_CONFIG',r.runtime(original)['config']);monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'schema_signature',lambda *a:'schema')
    monkeypatch.setattr(r,'tree',lambda *a:{});monkeypatch.setattr(r,'STATIC_SHA',r.digest({}));monkeypatch.setattr(r,'verify_public',lambda *a:'public');monkeypatch.setattr(r,'private_boundary',Mock())
    monkeypatch.setattr(r,'inspect_optional',lambda *a:active);monkeypatch.setattr(r,'inspect',lambda *a:stopped);monkeypatch.setattr(r,'ready',Mock());monkeypatch.setattr(r,'inventory',lambda *a:{'service':'new'})
    monkeypatch.setattr(r,'read',lambda path,*a:json.dumps({'backend_after':{'service':'new'}}).encode() if path.name=='manifest.json' else path.read_bytes())
    def write(path,value):
        events.append(('write',path.name));path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());return 'hash'
    monkeypatch.setattr(r,'write',write)
    snapshots=Mock(side_effect=lambda path:rows);monkeypatch.setattr(r,'sql_snapshot',snapshots)
    def backup(source,target):
        assert (tmp_path/'production-before-rows.json').exists();events.append(('backup',target.name))
    backups=Mock(side_effect=backup);monkeypatch.setattr(r,'backup',backups)
    def run(command,*a):
        events.append(('command',command));return json.dumps({'version':r.FRONTEND_VERSION}).encode()
    runs=Mock(side_effect=run);monkeypatch.setattr(r,'run',runs)
    def create(*a):
        assert backups.call_count==1 and (tmp_path/'production-before-rows.json').exists();events.append(('create','candidate'));return 'candidate'
    creates=Mock(side_effect=create);monkeypatch.setattr(r,'docker_create',creates);monkeypatch.setattr(r,'boundary',lambda *a,**k:(candidate,'schema','public'))
    return original,receipt,rows,events,snapshots,backups,runs,creates


def test_early_failure_can_only_capture_stopped_original_baseline_before_forward(monkeypatch,tmp_path):
    original,receipt,rows,events,snapshots,backups,runs,creates=setup_forward_state(monkeypatch,tmp_path)
    result=r.rollback(tmp_path,receipt,original,{'service':'old'},{},'EARLY_FAILURE')
    assert result['all_111_rows_unchanged'] and result['old_crm_build_started'] is False and result['database_restored'] is False
    assert json.loads((tmp_path/'production-before-rows.json').read_text())==rows
    assert events.index(('write','production-before-rows.json'))<next(i for i,e in enumerate(events) if e[0]=='backup')<events.index(('create','candidate'))
    commands=[x.args[0] for x in runs.call_args_list];assert commands[0]==['docker','stop','-t','30',r.OLD_ID]
    assert ['docker','start',r.OLD_ID] not in commands and ['docker','start','candidate'] in commands


@pytest.mark.parametrize('kind',['candidate','missing','unknown'])
def test_missing_baseline_after_code_boundary_cannot_be_reinvented(monkeypatch,tmp_path,kind):
    original,receipt,rows,events,snapshots,backups,runs,creates=setup_forward_state(monkeypatch,tmp_path,kind)
    with pytest.raises(RuntimeError):r.rollback(tmp_path,receipt,original,{'service':'old'},{},'TEST')
    snapshots.assert_not_called();backups.assert_not_called();runs.assert_not_called();creates.assert_not_called()
    assert not (tmp_path/'production-before-rows.json').exists();r.replace_nginx.assert_not_called()


@pytest.mark.parametrize('failure',['stop','capture','backup'])
def test_early_forward_failures_leave_no_started_candidate_or_mixed_public_tree(monkeypatch,tmp_path,failure):
    original,receipt,rows,events,snapshots,backups,runs,creates=setup_forward_state(monkeypatch,tmp_path)
    if failure=='stop':monkeypatch.setattr(r,'run',Mock(side_effect=RuntimeError('STOP_FAILED')))
    if failure=='capture':monkeypatch.setattr(r,'write',Mock(side_effect=OSError('simulated disk full')))
    if failure=='backup':monkeypatch.setattr(r,'backup',Mock(side_effect=RuntimeError('BACKUP_FAILED')))
    with pytest.raises((RuntimeError,OSError)):r.rollback(tmp_path,receipt,original,{'service':'old'},{},'TEST')
    creates.assert_not_called();r.replace_nginx.assert_not_called();old.reload_nginx.assert_not_called()
    assert not any(e[0]=='command' and e[1][:2]==['docker','start'] for e in events)


def test_live_success_receipt_requires_111_rows_after_public_ready_and_version(monkeypatch,tmp_path):
    original=original_info();candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64)
    stopped=copy.deepcopy(original);stopped['State']['Running']=False
    receipt={'candidate_image':candidate['Image'],'old_crm':r.runtime(original),'schema_sha256':'schema','old_static_sha256':'static','public_inventory_sha256':'newstatic','nginx_next_sha256':r.H(r.next_nginx(r.NGINX.read_bytes()))}
    rows={str(i):'before' for i in range(111)};changed={**rows,'0':'changed after public ready'}
    monkeypatch.setattr(r,'reviewed_receipt',lambda *a:(receipt,original,{'source':'old'},{'source':'new'}))
    monkeypatch.setattr(r,'boundary',lambda *a,**k:(candidate if k.get('candidate') else original,'schema','newstatic' if k.get('new_public') else 'static'))
    monkeypatch.setattr(r,'inventory',lambda name:{'source':'old'} if name==r.OLD_ID else {'source':'new'})
    monkeypatch.setattr(r,'inspect',lambda name:stopped if name==r.OLD_ID else candidate);monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'backup',Mock())
    monkeypatch.setattr(r,'sql_snapshot',Mock(side_effect=[rows,rows,rows,changed]));monkeypatch.setattr(r,'docker_create',lambda *a:'candidate');monkeypatch.setattr(r,'ready',Mock())
    writes=Mock(return_value='hash');monkeypatch.setattr(r,'write',writes);run=Mock(return_value=json.dumps({'version':r.FRONTEND_VERSION}).encode());monkeypatch.setattr(r,'run',run);recovery=Mock();monkeypatch.setattr(r,'rollback',recovery)
    with pytest.raises(RuntimeError,match='FINAL_FILLED_ROWS_CHANGED'):r.activate(tmp_path,args(),manifest(),{})
    assert ['curl','-fsS','https://t24-crm.com/ready'] in [x.args[0] for x in run.call_args_list]
    assert ['curl','-fsS','https://t24-crm.com/app-version.json'] in [x.args[0] for x in run.call_args_list]
    assert not any(call.args[0].name=='deployed.json' for call in writes.call_args_list);recovery.assert_called_once()
