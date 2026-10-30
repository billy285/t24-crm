"""Generate immutable-carrier wrappers; activate/recover require reviewed preparation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
DIRECTORY='deployments/media-ops-review-refresh-retry-20261031'
spec=importlib.util.spec_from_file_location('review_refresh_commands_scope',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
H=lambda value:hashlib.sha256(value).hexdigest()


def need(ok,code):
    if not ok:raise RuntimeError(code)


def generate(carrier,summary,prepared=None):
    need(re.fullmatch('[a-f0-9]{40}',carrier or ''),'EXACT_IMMUTABLE_CARRIER_REQUIRED')
    need(summary['stage']=='MEDIA_OPS_REVIEW_REFRESH_RETRY_PREFLIGHT_CAPTURED' and summary['source_sha']==r.BASE_SOURCE and summary['frontend_version']==r.BASE_FRONTEND and summary['schema_revision']==r.REVISION and summary['table_count']==129,'EXACT_PREFLIGHT_SUMMARY_REQUIRED')
    need(summary['deployed_sha256']==r.BASE_DEPLOYED_SHA and summary['scheduler_disabled'] is True and summary['gbp_feature_enabled'] is True and summary['callback_logging_protection_retained'] is True and summary['private_boundary_verified'] is True and all(summary[k] is False for k in ('credential_content_read','private_content_read','executed_business_writes')),'EXACT_READONLY_OFF_GBP_BOUNDARY_REQUIRED')
    need(summary.get('recovered_sha256')==r.RECOVERED_SHA and summary.get('host_docker_timestamp_parser_verified') is True,'EXACT_RECOVERED_HOST_PARSER_PROOF_REQUIRED')
    proof=summary['sha256'];need(re.fullmatch('[a-f0-9]{64}',proof) and summary['path']=='/opt/t24-crm/releases/media-ops-review-refresh-retry-preflight-'+proof[:12]+'.json','EXACT_PROOF_PATH_REQUIRED')
    need(subprocess.check_output(['git','rev-parse',carrier+':app'])==subprocess.check_output(['git','rev-parse',r.SOURCE_SHA+':app']),'CARRIER_APP_TREE_DRIFT')
    files={}
    for name,target in [('release.py','release.py'),('preflight.py','preflight.py'),('artifacts/manifest.json','manifest.json'),('artifacts/payload.tar.gz','payload.tar.gz')]:
        body=(HERE/name).read_bytes();need(subprocess.check_output(['git','show',carrier+':'+DIRECTORY+'/'+name])==body,'EXACT_COMMITTED_MEMBER_REQUIRED');files[name]=(target,H(body),len(body))
    manifest=json.loads((HERE/'artifacts/manifest.json').read_bytes());need(manifest['source_sha']==r.SOURCE_SHA and manifest['frontend_version']==r.FRONTEND and manifest['preflight_sha256']==proof and manifest['database_migration'] is False,'EXACT_MANIFEST_SCOPE_REQUIRED')
    release='/opt/t24-crm/releases/'+r.SCOPE+'-'+r.SOURCE_SHA[:12]+'-20261031'
    common=['--release',release,'--manifest-sha256',files['artifacts/manifest.json'][1],'--payload-sha256',files['artifacts/payload.tar.gz'][1],'--preflight',summary['path'],'--preflight-sha256',proof]
    prepare=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PYCODE'
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
  need(0<size<16777216,'EXACT_MEMBER_SIZE_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  with urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect()).open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_IMMUTABLE_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_MEMBER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={{'__name__':'reviewed_review_refresh','__file__':str(release/'release.py')}};sys.argv=[str(release/'release.py'),'--phase','prepare',*{common!r}]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'REVIEW_REFRESH_PREPARE_REJECTED'
 print(json.dumps({{'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_PREPARE_REJECTED','code':code}}));sys.exit(1)
PYCODE
'''
    outputs={'prepare-command.sh':prepare};review_sha=None
    if prepared is not None:
        need(prepared['stage']=='MEDIA_OPS_REVIEW_REFRESH_RETRY_PREPARED_OFFLINE_VERIFIED' and prepared['source_sha']==r.SOURCE_SHA and prepared['frontend_version']==r.FRONTEND and prepared['schema_revision']==r.REVISION,'EXACT_PREPARED_SCOPE_REQUIRED')
        need(prepared['manifest_sha256']==files['artifacts/manifest.json'][1] and prepared['payload_sha256']==files['artifacts/payload.tar.gz'][1] and prepared['preflight_sha256']==proof and prepared['database_migrated'] is False and prepared['provider_requests'] is False,'EXACT_PREPARED_IDENTITIES_REQUIRED')
        review_sha=prepared.get('_canonical_sha256')
        need(re.fullmatch('[a-f0-9]{64}',review_sha or ''),'EXACT_CANONICAL_PREPARED_HASH_REQUIRED')
        for phase in ('activate','recover'):
            outputs[phase+'-command.sh']=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PYCODE'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!={r.HOST!r}:raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path({release!r});path=release/'release.py';row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:body=stream.read({files['release.py'][2]+1})
 if len(body)!={files['release.py'][2]} or hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase',{phase!r},*{common!r},'--review-sha256',{review_sha!r}];namespace={{'__name__':'reviewed_review_refresh','__file__':str(path)}}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'REVIEW_REFRESH_SWITCH_REJECTED'
 print(json.dumps({{'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_SWITCH_REJECTED','code':code}}));sys.exit(1)
PYCODE
'''
    need(all(len(v.encode())<11000 for v in outputs.values()),'SMALL_WRAPPER_LIMIT_REQUIRED')
    pins={'carrier':carrier,'source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'preflight_sha256':proof,'release':release,'members':files,'prepared_sha256':review_sha,'command_sha256':{k:H(v.encode()) for k,v in outputs.items()},'executed':False}
    return outputs,pins


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--carrier',required=True);parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--prepared-receipt',type=Path);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    summary=json.loads(a.preflight_summary.read_bytes());prepared=None
    if a.prepared_receipt:
        body=a.prepared_receipt.read_bytes();prepared=json.loads(body);prepared['_canonical_sha256']=H(body)
    outputs,pins=generate(a.carrier,summary,prepared);a.out.mkdir(parents=True,exist_ok=True)
    for n,b in {**outputs,'command-pins.json':json.dumps(pins,sort_keys=True,indent=2)+'\n'}.items():
        with (a.out/n).open('x') as stream:stream.write(b)
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
