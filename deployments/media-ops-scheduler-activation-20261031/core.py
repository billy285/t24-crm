"""Same-image scheduler configuration only. No provider/SQL/Nginx writes."""
import copy
import fcntl
import hashlib
import json
import os
import re
import resource
import socket
import sqlite3
import stat
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '6b47aefa201fb5e4963e4cfa522b7a5776e5a2c4'
FRONTEND = 'b06112728ac2'
REVISION = 'd9e4f6a7b803'
DEPLOYED_SHA = '17858808bd0ac0f825e8a51931bdf49cde6253f431a0ab7e8280b301fe3b9f37'
ORIGINAL_ID = 'fc368b511c945fc9fd28b4ccd889fddc2d50d5b7d068a2afd789e6e262e98441'
IMAGE = 'sha256:925f4b723f13e89ee5217955d9f5208336b5bd063af2e1878fc06b036a50a2bf'
RELEASE = Path('/opt/t24-crm/releases/media-ops-management-6b47aefa201f-20261031')
ROOT = Path('/opt/t24-crm/releases/media-ops-scheduler-6b47aefa201f-20261031')
PUBLISHER_SHA = 'ebe95b02fb337bd4d2c0cb10fed9e1f29ef7c71aececff2e94c40a7443acd27c'
PREFLIGHT_SHA = '12a65720a072901bbeb55cdc91ca69a3430c06da178d8d6d0b80d46e8787d95b'
LEGACY = Path('/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py')
LEGACY_SHA = 'bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0'
KEYS = frozenset({'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'})
FILE_OWNER = 0
H = lambda blob: hashlib.sha256(blob).hexdigest()


class GuardError(RuntimeError): pass


def need(ok, code):
    if not ok: raise GuardError(code)


def now(): return datetime.now(timezone.utc)


def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def safe_code(error):
    return str(error) if isinstance(error, GuardError) and re.fullmatch('[A-Z][A-Z0-9_]{0,95}', str(error)) else 'SCHEDULER_CONFIG_REJECTED'


def guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_SERVER_ROOT_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0));os.umask(0o077)


def directory(path):
    need(path.is_absolute() and path.resolve() == path, 'PROTECTED_DIRECTORY_REQUIRED')
    for parent in (path, *path.parents):
        row = parent.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == FILE_OWNER and not row.st_mode & 0o022, 'PROTECTED_PARENT_REQUIRED')


def mkdir(path):
    directory(path.parent)
    if not path.exists() and not path.is_symlink(): path.mkdir(mode=0o700)
    directory(path);need(stat.S_IMODE(path.stat().st_mode) == 0o700, 'PRIVATE_ATTEMPT_MODE_REQUIRED')


def read(path, expected=None, maximum=1024*1024):
    directory(path.parent);before=path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == FILE_OWNER and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, 'PROTECTED_FILE_REQUIRED')
    fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'FILE_OPEN_DRIFT');blob=stream.read(maximum+1)
    after=path.lstat()
    need(len(blob)<=maximum and (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'FILE_READ_DRIFT')
    need(expected is None or H(blob)==expected,'FILE_HASH_DRIFT');return blob


def write(path, value):
    directory(path.parent);blob=value if isinstance(value,bytes) else encoded(value)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(blob);stream.flush();os.fsync(stream.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    return H(blob)


def load(path, sha, name):
    blob=read(path,sha);module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(blob,str(path),'exec'),module.__dict__);return module


def env(info):
    result={}
    for row in info['Config']['Env']:
        need(isinstance(row,str) and '=' in row and not any(c in row for c in '\r\n\0'),'ENVIRONMENT_FORMAT_REJECTED')
        key,value=row.split('=',1);need(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key) and key not in result,'DUPLICATE_ENVIRONMENT_KEY');result[key]=value
    return result


def scheduler_off(info):
    values=env(info)
    need(values.get('T24_GBP_SCHEDULER_ENABLED','false')=='false' and not values.get('T24_GBP_SCHEDULER_ACTIVATION_FROM',''),'SCHEDULER_MUST_BE_OFF')


def cutoff(value):
    need(isinstance(value,str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value),'FIXED_UTC_CUTOFF_REQUIRED')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def networks(info):
    values=info.get('NetworkSettings',{}).get('Networks',{})
    need(isinstance(values,dict),'NETWORK_METADATA_REQUIRED')
    known={'IPAMConfig','Links','Aliases','NetworkID','EndpointID','Gateway','IPAddress','IPPrefixLen','IPv6Gateway','GlobalIPv6Address','GlobalIPv6PrefixLen','MacAddress','DriverOpts','DNSNames','GwPriority'}
    for endpoint in values.values():
        need(isinstance(endpoint,dict) and not (set(endpoint)-known),'UNSUPPORTED_NETWORK_METADATA')
        need(endpoint.get('IPAMConfig') is None or endpoint.get('IPAMConfig')=={},'EXPLICIT_IPAM_CONFIGURATION_UNSUPPORTED')
    return values


def compare(candidate, original, runtime, activation_from):
    need(candidate['Image']==original['Image'],'SAME_IMAGE_REQUIRED')
    need(set(networks(candidate))==set(networks(original)),'ATTACHED_NETWORK_SET_DRIFT')
    old,new=env(original),env(candidate)
    wanted={**old,'T24_GBP_SCHEDULER_ENABLED':'true','T24_GBP_SCHEDULER_ACTIVATION_FROM':activation_from}
    need(new==wanted,'ONLY_TWO_SCHEDULER_VALUES_ALLOWED')
    normalized=copy.deepcopy(candidate);normalized['Config']['Env']=copy.deepcopy(original['Config']['Env'])
    for key in ('Image','Hostname'):normalized['Config'][key]=copy.deepcopy(original['Config'].get(key))
    # Comparison-only Docker default equivalence. True, integer zero, missing,
    # and unrelated HostConfig changes are never admitted or rewritten.
    for row in (original,candidate):
        need('OomKillDisable' in row['HostConfig'] and (row['HostConfig']['OomKillDisable'] is None or row['HostConfig']['OomKillDisable'] is False),'EXACT_OOM_DEFAULT_REQUIRED')
    normalized['HostConfig']['OomKillDisable']=original['HostConfig']['OomKillDisable']
    need(runtime(normalized)['config']==runtime(original)['config'],'OTHER_RUNTIME_CONFIGURATION_DRIFT')


def clone(original, activation_from, endpoints):
    scheduler_off(original);cutoff(activation_from);networks(original)
    config=copy.deepcopy(original['Config']);config['Image']=original['Image'];config['Hostname']=''
    found=set();rows=[]
    values={'T24_GBP_SCHEDULER_ENABLED':'true','T24_GBP_SCHEDULER_ACTIVATION_FROM':activation_from}
    for row in config['Env']:
        key=row.split('=',1)[0]
        rows.append(key+'='+values[key] if key in KEYS else row);found.add(key)
    rows.extend(key+'='+values[key] for key in sorted(KEYS-found));config['Env']=rows
    config['HostConfig']=copy.deepcopy(original['HostConfig'])
    need(config['HostConfig'].get('AutoRemove') is False,'RETAINED_CONTAINER_REQUIRED')
    need(endpoints or config['HostConfig']['NetworkMode'] in {'host','none'},'EXACT_NETWORKS_REQUIRED')
    config['NetworkingConfig']={'EndpointsConfig':copy.deepcopy(endpoints)};return config


def oauth_and_queue(m, owner_id):
    con=sqlite3.connect('file:'+str(m.BUSINESS)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(REVISION,)],'EXACT_SCHEMA_REQUIRED')
        need(con.execute('SELECT COUNT(*) FROM google_business_schedules').fetchone()[0]==0,'FIRST_ENABLE_REQUIRES_EMPTY_QUEUE')
        owner=con.execute('SELECT role,status FROM employees WHERE id=?',(owner_id,)).fetchone()
        need(owner is not None and owner[0]=='super_admin' and owner[1] in {'active','probation'},'ACTIVE_OWNER_REQUIRED')
        count=con.execute("SELECT COUNT(*) FROM google_business_connections WHERE owner_id=? AND active=1 AND needs_reconnect=0 AND token_encrypted IS NOT NULL AND token_encrypted<>''",(owner_id,)).fetchone()[0]
        need(count>0,'EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED')
        return {'queue_empty':True,'active_owner_verified':True,'active_owner_google_connections':count}
    finally:con.close()


def config_probe(flag, activation_from=None):
    return ("import os,socket,sys,sysconfig\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nsys.path.insert(0,'/app/backend')\nsys.path.extend(sorted(set(sysconfig.get_path(k) for k in ('purelib','platlib'))))\n"
        "from services.google_business_provider import enabled,settings\nfrom services.google_business_scheduler import enabled as worker,activation_from as start\n"
        "assert enabled() is True and not settings()[1]\nassert worker() is "+repr(flag)+"\n"
        + ("assert start().isoformat()=="+repr(cutoff(activation_from).isoformat())+"\n" if flag else '')
        + "print('SCHEDULER_CONFIG_NO_NETWORK_VERIFIED')\n")


class Workflow:
    def __init__(self, attempt, receipt_sha, owner_id):
        need(isinstance(attempt,str) and str(UUID(attempt))==attempt,'CANONICAL_ATTEMPT_UUID_REQUIRED')
        need(receipt_sha==DEPLOYED_SHA and type(owner_id) is int and owner_id>0,'EXACT_RECEIPT_AND_OWNER_REQUIRED')
        self.attempt=attempt;self.path=ROOT/attempt;self.owner=owner_id;self.receipt_sha=receipt_sha
        self.m=load(LEGACY,LEGACY_SHA,'_scheduler_retained')
        self.p=load(RELEASE/'release.py',PUBLISHER_SHA,'_scheduler_publisher')
        self.safe=load(RELEASE/'preflight.py',PREFLIGHT_SHA,'_scheduler_safe_metadata')
        self.receipt=json.loads(read(RELEASE/'deployed.json',receipt_sha))
        r=self.receipt
        need(r.get('stage')=='MEDIA_OPS_MANAGEMENT_DEPLOYED_VERIFIED' and r.get('deployed') is True and r.get('source_sha')==SOURCE and r.get('frontend_version')==FRONTEND and r.get('schema_revision')==REVISION and r.get('scheduler_disabled') is True and r.get('existing_google_environment_preserved') is True,'EXACT_DEPLOYED_RELEASE_REQUIRED')
        need(r['crm']['id']==ORIGINAL_ID and r['crm']['image']==IMAGE,'EXACT_DEPLOYED_CONTAINER_IMAGE_REQUIRED')
        self.pins=json.loads(self.m.read(self.p.PRIVATE_PINS,self.p.PRIVATE_PINS_SHA))
        self.inventory=json.loads(self.m.read(RELEASE/'backend-candidate-inventory.json',r['candidate_inventory_sha256']))
        prepared=json.loads(read(RELEASE/'prepared.json'))
        proof_sha=prepared['preflight_sha256']
        need(re.fullmatch('[a-f0-9]{64}',proof_sha),'DEPLOYMENT_PROOF_HASH_REQUIRED')
        proof_path=Path('/opt/t24-crm/releases/media-ops-management-preflight-'+proof_sha[:12]+'.json')
        self.deployment_proof=json.loads(read(proof_path,proof_sha))
        self.original_name='t24-crm-scheduler-off-'+attempt[:8]
        self.candidate_name='t24-crm-scheduler-on-'+attempt[:8]

    def metadata(self):
        return {'private':self.safe.safe_private_boundary(self.m,self.pins),'stripe':self.m.credential_boundary(),'google':self.safe.protected_metadata(self.safe.GBP_ENV)}

    def nginx(self):
        m=self.m;r=self.receipt;body=m.NGINX.read_bytes();need(H(body)==r['nginx_sha256'],'NGINX_SITE_DRIFT')
        active=m.run(['nginx','-T'],'NGINX_PARSE_FAILED')
        old=os.fsencode(self.deployment_proof['public_root']);new=os.fsencode(r['public_root'])
        need(active.count(new)==1 and H(active.replace(new,old,1))==self.deployment_proof['active_nginx_config_sha256'],'FULL_NGINX_DRIFT')
        return {'site':H(body),'active':H(active)}

    def boundary(self, *, queue=True):
        m=self.m;r=self.receipt
        need(m.schema_signature(m.BUSINESS,REVISION)==r['schema_sha256'],'SCHEMA_DRIFT')
        need(m.digest(m.tree(Path(r['public_root'])))==r['public_inventory_sha256'] and json.loads((Path(r['public_root'])/'app-version.json').read_bytes())['version']==FRONTEND,'STATIC_OR_FRONTEND_DRIFT')
        row=m.BUSINESS.stat()
        facts={'database_identity':[row.st_dev,row.st_ino],'metadata':self.metadata(),'nginx':self.nginx()}
        if queue:facts['oauth']=oauth_and_queue(m,self.owner)
        return facts

    def rows(self): return self.m.sql_snapshot(self.m.BUSINESS)

    def source(self,info):
        self.p.Release.source_overlay_boundary(SimpleNamespace(m=self.m),info,self.inventory)

    def initial(self):
        m=self.m;original=m.inspect('t24-crm')
        need(original['State']['Running'] and m.runtime(original)==self.receipt['crm'],'EXACT_LIVE_BASELINE_REQUIRED')
        self.p.verify_gbp_environment_enabled(original);scheduler_off(original);m.verify_secret_mount(original);m.verify_production_worker_enabled(original)
        self.source(original);facts=self.boundary();rows=self.rows()
        output=m.run(['docker','exec',original['Id'],'python','-I','-S','-B','-c',config_probe(False)],'BASELINE_CONFIGURATION_PROBE_FAILED')
        need(output.strip()==b'SCHEDULER_CONFIG_NO_NETWORK_VERIFIED','BASELINE_PROBE_MARKER_REQUIRED')
        need(rows==self.rows() and m.runtime(original)==m.runtime(m.inspect('t24-crm')) and facts==self.boundary(),'BASELINE_CHANGED_DURING_READ')
        return original,facts,rows

    def plan(self):
        original,facts,rows=self.initial();mkdir(ROOT);mkdir(self.path)
        value={'stage':'SCHEDULER_CONFIG_PLAN','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'attempt':self.attempt,'owner_id':self.owner,'deployed_sha256':self.receipt_sha,'crm':self.m.runtime(original),'facts':facts,'rows':rows,'activation_delay_seconds':120,'tool_sha256':tool_hash(),'provider_requests':False,'business_writes':False,'nginx_changed':False}
        sha=write(self.path/'plan.json',value)
        return {'stage':value['stage'],'plan_sha256':sha,'attempt':self.attempt,'source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'crm':value['crm'],'owner_id':self.owner,'activation_delay_seconds':120,'queue_empty':True,'provider_requests':False,'business_writes':False,'nginx_changed':False}

    def read_plan(self, plan_sha):
        value=json.loads(read(self.path/'plan.json',plan_sha))
        need(value['stage']=='SCHEDULER_CONFIG_PLAN' and value['source_sha']==SOURCE and value['frontend_version']==FRONTEND and value['schema_revision']==REVISION and value['attempt']==self.attempt and value['owner_id']==self.owner and value['deployed_sha256']==self.receipt_sha and value['activation_delay_seconds']==120 and value['tool_sha256']==tool_hash(),'PLAN_SCOPE_DRIFT')
        return value

    def identities(self, original, state):
        m=self.m;retained=m.inspect(original['Id']);candidate=m.inspect(state['candidate_id'])
        need(retained['Image']==original['Image']==candidate['Image'] and retained['Id']!=candidate['Id'],'EXACT_SAME_IMAGE_IDS_REQUIRED')
        need(m.runtime(retained)['config']==m.runtime(original)['config'],'RETAINED_ORIGINAL_CONFIG_DRIFT');scheduler_off(retained)
        active=m.inspect_optional('t24-crm')
        need(not active or active['Id'] in {original['Id'],candidate['Id']},'UNKNOWN_PRIMARY_CONTAINER')
        for name,identity in ((self.original_name,original['Id']),(self.candidate_name,candidate['Id'])):
            found=m.inspect_optional(name);need(not found or found['Id']==identity,'UNKNOWN_RESERVED_CONTAINER')
        need(retained['Name'] in {'/t24-crm','/'+self.original_name} and candidate['Name'] in {'/t24-crm','/'+self.candidate_name},'CONTAINER_NAME_DRIFT')
        return retained,candidate

    def fresh(self, original, candidate, plan, activation_from, *, stopped=False):
        need(cutoff(activation_from)>now(),'ACTIVATION_CUTOFF_NO_LONGER_FUTURE')
        compare(candidate,original,self.m.runtime,activation_from)
        need(self.boundary()==plan['facts'] and self.rows()==plan['rows'],'DATABASE_METADATA_OR_QUEUE_DRIFT')
        self.source(original);self.source(candidate)
        need(original['State']['Running'] is (not stopped) and not candidate['State']['Running'],'EXPECTED_PRESTART_STATES_REQUIRED')
        need(cutoff(activation_from)>now(),'CUTOFF_EXPIRED_DURING_RECHECK')

    def activate(self, plan_sha, confirmed):
        need(confirmed is True,'EXPLICIT_SCHEDULER_CONFIRMATION_REQUIRED')
        plan=self.read_plan(plan_sha);need(not (self.path/'intent.json').exists(),'EXISTING_ATTEMPT_REQUIRES_ROLLBACK')
        original,facts,rows=self.initial()
        need(facts==plan['facts'] and rows==plan['rows'] and self.m.runtime(original)==plan['crm'],'PLAN_STALE')
        m=self.m
        need(not m.inspect_optional(self.original_name) and not m.inspect_optional(self.candidate_name),'RESERVED_NAME_OCCUPIED')
        activation_from=(now()+timedelta(seconds=120)).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
        original_sha=write(self.path/'original-container.json',original)
        intent={'stage':'SCHEDULER_SWITCH_INTENT','original_id':original['Id'],'image':original['Image'],'source_sha':SOURCE,'plan_sha256':plan_sha,'original_sha256':original_sha,'attempt':self.attempt,'activation_from':activation_from,'tool_sha256':tool_hash()}
        write(self.path/'intent.json',intent)
        config=clone(original,activation_from,m.retained().clone_networks(original))
        status,blob=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,config)
        need(status==201,'CANDIDATE_CREATE_FAILED');identity=json.loads(blob)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'CANDIDATE_ID_REQUIRED')
        state={**intent,'candidate_id':identity,'candidate_name':self.candidate_name};write(self.path/'candidate-created.json',state)
        try:
            old,candidate=self.identities(original,state)
            need(candidate['State'].get('Status')=='created' and candidate['State'].get('StartedAt') in {'','0001-01-01T00:00:00Z','0001-01-01T00:00:00.000000000Z'} and type(candidate['RestartCount']) is int and candidate['RestartCount']==0,'NEVER_STARTED_CANDIDATE_REQUIRED')
            self.fresh(old,candidate,plan,activation_from)
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60)
            old,candidate=self.identities(original,state);self.fresh(old,candidate,plan,activation_from,stopped=True)
            m.run(['docker','rename',old['Id'],self.original_name],'ORIGINAL_RENAME_FAILED')
            m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED')
            # Last empty-queue/credential/source check is after ID persistence and
            # before starting any executor. No historical job can sneak in.
            old,candidate=self.identities(original,state);self.fresh(old,candidate,plan,activation_from,stopped=True)
            need(cutoff(activation_from)>now(),'CUTOFF_EXPIRED_BEFORE_START')
            m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity)
            active=m.inspect('t24-crm');need(active['Id']==identity and active['State']['Running'],'ACTIVE_CANDIDATE_ID_REQUIRED')
            compare(active,original,m.runtime,activation_from);self.source(active)
            need(cutoff(activation_from)>now() and self.boundary()==plan['facts'] and self.rows()==rows,'ACTIVATION_ACCEPTANCE_DRIFT')
            output=m.run(['docker','exec',identity,'python','-I','-S','-B','-c',config_probe(True,activation_from)],'EXECUTOR_CONFIGURATION_PROBE_FAILED')
            need(output.strip()==b'SCHEDULER_CONFIG_NO_NETWORK_VERIFIED','EXECUTOR_PROBE_MARKER_REQUIRED')
            compare(m.inspect(identity),original,m.runtime,activation_from)
            need(self.boundary()==plan['facts'] and self.rows()==rows and cutoff(activation_from)>now(),'FINAL_ACCEPTANCE_DRIFT')
            old,active=self.identities(original,state);primary=m.inspect('t24-crm')
            need(primary['Id']==identity and active['Id']==identity and active['State']['Running'] is True and old['State']['Running'] is False,'FINAL_PRIMARY_ROLE_DRIFT')
            compare(active,original,m.runtime,activation_from);self.source(active)
            need(cutoff(activation_from)>now(),'CUTOFF_EXPIRED_BEFORE_RECEIPT')
            receipt={'stage':'SCHEDULER_CONFIG_ENABLED_VERIFIED','source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'crm':m.runtime(active),'original_id':original['Id'],'attempt':self.attempt,'plan_sha256':plan_sha,'deployed_sha256':self.receipt_sha,'activation_from':activation_from,'queue_empty':True,'same_image':True,'exact_two_scheduler_keys_only':True,'all_existing_env_mounts_network_unchanged':True,'all_business_rows_unchanged':True,'nginx_changed':False,'private_content_read':False,'database_migrated_or_restored':False,'containers_deleted':False,'provider_requests_by_tool':False,'live_kernel_oom_behavior_verified':False,'tool_sha256':tool_hash()}
            sha=write(self.path/'enabled.json',receipt);return {**receipt,'receipt_sha256':sha}
        except BaseException:
            self.rollback(plan_sha);raise

    def rollback(self,plan_sha):
        plan=self.read_plan(plan_sha);original=json.loads(read(self.path/'original-container.json'));state=json.loads(read(self.path/'candidate-created.json'))
        need(state['original_id']==original['Id'] and state['image']==original['Image'] and state['plan_sha256']==plan_sha and state['tool_sha256']==tool_hash(),'ROLLBACK_INTENT_DRIFT')
        need(re.fullmatch('[a-f0-9]{64}',state['candidate_id']) and state['candidate_id']!=original['Id'],'EXACT_ROLLBACK_CANDIDATE_REQUIRED')
        candidate=self.m.inspect(state['candidate_id'])
        need(candidate['Id']==state['candidate_id'] and candidate['Image']==state['image'] and candidate['Name'] in {'/t24-crm','/'+self.candidate_name},'OWNED_CANDIDATE_ID_IMAGE_ROLE_REQUIRED')
        # Contain our durably recorded executor before any failing restoration
        # precondition can leave it enabled. Unknown containers are never touched.
        if candidate['State']['Running']:self.m.run(['docker','stop','--time','30',candidate['Id']],'ROLLBACK_CANDIDATE_STOP_FAILED',60)
        candidate=self.m.inspect(state['candidate_id'])
        need(candidate['Id']==state['candidate_id'] and candidate['State']['Running'] is False,'EXECUTOR_CONTAINMENT_FAILED')
        try:
            marker={'stage':'SCHEDULER_EXECUTOR_CONTAINED','candidate_id':candidate['Id'],'image':candidate['Image'],'stopped':True}
            path=self.path/'contained.json'
            if path.exists():need(json.loads(read(path))==marker,'CONTAINMENT_RECORD_DRIFT')
            else:write(path,marker)
        except (OSError,GuardError):pass
        need(self.m.runtime(original)==plan['crm'],'SAVED_ORIGINAL_PLAN_DRIFT')
        intent=json.loads(read(self.path/'intent.json'))
        need(state.get('stage')=='SCHEDULER_SWITCH_INTENT' and state.get('source_sha')==SOURCE and state.get('candidate_name')==self.candidate_name and state.get('attempt')==self.attempt and all(state.get(k)==intent.get(k) for k in intent),'ROLLBACK_STATE_SCOPE_DRIFT')
        need(state.get('original_sha256')==H(read(self.path/'original-container.json')),'SAVED_ORIGINAL_HASH_DRIFT')
        cutoff(state['activation_from'])
        old,candidate=self.identities(original,state)
        # Empty-queue and row equality are NOT prerequisites for restoring OFF.
        # Metadata/schema drift may still require manual recovery, with our
        # known candidate already stopped and retained for inspection.
        need(self.boundary(queue=False)=={key:value for key,value in plan['facts'].items() if key!='oauth'},'ROLLBACK_PROTECTION_DRIFT')
        self.source(old);self.m.verify_secret_mount(old)
        if candidate['Name']=='/t24-crm':self.m.run(['docker','rename',candidate['Id'],self.candidate_name],'ROLLBACK_KEEP_CANDIDATE_FAILED')
        old=self.m.inspect(original['Id'])
        if old['Name']!='/t24-crm':self.m.run(['docker','rename',old['Id'],'t24-crm'],'ROLLBACK_ORIGINAL_RENAME_FAILED')
        if not old['State']['Running']:self.m.run(['docker','start',old['Id']],'ROLLBACK_ORIGINAL_START_FAILED')
        self.m.ready(old['Id']);restored=self.m.inspect('t24-crm')
        need(restored['Id']==original['Id'] and restored['State']['Running'] and self.m.runtime(restored)['config']==self.m.runtime(original)['config'],'DISABLED_ORIGINAL_NOT_RESTORED')
        scheduler_off(restored);self.source(restored)
        need(self.boundary(queue=False)=={key:value for key,value in plan['facts'].items() if key!='oauth'},'POST_RESTORE_PROTECTION_DRIFT')
        result=self.m.run(['docker','exec',old['Id'],'python','-I','-S','-B','-c',config_probe(False)],'ROLLBACK_CONFIG_PROBE_FAILED')
        need(result.strip()==b'SCHEDULER_CONFIG_NO_NETWORK_VERIFIED','ROLLBACK_CONFIG_MARKER_REQUIRED')
        kept=self.m.inspect(state['candidate_id'])
        need(kept['Id']==state['candidate_id'] and kept['Image']==state['image'] and kept['Name']=='/'+self.candidate_name and kept['State']['Running'] is False,'FINAL_CANDIDATE_STOPPED_PROOF_REQUIRED')
        value={'stage':'SCHEDULER_CONFIG_ROLLED_BACK_DISABLED','source_sha':SOURCE,'crm':self.m.runtime(restored),'attempt':self.attempt,'candidate_retained_stopped':True,'containers_deleted':False,'nginx_changed':False,'database_migrated_or_restored':False,'business_sql_writes_by_tool':False,'provider_requests_by_tool':False,'tool_sha256':tool_hash()}
        target=self.path/'rolled-back.json'
        if target.exists():return json.loads(read(target))
        write(target,value);return value


def tool_hash(): return getattr(sys.modules[__name__],'__tool_sha256__',None) or H(Path(__file__).read_bytes())


def dispatch(phase,attempt,receipt_sha,owner_id,plan_sha=None,confirmed=False):
    guard();need(phase in {'plan','activate','rollback'},'EXACT_PHASE_REQUIRED')
    mkdir(ROOT);lock=ROOT/'activation.lock';fd=os.open(lock,os.O_RDWR|os.O_NONBLOCK|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        read(lock,maximum=0);opened=os.fstat(fd);actual=lock.lstat()
        need((opened.st_dev,opened.st_ino)==(actual.st_dev,actual.st_ino),'LOCK_IDENTITY_DRIFT')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        workflow=Workflow(attempt,receipt_sha,owner_id)
        if phase=='plan':need(plan_sha is None and confirmed is False,'PLAN_NO_ENABLE_ARGUMENTS');return workflow.plan()
        need(isinstance(plan_sha,str) and re.fullmatch('[a-f0-9]{64}',plan_sha),'REVIEWED_PLAN_HASH_REQUIRED')
        return workflow.activate(plan_sha,confirmed) if phase=='activate' else workflow.rollback(plan_sha)
    finally:os.close(fd)

