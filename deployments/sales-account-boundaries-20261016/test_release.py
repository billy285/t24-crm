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
old=load(Path(__file__).parents[1]/'sales-dossier-20261016/release.py','retained_release')

@pytest.fixture(autouse=True)
def no_real_actions(monkeypatch):
    def forbid(*args,**kwargs):raise AssertionError('No real process, Docker or public write allowed')
    monkeypatch.setattr(subprocess,'run',forbid);monkeypatch.setattr(subprocess,'check_output',forbid)
    monkeypatch.setattr(old,'docker_request',forbid);monkeypatch.setattr(r,'retained',lambda:old)

def original_info():
    return {'Id':r.OLD_ID,'Image':r.BASE_IMAGE,'State':{'Running':True,'StartedAt':'2026-10-16T00:00:00Z'},
        'RestartCount':0,'Name':'/t24-crm','Config':{'Image':r.BASE_IMAGE,'Hostname':'original','Labels':{'old':'preserved'},
        'Env':['PRIVATE_KEY=synthetic-only','DATABASE_SCHEMA_MODE=verify'],'Cmd':['python','-m','main']},
        'HostConfig':{'AutoRemove':False,'NetworkMode':'none','RestartPolicy':{'Name':'unless-stopped'},'Binds':['/data:/app/backend/data:rw']},
        'Mounts':[{'Type':'bind','Source':'/data','Destination':'/app/backend/data','RW':True,'Propagation':'rprivate'}],
        'NetworkSettings':{'Networks':{}}}

def manifest():
    return {'source_sha':r.SOURCE,'baseline_source_sha':r.BASELINE,'baseline_application_source':r.BASELINE_APPLICATION_SOURCE,
        'frontend_version':r.FRONTEND_VERSION,'schema_revision':r.REVISION,'payload_sha256':'payload',
        'credentials_included':False,'preserved':r.PRESERVED,'backend_only':True,
        'backend_before':dict.fromkeys(r.BACKEND,'1'*64),'backend_after':dict.fromkeys(r.BACKEND,'2'*64),
        'files':{'backend/'+path:'2'*64 for path in r.BACKEND}}

def read_manifest(monkeypatch,value):
    monkeypatch.setattr(r,'read',lambda path,*args:json.dumps(value).encode() if path.name=='manifest.json' else b'payload')

def args():return SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload',preflight_sha256='preflight',review_sha256='review')

def test_exact_three_router_manifest_accepted(monkeypatch,tmp_path):
    value=manifest();read_manifest(monkeypatch,value);assert r.checked_manifest(tmp_path,args())==value

@pytest.mark.parametrize('field,value',[('source_sha','0'*40),('baseline_source_sha','0'*40),
    ('baseline_application_source','0'*40),('frontend_version','0'*12),('schema_revision','other'),
    ('credentials_included',True),('backend_only',False),('preserved',{'schema':True}),
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
    value=manifest();value['files']['backend/routers/ringcentral.py']='3'*64;read_manifest(monkeypatch,value)
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
        db.executescript("CREATE TABLE alembic_version(version_num TEXT);INSERT INTO alembic_version VALUES ('f7d1c5a9b027');CREATE TABLE payments(id INTEGER PRIMARY KEY,amount REAL);INSERT INTO payments VALUES(1,123.45);")
    first=r.schema_signature(path)
    with sqlite3.connect(path) as db:db.execute('CREATE INDEX new_index ON payments(amount)')
    assert r.schema_signature(path)!=first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM payments').fetchall()==[(1,123.45)]
        db.execute("UPDATE alembic_version SET version_num='wrong'")
    with pytest.raises(RuntimeError,match='SCHEMA_REVISION_DRIFT'):r.schema_signature(path)

@pytest.mark.parametrize('running,wrong_id,wrong_image',[(True,False,False),(False,True,False),(False,False,True)])
def test_stop_must_be_verified_before_snapshot_or_swap(monkeypatch,tmp_path,running,wrong_id,wrong_image):
    original=original_info();receipt={'candidate_image':'sha256:'+'9'*64,'old_crm':r.runtime(original),'schema_sha256':'schema','static_sha256':'static'}
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

def test_rollback_restores_only_pinned_original_and_never_restores_database(monkeypatch,tmp_path):
    original=original_info();original['State']['Running']=False;original['Name']='/retained'
    candidate=copy.deepcopy(original);candidate.update(Id='candidate',Image='sha256:'+'9'*64)
    candidate['Config']['Labels']=r.expected_labels(original)
    receipt={'candidate_image':candidate['Image'],'old_crm':r.runtime(original),'schema_sha256':'schema','static_sha256':'static'}
    monkeypatch.setattr(r,'schema_boundary',lambda:'schema');monkeypatch.setattr(r,'inspect_optional',lambda name:candidate)
    monkeypatch.setattr(r,'inspect',lambda name:original if name==r.OLD_ID else candidate)
    monkeypatch.setattr(r,'inventory',lambda name:{'router.py':'original'});monkeypatch.setattr(r,'ready',Mock())
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(original,'schema','static'));monkeypatch.setattr(r,'write',Mock())
    run=Mock();monkeypatch.setattr(r,'run',run)
    monkeypatch.setattr(r,'backup',Mock(side_effect=AssertionError('no DB restore or replacement allowed')))
    result=r.rollback(tmp_path,receipt,original,{'router.py':'original'},{},'TEST_FAILURE')
    assert result['stage']=='SALES_ACCOUNT_ROLLED_BACK' and result['database_restored'] is False
    assert result['database_migration'] is False and result['static_modified'] is False and result['nginx_modified'] is False
    starts=[call.args[0] for call in run.call_args_list if call.args[0][1]=='start']
    assert starts==[['docker','start',r.OLD_ID]]
    assert all('private' not in ' '.join(call.args[0]) for call in run.call_args_list)

@pytest.mark.parametrize('kind',['schema','unknown_active','original_image','original_config'])
def test_rollback_fails_closed_on_unknown_container_schema_or_saved_config(monkeypatch,tmp_path,kind):
    original=original_info();receipt={'candidate_image':'sha256:'+'9'*64,'old_crm':r.runtime(original),'schema_sha256':'schema','static_sha256':'static'}
    monkeypatch.setattr(r,'schema_boundary',lambda:'bad' if kind=='schema' else 'schema')
    active={'Id':'unknown','Image':'sha256:'+'8'*64,'Config':{'Labels':{}},'State':{'Running':True}}
    monkeypatch.setattr(r,'inspect_optional',lambda name:active if kind=='unknown_active' else None)
    if kind=='original_image':original['Image']='wrong'
    if kind=='original_config':original['Config']['Env'].append('UNREVIEWED=1')
    monkeypatch.setattr(r,'inspect',lambda name:original);monkeypatch.setattr(r,'write',Mock())
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(original,'schema','static'))
    run=Mock();monkeypatch.setattr(r,'run',run)
    with pytest.raises(RuntimeError,match='ROLLBACK_INCOMPLETE'):r.rollback(tmp_path,receipt,original,{}, {},'TEST')
    run.assert_not_called()

def test_recovery_cannot_undo_a_successful_release_without_new_review(monkeypatch,tmp_path):
    (tmp_path/'deployed.json').write_text('{}')
    monkeypatch.setattr(r,'reviewed_receipt',lambda *a:({}, {}, {}, {}))
    rollback=Mock(side_effect=AssertionError('successful release requires explicit new review'));monkeypatch.setattr(r,'rollback',rollback)
    with pytest.raises(RuntimeError,match='SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW'):r.recover(tmp_path,args(),manifest(),{})
    rollback.assert_not_called()

def test_builder_scope_and_no_migration_or_frontend_payload_contract():
    builder=load(Path(__file__).with_name('build_payload.py'),'account_builder')
    assert builder.SOURCE==r.SOURCE and builder.BASE==r.BASELINE and builder.BACKEND==r.BACKEND
    assert r.BACKEND=={'routers/ringcentral.py','routers/sales_intelligence.py','routers/sales_deal_controls.py'}
    code=Path(__file__).with_name('release.py').read_text()
    assert 'MIGRATE=' not in code and 'sqlite3.connect' in code and '?mode=ro' in code
    assert 'swap_nginx' not in code and 'reload_nginx' not in code

@pytest.mark.parametrize('name',['crm.env','business-before.db','probe-data/crm_prod.db','private/data.db','static/index.html','backend/.env','backend/routers/payments.py'])
def test_build_context_reincludes_only_three_approved_sources(name):
    includes=[line[1:] for line in r.DOCKERIGNORE.decode().splitlines() if line.startswith('!')]
    assert name not in includes
    assert set(includes)=={'Dockerfile','backend','backend/routers',*{'backend/'+path for path in r.BACKEND}}


@pytest.mark.parametrize('drift',[None,'rows','schema','protected_source'])
def test_offline_candidate_must_preserve_database_schema_and_every_other_backend_file(monkeypatch,tmp_path,drift):
    for name in ('release.py','manifest.json','payload.tar.gz'):(tmp_path/name).write_bytes(b'staged')
    original=original_info();selected=manifest();before={**selected['backend_before'],'services/finance.py':'protected'}
    after={**before,**selected['backend_after']}
    if drift=='protected_source':after['services/finance.py']='changed'
    monkeypatch.setattr(r,'boundary',lambda *a,**kw:(original,'schema','static'))
    monkeypatch.setattr(r,'inventory',Mock(side_effect=[before,after]))
    monkeypatch.setattr(r,'extract',Mock());monkeypatch.setattr(old,'environment_file',Mock())
    monkeypatch.setattr(r,'build_image',lambda *a:'sha256:'+'9'*64);monkeypatch.setattr(r,'backup',Mock())
    monkeypatch.setattr(r,'offline_args',lambda *a:['docker','run','--rm','--network=none','image'])
    monkeypatch.setattr(r,'schema_signature',Mock(side_effect=['schema','changed' if drift=='schema' else 'schema']))
    monkeypatch.setattr(r,'sql_snapshot',Mock(side_effect=[{'rows':'before'},{'rows':'changed' if drift=='rows' else 'before'}]))
    monkeypatch.setattr(r,'ready',Mock());write=Mock(return_value='hash');monkeypatch.setattr(r,'write',write)
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
    assert ['docker','stop','-t','20','t24-sales-account-probe-'+r.SOURCE[:12]] in [call.args[0] for call in run.call_args_list]


def test_generated_commands_are_hash_pinned_backend_only_python(monkeypatch,tmp_path):
    generator=load(Path(__file__).with_name('make_commands.py'),'account_commands')
    package=tmp_path/'package';(package/'artifacts').mkdir(parents=True)
    selected=manifest();(package/'release.py').write_bytes(b'approved helper')
    (package/'artifacts/manifest.json').write_text(json.dumps(selected));(package/'artifacts/payload.tar.gz').write_bytes(b'payload')
    output=tmp_path/'commands';monkeypatch.setattr(generator,'DIRECTORY',str(package))
    monkeypatch.setattr(generator,'__file__',str(package/'make_commands.py'))
    monkeypatch.setattr('sys.argv',['commands','--carrier','4'*40,'--preflight','/opt/t24-crm/releases/preflight.json',
        '--preflight-sha256','5'*64,'--out',str(output)])
    generator.main()
    script=(output/'prepare-command.sh').read_text();embedded=script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    compile(embedded,'generated_prepare','exec')
    assert 'len(manifest' not in script and "set(manifest['backend_after'])=={'routers/ringcentral.py'" in script
    assert 'CARRIER_MEMBER_HASH_DRIFT' in script and 'IMMUTABLE_SOURCE_REQUIRED' in script
    assert 'sales-account-boundaries-' in script and "namespace['main']()" in script
    pins=json.loads((output/'package-pins.json').read_text())
    assert pins['source']==r.SOURCE and len(pins['files'])==3
