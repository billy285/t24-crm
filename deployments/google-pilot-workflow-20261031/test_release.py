"""Synthetic Docker state machine: never migrate, seed, restore or call providers."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v

r=load('pilot_author_release',HERE/'release.py');retained=load('pilot_reused_release_primitives',HERE.parent/'media-workflow-20261031/release.py')
OLD,NEW,IMAGE='a'*64,'b'*64,'sha256:'+'e'*64


def original():
    return {'Id':OLD,'Image':'sha256:'+'d'*64,'Name':'/t24-crm','Config':{'Image':'old','Hostname':'old','Env':['PRESERVED=synthetic','T24_GBP_SCHEDULER_ENABLED=true','T24_GBP_SCHEDULER_ACTIVATION_FROM='+r.ACTIVATION_FROM],'Labels':{'prior':'same'},'Cmd':['serve']},'HostConfig':{'AutoRemove':False,'OomKillDisable':None,'NetworkMode':'host','Privileged':False},'Mounts':[{'Source':'/synthetic/data','Destination':'/app/backend/data','RW':True}],'NetworkSettings':{'Networks':{}},'State':{'Running':True,'Status':'running','StartedAt':'old-start'},'RestartCount':0}


def runtime(info):return {'id':info['Id'],'image':info['Image'],'started':info['State']['StartedAt'],'restart':info['RestartCount'],'config':r.digest({key:info[key] for key in ('Config','HostConfig','Mounts','NetworkSettings')})}


def rows():
    value={'table_'+str(i):{'columns':['id'],'schema':{},'indexes':{},'count':i,'rows_sha256':r.H(str(i).encode())} for i in range(134)}
    value['media_publication_image_policies']={'columns':['owner_id','enabled'],'schema':{},'indexes':{},'count':1,'rows_sha256':r.H(b'EXISTING_OWNER_POLICY_ON')}
    value['media_operation_tasks']={'columns':['id'],'schema':{},'indexes':{},'count':1,'rows_sha256':r.H(b'EXISTING_DRAFT_TASK_ONE')};return value


class Docker:
    runtime=staticmethod(runtime)
    def __init__(self,nginx):self.items={OLD:original()};self.NGINX=nginx;self.calls=[];self.fault=None;self.rows=rows();self.sources={OLD:'old'}
    def inspect_optional(self,key):return copy.deepcopy(next((v for v in self.items.values() if key==v['Id'] or '/'+key==v['Name']),None))
    def inspect(self,key):
        row=self.inspect_optional(key);r.need(row is not None,'SYNTHETIC_CONTAINER_MISSING');return row
    def retained(self):return self
    def expected_labels(self,old):return {**old['Config']['Labels'],'t24.release.scope':r.SCOPE,'t24.release.source':r.SOURCE_SHA}
    def clone_config(self,image,old):
        c=copy.deepcopy(old['Config']);c.update(Image=image,Hostname='',Labels=self.expected_labels(old));c['HostConfig']=copy.deepcopy(old['HostConfig']);return c
    def docker_request(self,method,path,config):
        assert method=='POST';row=copy.deepcopy(original());row.update(Id=NEW,Image=IMAGE,Name='/'+path.split('=',1)[1]);row['Config']={k:copy.deepcopy(v) for k,v in config.items() if k!='HostConfig'};row['HostConfig']['OomKillDisable']=False;row['State'].update(Running=False,Status='created',StartedAt='0001-01-01T00:00:00Z');self.items[NEW]=row;self.sources[NEW]='new';return 201,json.dumps({'Id':NEW}).encode()
    def run(self,args,code,*_):
        self.calls.append(args)
        if self.fault:self.fault(args,code)
        if args[0]=='curl':return json.dumps({'version':r.FRONTEND} if args[-1].endswith('app-version.json') else {'status':'ready'}).encode()
        assert args[0]=='docker';op=args[1]
        if op=='stop':self.items[args[-1]]['State'].update(Running=False,Status='exited')
        elif op=='rename':assert not self.inspect_optional(args[3]);self.items[args[2]]['Name']='/'+args[3]
        elif op=='start':self.items[args[2]]['State'].update(Running=True,Status='running',StartedAt='new-start')
        elif op=='exec':return b'EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK'
        else:pytest.fail('Unexpected or write-capable command '+repr(args[:2]))
        return b''
    def read(self,path,sha=None):
        body=path.read_bytes();r.need(sha is None or r.H(body)==sha,'SYNTHETIC_HASH_DRIFT');return body
    def write(self,path,value):
        with path.open('xb') as stream:stream.write(value if isinstance(value,bytes) else r.encoded(value))
        return r.H(path.read_bytes())
    def ready(self,key):r.need(self.inspect(key)['State']['Running'] is True,'SYNTHETIC_NOT_READY')
    def verify_secret_mount(self,info):r.need(info['Mounts']==original()['Mounts'],'SECRET_MOUNT_DRIFT')
    def verify_production_worker_enabled(self,_):pass
    def verify_public(self,*_):return 'static'
    def next_nginx(self,body):return r.next_nginx(body,Path('/public/old'),Path('/public/new'))
    def replace_nginx(self,before,after):assert self.NGINX.read_bytes()==before;self.NGINX.write_bytes(after)
    def reload_nginx(self):
        self.calls.append(['reload-nginx'])
        if self.fault:self.fault(['reload-nginx'],'RELOAD')


@pytest.fixture
def publisher(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA','e'*40);monkeypatch.setattr(r,'FRONTEND','f'*12);monkeypatch.setattr(retained,'SOURCE_SHA',r.SOURCE_SHA);monkeypatch.setattr(retained,'FRONTEND',r.FRONTEND)
    release=tmp_path/'release';release.mkdir();nginx=tmp_path/'nginx';nginx.write_bytes(b'root /public/old; # callback and delivery blocks remain exact')
    v=object.__new__(r.Release);v.w=retained;v.args=SimpleNamespace(release=release,review_sha256='f'*64,preflight_sha256='c'*64);v.m=Docker(nginx);v.m.BUSINESS=tmp_path/'synthetic.db';v.public=Path('/public/new');v.old_name='reserved-old';v.candidate_name='reserved-new';v.manifest={};v.metadata='same';v.head=r.REVISION
    v.proof={'rows':retained.evidence(v.m.rows),'crm':runtime(original()),'nginx_sha256':r.H(nginx.read_bytes()),'schema_sha256':'schema'};v.before={'service':'old'};v.expected={'service':'new'}
    v.receipt={'candidate_image':IMAGE,'nginx_next_sha256':r.H(v.m.next_nginx(nginx.read_bytes())),'public_inventory_sha256':'static','candidate_inventory_sha256':'b'*64}
    v.reviewed=lambda:(copy.deepcopy(v.receipt),original(),v.before,v.expected);v.current=lambda:(original(),v.before);v.rows=lambda path=None:copy.deepcopy(v.m.rows)
    v.delivery_sentinel=lambda candidate_id:{'delivery_prefix_logging_protected':True,'noncapability_get_and_head_404_verified':True}
    def protections(**kwargs):r.need(v.metadata=='same' and v.head==r.REVISION,'SYNTHETIC_PRIVATE_OR_SCHEMA_DRIFT')
    v.protections=protections;v.source_boundary=lambda info,expected:r.need(v.m.sources[info['Id']]==('old' if expected==v.before else 'new'),'SYNTHETIC_SOURCE_DRIFT')
    def google(info):
        values=dict(row.split('=',1) for row in info['Config']['Env']);r.need(values['T24_GBP_SCHEDULER_ENABLED']=='true' and values['T24_GBP_SCHEDULER_ACTIVATION_FROM']==r.ACTIVATION_FROM,'SYNTHETIC_ON_CUTOFF_DRIFT')
    v.pf=SimpleNamespace(google_environment=google,ACTIVATION_FROM=r.ACTIVATION_FROM);v.helper=SimpleNamespace(validation_window=lambda _:None)
    return v


def test_complete_no_migration_switch_keeps_nonempty_policy_and_all_136_tables(publisher):
    v=publisher;before=copy.deepcopy(v.m.rows);result=v.activate()
    assert result['stage']=='GOOGLE_PILOT_WORKFLOW_DEPLOYED_VERIFIED' and result['all_136_table_rows_and_schema_unchanged'] and result['database_migration'] is False
    assert v.m.rows==before and len(v.m.rows)==136 and v.m.inspect('t24-crm')['Id']==NEW and not v.m.inspect(OLD)['State']['Running']
    assert v.m.inspect(NEW)['Config']['Env']==original()['Config']['Env']
    assert not any(c[:2] in (['docker','rm'],['docker','run']) for c in v.m.calls)
    assert not hasattr(r.Release,'run_migration')


def test_identity_persisted_before_original_stop(publisher):
    v=publisher
    def check(args,code):
        if args[:2]==['docker','stop']:assert json.loads((v.args.release/'candidate-created.json').read_bytes())['candidate_id']==NEW
    v.m.fault=check;v.activate()


@pytest.mark.parametrize('op',['rename','start','reload-nginx','curl'])
def test_failure_resumes_compatible_old_runtime_and_keeps_candidate_stopped(publisher,op):
    v=publisher;before=copy.deepcopy(v.m.rows);fired=[False]
    def fail(args,code):
        match=args[0]==op if op in {'reload-nginx','curl'} else args[:2]==['docker',op]
        if match and not fired[0]:fired[0]=True;raise RuntimeError('SYNTHETIC_SWITCH_FAILED')
    v.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_SWITCH_FAILED'):v.activate()
    assert v.m.inspect('t24-crm')['Id']==OLD and v.m.inspect(OLD)['State']['Running'] and not v.m.inspect(NEW)['State']['Running']
    assert v.m.rows==before and v.m.NGINX.read_bytes().startswith(b'root /public/old;')


def test_recovery_preserves_new_independent_rows_without_restore(publisher):
    v=publisher;fired=[False]
    def fail(args,code):
        if args[:3]==['docker','start',NEW] and not fired[0]:fired[0]=True;v.m.rows['media_operation_tasks']['count']=2;v.m.rows['media_operation_tasks']['rows_sha256']=r.H(b'LEGITIMATE_NEW_TASK');raise RuntimeError('SYNTHETIC_AFTER_INDEPENDENT_WRITE')
    v.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_AFTER_INDEPENDENT_WRITE'):v.activate()
    assert v.m.rows['media_operation_tasks']['count']==2 and v.m.inspect('t24-crm')['Id']==OLD


def test_identity_write_failure_never_stops_original_or_guesses_orphan(publisher):
    v=publisher;write=v.m.write
    def fail(path,value):
        if path.name=='candidate-created.json':raise OSError('synthetic full disk')
        return write(path,value)
    v.m.write=fail
    with pytest.raises(OSError):v.activate()
    assert v.m.inspect(OLD)['State']['Running'] and not any(c[:2] in (['docker','stop'],['docker','start'],['docker','rename']) for c in v.m.calls)


def test_late_private_or_schema_drift_contains_candidate_then_refuses_unsafe_resume(publisher):
    v=publisher
    def fail(args,code):
        if args[:3]==['docker','start',NEW]:v.metadata='changed'
    v.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_PRIVATE_OR_SCHEMA_DRIFT'):v.activate()
    assert not v.m.inspect(NEW)['State']['Running'] and not v.m.inspect(OLD)['State']['Running']


def test_owner_policy_mutation_during_start_is_detected_and_never_rewritten(publisher):
    v=publisher
    def mutate(args,code):
        if args[:3]==['docker','start',NEW]:v.m.rows['media_publication_image_policies']['rows_sha256']=r.H(b'OWNER_CHANGED_POLICY')
    v.m.fault=mutate
    with pytest.raises(RuntimeError,match='BUSINESS_ROWS_CHANGED_DURING_SWITCH'):v.activate()
    assert v.m.rows['media_publication_image_policies']['rows_sha256']==r.H(b'OWNER_CHANGED_POLICY')
    assert v.m.inspect('t24-crm')['Id']==OLD


def test_root_only_nginx_change_is_byte_reversible():
    before=b'root /public/old; location = /api/v1/google-business/oauth/callback { access_log off; } location ^~ /api/v1/media-publication-images/delivery/ { access_log off; error_log /dev/null crit; }'
    after=r.next_nginx(before,'/public/old','/public/new');assert after.replace(b'/public/new',b'/public/old')==before
    with pytest.raises(RuntimeError):r.next_nginx(before+b'root /public/old;','/public/old','/public/new')


def test_missing_or_zero_final_pins_rejected_before_any_helper_read(monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA','0'*40);monkeypatch.setattr(r,'protected_read',lambda *_:pytest.fail('read before pins'))
    with pytest.raises(RuntimeError,match='ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED'):r.Release(SimpleNamespace())


def isolated_prepare(v,tmp_path,*,startup_mutation=None):
    import sqlite3
    metadata=load('pilot_actual_retained_metadata',HERE.parent/'media-ops-review-refresh-retry-20261031/preflight.py')
    base=load('pilot_actual_retained_offline_environment',HERE.parent/'media-ops-management-20261031/release.py')
    prior_tests=load('pilot_reused_sql_snapshot_fixture',HERE.parent/'media-workflow-20261031/test_release.py')
    source=tmp_path/'production-synthetic.db'
    with sqlite3.connect(source) as con:
        con.execute('CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)');con.execute('INSERT INTO alembic_version VALUES(?)',(r.REVISION,));con.execute('CREATE TABLE finance_canary(id INTEGER PRIMARY KEY AUTOINCREMENT, amount INTEGER UNIQUE)');con.execute('INSERT INTO finance_canary VALUES(42,198)')
        con.execute('CREATE TABLE media_publication_image_policies(owner_id INTEGER PRIMARY KEY,enabled INTEGER)');con.execute('INSERT INTO media_publication_image_policies VALUES(1,1)')
        con.execute('CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY,status TEXT)');con.execute("INSERT INTO media_operation_tasks VALUES(1,'draft')")
        for i in range(132):con.execute('CREATE TABLE table_'+str(i)+'(id INTEGER PRIMARY KEY)')
        con.execute('PRAGMA user_version=17');con.execute('PRAGMA application_id=42')
    v.base=base;v.m.BUSINESS=source;v.m.sql_snapshot=prior_tests.sql_snapshot;v.rows=lambda path=None:retained.snapshot(v.m,path or source)
    v.m.schema_signature=lambda path,revision:r.digest(sorted((list(k),value) for k,value in retained.objects(path).items()));v.metadata=lambda path:metadata.db_metadata(path)
    v.proof={'rows':retained.evidence(v.rows()),'database_metadata':v.metadata(source),'schema_sha256':v.m.schema_signature(source,r.REVISION)};v.args.manifest_sha256='4'*64;v.args.payload_sha256='5'*64;v.manifest={'backend_after':v.expected};v.offline_name='synthetic-pilot-offline';v.image=lambda:IMAGE
    def backup(left,right):
        with sqlite3.connect('file:'+str(left)+'?mode=ro',uri=True) as src,sqlite3.connect(right) as dst:src.backup(dst)
    v.m.backup=backup;v.m.extract=lambda *_:None;v.helper=SimpleNamespace(docker_timestamp_probe=metadata.docker_timestamp_probe)
    v.m.inventory=lambda key:v.expected if key==v.offline_name else v.before;v.m.stage_public=lambda *_:(v.public,'static')
    for name in ('release.py','preflight.py','manifest.json','payload.tar.gz'):(v.args.release/name).write_bytes(b'synthetic-public-tool')
    run=v.m.run;injected=[False]
    def offline_run(args,code,*timeout):
        if args[:2]==['docker','run']:
            assert '--network=none' in args and '--read-only' in args and '--env-file' not in args
            values=[args[i+1] for i,arg in enumerate(args) if arg=='-e'];assert 'T24_GBP_SCHEDULER_ENABLED=false' in values and 'T24_GBP_SCHEDULER_ACTIVATION_FROM=' in values
            assert all('DO_NOT_EXPORT' not in value for value in values)
            row=original();row.update(Id='7'*64,Name='/'+v.offline_name);row['Config']['Env']=values;row['HostConfig']['NetworkMode']='none';row['Mounts']=[];v.m.items[row['Id']]=row;return b''
        if args[:3]==['docker','exec',v.offline_name]:
            if startup_mutation and not injected[0]:
                injected[0]=True
                with sqlite3.connect(v.args.release/'probe-data/crm_prod.db') as con:
                    if startup_mutation=='ignored_insert':con.execute('INSERT OR IGNORE INTO finance_canary(amount) VALUES(198)')
                    elif startup_mutation=='policy':con.execute('UPDATE media_publication_image_policies SET enabled=0')
                    elif startup_mutation=='schema':con.execute('CREATE TABLE surprise(id INTEGER)')
            return b'EXACT_PYTHON310 EXACT_GOOGLE_PILOT_AND_EXISTING_MEDIA_ROUTES EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'
        if args[:2]==['docker','stop'] and args[-1]==v.offline_name:v.m.items['7'*64]['State']['Running']=False;return b''
        return run(args,code,*timeout)
    v.m.run=offline_run;return source,metadata


def test_actual_prepare_offline_no_migration_preserves_136_nonempty_tables_and_own_metadata(publisher,tmp_path):
    v=publisher;source,metadata=isolated_prepare(v,tmp_path);before=source.read_bytes();result=v.prepare()
    assert result['stage']=='GOOGLE_PILOT_WORKFLOW_PREPARED_OFFLINE_VERIFIED' and result['database_migration'] is False and result['offline_all_rows_schema_metadata_unchanged']
    assert source.read_bytes()==before and v.rows()==v.rows(v.args.release/'probe-data/crm_prod.db') and len(v.rows())==136
    assert metadata.db_metadata(source)==metadata.db_metadata(v.args.release/'probe-data/crm_prod.db')
    assert v.rows()['media_publication_image_policies']['count']==1


@pytest.mark.parametrize('mutation',['ignored_insert','policy','schema'])
def test_offline_startup_cannot_change_counter_policy_or_schema(publisher,tmp_path,mutation):
    v=publisher;source,_=isolated_prepare(v,tmp_path,startup_mutation=mutation);before=source.read_bytes()
    with pytest.raises(RuntimeError,match='OFFLINE_STARTUP_CHANGED_DATABASE'):v.prepare()
    assert source.read_bytes()==before and not (v.args.release/'prepared.json').exists()
