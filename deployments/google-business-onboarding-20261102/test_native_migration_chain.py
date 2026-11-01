"""Run the actual frozen create/settle/start/wait chain with synthetic Docker."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace,MethodType
import pytest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=load(HERE/'release.py','onboarding_r3_migration_release')
base=load(ROOT/'deployments/media-ops-management-20261031/release.py','onboarding_native_migration_chain_base')

class Docker:
    def __init__(self,data,release):
        self.BUSINESS=data.parent/'production'/'crm_prod.db';self.infos={};self.calls=[];self.data=data;self.release=release;self.exit_code=0
    def inspect_optional(self,name):return next((copy.deepcopy(x) for x in self.infos.values() if x['Name']=='/'+name),None)
    def inspect(self,identity):return copy.deepcopy(self.infos[identity])
    def read(self,path):return path.read_bytes()
    def write(self,path,value):path.write_text(json.dumps(value))
    def run(self,args,*a):
        self.calls.append(args[:])
        if args[:2]==['docker','create']:
            identity='1'*64;name=args[args.index('--name')+1]
            self.infos[identity]={'Id':identity,'Name':'/'+name,'Image':'sha256:'+'2'*64,'Config':{'Env':['T24_GBP_ENABLED=false','T24_GBP_API_APPROVED=false','T24_GBP_SCHEDULER_ENABLED=false','T24_GBP_ONBOARDING_WORKER_ENABLED=false','STRIPE_AUTO_POSTING_ENABLED=false','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false'],'Cmd':['python','-B','-c','SYNTHETIC_PINNED_MIGRATION']},'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True},'Mounts':[{'Type':'bind','Source':str(self.data),'Destination':'/app/backend/data','RW':True},{'Type':'bind','Source':str(self.release/'probe-logs'),'Destination':'/app/backend/logs','RW':True}],'State':{'Status':'created','Running':False,'ExitCode':0}}
            return identity.encode()
        identity=args[-1]
        if args[1]=='start':self.infos[identity]['State'].update(Status='running',Running=True)
        elif args[1]=='wait':self.infos[identity]['State'].update(Status='exited',Running=False,ExitCode=self.exit_code)
        else:raise AssertionError(args)
        return b'0\n'

@pytest.fixture
def subject(tmp_path,monkeypatch):
    data=tmp_path/'data';data.mkdir();(data/'crm_prod.db').write_bytes(b'SYNTHETIC_NOT_SQLITE')
    release=tmp_path/'fresh-r3';release.mkdir();(release/'probe-logs').mkdir()
    monkeypatch.setattr(base,'migration_script',lambda:'SYNTHETIC_PINNED_MIGRATION')
    original=base.verify_disabled_environment
    value=SimpleNamespace(args=SimpleNamespace(release=release),source=r.SOURCE_SHA,m=Docker(data,release),base=base,_original_offline_validator=original)
    value.verify_offline_environment=MethodType(r.Methods.verify_offline_environment,value)
    value._native_migration_run,value._native_migration_settle=r.scoped_migration_methods(base,value.verify_offline_environment)
    value.run_migration=MethodType(r.Methods.run_migration,value);value.settle_migration=MethodType(r.Methods.settle_migration,value)
    value.migration_identity=MethodType(base.Release.migration_identity,value)
    value.offline_args=lambda data,image:['docker','run','--rm','--network=none',image]
    yield value,data
    assert base.verify_disabled_environment is original


@pytest.mark.parametrize('phase',['offline','production'])
def test_full_create_settle_start_wait_settle_and_known_success_no_replay(subject,phase):
    value,data=subject
    if phase=='production':value.m.BUSINESS=data/'crm_prod.db'
    image='sha256:'+'2'*64
    if phase=='production':base.Release.migrate(value,image)
    else:value.run_migration(data,image)
    assert [x[1] for x in value.m.calls]==['create','start','wait']
    saved=json.loads((value.args.release/('migration-'+phase+'-container.json')).read_text())
    assert saved['name']=='t24-'+r.SCOPE+'-migration-'+r.SOURCE_SHA[:12]+'-'+phase
    assert saved['source_sha']==r.SOURCE_SHA and saved['phase']==phase
    assert value.settle_migration(data,required=True)['State']['ExitCode']==0
    calls=copy.deepcopy(value.m.calls);value.run_migration(data,image);assert value.m.calls==calls
    # An occupied name from attempt1 is preserved and never selected or removed.
    assert saved['name']!='t24-management-migration-'+r.SOURCE_SHA[:12]+'-offline'

@pytest.mark.parametrize('attack',['inode','source','name','image','cmd','rootfs','mount','secret','flag_true','flag_duplicate','network'])
def test_native_settlement_guards_reject_identity_or_isolation_drift(subject,attack):
    value,data=subject;value.run_migration(data,'sha256:'+'2'*64)
    path=value.args.release/'migration-offline-container.json';saved=json.loads(path.read_text());row=value.m.infos[saved['id']]
    if attack=='inode':saved['database_identity'][1]+=1
    elif attack=='source':saved['source_sha']='f'*40
    elif attack=='name':row['Name']='/unknown'
    elif attack=='image':row['Image']='sha256:'+'3'*64
    elif attack=='cmd':row['Config']['Cmd']=['python','-c','UNREVIEWED']
    elif attack=='rootfs':row['HostConfig']['ReadonlyRootfs']=False
    elif attack=='mount':row['Mounts'][0]['RW']=False
    elif attack=='secret':row['Config']['Env'].append('T24_GBP_CLIENT_SECRET=SYNTHETIC_BAD')
    elif attack=='flag_true':row['Config']['Env']=[x.replace('ONBOARDING_WORKER_ENABLED=false','ONBOARDING_WORKER_ENABLED=true') for x in row['Config']['Env']]
    elif attack=='flag_duplicate':row['Config']['Env'].append('T24_GBP_ONBOARDING_WORKER_ENABLED=false')
    else:row['HostConfig']['NetworkMode']='bridge'
    path.write_text(json.dumps(saved));calls=copy.deepcopy(value.m.calls)
    with pytest.raises(RuntimeError):value.settle_migration(data,required=True)
    assert value.m.calls==calls


def test_unsuccessful_process_requires_explicit_same_known_retry(subject):
    value,data=subject;image='sha256:'+'2'*64;value.m.exit_code=1
    with pytest.raises(RuntimeError,match='MIGRATION_PROCESS_FAILED'):value.run_migration(data,image)
    calls=copy.deepcopy(value.m.calls)
    with pytest.raises(RuntimeError,match='MIGRATION_RESULT_REQUIRES_REVIEW'):value.run_migration(data,image)
    assert value.m.calls==calls
    value.m.exit_code=0;value.run_migration(data,image,retry=True)
    assert [x[1] for x in value.m.calls].count('create')==1
    assert [x[1] for x in value.m.calls][-2:]==['start','wait']


def test_only_run_name_constant_changes_and_frozen_globals_never_mutated(subject):
    value,data=subject;original=base.Release.run_migration;run=value._native_migration_run;settle=value._native_migration_settle
    assert run.__code__.co_code==original.__code__.co_code
    assert run.__code__.co_consts==tuple('t24-'+r.SCOPE+'-migration-' if x=='t24-management-migration-' else x for x in original.__code__.co_consts)
    assert settle.__code__ is base.Release.settle_migration.__code__
    assert run.__globals__ is settle.__globals__ and run.__globals__ is not original.__globals__
    assert run.__globals__['verify_disabled_environment']==value.verify_offline_environment
    assert original.__globals__['verify_disabled_environment'] is value._original_offline_validator
    assert run.__kwdefaults__==original.__kwdefaults__ and settle.__kwdefaults__==base.Release.settle_migration.__kwdefaults__


def test_unknown_occupied_new_namespace_is_never_reused_or_removed(subject):
    value,data=subject
    name='t24-'+r.SCOPE+'-migration-'+r.SOURCE_SHA[:12]+'-offline'
    value.m.infos['9'*64]={'Name':'/'+name}
    with pytest.raises(RuntimeError,match='UNKNOWN_MIGRATION_NAME_OCCUPIED'):value.run_migration(data,'sha256:'+'2'*64)
    assert value.m.calls==[] and len(value.m.infos)==1


def test_known_running_migration_is_waited_to_exit_before_settlement(subject):
    value,data=subject;value.run_migration(data,'sha256:'+'2'*64)
    value.m.infos['1'*64]['State'].update(Status='running',Running=True)
    result=value.settle_migration(data,required=True)
    assert result['State']['Status']=='exited' and value.m.calls[-1]==['docker','wait','1'*64]


def test_known_image_mismatch_does_not_restart_or_reuse_migration(subject):
    value,data=subject;value.run_migration(data,'sha256:'+'2'*64);calls=copy.deepcopy(value.m.calls)
    with pytest.raises(RuntimeError,match='REVIEWED_MIGRATION_IMAGE_REQUIRED'):value.run_migration(data,'sha256:'+'3'*64,retry=True)
    assert value.m.calls==calls


def test_directory_fsync_barrier_precedes_start_and_writer_is_restored(subject,monkeypatch):
    value,data=subject;events=[];original=value.m.run;writer=value.m.write
    def run(args,*a):events.append(args[1]);return original(args,*a)
    value.m.run=run
    monkeypatch.setattr(r.os,'fsync',lambda fd:events.append('directory-fsync'))
    value.run_migration(data,'sha256:'+'2'*64)
    assert events==['create','directory-fsync','start','wait'] and value.m.write==writer


def test_actual_forward_recovery_entry_dispatches_through_scoped_settlement(subject):
    value,data=subject;value.m.BUSINESS=data/'crm_prod.db';value.run_migration(data,'sha256:'+'2'*64)
    meta=load(ROOT/'deployments/meta-business-20261031/release.py','onboarding_recovery_dispatch_probe')
    candidate='4'*64;value.candidate_name='synthetic-candidate';value.m.infos[candidate]={'Id':candidate,'Name':'/synthetic-candidate','Image':'sha256:'+'2'*64,'State':{'Running':False}}
    value.state=lambda receipt,old:{'candidate_id':candidate}
    original=value._native_migration_settle;calls=[]
    class ReachedScopedSettlement(Exception):pass
    def scoped(self,data,*,required=False):
        known=original(self,data,required=required);assert known['Name'].startswith('/t24-'+r.SCOPE+'-migration-')
        calls.append(known['Id']);raise ReachedScopedSettlement
    value._native_migration_settle=scoped
    with pytest.raises(ReachedScopedSettlement):meta.Release.recover_internal(value,{'candidate_image':'sha256:'+'2'*64},{},{},{})
    assert calls==['1'*64]


def test_existing_durable_directory_barrier_wrapper_is_ast_identical_except_native_delegate():
    import ast
    source=ast.parse((HERE/'release.py').read_text());prior=ast.parse((ROOT/'deployments/meta-business-20261031/release.py').read_text())
    method=lambda tree,cls:next(x for node in tree.body if isinstance(node,ast.ClassDef) and node.name==cls for x in node.body if isinstance(x,ast.FunctionDef) and x.name=='run_migration')
    current=method(source,'Methods');old=method(prior,'Release')
    call=next(x for x in ast.walk(current) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='_native_migration_run')
    old_call=next(x for x in ast.walk(old) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='run_migration')
    call.func=old_call.func
    assert ast.dump(current,include_attributes=False)==ast.dump(old,include_attributes=False)


def test_r3_source_reverses_to_exact_preserved_r2_only_through_reviewed_changes():
    import hashlib
    prior=(HERE/'attempt2-release.py').read_bytes();assert hashlib.sha256(prior).hexdigest()=='e926a51afafa913e9aec7bcc48cf099cb123fa49ca43346a647dcc3fc2ec8c43'
    value=(HERE/'release.py').read_text()
    start=value.index('def scoped_migration_methods(base,validator):\n');end=value.index('class Methods:\n',start)
    value=value[:start]+value[end:]
    extra='        self._original_offline_validator=self.base.verify_disabled_environment\n        self._native_migration_run,self._native_migration_settle=scoped_migration_methods(self.base,self.verify_offline_environment)\n'
    assert value.count(extra)==1;value=value.replace(extra,'',1)
    start=value.index('    def run_migration(self,data,image,*,retry=False):\n');end=value.index('    def verify_offline_environment(self,info):\n',start)
    value=value[:start]+value[end:]
    assert value.count('        self._original_offline_validator(projected)\n')==1
    value=value.replace('        self._original_offline_validator(projected)\n','        self.base.verify_disabled_environment(projected)\n',1)
    value=value.replace("SCOPE = 'google-business-onboarding-r3'","SCOPE = 'google-business-onboarding-r2'",1)
    assert value.encode()==prior
