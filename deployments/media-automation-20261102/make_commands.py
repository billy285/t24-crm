"""Emit immutable carrier commands; never execute a server phase."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import stat

HERE = Path(__file__).resolve().parent
DIRECTORY = 'deployments/media-automation-20261102'
spec = importlib.util.spec_from_file_location('google_onboarding_priority_commands_scope', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()


def local_bytes(path,maximum=16777216):
    path=Path(path);before=path.lstat()
    r.need(path.resolve()==path.absolute() and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=maximum,'EXACT_LOCAL_REGULAR_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1);after=os.fstat(stream.fileno())
    identity=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    r.need(identity(before)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==before.st_size<=maximum,'UNCHANGED_BOUNDED_LOCAL_BYTES_REQUIRED');return body


def strict_json(body):
    def pairs(items):
        result = {}
        for key,value in items:
            r.need(key not in result, 'DUPLICATE_RECEIPT_KEY_REJECTED'); result[key] = value
        return result
    def constant(value): raise RuntimeError('NONFINITE_RECEIPT_VALUE_REJECTED')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def canonical_prepared(body):
    """Pin server prepared.json, not a transport envelope containing its SHA."""
    value = strict_json(body)
    r.need(isinstance(value,dict) and '_canonical_sha256' not in value, 'CANONICAL_RECEIPT_OBJECT_REQUIRED')
    marker = value.pop('receipt_sha256', None)
    canonical = r.encoded(value); sha = H(canonical)
    if marker is not None:
        r.need(isinstance(marker,str) and re.fullmatch('[a-f0-9]{64}',marker) and marker == sha, 'ENVELOPE_RECEIPT_HASH_MISMATCH')
    else:
        r.need(body == canonical, 'EXACT_CANONICAL_SERVER_RECEIPT_REQUIRED')
    value['_canonical_sha256'] = sha
    return value


def generate(carrier, summary, prepared=None):
    r.pins_ready()
    r.need(summary['stage']=='MEDIA_AUTOMATION_PREFLIGHT_CAPTURED' and summary['sha256']==r.PREFLIGHT_SHA and summary['path']=='/opt/t24-crm/releases/media-automation-preflight-'+r.PREFLIGHT_SHA[:12]+'.json','EXACT_FRESH_STATIC_PREFLIGHT_REQUIRED')
    r.need(re.fullmatch('[a-f0-9]{40}',carrier or ''),'EXACT_IMMUTABLE_CARRIER_REQUIRED')
    git=lambda *args:subprocess.check_output(['git',*args])
    r.need(git('rev-parse',carrier+':app')==git('rev-parse',r.SOURCE_SHA+':app'),'CARRIER_APPLICATION_TREE_DRIFT')
    files={}
    for name,target in [('release.py','release.py'),('preflight.py','preflight.py'),('artifacts/manifest.json','manifest.json'),('artifacts/payload.tar.gz','payload.tar.gz')]:
        body=local_bytes(HERE/name)
        # Local source symlinks/hardlinks are rejected before Git comparison.
        row=(HERE/name).lstat();r.need((HERE/name).resolve()==(HERE/name).absolute() and not (HERE/name).is_symlink() and row.st_nlink==1,'EXACT_LOCAL_MEMBER_REQUIRED')
        r.need(git('show',carrier+':'+DIRECTORY+'/'+name)==body,'EXACT_COMMITTED_MEMBER_REQUIRED');files[name]=(target,H(body),len(body))
    r.need(files['preflight.py'][1]==r.PREFLIGHT_CODE_SHA,'EXACT_REVIEWED_PREFLIGHT_CODE_REQUIRED')
    manifest=strict_json((HERE/'artifacts/manifest.json').read_bytes());r.validate_manifest(manifest,files['artifacts/payload.tar.gz'][1])
    release = '/opt/t24-crm/releases/' + r.SCOPE + '-' + r.SOURCE_SHA[:12] + '-20261102'
    common = ['--release', release, '--manifest-sha256', files['artifacts/manifest.json'][1], '--payload-sha256', files['artifacts/payload.tar.gz'][1], '--preflight', summary['path'], '--preflight-sha256', summary['sha256']]
    prepare = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('CARRIER_REDIRECT_REJECTED')
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=={r.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 release=Path({release!r});files={files!r};carrier={carrier!r}
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={{}}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={{'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')}};sys.argv=[str(release/'release.py'),'--phase','prepare',*{common!r}]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_AUTOMATION_PREPARE_REJECTED'
 print(json.dumps({{'stage':'MEDIA_AUTOMATION_PREPARE_REJECTED','code':code}}));sys.exit(1)
WORKFLOW
'''
    outputs = {'prepare-command.sh': prepare}; review_sha = None
    if prepared is not None:
        r.validate_prepared(prepared, files['artifacts/manifest.json'][1], files['artifacts/payload.tar.gz'][1], summary['sha256'])
        review_sha = prepared.get('_canonical_sha256'); r.need(re.fullmatch('[a-f0-9]{64}', review_sha or ''), 'EXACT_CANONICAL_PREPARED_HASH_REQUIRED')
        for phase in ('activate', 'recover'):
            outputs[phase + '-command.sh'] = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!={r.HOST!r}:raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path({release!r});path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read({files['release.py'][2] + 1})
 if len(body)!={files['release.py'][2]} or hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase',{phase!r},*{common!r},'--review-sha256',{review_sha!r}];namespace={{'__name__':'reviewed_workflow_release','__file__':str(path)}}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_AUTOMATION_SWITCH_REJECTED'
 print(json.dumps({{'stage':'MEDIA_AUTOMATION_SWITCH_REJECTED','code':code}}));sys.exit(1)
WORKFLOW
'''
    r.need(all(len(command.encode()) < 11000 for command in outputs.values()), 'SMALL_WRAPPER_LIMIT_REQUIRED')
    return outputs, {'carrier': carrier, 'source_sha': r.SOURCE_SHA, 'frontend_version': r.FRONTEND, 'preflight_sha256': summary['sha256'], 'release': release, 'members': files, 'prepared_sha256': review_sha, 'command_sha256': {name: H(command.encode()) for name, command in outputs.items()}, 'executed': False}

def generate_worker(carrier,summary,prepared,deployed,worker_prepared=None):
    _,pins=generate(carrier,summary,prepared);release=pins['release'];members=pins['members'];sha=deployed.get('_canonical_sha256');r.need(re.fullmatch('[a-f0-9]{64}',sha or '') and deployed['stage']=='MEDIA_AUTOMATION_DEPLOYED' and deployed['source_sha']==r.SOURCE_SHA and deployed['schema_revision']==r.NEW_REVISION and deployed['prepared_sha256']==prepared['_canonical_sha256'] and deployed['three_new_tables_empty'] is True and deployed['automation_worker_enabled'] is False,'EXACT_DEPLOYED_DEFAULT_OFF_RECEIPT_REQUIRED')
    body=local_bytes(HERE/'worker_enable.py');committed=subprocess.check_output(['git','show',carrier+':'+DIRECTORY+'/worker_enable.py']);r.need(committed==body,'EXACT_COMMITTED_WORKER_HELPER_REQUIRED');helper=H(body)
    common=['--release',release,'--main-release-sha256',members['release.py'][1],'--main-prepared-sha256',prepared['_canonical_sha256'],'--main-deployed-sha256',sha,'--manifest-sha256',members['artifacts/manifest.json'][1],'--payload-sha256',members['artifacts/payload.tar.gz'][1],'--preflight',summary['path'],'--preflight-sha256',summary['sha256']]
    phases=['prepare'];review=None
    if worker_prepared is not None:
        r.need(worker_prepared['stage']=='MEDIA_AUTOMATION_WORKER_PREPARED' and worker_prepared['source_sha']==r.SOURCE_SHA and worker_prepared['main_release_sha256']==members['release.py'][1] and worker_prepared['main_deployed_sha256']==sha and worker_prepared['main_prepared_sha256']==prepared['_canonical_sha256'] and worker_prepared['new_runtime_entry']=='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=true' and worker_prepared['three_tables_empty'] is True,'EXACT_REVIEWED_ZERO_POLICY_WORKER_SCOPE_REQUIRED');review=worker_prepared.get('_canonical_sha256');r.need(re.fullmatch('[a-f0-9]{64}',review or ''),'EXACT_CANONICAL_WORKER_PREPARED_HASH_REQUIRED');phases=['activate','recover']
    outputs={}
    for phase in phases:
        argv=['--phase',phase,*common]+(['--review-sha256',review] if review else [])
        outputs['worker-'+phase+'-command.sh']=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKER'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('WORKER_CARRIER_REDIRECT_REJECTED')
try:
 os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0));sys.dont_write_bytecode=True
 need(os.geteuid()==0 and socket.gethostname()=={r.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 path=Path({release!r})/'worker_enable.py'
 for parent in path.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_WORKER_PARENT_REQUIRED')
 if not path.exists():
  need({phase!r}=='prepare','REVIEWED_WORKER_HELPER_MUST_ALREADY_EXIST');url='https://raw.githubusercontent.com/billy285/t24-crm/{carrier}/{DIRECTORY}/worker_enable.py';opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_WORKER_CARRIER_RESPONSE_REQUIRED');body=response.read({len(body)+1})
  need(len(body)=={len(body)} and hashlib.sha256(body).hexdigest()=={helper!r},'EXACT_WORKER_CARRIER_BYTES_REQUIRED')
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_WORKER_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(row.st_dev,row.st_ino),'WORKER_HELPER_OPEN_DRIFT');body=stream.read({len(body)+1})
 need(len(body)=={len(body)} and hashlib.sha256(body).hexdigest()=={helper!r},'EXACT_REVIEWED_WORKER_HELPER_REQUIRED')
 sys.argv=[str(path),*{argv!r}];namespace={{'__name__':'reviewed_worker_enable','__file__':str(path)}};exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_AUTOMATION_WORKER_COMMAND_REJECTED'
 print(json.dumps({{'stage':'MEDIA_AUTOMATION_WORKER_COMMAND_REJECTED','code':code,'database_restored':False}}));sys.exit(1)
WORKER
'''
    r.need(all(len(x.encode())<11000 for x in outputs.values()),'BOUNDED_WORKER_WRAPPER_REQUIRED');return outputs,{'carrier':carrier,'source_sha':r.SOURCE_SHA,'main_deployed_sha256':sha,'worker_prepared_sha256':review,'worker_helper_sha256':helper,'only_runtime_entry_added':'T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=true','policies_created':False,'executed':False,'command_sha256':{n:H(v.encode()) for n,v in outputs.items()}}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--carrier', required=True); parser.add_argument('--preflight-summary', type=Path, required=True); parser.add_argument('--prepared-receipt', type=Path); parser.add_argument('--out', type=Path, required=True);parser.add_argument('--worker-deployed-receipt',type=Path);parser.add_argument('--worker-prepared-receipt',type=Path);args = parser.parse_args()
    summary = strict_json(local_bytes(args.preflight_summary, 1048576)); prepared = None
    if args.prepared_receipt:
        prepared = canonical_prepared(local_bytes(args.prepared_receipt, 1048576))
    if args.worker_deployed_receipt:
        r.need(prepared is not None,'MAIN_PREPARED_RECEIPT_REQUIRED');deployed=canonical_prepared(local_bytes(args.worker_deployed_receipt,1048576));worker=canonical_prepared(local_bytes(args.worker_prepared_receipt,1048576)) if args.worker_prepared_receipt else None;commands,pins=generate_worker(args.carrier,summary,prepared,deployed,worker)
    else:
        r.need(args.worker_prepared_receipt is None,'WORKER_DEPLOYED_RECEIPT_REQUIRED');commands,pins=generate(args.carrier, summary, prepared)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in {**commands, 'command-pins.json': json.dumps(pins, sort_keys=True, indent=2) + '\n'}.items():
        fd = os.open(args.out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(text); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(pins, sort_keys=True))


if __name__ == '__main__': main()
