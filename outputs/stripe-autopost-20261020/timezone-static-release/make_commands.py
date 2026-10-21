"""Generate exact immutable static acquisition; never execute server actions."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DIRECTORY='outputs/stripe-autopost-20261020/timezone-static-release'
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
 if not ok:raise RuntimeError(code)

def main():
 p=argparse.ArgumentParser();p.add_argument('--carrier',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--prepared',type=Path);a=p.parse_args()
 need(bool(re.fullmatch('[a-f0-9]{40}',a.carrier)),'EXACT_IMMUTABLE_CARRIER_REQUIRED')
 manifest=json.loads((ROOT/'artifacts/static-manifest.json').read_bytes());source=manifest['source_sha'];version=manifest['frontend_version']
 release='/opt/t24-crm/releases/stripe-auto-timezone-'+source[:12]+'-20261021'
 files={}
 for name,target in [('static_release.py','static_release.py'),('artifacts/static-manifest.json','static-manifest.json'),('artifacts/static-payload.tar.gz','static-payload.tar.gz'),('artifacts/post-pilot-baseline.json','post-pilot-baseline.json')]:
  body=(ROOT/name).read_bytes();need(subprocess.check_output(['git','show',a.carrier+':'+DIRECTORY+'/'+name])==body,'CARRIER_MEMBER_DRIFT');files[name]=(target,H(body),len(body))
 common=['--release',release,'--manifest-sha256',files['artifacts/static-manifest.json'][1],'--payload-sha256',files['artifacts/static-payload.tar.gz'][1]]
 prepare=f'''#!/bin/bash
set -eu
sudo python3 -B - <<'PY'
import hashlib,json,os,re,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
try:
 sys.dont_write_bytecode=True;os.umask(0o077)
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_SERVER_ROOT_REQUIRED')
 files={files!r};release=Path({release!r});carrier={a.carrier!r}
 for parent in release.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_STATIC_RELEASE_REQUIRED')
 selected={{}}
 for name,(target,expected,size) in files.items():
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  with urllib.request.build_opener(NoRedirect()).open(url,timeout=60) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'CARRIER_MEMBER_HASH_DRIFT');selected[target]=body
 manifest=json.loads(selected['static-manifest.json'])
 need(manifest['source_sha']=={source!r} and manifest['frontend_version']=={version!r} and manifest['static_only'] is True and manifest['backend_changes'] is False and manifest['database_changes'] is False and manifest['credentials_included'] is False,'PURE_STATIC_SCOPE_REQUIRED')
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 helper=release/'static_release.py';body=helper.read_bytes();need(H(body)==files['static_release.py'][1],'STATIC_HELPER_HASH_DRIFT')
 ns={{'__name__':'pinned_timezone_static_prepare','__file__':str(helper)}}
 sys.argv=[str(helper),'--phase','prepare',*{common!r}];exec(compile(body,str(helper),'exec'),ns);ns['main']()
except BaseException as error:
 code=str(error) if re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'STRIPE_AUTO_TIMEZONE_STATIC_PREPARE_REJECTED','code':code,'database_written':False,'services_changed':False}}));sys.exit(1)
PY
'''
 outputs={'prepare-command.sh':prepare}
 pins={'carrier':a.carrier,'source_sha':source,'frontend_version':version,'backend_source_sha':manifest['backend_source_sha'],'release':release,'files':files}
 if a.prepared:
  body=a.prepared.read_bytes();r=json.loads(body);review=H(body)
  need(r['stage']=='STRIPE_AUTO_TIMEZONE_STATIC_PREPARED' and r['source_sha']==source and r['frontend_version']==version,'EXACT_STATIC_PREPARED_SOURCE_REQUIRED')
  need(r['manifest_sha256']==files['artifacts/static-manifest.json'][1] and r['payload_sha256']==files['artifacts/static-payload.tar.gz'][1],'EXACT_STATIC_PREPARED_ARTIFACTS_REQUIRED')
  need(r['all_113_noncheckpoint_tables_unchanged'] is True and all(r[key] is False for key in ('production_database_written','services_changed','credentials_used','provider_requests')),'STATIC_PREPARED_BOUNDARY_REQUIRED')
  pins['prepared_sha256']=review
  for phase in ('activate','recover'):
   outputs[phase+'-command.sh']=f'''#!/bin/bash
set -eu
sudo python3 -B - <<'PY'
import hashlib,json,re,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True
 helper=Path({(release+'/static_release.py')!r});body=helper.read_bytes()
 if hashlib.sha256(body).hexdigest()!={files['static_release.py'][1]!r}:raise RuntimeError('STATIC_HELPER_HASH_DRIFT')
 ns={{'__name__':'pinned_timezone_static_{phase}','__file__':str(helper)}}
 sys.argv=[str(helper),'--phase',{phase!r},*{common!r},'--review-sha256',{review!r}];exec(compile(body,str(helper),'exec'),ns);ns['main']()
except BaseException as error:
 code=str(error) if re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'STRIPE_AUTO_TIMEZONE_STATIC_{phase.upper()}_REJECTED','code':code,'database_written':False,'services_changed':False}}));sys.exit(1)
PY
'''
 a.out.mkdir(parents=True,exist_ok=True)
 for name,body in outputs.items():(a.out/name).write_text(body);(a.out/name).chmod(0o600)
 (a.out/'package-pins.json').write_text(json.dumps(pins,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'commands_generated':True,'source_sha':source,'frontend_version':version,'activation_generated':bool(a.prepared)}))

if __name__=='__main__':main()
