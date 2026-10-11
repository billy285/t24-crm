#!/usr/bin/env python3
"""Reviewed read-only Stripe seed diagnosis. Never connects, seeds or retries.

Both database mounts are physically readonly. Existing encrypted credentials are
checked in memory, followed by the existing GET-only provider's six probes.
Only fixed stages, bounded exception classes and provider codes leave the helper.
The original one-use bootstrap claim remains untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from uuid import uuid4

import credential_transfer as transfer
import live_preflight as live
import private_schema_guard as guard
import seed_private_stripe as seed
import switch_completed as switch

LABEL = 't24.private_finance.stripe_diagnosis'
STAGES = frozenset({'configuration','owner','existing_credentials','stripe_configuration',
    'account','balance','charges','refunds','disputes','payouts','credential_identity','complete'})
ERRORS = frozenset({'invalid_credentials','not_configured','invalid_response','stripe_account_changed',
    'authorization_expired','access_denied','rate_limited','upstream_unavailable','upstream_timeout',
    'request_not_allowed','sync_limit','owner_changed','configuration_changed','existing_credential_unreadable'})
CLASSES = frozenset({'ProviderError','HTTPException','InvalidToken','ValueError','TypeError','AssertionError',
    'OSError','OperationalError','TimeoutError','CancelledError','RuntimeError','Exception'})
PROBES = ('account','balance','charges','refunds','disputes','payouts')


class DiagnosisError(RuntimeError): pass

class SafeParser(argparse.ArgumentParser):
    def error(self,message): raise DiagnosisError('ARGUMENTS_REJECTED')

def need(condition,code):
    if not condition: raise DiagnosisError(code)

def sha(blob): return hashlib.sha256(blob).hexdigest()

def helper_code():
    # No production values or arbitrary program strings enter this source.
    return '''import asyncio,io,json,os,sqlite3,sys
from contextlib import redirect_stdout,redirect_stderr
packet=json.load(sys.stdin)
stage='configuration';calls=[];report=None
class DiagError(RuntimeError):
 def __init__(self,code):self.code=code
async def operation():
 global stage
 os.environ.update(packet['configuration'])
 from sqlalchemy.ext.asyncio import async_sessionmaker
 from dependencies.private_workspace import valid_private_owner
 from services.private_workspace_worker import create_business_reader
 from services import private_workspace as core,private_workspace_providers as provider
 engine=create_business_reader();sessions=async_sessionmaker(engine,expire_on_commit=False)
 original=provider._Client.request
 async def owner():
  async with sessions() as db:return await valid_private_owner('4',db)
 async def request(client,method,url,**arguments):
  global stage
  allowed={RESOURCE_MAP}
  if method!='GET' or url not in allowed:raise DiagError('request_not_allowed')
  stage=allowed[url];calls.append(stage)
  return await original(client,method,url,**arguments)
 try:
  if os.environ.get('PRIVATE_WORKSPACE_OWNER_IDS')!='4' or os.environ.get('PRIVATE_WORKSPACE_STRIPE_MODE')!='live':raise DiagError('configuration_changed')
  stage='owner'
  if not await owner():raise DiagError('owner_changed')
  stage='existing_credentials'
  with sqlite3.connect('file:/private-data/workspace.db?mode=ro',uri=True,timeout=15) as db:
   db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
   rows=db.execute("SELECT owner_id,status,encrypted_credentials FROM private_connections").fetchall()
  for owner_id,status,ciphertext in rows:
   if owner_id!='4':raise DiagError('owner_changed')
   if status=='connected':
    try:
     if not core.decrypt_credentials(ciphertext):raise DiagError('existing_credential_unreadable')
    except Exception:raise DiagError('existing_credential_unreadable') from None
  stage='stripe_configuration'
  os.environ['PRIVATE_WORKSPACE_STRIPE_KEY']=packet['credentials']['api_key']
  provider._Client.request=request
  result=await provider.begin_connect('stripe','synthetic-readonly-diagnosis-state')
  stage='credential_identity'
  if result.get('credentials')!=packet['credentials']:raise DiagError('stripe_account_changed')
  metadata=result.get('metadata') or {}
  if metadata.get('stripe_account_id')!=packet['credentials']['stripe_account_id'] or metadata.get('mode')!='live' or metadata.get('read_only_adapter') is not True:raise DiagError('stripe_account_changed')
  if not await owner():raise DiagError('owner_changed')
  stage='complete'
  return {'stage':'PRIVATE_STRIPE_READONLY_DIAGNOSIS_COMPLETE','last_stage':stage,'probes':calls,'success':True,'database_writes':False,'connected':False}
 finally:
  provider._Client.request=original
  os.environ.pop('PRIVATE_WORKSPACE_STRIPE_KEY',None)
  await engine.dispose()
try:
 with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
  report=asyncio.run(asyncio.wait_for(operation(),timeout=65))
except BaseException as error:
 classes={CLASSES};codes={ERRORS};stages={STAGES}
 name=type(error).__name__;code=getattr(error,'code','')
 report={'stage':'PRIVATE_STRIPE_READONLY_DIAGNOSIS_FAILED','last_stage':stage if stage in stages else 'configuration','error_class':name if name in classes else 'Exception','error_code':code if code in codes else 'unclassified','probes':calls,'success':False,'database_writes':False,'connected':False}
finally:os.environ.pop('PRIVATE_WORKSPACE_STRIPE_KEY',None)
print(json.dumps(report,sort_keys=True))
'''.replace('{RESOURCE_MAP}',repr({'https://api.stripe.com/v1/'+name:name for name in
        ('account','balance','charges','refunds','disputes','payouts')})).replace('{CLASSES}',repr(CLASSES)).replace(
        '{ERRORS}',repr(ERRORS)).replace('{STAGES}',repr(STAGES))

def docker(arguments,*,input=None,timeout=30):
    try: result=subprocess.run(['docker',*arguments],input=input,capture_output=True,timeout=timeout,check=False)
    except Exception: raise DiagnosisError('DIAGNOSIS_DOCKER_OUTCOME_REQUIRES_REVIEW') from None
    need(result.returncode==0,'DIAGNOSIS_DOCKER_FAILED')
    return result.stdout

def inspect(identity):
    rows=json.loads(docker(['inspect',identity]));need(len(rows)==1,'DIAGNOSIS_SINGLE_CONTAINER_REQUIRED')
    return rows[0]

def create_command(name,image,attempt):
    need(re.fullmatch('t24-private-stripe-diagnosis-[a-f0-9]{32}',name) and
         name == 't24-private-stripe-diagnosis-'+attempt and re.fullmatch('[a-f0-9]{32}',attempt) and
         re.fullmatch('sha256:[a-f0-9]{64}',image),'EXACT_DIAGNOSIS_HELPER_REQUIRED')
    return ['create','--interactive','--name',name,'--label',LABEL+'='+attempt,'--restart','no',
        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--network','bridge','--no-healthcheck',
        '--log-driver','none','--pids-limit','64','--memory','256m','--cpus','1',
        '--tmpfs','/tmp:rw,nosuid,noexec,size=64m','--workdir','/app/backend','--env','PYTHONDONTWRITEBYTECODE=1',
        '--mount','type=bind,src='+str(live.BUSINESS.parent)+',dst=/app/backend/data,readonly',
        '--mount','type=bind,src='+str(live.PRIVATE_DB.parent)+',dst=/private-data,readonly',
        '--entrypoint','python',image,'-c',helper_code()]

def checked_helper(info,identity,image,attempt):
    host,config=info['HostConfig'],info['Config']
    need(info['Id']==identity and info['Image']==image and identity not in {live.CRM_ID,*live.PRIVATE_IDS.values()} and
        config.get('Labels',{}).get(LABEL)==attempt,'DIAGNOSIS_EXACT_HELPER_REQUIRED')
    need(host.get('ReadonlyRootfs') is True and host.get('CapDrop')==['ALL'] and
        host.get('SecurityOpt') in (['no-new-privileges'],['no-new-privileges:true']) and
        host.get('NetworkMode')=='bridge' and host.get('RestartPolicy',{}).get('Name')=='no' and
        host.get('LogConfig',{}).get('Type')=='none' and not host.get('PortBindings') and not host.get('Binds') and
        not host.get('Privileged') and not host.get('CapAdd') and not host.get('Devices') and not host.get('DeviceRequests') and
        host.get('PidMode','')=='' and host.get('UTSMode','')=='' and host.get('IpcMode')=='private' and
        host.get('PidsLimit')==64 and host.get('Memory')==256*1024**2 and host.get('NanoCpus')==10**9 and
        host.get('Tmpfs')=={'/tmp':'rw,nosuid,noexec,size=64m'},'DIAGNOSIS_ISOLATION_REQUIRED')
    binds=[m for m in info['Mounts'] if m.get('Type')=='bind']
    need(len(binds)==2 and {(m['Source'],m['Destination'],m['RW']) for m in binds}=={
        (str(live.BUSINESS.parent),'/app/backend/data',False),(str(live.PRIVATE_DB.parent),'/private-data',False)} and
        len(info['Mounts'])<=3 and all(m['Type']=='bind' or m['Type']=='tmpfs' and m['Destination']=='/tmp' for m in info['Mounts']),
        'BOTH_DATABASE_MOUNTS_MUST_BE_READONLY')
    need(config.get('Entrypoint')==['python'] and config.get('Cmd')==['-c',helper_code()] and
        config.get('WorkingDir')=='/app/backend' and config.get('OpenStdin') is True,
        'DIAGNOSIS_FIXED_PROGRAM_REQUIRED')
    for entry in config.get('Env',[]):
        name,value=entry.split('=',1)
        need(name in transfer.SAFE_IMAGE_ENV_NAMES and not re.search(r'rk_(?:live|test)_|Bearer ',value),
             'NO_DIAGNOSIS_CREDENTIAL_IN_DOCKER_CONFIG')
    return info

def checked_report(raw):
    need(len(raw)<=4096,'BOUNDED_DIAGNOSIS_OUTPUT_REQUIRED');value=json.loads(raw)
    need(isinstance(value,dict) and value.get('database_writes') is False and value.get('connected') is False and
        type(value.get('success')) is bool and value.get('last_stage') in STAGES and
        isinstance(value.get('probes'),list) and len(value['probes'])<=6 and
        value['probes']==list(PROBES[:len(value['probes'])]),
        'FIXED_SAFE_DIAGNOSIS_REPORT_REQUIRED')
    fields={'stage','last_stage','probes','success','database_writes','connected'}
    if value['success']:
        need(set(value)==fields and value['stage']=='PRIVATE_STRIPE_READONLY_DIAGNOSIS_COMPLETE' and
            value['last_stage']=='complete' and value['probes']==['account','balance','charges','refunds','disputes','payouts'],
            'EXACT_SIX_READONLY_PROBES_REQUIRED')
    else:
        need(set(value)==fields|{'error_class','error_code'} and value['stage']=='PRIVATE_STRIPE_READONLY_DIAGNOSIS_FAILED' and
            value['error_class'] in CLASSES and value['error_code'] in ERRORS|{'unclassified'}, 'FIXED_DIAGNOSIS_FAILURE_REQUIRED')
    return value

def checked_failed_outcome(current,after,connections):
    # A refreshed OAuth token also requires a separately reviewed recovery lineage.
    need(current==after,'EXACT_FAILED_SEED_SCHEMA_AFTER_REQUIRED')
    need(connections.get('row') is None,'FAILED_SEED_MUST_HAVE_NO_STRIPE_CONNECTION')

def checked_failed_claim(claim,args,state):
    lineage=state.get('resume_lineage')
    original_candidate=lineage['original_candidate_sha256'] if lineage else args.candidate_sha256
    original_source=lineage['original_source_sha'] if lineage else args.source_sha
    need(claim.get('stage')=='STRIPE_SEED_ONE_USE_CLAIMED' and
         claim.get('candidate_sha256')==original_candidate and claim.get('source_sha')==original_source and
         claim.get('bootstrap_sha256')==args.bootstrap_sha256 and re.fullmatch('[a-f0-9]{32}',claim.get('attempt','')),
         'EXACT_FAILED_ONE_USE_CLAIM_REQUIRED')
    if lineage:
        need(args.failed_claim_sha256==lineage['original_claim_sha256'] and
             args.bootstrap_sha256==lineage['bootstrap_sha256'],'RESUME_DIAGNOSIS_ORIGINAL_CLAIM_BINDING_REQUIRED')

def main(args):
    need(args.execute and os.geteuid()==0 and socket.gethostname()==live.HOST,'EXPLICIT_ROOT_DIAGNOSIS_REQUIRED')
    os.umask(0o077)
    with switch.release_lock():
        receipt=switch.checked_candidate(args)
        state,before,after,baseline=switch.checked_schema_state(args,receipt)
        switch.runtime_guard(baseline);switch.no_writers()
        current=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
        switch.schema_and_business_unchanged(current,after);switch.disabled_data(current)
        checked_failed_outcome(current,after,seed.connection_state(live.PRIVATE_DB))
        expected=seed.fixed_json(args.readonly_baseline,args.readonly_baseline_sha256)
        need(current==expected,'EXACT_CURRENT_READONLY_DIAGNOSIS_BASELINE_REQUIRED')
        need(sha(transfer.read_protected(transfer.BOOTSTRAP,32768))==args.bootstrap_sha256,'SEALED_BOOTSTRAP_HASH_DRIFT')
        claim_path=transfer.CONFIG/'stripe-seed-claims'/(args.bootstrap_sha256+'.json')
        claim=seed.fixed_json(claim_path,args.failed_claim_sha256)
        checked_failed_claim(claim,args,state)
        need(args.output.parent==args.candidate.parent/'completed-release' and
             re.fullmatch('stripe-diagnosis-[a-f0-9]{32}\\.json',args.output.name) and not args.output.exists(),
             'NEW_PROTECTED_DIAGNOSIS_OUTPUT_REQUIRED')
        configuration=seed.checked_configuration(transfer.read_protected(transfer.ENV))
        payload=transfer.get_bootstrap(sealed_crypto='docker')
        attempt=uuid4().hex;identity=None;name='t24-private-stripe-diagnosis-'+attempt
        try:
            exists=subprocess.run(['docker','inspect',name],capture_output=True,timeout=30,check=False)
            need(exists.returncode!=0,'EXCLUSIVE_DIAGNOSIS_NAME_REQUIRED')
            identity=docker(create_command(name,receipt['image_id'],attempt)).decode().strip()
            need(re.fullmatch('[a-f0-9]{64}',identity),'DIAGNOSIS_HELPER_ID_REQUIRED')
            checked_helper(inspect(identity),identity,receipt['image_id'],attempt)
            packet=transfer.encoded({'configuration':configuration,'credentials':payload['credentials']})
            raw=docker(['start','--attach','--interactive',identity],input=packet,timeout=75)
            result=checked_report(raw)
            helper=checked_helper(inspect(identity),identity,receipt['image_id'],attempt)
            need(not helper['State']['Running'] and helper['State'].get('ExitCode')==0,'DIAGNOSIS_HELPER_MUST_EXIT')
            switch.runtime_guard(baseline);switch.no_writers()
            need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)==current,'READONLY_DIAGNOSIS_DATABASE_DRIFT')
            need(sha(transfer.read_protected(transfer.BOOTSTRAP,32768))==args.bootstrap_sha256,'DIAGNOSIS_BOOTSTRAP_CHANGED')
            need(seed.fixed_json(claim_path,args.failed_claim_sha256)==claim,'DIAGNOSIS_ONE_USE_CLAIM_CHANGED')
            value={**result,'format_version':1,'source_sha':args.source_sha,'candidate_sha256':args.candidate_sha256,
                'image_id':receipt['image_id'],'runtime_env_sha256':live.ENV_SHA,'bootstrap_sha256':args.bootstrap_sha256,
                'before_snapshot_sha256':guard.digest(current),'after_snapshot_sha256':guard.digest(current),
                'schema_state_sha256':args.schema_state_sha256,'schema_after_sha256':state['schema_after_sha256'],
                'failed_claim_sha256':args.failed_claim_sha256,'failed_seed_attempt':claim['attempt'],
                'stripe_connection_absent':True,'exact_accepted_schema_after':True,
                'resume_lineage_sha256':guard.digest(state['resume_lineage']) if state.get('resume_lineage') else None,
                'credential_seed_attempted':False,'one_use_claim_changed':False,'production_services_changed':False,'deployed':False}
            transfer.write_exclusive(args.output,transfer.encoded(value))
            print(json.dumps({**result,'receipt_sha256':sha(transfer.read_protected(args.output)),'deployed':False},sort_keys=True))
        finally:
            if identity:
                checked_helper(inspect(identity),identity,receipt['image_id'],attempt)
                docker(['rm','--force',identity])

def cli(argv=None):
    parser=SafeParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--source-sha',required=True)
    for name in ('candidate','schema-state','readonly-baseline'):
        parser.add_argument('--'+name,type=Path,required=True);parser.add_argument('--'+name+'-sha256',required=True)
    parser.add_argument('--bootstrap-sha256',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--failed-claim-sha256',required=True)
    try: main(parser.parse_args(argv))
    except BaseException as error:
        code=str(error) if isinstance(error,DiagnosisError) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else 'READONLY_DIAGNOSIS_REJECTED'
        print(json.dumps({'stage':'PRIVATE_STRIPE_DIAGNOSIS_REJECTED','code':code,'connected':False,'database_writes':False},sort_keys=True));return 1
    return 0

if __name__=='__main__':raise SystemExit(cli())
