"""Synthetic Docker and real SQLite copying only; never production or providers."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v
r=load('diagnostic_release_author',HERE/'release.py');w=load('diagnostic_retained_safe_primitives',HERE.parent/'meta-business-20261031/release.py')
OLD='a'*64;NEW='b'*64;BASE='sha256:'+'d'*64;IMAGE='sha256:'+'e'*64


def original():
    return {'Id':OLD,'Image':BASE,'Name':'/t24-crm','Config':{'Image':'retained-original-image','Hostname':'old-host','Env':['PRESERVED=DO_NOT_EXPORT','T24_META_APP_SECRET=SYNTHETIC_META_SECRET','T24_META_ENABLED=true','T24_GBP_SCHEDULER_ENABLED=true','T24_GBP_SCHEDULER_ACTIVATION_FROM=2026-10-30T19:42:04Z'],'Labels':{'existing':'unchanged'},'Cmd':['serve']},'HostConfig':{'AutoRemove':False,'OomKillDisable':None,'NetworkMode':'host','Privileged':False},'Mounts':[{'Source':'/synthetic/data','Destination':'/app/backend/data','RW':True}],'NetworkSettings':{'Networks':{}},'State':{'Running':True,'Status':'running','StartedAt':'old-start'},'RestartCount':0}


def runtime(info):return {'id':info['Id'],'image':info['Image'],'config':r.digest({k:info[k] for k in ('Config','HostConfig','Mounts','NetworkSettings')}),'started':info['State']['StartedAt'],'restart':info['RestartCount']}


def rows():
    result={f'table_{i}':{'columns':['id'],'schema':{},'indexes':{},'count':i,'rows_sha256':'a'*64} for i in range(138)}
    result.update(meta_business_oauth_states={'columns':['id','consumed'],'schema':{},'indexes':{},'count':2,'rows_sha256':'existing-two-flows'},media_publication_image_policies={'columns':['owner_id','enabled'],'schema':{},'indexes':{},'count':1,'rows_sha256':'owner-on'},google_business_actions={'columns':['id','status'],'schema':{},'indexes':{},'count':8,'rows_sha256':'already-live'});return result


class Docker:
    runtime=staticmethod(runtime)
    def __init__(self):self.items={OLD:original()};self.calls=[];self.hook=None;self.sources={OLD:'old'};self.rows=rows()
    def inspect_optional(self,key):return copy.deepcopy(next((row for row in self.items.values() if row['Id']==key or row['Name']=='/'+key),None))
    def inspect(self,key):row=self.inspect_optional(key);r.need(row is not None,'SYNTHETIC_CONTAINER_MISSING');return row
    def retained(self):return self
    def clone_networks(self,info):return copy.deepcopy(info['NetworkSettings']['Networks'])
    def docker_request(self,method,path,config):
        assert method=='POST';row=original();row.update(Id=NEW,Image=IMAGE,Name='/'+path.split('=',1)[1]);row['Config']={k:copy.deepcopy(v) for k,v in config.items() if k not in {'HostConfig','NetworkingConfig'}};row['HostConfig']=copy.deepcopy(config['HostConfig']);row['HostConfig']['OomKillDisable']=False;row['State'].update(Running=False,Status='created',StartedAt='0001-01-01T00:00:00Z');self.items[NEW]=row;self.sources[NEW]='new'
        if self.hook:self.hook('created',self)
        return 201,json.dumps({'Id':NEW}).encode()
    def run(self,args,code,*_):
        self.calls.append(args)
        if self.hook:self.hook(code,self)
        assert args[0]=='docker';op=args[1]
        if op=='stop':self.items[args[-1]]['State'].update(Running=False,Status='exited')
        elif op=='rename':assert not self.inspect_optional(args[3]);self.items[args[2]]['Name']='/'+args[3]
        elif op=='start':self.items[args[2]]['State'].update(Running=True,Status='running',StartedAt='new-start')
        elif op=='exec':return b'EXACT_META_CONFIGURED_GOOGLE_ON_NO_NETWORK'
        else:pytest.fail('Unreviewed operation '+repr(args[:2]))
        return b''
    def read(self,path,sha=None):
        body=path.read_bytes();r.need(sha is None or r.H(body)==sha,'SYNTHETIC_HASH_DRIFT');return body
    def write(self,path,value):
        body=value if isinstance(value,bytes) else r.encoded(value)
        with path.open('xb') as stream:stream.write(body)
        return r.H(body)
    def ready(self,key):r.need(self.inspect(key)['State']['Running'] is True,'SYNTHETIC_NOT_READY')


@pytest.fixture
def publisher(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA','f'*40);stage=tmp_path/'release';stage.mkdir(mode=0o700)
    v=object.__new__(r.Release);v.m=Docker();v.w=w;v.args=SimpleNamespace(release=stage,review_sha256='9'*64,preflight_sha256=r.ACTUAL_PREFLIGHT_SHA);v.old_name='old-reserved';v.candidate_name='new-reserved';v.before={'service':'old'};v.expected={'service':'new'};v.manifest={};v.proof={'crm':runtime(original()),'rows':w.evidence(v.m.rows)};v.unsafe=False
    v.receipt={'candidate_image':IMAGE,'after_inventory_sha256':'b'*64};v.reviewed=lambda **kwargs:(copy.deepcopy(v.receipt),original(),v.before,v.expected);v.current=lambda:(original(),v.before);v.rows=lambda path=None:copy.deepcopy(v.m.rows)
    def boundaries(*,recovery=False):
        r.need(not v.unsafe,'SYNTHETIC_PRIVATE_OR_SCHEMA_DRIFT')
        if not recovery:r.need(w.evidence(v.m.rows)==v.proof['rows'],'SYNTHETIC_BUSINESS_ROWS_CHANGED')
    v.boundaries=boundaries
    v.environment=lambda info:r.need(info['Config']['Env']==original()['Config']['Env'],'SYNTHETIC_EXISTING_META_ENV_CHANGED')
    v.source_boundary=lambda info,expected:r.need(v.m.sources[info['Id']]==('old' if expected==v.before else 'new'),'SYNTHETIC_SOURCE_CHANGED')
    v.helper=SimpleNamespace(validation_window=lambda _:None);v.activation=SimpleNamespace(_configured_probe=lambda:'public-config-only-no-network')
    v.public_check=lambda *args:{'meta_callback_privacy_headers_verified':True,'content_security_policy_sha256':'same-csp'}
    return v


def test_backend_only_switch_retains_two_oauth_rows_and_all_env_labels_without_secret_journal(publisher):
    v=publisher;before=copy.deepcopy(v.m.rows);result=v.activate();assert result['stage']=='META_OAUTH_DIAGNOSTICS_DEPLOYED' and result['frontend_static_nginx_csp_unchanged']
    assert v.m.rows==before and len(v.m.rows)==141 and v.m.rows['meta_business_oauth_states']['count']==2
    assert v.m.inspect('t24-crm')['Id']==NEW and not v.m.inspect(OLD)['State']['Running']
    assert v.m.inspect(NEW)['Config']['Env']==original()['Config']['Env'] and v.m.inspect(NEW)['Config']['Labels']==original()['Config']['Labels']
    for path in v.args.release.glob('*.json'):assert 'SYNTHETIC_META_SECRET' not in path.read_text() and 'DO_NOT_EXPORT' not in path.read_text()
    assert not (v.args.release/'original-container.json').exists() and not any(x[:2] in (['docker','rm'],['docker','cp']) for x in v.m.calls)


def test_candidate_id_durable_before_old_stop(publisher):
    v=publisher
    def check(code,m):
        if code=='ORIGINAL_STOP_FAILED':assert json.loads((v.args.release/'candidate-created.json').read_bytes())['candidate_id']==NEW
    v.m.hook=check;v.activate()


@pytest.mark.parametrize('kind',['rename','start','probe','privacy','independent_rows'])
def test_failure_recovers_original_without_writing_or_restoring_database(publisher,kind):
    v=publisher;fired=[]
    def fail(code,m):
        target={'rename':'ORIGINAL_RENAME_FAILED','start':'PATCH_START_FAILED','probe':'META_AND_GOOGLE_CONFIGURATION_PROBE_FAILED','independent_rows':'PATCH_START_FAILED'}.get(kind)
        if code==target and not fired:
            fired.append(True)
            if kind=='independent_rows':m.rows['meta_business_oauth_states']['count']=3
            raise RuntimeError('SYNTHETIC_SWITCH_FAILED')
    v.m.hook=fail
    if kind=='privacy':v.public_check=lambda *a:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_PRIVACY_FAILED'))
    with pytest.raises(RuntimeError):v.activate()
    assert v.m.inspect('t24-crm')['Id']==OLD and v.m.inspect(OLD)['State']['Running'] and not v.m.inspect(NEW)['State']['Running']
    assert not (v.args.release/'deployed.json').exists()
    if kind=='independent_rows':assert v.m.rows['meta_business_oauth_states']['count']==3


def test_identity_write_failure_never_guesses_or_stops_original(publisher):
    v=publisher;write=v.m.write
    def fail(path,value):
        if path.name=='candidate-created.json':raise OSError('synthetic full disk')
        return write(path,value)
    v.m.write=fail
    with pytest.raises(OSError):v.activate()
    assert v.m.inspect(OLD)['State']['Running'] and not any(x[:2] in (['docker','stop'],['docker','rename']) for x in v.m.calls)


def test_private_drift_after_start_contains_candidate_and_refuses_unsafe_resume(publisher):
    v=publisher
    def drift(code,m):
        if code=='META_AND_GOOGLE_CONFIGURATION_PROBE_FAILED':v.unsafe=True
    v.m.hook=drift
    with pytest.raises(RuntimeError,match='SYNTHETIC_PRIVATE_OR_SCHEMA_DRIFT'):v.activate()
    assert not v.m.inspect(NEW)['State']['Running'] and not v.m.inspect(OLD)['State']['Running']


@pytest.mark.parametrize('field',['env','label','mount','host','oom','image','ipam'])
def test_only_two_backend_image_change_is_permitted(publisher,field):
    old=original();v=publisher;config=copy.deepcopy(old['Config']);config['HostConfig']=copy.deepcopy(old['HostConfig']);v.m.docker_request('POST','/containers/create?name=new',config);candidate=v.m.inspect(NEW)
    if field=='env':candidate['Config']['Env'].append('EXTRA=true')
    elif field=='label':candidate['Config']['Labels']['changed']='yes'
    elif field=='mount':candidate['Mounts'][0]['RW']=False
    elif field=='host':candidate['HostConfig']['Privileged']=True
    elif field=='oom':candidate['HostConfig']['OomKillDisable']=True
    elif field=='image':candidate['Image']=BASE
    else:candidate['NetworkSettings']['Networks']['bridge']={'IPAMConfig':{'IPv4Address':'192.0.2.1'}}
    with pytest.raises(RuntimeError):r.compare(candidate,old,IMAGE,v.m)


def test_missing_final_source_pin_fails_before_reading_any_helper(monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA',None);monkeypatch.setattr(r,'local_bytes',lambda *_:pytest.fail('read before pins'))
    with pytest.raises(RuntimeError,match='ACTUAL_DIAGNOSTIC_SOURCE_AND_FREEZE_REQUIRED'):r.Release(SimpleNamespace())


def db_snapshot(path):
    out={}
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as con:
        for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            fields=con.execute('PRAGMA table_info("'+name+'")').fetchall();values=sorted(json.dumps(list(row)) for row in con.execute('SELECT * FROM "'+name+'"'))
            out[name]={'columns':[x[1] for x in fields],'schema':{x[1]:list(x[2:]) for x in fields},'indexes':{},'count':len(values),'rows_sha256':r.H('\n'.join(values).encode())}
    return out


def isolated(v,tmp_path,*,mutate=None):
    base=load('diag_actual_offline_environment',HERE.parent/'media-ops-management-20261031/release.py');md=load('diag_actual_db_metadata',HERE.parent/'media-ops-review-refresh-retry-20261031/preflight.py');source=tmp_path/'source.db'
    with sqlite3.connect(source) as con:
        con.executescript("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);CREATE TABLE monthly_deduction_rates(id INTEGER PRIMARY KEY AUTOINCREMENT,value INTEGER UNIQUE);INSERT INTO monthly_deduction_rates VALUES(326419,198);CREATE TABLE meta_business_oauth_states(id INTEGER PRIMARY KEY,consumed INTEGER);INSERT INTO meta_business_oauth_states VALUES(1,1),(2,1);CREATE TABLE media_publication_image_policies(owner_id INTEGER PRIMARY KEY,enabled INTEGER);INSERT INTO media_publication_image_policies VALUES(1,1);PRAGMA user_version=17;PRAGMA application_id=42;")
        con.execute('INSERT INTO alembic_version VALUES(?)',(r.REVISION,))
        for i in range(137):con.execute('CREATE TABLE table_'+str(i)+'(id INTEGER PRIMARY KEY)')
    v.base=base;v.ctx=SimpleNamespace(pf=SimpleNamespace(meta_environment=lambda info:r.need(not any(x.startswith('T24_META_') for x in info['Config']['Env']),'OFFLINE_META_CREDENTIAL_PRESENT')));v.m.BUSINESS=source;v.m.sql_snapshot=db_snapshot;v.rows=lambda path=None:w.snapshot(v.m,path or source);v.metadata=md.db_metadata;v.m.schema_signature=lambda path,head:r.digest(sorted((list(k),val) for k,val in w.objects(path).items()));v.proof={'rows':w.evidence(v.rows()),'schema_sha256':v.m.schema_signature(source,r.REVISION),'database_metadata':v.metadata(source),'crm':runtime(original())};v.helper=SimpleNamespace(docker_timestamp_probe=md.docker_timestamp_probe);v.image=lambda:IMAGE;v.args.manifest_sha256='4'*64;v.args.payload_sha256='5'*64;v.manifest={'backend_after':v.expected};v.offline_name='synthetic-offline';v.m.extract=lambda *_:None
    v.m.inventory=lambda key:v.expected if key==v.offline_name else v.before
    def backup(left,right):
        with sqlite3.connect('file:'+str(left)+'?mode=ro',uri=True) as src,sqlite3.connect(right) as dst:src.backup(dst)
    v.m.backup=backup
    for name in ('release.py','preflight.py','manifest.json','payload.tar.gz'):(v.args.release/name).write_bytes(b'public-synthetic-tool')
    run=v.m.run;changed=[]
    def offline(args,code,*timeout):
        if args[:2]==['docker','run']:
            assert '--network=none' in args and '--read-only' in args and '--env-file' not in args;env=[args[i+1] for i,x in enumerate(args) if x=='-e'];assert not any('SYNTHETIC_META_SECRET' in x or x.startswith('T24_META_') for x in env)
            row=original();row.update(Id='7'*64,Name='/'+v.offline_name);row['Config']['Env']=env;row['HostConfig']['NetworkMode']='none';v.m.items[row['Id']]=row;return b''
        if args[:3]==['docker','exec',v.offline_name]:
            if mutate and not changed:
                changed.append(True)
                with sqlite3.connect(v.args.release/'probe-data/crm_prod.db') as con:
                    if mutate=='counter':con.execute('INSERT OR IGNORE INTO monthly_deduction_rates(value) VALUES(198)')
                    elif mutate=='row':con.execute('DELETE FROM meta_business_oauth_states WHERE id=1')
                    else:con.execute('CREATE TABLE unexpected(id INTEGER)')
            return b'EXACT_PYTHON310 EXACT_META_AND_EXISTING_MEDIA_GOOGLE_ROUTES EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK EXACT_META_ABSENT_DISABLED_NO_NETWORK'
        if args[:2]==['docker','stop'] and args[-1]==v.offline_name:v.m.items['7'*64]['State']['Running']=False;return b''
        return run(args,code,*timeout)
    v.m.run=offline;return source


def test_actual_offline_copy_preserves_all141_two_flows_and_own_metadata(publisher,tmp_path):
    v=publisher;source=isolated(v,tmp_path);before=source.read_bytes();result=v.prepare();assert result['existing_meta_rows_preserved'] and source.read_bytes()==before and len(v.rows())==141 and v.rows()['meta_business_oauth_states']['count']==2
    assert v.rows()==v.rows(v.args.release/'probe-data/crm_prod.db') and v.metadata(source)==v.metadata(v.args.release/'probe-data/crm_prod.db')
    assert not (v.args.release/'original-container.json').exists()


@pytest.mark.parametrize('mutation',['counter','row','schema'])
def test_offline_startup_rejects_even_known_monthly_counter_or_other_mutations(publisher,tmp_path,mutation):
    v=publisher;source=isolated(v,tmp_path,mutate=mutation);before=source.read_bytes()
    with pytest.raises(RuntimeError,match='OFFLINE_STARTUP_CHANGED_DATABASE'):v.prepare()
    assert source.read_bytes()==before and not (v.args.release/'prepared.json').exists()


def test_restart_during_failed_acceptance_can_be_contained_then_original_resumed(publisher):
    v=publisher
    def restart(code,m):
        if code=='PATCH_START_FAILED':m.items[NEW]['RestartCount']=1
    v.m.hook=restart
    with pytest.raises(RuntimeError,match='PATCH_CANDIDATE_RESTARTED'):v.activate()
    assert v.m.inspect('t24-crm')['Id']==OLD and v.m.inspect(OLD)['State']['Running'] and not v.m.inspect(NEW)['State']['Running']


@pytest.mark.parametrize('drift',['original_env','private','original_missing'])
def test_external_recovery_contains_known_running_candidate_before_old_or_private_drift_checks(publisher,drift):
    v=publisher;recover=v.recover_internal
    v.recover_internal=lambda *args:(_ for _ in ()).throw(SystemExit('simulated process interruption'))
    def stop_after_start(code,m):
        if code=='META_AND_GOOGLE_CONFIGURATION_PROBE_FAILED':raise RuntimeError('SYNTHETIC_INTERRUPTION')
    v.m.hook=stop_after_start
    with pytest.raises(SystemExit):v.activate()
    assert v.m.inspect(NEW)['State']['Running']
    v.recover_internal=recover;v.m.hook=None;reviewed=v.reviewed
    def receipt_only(**kwargs):
        assert kwargs=={'recovery':True};return reviewed()
    v.reviewed=receipt_only
    if drift=='original_env':v.m.items[OLD]['Config']['Env'][0]='CHANGED=unsafe'
    elif drift=='private':v.unsafe=True
    else:del v.m.items[OLD]
    with pytest.raises(RuntimeError):v.recover()
    assert not v.m.inspect(NEW)['State']['Running'] and not any(x[:3]==['docker','start',OLD] for x in v.m.calls)
