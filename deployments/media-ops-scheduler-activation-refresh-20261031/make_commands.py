"""Generate small immutable-carrier commands only; never execute a server phase."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import UUID

HERE=Path(__file__).resolve().parent
DIRECTORY='deployments/media-ops-scheduler-activation-refresh-20261031'
SOURCE='5a52cdcf8e9560fcf5ec6e2b27f264f6f0fe1087'
RECEIPT='e9790ac0c05b14a79f0e72d7a6d11d2547d5bf9d8892c29b3d9703295f866c80'
HOST='iZj6c4cj7edgnhdimts4l7Z'
H=lambda value:hashlib.sha256(value).hexdigest()


def need(ok,code):
    if not ok:raise RuntimeError(code)


def git(*args):return subprocess.check_output(['git',*args],cwd=HERE)


def validate(carrier,phase,attempt,receipt,owner,plan,confirmed):
    need(isinstance(carrier,str) and re.fullmatch('[a-f0-9]{40}',carrier),'EXACT_IMMUTABLE_CARRIER_REQUIRED')
    need(phase in {'plan','activate','rollback'},'EXACT_PHASE_REQUIRED')
    need(isinstance(attempt,str) and str(UUID(attempt))==attempt,'CANONICAL_ATTEMPT_UUID_REQUIRED')
    need(RECEIPT!='0'*64 and receipt==RECEIPT and type(owner) is int and owner>0,'EXACT_DEPLOYED_RECEIPT_AND_OWNER_REQUIRED')
    if phase=='plan':need(plan is None and confirmed is False,'PLAN_NO_ENABLE_ARGUMENTS')
    else:need(isinstance(plan,str) and re.fullmatch('[a-f0-9]{64}',plan),'REVIEWED_PLAN_HASH_REQUIRED')
    need(type(confirmed) is bool and (phase=='activate') is confirmed,'EXPLICIT_ACTIVATION_ONLY_CONFIRMATION_REQUIRED')


def reviewed_core(carrier):
    freeze_bytes=(HERE/'tool-freeze.json').read_bytes();freeze=json.loads(freeze_bytes)
    need(freeze['stage']=='SCHEDULER_CONFIG_TOOL_REVIEW_READY' and freeze['source_sha']==SOURCE and freeze['deployed_sha256']==RECEIPT,'EXACT_TOOL_FREEZE_REQUIRED')
    need(git('rev-parse',carrier+':app')==git('rev-parse',SOURCE+':app'),'CARRIER_APPLICATION_SOURCE_DRIFT')
    need(set(freeze['members'])=={'core.py','make_commands.py','test_core.py','test_commands.py','test_independent.py','README.md'},'EXACT_TOOL_MEMBERS_REQUIRED')
    for name,pin in freeze['members'].items():
        local=(HERE/name).read_bytes()
        need(H(local)==pin['sha256'] and len(local)==pin['size'],'LOCAL_FROZEN_MEMBER_DRIFT')
        need(git('show',carrier+':'+DIRECTORY+'/'+name)==local,'CARRIER_FROZEN_MEMBER_DRIFT')
    need(git('show',carrier+':'+DIRECTORY+'/tool-freeze.json')==freeze_bytes,'CARRIER_FREEZE_DRIFT')
    return (HERE/'core.py').read_bytes()


def render(carrier,phase,attempt,receipt,owner,plan=None,confirmed=False):
    validate(carrier,phase,attempt,receipt,owner,plan,confirmed)
    body=reviewed_core(carrier)
    need(0<len(body)<=65536,'BOUNDED_REVIEWED_CORE_REQUIRED')
    arguments=(phase,attempt,receipt,owner,plan,confirmed)
    code=f'''import hashlib,json,os,re,resource,socket,sys,types,urllib.request
sys.dont_write_bytecode=True
os.umask(0o077)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
def need(ok,code):
 if not ok:raise RuntimeError(code)
try:
 need(os.geteuid()==0 and socket.gethostname()=={HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):raise RuntimeError('CARRIER_REDIRECT_REJECTED')
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
 url='https://raw.githubusercontent.com/billy285/t24-crm/{carrier}/{DIRECTORY}/core.py'
 request=urllib.request.Request(url,headers={{'Accept':'application/octet-stream'}})
 with opener.open(request,timeout=20) as response:
  need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED')
  blob=response.read({len(body)+1})
 need(len(blob)=={len(body)} and hashlib.sha256(blob).hexdigest()=={H(body)!r},'EXACT_CORE_BYTES_REQUIRED')
 module=types.ModuleType('_scheduler_activation_frozen');module.__file__='<reviewed-scheduler-config-core>';module.__tool_sha256__={H(body)!r}
 sys.modules[module.__name__]=module
 exec(compile(blob,module.__file__,'exec'),module.__dict__)
 result=module.dispatch(*{arguments!r})
 print(json.dumps(result,sort_keys=True))
except BaseException as error:
 value=str(error)
 code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'SCHEDULER_CONFIG_REJECTED'
 print(json.dumps({{'stage':'SCHEDULER_CONFIG_REJECTED','code':code}}));sys.exit(1)
'''
    command="#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'PY'\n"+code+"PY\n"
    need(len(command.encode())<8000 and len(__import__('base64').b64encode(command.encode()))<16000,'SMALL_COMMAND_LIMIT_REQUIRED')
    return command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carrier',required=True);parser.add_argument('--phase',choices=['plan','activate','rollback'],required=True)
    parser.add_argument('--attempt',required=True);parser.add_argument('--deployed-sha',required=True)
    parser.add_argument('--owner-id',type=int,required=True);parser.add_argument('--plan-sha');parser.add_argument('--confirmed',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();text=render(args.carrier,args.phase,args.attempt,args.deployed_sha,args.owner_id,args.plan_sha,args.confirmed)
    fd=os.open(args.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)
    print(json.dumps({'phase':args.phase,'command_sha256':H(text.encode()),'size':len(text.encode()),'carrier':args.carrier,'executed':False},sort_keys=True))


if __name__=='__main__':main()
