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
