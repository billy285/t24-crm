"""Local synthetic lifecycle tests; no real Docker/server/provider access."""
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('scheduler_author_core',HERE/'core.py')
c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)
OLD='a'*64;NEW='b'*64;ATTEMPT='11111111-1111-4111-8111-111111111111'


def original():
    return {'Id':OLD,'Name':'/t24-crm','Image':'sha256:'+'d'*64,'Config':{'Image':'base-tag','Hostname':'old','Env':['KEEP=value','T24_GBP_ENABLED=true','T24_GBP_SCHEDULER_ENABLED=false'],'Cmd':['serve']},'HostConfig':{'NetworkMode':'host','AutoRemove':False,'OomKillDisable':None,'Privileged':False},'Mounts':[{'Type':'bind','Source':'/synthetic/db','Destination':'/app/backend/data','RW':True}],'NetworkSettings':{'Networks':{}},'State':{'Running':True,'Status':'running','StartedAt':'2026-10-31T02:00:00Z'},'RestartCount':0}


def runtime(info):
    return {'id':info['Id'],'image':info['Image'],'started':info['State']['StartedAt'],'restart':info['RestartCount'],'config':c.digest({k:info[k] for k in ('Config','HostConfig','Mounts','NetworkSettings')})}


class Docker:
    runtime=staticmethod(runtime)
    def __init__(self):
        self.items={OLD:original()};self.commands=[];self.sources={OLD:'exact'};self.source_reads=[];self.fault=None;self.created=0
    def inspect_optional(self,key):
        row=next((row for row in self.items.values() if row['Id']==key or row['Name']=='/'+key),None)
        return copy.deepcopy(row) if row else None
    def inspect(self,key):
        row=self.inspect_optional(key);c.need(row is not None,'SYNTHETIC_CONTAINER_MISSING');return row
    def retained(self):return self
    def clone_networks(self,_):return {}
    def docker_request(self,method,path,config):
        assert method=='POST' and path.startswith('/containers/create?name=')
        self.created+=1;assert NEW not in self.items
        row=copy.deepcopy(self.items[OLD]);row.update(Id=NEW,Name='/'+path.split('=',1)[1])
        row['Config']={k:copy.deepcopy(v) for k,v in config.items() if k not in {'HostConfig','NetworkingConfig'}}
        row['Config']['Hostname']='generated';row['HostConfig']=copy.deepcopy(config['HostConfig']);row['HostConfig']['OomKillDisable']=False
        row['State']={'Running':False,'Status':'created','StartedAt':'0001-01-01T00:00:00Z'}
        self.items[NEW]=row;self.sources[NEW]='exact';return 201,json.dumps({'Id':NEW}).encode()
    def run(self,args,code,*timeout):
        self.commands.append(args)
        if self.fault:self.fault(args,code)
        op=args[1]
        if op=='stop':self.items[args[-1]]['State'].update(Running=False,Status='exited')
        elif op=='rename':
            assert not self.inspect_optional(args[3]);self.items[args[2]]['Name']='/'+args[3]
        elif op=='start':self.items[args[2]]['State'].update(Running=True,Status='running',StartedAt='2026-10-31T02:00:05Z')
        elif op=='exec':
            assert args[3:7]==['python','-I','-S','-B'];assert 'socket.socket.connect=blocked' in args[-1]
            return b'SCHEDULER_CONFIG_NO_NETWORK_VERIFIED\n'
        else:pytest.fail('Unexpected command: '+repr(args[:2]))
        return b''
    def ready(self,key):c.need(self.inspect(key)['State']['Running'],'SYNTHETIC_NOT_READY')
    def verify_secret_mount(self,info):assert info['Mounts']==original()['Mounts']
    def verify_production_worker_enabled(self,info):assert c.env(info)['KEEP']=='value'


@pytest.fixture
def workflow(tmp_path,monkeypatch):
    root=tmp_path/'root';root.mkdir(mode=0o700)
    monkeypatch.setattr(c,'ROOT',root);monkeypatch.setattr(c,'FILE_OWNER',os.getuid())
    # pytest's temporary ancestors are not server root-owned dirs; this one seam
    # is only used here. Separate tests exercise real nofollow/mode primitives.
    monkeypatch.setattr(c,'directory',lambda path:None)
    clock=[datetime(2026,10,31,3,0,tzinfo=timezone.utc)];monkeypatch.setattr(c,'now',lambda:clock[0])
    w=object.__new__(c.Workflow);w.attempt=ATTEMPT;w.path=root/ATTEMPT;w.owner=1;w.receipt_sha='e'*64
    w.original_name='t24-crm-scheduler-off-'+ATTEMPT[:8];w.candidate_name='t24-crm-scheduler-on-'+ATTEMPT[:8];w.m=Docker()
    w.receipt={'crm':runtime(original())};w.p=SimpleNamespace(verify_gbp_environment_enabled=lambda info:c.need(c.env(info)['T24_GBP_ENABLED']=='true','GBP_REQUIRED'))
    w.facts={'database_identity':[1,2],'metadata':{'google':'metadata-only','stripe':'metadata-only','private':'metadata-only'},'nginx':{'site':'same','active':'same'},'oauth':{'queue_empty':True,'active_owner_verified':True,'active_owner_google_connections':1}}
    w.snapshot={'financial_canary':{'count':1,'hash':'unchanged'},'google_business_schedules':{'count':0,'hash':'empty'}}
    w.boundary=lambda **kw:copy.deepcopy(w.facts if kw.get('queue',True) else {k:v for k,v in w.facts.items() if k!='oauth'})
    w.rows=lambda:copy.deepcopy(w.snapshot)
    def source(info):
        w.m.source_reads.append((info['Id'],info['State']['Running']));c.need(w.m.sources[info['Id']]=='exact','SYNTHETIC_SOURCE_DRIFT')
    w.source=source;w.clock=clock
    return w


def planned(w):return w.plan()['plan_sha256']


def test_plan_activate_and_no_delete_rollback_complete_workflow(workflow):
    w=workflow;plan=planned(w);before=copy.deepcopy(w.snapshot);result=w.activate(plan,True)
    assert result['stage']=='SCHEDULER_CONFIG_ENABLED_VERIFIED'
    assert w.m.inspect('t24-crm')['Id']==NEW and w.m.inspect(OLD)['State']['Running'] is False
    assert c.env(w.m.inspect(NEW))['T24_GBP_SCHEDULER_ACTIVATION_FROM']=='2026-10-31T03:02:00Z'
    assert result['all_business_rows_unchanged'] and result['nginx_changed'] is False and w.snapshot==before
    rolled=w.rollback(plan);assert rolled['stage']=='SCHEDULER_CONFIG_ROLLED_BACK_DISABLED'
    assert w.m.inspect('t24-crm')['Id']==OLD and w.m.inspect(NEW)['State']['Running'] is False
    assert len(w.m.items)==2 and not any(x[:2] in (['docker','rm'],['docker','run']) for x in w.m.commands)
    assert w.rollback(plan)==rolled


def test_plan_is_read_only_and_records_only_hashes(workflow):
    w=workflow;result=w.plan();raw=(w.path/'plan.json').read_bytes()
    assert w.m.created==0 and all(cmd[1]=='exec' for cmd in w.m.commands)
    assert result['queue_empty'] is True and b'KEEP=value' not in raw and b'T24_GBP_ENABLED=true' not in raw
    assert (w.path/'plan.json').stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('what',['rows','metadata','source','runtime'])
def test_stale_plan_fails_before_creating_candidate(workflow,what):
    w=workflow;plan=planned(w)
    if what=='rows':w.snapshot['financial_canary']['count']=2
    if what=='metadata':w.facts['metadata']['google']='changed'
    if what=='source':w.m.sources[OLD]='changed'
    if what=='runtime':w.m.items[OLD]['HostConfig']['Privileged']=True
    with pytest.raises(c.GuardError):w.activate(plan,True)
    assert w.m.created==0 and w.m.inspect(OLD)['State']['Running']


@pytest.mark.parametrize('operation',['stop','rename','start'])
def test_each_switch_command_failure_restores_off_retains_candidate(workflow,operation):
    w=workflow;plan=planned(w);fired=[False]
    def fail(args,_):
        if not fired[0] and args[1]==operation:
            fired[0]=True;raise c.GuardError('SYNTHETIC_SWITCH_FAILURE')
    w.m.fault=fail
    with pytest.raises(c.GuardError,match='SYNTHETIC_SWITCH_FAILURE'):w.activate(plan,True)
    assert w.m.inspect('t24-crm')['Id']==OLD and w.m.inspect(OLD)['State']['Running']
    assert not w.m.inspect(NEW)['State']['Running'] and len(w.m.items)==2


def test_receipt_write_failure_always_attempts_disable_recovery(workflow,monkeypatch):
    w=workflow;plan=planned(w);write=c.write
    def fail(path,value):
        if path.name=='enabled.json':raise OSError('synthetic disk full')
        return write(path,value)
    monkeypatch.setattr(c,'write',fail)
    with pytest.raises(OSError):w.activate(plan,True)
    assert w.m.inspect('t24-crm')['Id']==OLD and not w.m.inspect(NEW)['State']['Running']


def test_containment_record_write_failure_does_not_prevent_off_recovery(workflow,monkeypatch):
    w=workflow;plan=planned(w);w.activate(plan,True);write=c.write
    def fail(path,value):
        if path.name=='contained.json':raise OSError('synthetic disk full')
        return write(path,value)
    monkeypatch.setattr(c,'write',fail)
    w.rollback(plan);assert w.m.inspect('t24-crm')['Id']==OLD


def test_rollback_preserves_new_independent_rows_including_new_schedules(workflow):
    w=workflow;plan=planned(w);w.activate(plan,True)
    w.snapshot['financial_canary']['count']=2;w.snapshot['google_business_schedules']['count']=1
    rows=copy.deepcopy(w.snapshot);w.rollback(plan);assert w.snapshot==rows


def test_late_protected_metadata_drift_stops_executor_but_does_not_restart_unsafe_original(workflow):
    w=workflow;plan=planned(w);w.activate(plan,True);w.facts['metadata']['google']='drift'
    with pytest.raises(c.GuardError,match='ROLLBACK_PROTECTION_DRIFT'):w.rollback(plan)
    assert not w.m.inspect(NEW)['State']['Running'] and not w.m.inspect(OLD)['State']['Running']


def test_prestart_late_queue_or_source_drift_never_starts_candidate(workflow):
    w=workflow;plan=planned(w)
    def drift(args,_):
        if args[1]=='stop':w.m.sources[NEW]='changed'
    w.m.fault=drift
    with pytest.raises(c.GuardError,match='SYNTHETIC_SOURCE_DRIFT'):w.activate(plan,True)
    assert not any(cmd[:3]==['docker','start',NEW] for cmd in w.m.commands)
    assert w.m.inspect(OLD)['State']['Running']


def test_candidate_create_identity_write_failure_leaves_original_running_without_start(workflow,monkeypatch):
    w=workflow;plan=planned(w);write=c.write
    def fail(path,value):
        if path.name=='candidate-created.json':raise OSError('synthetic disk full')
        return write(path,value)
    monkeypatch.setattr(c,'write',fail)
    with pytest.raises(OSError):w.activate(plan,True)
    assert w.m.inspect('t24-crm')['Id']==OLD and w.m.inspect(OLD)['State']['Running']
    assert not w.m.inspect(NEW)['State']['Running'] and not any(cmd[1] in {'stop','start','rename'} for cmd in w.m.commands)


def test_unknown_primary_is_never_stopped_by_rollback(workflow):
    w=workflow;plan=planned(w);w.activate(plan,True)
    w.m.items[NEW]['Name']='/'+w.candidate_name
    extra=copy.deepcopy(w.m.items[NEW]);extra['Id']='f'*64;extra['Name']='/t24-crm';w.m.items[extra['Id']]=extra
    before=len(w.m.commands)
    with pytest.raises(c.GuardError,match='UNKNOWN_PRIMARY_CONTAINER'):w.rollback(plan)
    assert extra['Id'] not in json.dumps(w.m.commands[before:])
    assert w.m.inspect(extra['Id'])['State']['Running']


def test_config_probe_blocks_network_before_loading_app_and_disables_site_hooks(workflow):
    w=workflow;plan=planned(w);w.activate(plan,True)
    probes=[cmd for cmd in w.m.commands if cmd[1]=='exec']
    assert probes and all(cmd[3:7]==['python','-I','-S','-B'] for cmd in probes)
    for cmd in probes:
        code=cmd[-1];assert code.index('socket.socket.connect=blocked')<code.index('from services.')
        assert "sysconfig.get_path(k) for k in ('purelib','platlib')" in code
