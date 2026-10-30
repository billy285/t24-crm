"""Synthetic Docker/filesystem-only lifecycle, no real server/provider access."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('refresh_author_release',HERE/'release.py');r=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)
OLD='a'*64;NEW='b'*64;BASE='sha256:'+'d'*64;IMAGE='sha256:'+'e'*64


def original():
    return {'Id':OLD,'Image':BASE,'Name':'/t24-crm','Config':{'Env':['PRESERVED=synthetic','T24_GBP_ENABLED=true'],'Image':'old-tag','Hostname':'old-host','Labels':{'prior':'same'},'Cmd':['serve']},'HostConfig':{'AutoRemove':False,'OomKillDisable':None,'NetworkMode':'host','Privileged':False},'Mounts':[{'Source':'/synthetic/db','Destination':'/app/backend/data','RW':True}],'NetworkSettings':{'Networks':{}},'State':{'Running':True,'Status':'running','StartedAt':'old-start'},'RestartCount':0}


def runtime(info):return {'id':info['Id'],'image':info['Image'],'started':info['State']['StartedAt'],'restart':info['RestartCount'],'config':r.digest({k:info[k] for k in ('Config','HostConfig','Mounts','NetworkSettings')})}


class Docker:
    runtime=staticmethod(runtime)
    def __init__(self,nginx):self.items={OLD:original()};self.NGINX=nginx;self.calls=[];self.sources={OLD:'old'};self.fault=None
    def inspect_optional(self,key):
        row=next((row for row in self.items.values() if key==row['Id'] or row['Name']=='/'+key),None);return copy.deepcopy(row) if row else None
    def inspect(self,key):
        row=self.inspect_optional(key);r.need(row is not None,'SYNTHETIC_CONTAINER_MISSING');return row
    def retained(self):return self
    def expected_labels(self,old):return {**old['Config']['Labels'],'t24.release.scope':r.SCOPE,'t24.release.source':r.SOURCE_SHA}
    def clone_config(self,image,old):
        config=copy.deepcopy(old['Config']);config.update(Image=image,Hostname='',Labels=self.expected_labels(old));config['HostConfig']=copy.deepcopy(old['HostConfig']);config['NetworkingConfig']={'EndpointsConfig':{}};return config
    def docker_request(self,method,path,config):
        assert method=='POST' and path.startswith('/containers/create?name=')
        row=copy.deepcopy(original());row.update(Id=NEW,Image=IMAGE,Name='/'+path.split('=',1)[1]);row['Config']={k:copy.deepcopy(v) for k,v in config.items() if k not in {'HostConfig','NetworkingConfig'}};row['Config']['Hostname']='generated';row['HostConfig']['OomKillDisable']=False;row['State'].update(Running=False,Status='created',StartedAt='0001-01-01T00:00:00Z')
        self.items[NEW]=row;self.sources[NEW]='new';return 201,json.dumps({'Id':NEW}).encode()
    def run(self,args,code,*_):
        self.calls.append(args)
        if self.fault:self.fault(args,code)
        if args[0]=='curl':
            assert args[1]=='-q' and '--noproxy' in args and '--resolve' in args and '?' not in args[-1]
            return json.dumps({'version':r.FRONTEND if b'/public/new' in self.NGINX.read_bytes() else r.BASE_FRONTEND}).encode()
        if args[0]=='nginx':return b'full-config\n'+self.NGINX.read_bytes()
        assert args[0]=='docker';op=args[1]
        if op=='stop':self.items[args[-1]]['State'].update(Running=False,Status='exited')
        elif op=='rename':
            assert self.inspect_optional(args[3]) is None;self.items[args[2]]['Name']='/'+args[3]
        elif op=='start':self.items[args[2]]['State'].update(Running=True,Status='running',StartedAt='new-start')
        elif op=='exec':return b'EXACT_GBP_PRESERVED_SCHEDULER_OFF_NO_NETWORK'
        else:pytest.fail('unexpected Docker op '+op)
        return b''
    def reload_nginx(self):self.calls.append(['reload-nginx']);self.fault and self.fault(['reload-nginx'],'SYNTHETIC_RELOAD')
    def next_nginx(self,body):return body.replace(b'/public/old',b'/public/new')
    def replace_nginx(self,before,after):assert self.NGINX.read_bytes()==before;self.NGINX.write_bytes(after)
    def validation_window(self,key):assert self.inspect(key)['State']['Running']
    def ready(self,key):r.need(self.inspect(key)['State']['Running'],'SYNTHETIC_NOT_READY')
    def verify_secret_mount(self,info):r.need(info['Mounts']==original()['Mounts'],'SYNTHETIC_SECRET_MOUNT_DRIFT')
    def verify_production_worker_enabled(self,_):pass
    def verify_public(self,*_):return 'static-hash'
    def write(self,path,value):
        with path.open('xb') as f:f.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode() if not isinstance(value,bytes) else value)
        return r.H(path.read_bytes())
    def read(self,path,sha=None):
        body=path.read_bytes();r.need(sha is None or r.H(body)==sha,'SYNTHETIC_FILE_HASH_DRIFT');return body


@pytest.fixture
def publisher_fixture(tmp_path):
    path=tmp_path/'release';path.mkdir();nginx=tmp_path/'nginx';nginx.write_bytes(b'root /public/old; # callback no-referrer protected')
    w=object.__new__(r.Release);w.args=SimpleNamespace(release=path,review_sha256='f'*64);w.m=Docker(nginx);w.public=Path('/public/new');w.old_name='old-reserved';w.candidate_name='new-reserved';w.manifest={}
    w.proof={'crm':runtime(original()),'rows':{'financial_canary':{'count':1,'hash':'preserved'}},'nginx_sha256':r.H(nginx.read_bytes()),'public_root':'/public/old','active_nginx_config_sha256':r.H(b'full-config\n'+nginx.read_bytes()),'schema_sha256':'same-schema'}
    w.args.preflight_sha256='c'*64
    w.metadata='preserved';w.current_rows=copy.deepcopy(w.proof['rows']);w.before={'routers':'old'};w.expected={'routers':'new'}
    w.receipt={'candidate_image':IMAGE,'nginx_next_sha256':r.H(w.m.next_nginx(nginx.read_bytes())),'public_inventory_sha256':'static-hash','candidate_inventory_sha256':'b'*64}
    w.reviewed=lambda:(copy.deepcopy(w.receipt),original(),copy.deepcopy(w.before),copy.deepcopy(w.expected))
    w.current=lambda **_:(original(),copy.deepcopy(w.before));w.rows=lambda:copy.deepcopy(w.current_rows)
    def protections(*,updated=False,recovery=False):
        r.need(w.metadata=='preserved','SYNTHETIC_PROTECTION_DRIFT');body=w.m.NGINX.read_bytes()
        if updated:body=body.replace(b'/public/new',b'/public/old')
        r.need(r.H(body)==w.proof['nginx_sha256'],'CALLBACK_OR_NONROOT_NGINX_CONFIGURATION_DRIFT')
    w.protections=protections;w.nginx=lambda updated=False:protections(updated=updated)
    def source(info,expected):r.need(w.m.sources[info['Id']]==('old' if expected==w.before else 'new'),'SYNTHETIC_SOURCE_DRIFT')
    w.source_boundary=source
    w.base=SimpleNamespace(verify_gbp_environment_enabled=lambda info:r.need('T24_GBP_ENABLED=true' in info['Config']['Env'],'SYNTHETIC_GBP_DRIFT'),active_configuration_probe=lambda:'no-provider-network')
    return w


def test_no_migration_full_activate_and_receipt(publisher_fixture):
    w=publisher_fixture;rows=copy.deepcopy(w.current_rows);result=w.activate()
    assert result['stage']=='MEDIA_OPS_REVIEW_REFRESH_DEPLOYED_VERIFIED' and result['database_migrated'] is False
    assert w.m.inspect('t24-crm')['Id']==NEW and w.m.inspect(OLD)['State']['Running'] is False
    assert w.current_rows==rows and b'/public/new' in w.m.NGINX.read_bytes()
    assert len(w.m.items)==2 and not any('alembic' in str(c) or c[:2]==['docker','rm'] for c in w.m.calls)


@pytest.mark.parametrize('operation',['stop','rename','start','reload-nginx'])
def test_switch_failure_restores_original_no_db_restore(publisher_fixture,operation):
    w=publisher_fixture;fired=[False]
    def fail(args,_):
        match=args[0]=='reload-nginx' if operation=='reload-nginx' else len(args)>1 and args[1]==operation
        if match and not fired[0]:fired[0]=True;raise RuntimeError('SYNTHETIC_SWITCH_FAILURE')
    w.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_SWITCH_FAILURE'):w.activate()
    assert w.m.inspect('t24-crm')['Id']==OLD and w.m.inspect(OLD)['State']['Running']
    assert w.m.inspect(NEW)['State']['Running'] is False and b'/public/old' in w.m.NGINX.read_bytes()


def test_deployed_receipt_disk_failure_does_not_skip_recovery(publisher_fixture):
    w=publisher_fixture;write=w.m.write
    def fail(path,value):
        if path.name=='deployed.json':raise OSError('synthetic full disk')
        return write(path,value)
    w.m.write=fail
    with pytest.raises(OSError):w.activate()
    assert w.m.inspect('t24-crm')['Id']==OLD and w.m.inspect(NEW)['State']['Running'] is False


def test_durable_candidate_before_first_stop(publisher_fixture):
    w=publisher_fixture
    def check(args,_):
        if len(args)>1 and args[1]=='stop':
            state=json.loads((w.args.release/'candidate-created.json').read_bytes());assert state['candidate_id']==NEW
    w.m.fault=check;w.activate()


def test_unknown_primary_is_not_touched_during_recovery(publisher_fixture):
    w=publisher_fixture;w.activate();(w.args.release/'deployed.json').unlink()
    w.m.items[NEW]['Name']='/'+w.candidate_name;other=copy.deepcopy(w.m.items[NEW]);other.update(Id='9'*64,Name='/t24-crm');w.m.items[other['Id']]=other
    with pytest.raises(RuntimeError,match='UNKNOWN_PRIMARY_CONTAINER'):w.recover()
    assert w.m.inspect(other['Id'])['State']['Running'] and not w.m.inspect(NEW)['State']['Running']


def test_no_recorded_identity_failure_keeps_original_and_never_guesses_container(publisher_fixture):
    w=publisher_fixture;write=w.m.write
    def fail(path,value):
        if path.name=='candidate-created.json':raise OSError('synthetic identity write failed')
        return write(path,value)
    w.m.write=fail
    with pytest.raises(OSError):w.activate()
    assert w.m.inspect('t24-crm')['Id']==OLD and not w.m.inspect(NEW)['State']['Running']
    w.m.write=write;result=w.recover();assert result['manual_orphan_review_required'] and result['candidate_not_touched']
    assert not any(c[:2] in (['docker','start'],['docker','stop'],['docker','rename']) for c in w.m.calls)


def test_recover_preserves_new_independent_rows(publisher_fixture):
    w=publisher_fixture;w.activate();(w.args.release/'deployed.json').unlink();w.current_rows['financial_canary']['count']=9
    after=copy.deepcopy(w.current_rows);w.recover();assert w.current_rows==after


def test_late_metadata_drift_contains_candidate_before_refusing_old_restart(publisher_fixture):
    w=publisher_fixture;w.activate();(w.args.release/'deployed.json').unlink();w.metadata='changed'
    with pytest.raises(RuntimeError,match='SYNTHETIC_PROTECTION_DRIFT'):w.recover()
    assert not w.m.inspect(NEW)['State']['Running'] and not w.m.inspect(OLD)['State']['Running']


@pytest.mark.parametrize('field',['environment','mount','privileged','network','oom_true','oom_zero'])
def test_exact_config_rejects_unrelated_changes(field):
    m=SimpleNamespace(runtime=runtime,expected_labels=lambda old:old['Config']['Labels']);old=original();candidate=copy.deepcopy(old)
    if field=='environment':candidate['Config']['Env'].append('OTHER=changed')
    if field=='mount':candidate['Mounts'][0]['RW']=False
    if field=='privileged':candidate['HostConfig']['Privileged']=True
    if field=='network':candidate['NetworkSettings']['Networks']['other']={}
    if field=='oom_true':candidate['HostConfig']['OomKillDisable']=True
    if field=='oom_zero':candidate['HostConfig']['OomKillDisable']=0
    with pytest.raises(RuntimeError):r.compare(candidate,old,m)


def test_only_oom_none_false_default_equivalence_and_objects_unchanged():
    m=SimpleNamespace(runtime=runtime,expected_labels=lambda old:old['Config']['Labels']);old=original();candidate=copy.deepcopy(old);candidate['HostConfig']['OomKillDisable']=False
    before=copy.deepcopy((candidate,old));r.compare(candidate,old,m);assert (candidate,old)==before


def offline_prepare_fixture(w,tmp_path,*,startup_ignored_insert=False):
    """Exercise actual prepare() copy/own-metadata flow on real SQLite."""
    import sqlite3
    spec=importlib.util.spec_from_file_location('refresh_offline_metadata',HERE/'preflight.py');pf=importlib.util.module_from_spec(spec);spec.loader.exec_module(pf)
    source=tmp_path/'production-synthetic.db'
    with sqlite3.connect(source) as db:
        db.executescript("CREATE TABLE canary(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT UNIQUE);INSERT INTO canary(value) VALUES('same');")
    baseline=pf.db_metadata(source)
    with sqlite3.connect(source) as db:db.execute("INSERT OR IGNORE INTO canary(value) VALUES('same')")
    assert pf.db_metadata(source)['sequence_values']['canary']>baseline['sequence_values']['canary']
    w.args.manifest_sha256='4'*64;w.args.payload_sha256='5'*64
    w.m.BUSINESS=source
    def snapshot(path):
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:rows=db.execute('SELECT id,value FROM canary ORDER BY id').fetchall()
        return {'canary':{'count':len(rows),'rows_sha256':r.digest(rows),'columns':['id','value'],'schema':{'id':'INTEGER','value':'TEXT'},'indexes':[]}}
    w.m.sql_snapshot=snapshot;w.pf=pf;w.proof['rows']=pf.row_evidence(w.m);w.proof['database_metadata']=baseline
    w.m.schema_signature=lambda path,revision:'same-schema';w.manifest={'backend_after':w.expected};w.offline_name='synthetic-offline'
    for name in ('release.py','preflight.py','manifest.json','payload.tar.gz'):(w.args.release/name).write_bytes(b'synthetic-public')
    def backup(src,dest):
        with sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True) as left,sqlite3.connect(dest) as right:left.backup(right)
    w.m.backup=backup;w.m.extract=lambda *_:None;w.image=lambda:IMAGE
    w.m.inventory=lambda key:copy.deepcopy(w.before if key==OLD else w.expected)
    w.base.Release=SimpleNamespace(offline_args=lambda *args:['docker','run','--network=none'])
    w.base.verify_disabled_environment=lambda _:None;w.base.gbp_disabled_probe=lambda:'no-provider-network'
    w.route_probe=lambda:'route_probe';w.m.stage_public=lambda *args:(w.public,'static-hash')
    run=w.m.run;injected=[False]
    def offline_run(args,code,*timeouts):
        if args[:2]==['docker','run']:
            row=copy.deepcopy(original());row.update(Id='7'*64,Name='/'+w.offline_name);w.m.items[row['Id']]=row;return b''
        if args[:2]==['docker','exec'] and args[2]==w.offline_name:
            if startup_ignored_insert and not injected[0]:
                injected[0]=True
                with sqlite3.connect(w.args.release/'probe-data/crm_prod.db') as db:db.execute("INSERT OR IGNORE INTO canary(value) VALUES('same')")
            return b'EXACT_PYTHON310 EXACT_AUTHORITATIVE_REVIEW_ROUTE_REGISTERED EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'
        if args[:2]==['docker','stop'] and args[-1]==w.offline_name:w.m.items['7'*64]['State']['Running']=False;return b''
        return run(args,code,*timeouts)
    w.m.run=offline_run
    return source,pf


def test_actual_prepare_accepts_copy_counter_forward_but_freezes_its_own_startup_metadata(publisher_fixture,tmp_path):
    w=publisher_fixture;source,pf=offline_prepare_fixture(w,tmp_path);before=source.read_bytes()
    result=w.prepare()
    assert result['stage']=='MEDIA_OPS_REVIEW_REFRESH_PREPARED_OFFLINE_VERIFIED' and source.read_bytes()==before
    assert pf.db_metadata(source)==pf.db_metadata(w.args.release/'probe-data/crm_prod.db')
    assert pf.db_metadata(source)['sequence_values']['canary']>w.proof['database_metadata']['sequence_values']['canary']


def test_actual_prepare_rejects_even_ignored_insert_during_offline_startup(publisher_fixture,tmp_path):
    w=publisher_fixture;source,pf=offline_prepare_fixture(w,tmp_path,startup_ignored_insert=True);before=source.read_bytes()
    with pytest.raises(RuntimeError,match='OFFLINE_STARTUP_CHANGED_DATABASE'):w.prepare()
    assert source.read_bytes()==before and not (w.args.release/'prepared.json').exists()
    assert pf.row_evidence(w.m)==w.proof['rows']
