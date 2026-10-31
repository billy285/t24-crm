"""Immutable three-tool Meta transport wrappers. Never execute a server phase."""
import argparse
import ast
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HERE=Path(__file__).resolve().parent
DIRECTORY='deployments/meta-business-activation-20261101'
TOOL_PINS={'core.py':('4df1106fd1bbcafeb895896ace72b7d285b92a955d618b11ed88ef05da108576',7395),
    'baseline.py':('0884eca1646e0891b9d2106282688bcb1fa9186807f470d8754f7f0fbf5655fb',8881),
    'transport.py':('7b87b16d709d257a5ab8e1f0cf9e16c21957e218d725ea883fee695a244bce34',7723)}
BASELINE_SHA='20be9f4367c65b7a00882dbcd789a5867d00a4bfa8a57bf611bc2b3c3ad0c823'
H=lambda body:hashlib.sha256(body).hexdigest()
spec=importlib.util.spec_from_file_location('_meta_transport_generator_public_core',HERE/'core.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


def local_bytes(path):
    row=path.lstat();c.need(path.resolve()==path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink==1,'REGULAR_CANONICAL_TRANSPORT_SOURCE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(131073)
    after=path.lstat();fields=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink)
    c.need(fields(row)==fields(opened)==fields(after) and len(body)<=131072,'TRANSPORT_SOURCE_READ_DRIFT');return body


def validate_summary(value):
    c.need(value['stage']=='META_ACTIVATION_BASELINE_CAPTURED' and value['sha256']==BASELINE_SHA and value['path']==str(c.ROOT/'baseline.json') and value['table_count']==141 and value['source_sha']==c.SOURCE_SHA and value['frontend_version']==c.FRONTEND and value['schema_revision']==c.SCHEMA_REVISION,'EXACT_ACTUAL_META_BASELINE_SUMMARY_REQUIRED')
    c.need(value['runtime']['id']==c.ORIGINAL_ID and value['runtime']['image']==c.IMAGE and value['runtime']['restart']==0 and value['meta_environment_keys_absent'] is True and value['google_scheduler_enabled'] is True and value['google_scheduler_activation_from']==c.ACTIVATION_FROM,'EXACT_DISABLED_META_ON_GOOGLE_RUNTIME_REQUIRED')
    c.need(all(value[key] is False for key in ('business_writes','credential_content_read','provider_requests','runtime_changed')),'READONLY_META_BASELINE_REQUIRED')


def generate(carrier,summary,*,transfer_id=None,ciphertext=None):
    c.pins_ready();validate_summary(summary);c.need(isinstance(carrier,str) and re.fullmatch('[a-f0-9]{40}',carrier),'EXACT_TRANSPORT_CARRIER_REQUIRED')
    git=lambda *args:subprocess.check_output(['git',*args])
    c.need(git('rev-parse',carrier+':app')==git('rev-parse',c.SOURCE_SHA+':app'),'TRANSPORT_CARRIER_APP_TREE_DRIFT')
    files={}
    for name,(sha,size) in TOOL_PINS.items():
        body=local_bytes(HERE/name);c.need(H(body)==sha and len(body)==size,'EXACT_REVIEWED_TRANSPORT_BYTES_REQUIRED')
        c.need(git('show',carrier+':'+DIRECTORY+'/'+name)==body,'EXACT_COMMITTED_TRANSPORT_MEMBER_REQUIRED');files[name]=(sha,size)
    assignments={target.id:ast.literal_eval(node.value) for node in ast.parse(local_bytes(HERE/'baseline.py')).body if isinstance(node,ast.Assign) and all(isinstance(target,ast.Name) for target in node.targets) and isinstance(node.value,ast.Constant) for target in node.targets}
    c.need(assignments.get('BASELINE_SHA')==BASELINE_SHA,'EXACT_BASELINE_CODE_PIN_REQUIRED')
    root=str(c.ROOT/'tools-transport-v1')
    install=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'META_TOOLS'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('TRANSPORT_CARRIER_REDIRECT_REJECTED')
def read(path,sha,size):
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_META_BASELINE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());body=stream.read(size+1)
 after=path.lstat();fields=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink,v.st_uid,v.st_mode)
 need(fields(row)==fields(opened)==fields(after) and len(body)<=size and H(body)==sha,'EXACT_META_BASELINE_REQUIRED');return body
def sync(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=={c.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 root=Path({root!r});files={files!r};carrier={carrier!r}
 for parent in root.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TRANSPORT_TOOL_PARENT_REQUIRED')
 need(stat.S_IMODE(root.parent.lstat().st_mode)==0o700 and not root.exists() and not root.is_symlink(),'FRESH_PROTECTED_TRANSPORT_TOOL_ROOT_REQUIRED')
 read(root.parent/'baseline.json',{BASELINE_SHA!r},1048576)
 selected={{}}
 for name,(sha,size) in files.items():
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_TRANSPORT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==sha,'EXACT_TRANSPORT_CARRIER_BYTES_REQUIRED');selected[name]=body
 root.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 receipt={{'stage':'META_TRANSPORT_TOOLS_INSTALLED','carrier':carrier,'source_sha':{c.SOURCE_SHA!r},'baseline_sha256':{BASELINE_SHA!r},'files':files}}
 body=(json.dumps(receipt,sort_keys=True,indent=2)+'\\n').encode()
 fd=os.open(root/'installed.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 sync(root);sync(root.parent)
 print(json.dumps({{'stage':'META_TRANSPORT_TOOLS_INSTALLED','tool_root':str(root),'carrier':carrier,'receipt_sha256':H(body),'runtime_changed':False,'business_writes':False,'credential_content_read':False}},sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_TRANSPORT_TOOL_INSTALL_REJECTED'
 print(json.dumps({{'stage':'META_TRANSPORT_TOOL_INSTALL_REJECTED','code':code}}));sys.exit(1)
META_TOOLS
'''
    commands={'transport-tools-install-command.sh':install}
    expected_receipt={'stage':'META_TRANSPORT_TOOLS_INSTALLED','carrier':carrier,'source_sha':c.SOURCE_SHA,'baseline_sha256':BASELINE_SHA,'files':{name:list(row) for name,row in files.items()}}
    receipt_body=(json.dumps(expected_receipt,sort_keys=True,indent=2)+'\n').encode();receipt_sha=H(receipt_body)
    phases=[('prepare',None,None)]
    if transfer_id is not None or ciphertext is not None:
        c.need(isinstance(transfer_id,str) and re.fullmatch('[a-f0-9]{32}',transfer_id),'EXACT_META_TRANSFER_ID_REQUIRED')
        try:raw=base64.b64decode(ciphertext,validate=True)
        except (ValueError,TypeError):raise c.GuardError('EXACT_META_CIPHERTEXT_REQUIRED') from None
        c.need(len(raw)==384 and base64.b64encode(raw).decode()==ciphertext,'EXACT_META_CIPHERTEXT_REQUIRED');phases.append(('install',transfer_id,ciphertext))
    for phase,key,sealed in phases:
        action="modules['transport.py'].prepare(baseline.verify)" if phase=='prepare' else "modules['transport.py'].receive(baseline.verify,"+repr(key)+","+repr(sealed)+")"
        commands['transport-'+phase+'-command.sh']=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'META_TRANSPORT'
import hashlib,json,os,re,resource,socket,stat,sys,types
from pathlib import Path
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def read(path,sha,size):
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_TRANSPORT_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(size+1)
 after=path.lstat();fields=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink,v.st_uid,v.st_mode)
 need(fields(row)==fields(opened)==fields(after) and len(body)==size and H(body)==sha,'EXACT_TRANSPORT_HELPER_REQUIRED');return body
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=={c.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 root=Path({root!r});files={files!r}
 for parent in (root,*root.parents):
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TRANSPORT_HELPER_PARENT_REQUIRED')
 need(stat.S_IMODE(root.lstat().st_mode)==0o700 and {{p.name for p in root.iterdir()}}==set(files)|{{'installed.json'}},'EXACT_TRANSPORT_TOOL_DIRECTORY_REQUIRED')
 receipt=read(root/'installed.json',{receipt_sha!r},{len(receipt_body)})
 need(json.loads(receipt)=={expected_receipt!r},'EXACT_INSTALLED_TRANSPORT_IDENTITY_REQUIRED')
 selected={{name:read(root/name,sha,size) for name,(sha,size) in files.items()}};modules={{}}
 for name,body in selected.items():
  module=types.ModuleType('core' if name=='core.py' else '_reviewed_meta_transport_'+name[:-3]);module.__file__=str(root/name)
  if name=='core.py':sys.modules['core']=module
  exec(compile(body,module.__file__,'exec'),module.__dict__);modules[name]=module
 core=modules['core.py'];baseline=modules['baseline.py'];baseline.configure(core);core.pins_ready()
 print(json.dumps({action},sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_TRANSPORT_PHASE_REJECTED'
 print(json.dumps({{'stage':'META_TRANSPORT_PHASE_REJECTED','code':code}}));sys.exit(1)
META_TRANSPORT
'''
    c.need(all(len(text.encode())<11000 for text in commands.values()),'SMALL_META_TRANSPORT_WRAPPER_REQUIRED')
    return commands,{'carrier':carrier,'source_sha':c.SOURCE_SHA,'tool_root':root,'baseline_sha256':BASELINE_SHA,'tool_files':files,'installed_receipt_sha256':receipt_sha,'transfer_id':transfer_id,'ciphertext_included':ciphertext is not None,'commands_sha256':{name:H(text.encode()) for name,text in commands.items()},'executed':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--carrier',required=True);parser.add_argument('--baseline-summary',type=Path,required=True);parser.add_argument('--transfer-id');parser.add_argument('--ciphertext');parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    commands,pins=generate(args.carrier,json.loads(local_bytes(args.baseline_summary)),transfer_id=args.transfer_id,ciphertext=args.ciphertext);args.out.mkdir(parents=True,exist_ok=True)
    for name,text in {**commands,'transport-command-pins.json':json.dumps(pins,sort_keys=True,indent=2)+'\n'}.items():
        fd=os.open(args.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
