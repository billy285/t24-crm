#!/usr/bin/env python3
"""Generate exact immutable acquisition and reviewed activation commands; never execute."""
import argparse,base64,hashlib,json,re,zlib
from pathlib import Path
DIRECTORY='deployments/stripe-history-charge-id-compat-20261018'
H=lambda body:hashlib.sha256(body).hexdigest()
def receipt_installer(path,body,expected):
 encoded=base64.b64encode(zlib.compress(body,9)).decode()
 return f'''#!/bin/bash
set -eu
sudo python3 -B - <<'PY'
import base64,hashlib,json,os,re,socket,stat,sys,zlib
from pathlib import Path
def need(ok,code):
 if not ok:raise RuntimeError(code)
try:
 sys.dont_write_bytecode=True;os.umask(0o077)
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 target=Path({path!r});expected={expected!r}
 need(target.parent==Path('/opt/t24-crm/releases') and target.resolve()==target,'EXACT_PROOF_PATH_REQUIRED')
 for parent in target.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 body=zlib.decompress(base64.b64decode({encoded!r}));need(hashlib.sha256(body).hexdigest()==expected,'PREFLIGHT_BODY_HASH_DRIFT')
 if target.exists() or target.is_symlink():
  info=target.lstat();need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'PROTECTED_PROOF_FILE_REQUIRED')
  fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as stream:
   opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'PROOF_FILE_CHANGED');actual=stream.read(len(body)+1)
  need(hashlib.sha256(actual).hexdigest()==expected,'EXISTING_PROOF_HASH_DRIFT')
 else:
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
  fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 print(json.dumps({{'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_PREFLIGHT_INSTALLED','sha256':expected,'database_modified':False,'configuration_modified':False}}))
except BaseException as error:
 code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_PREFLIGHT_INSTALL_REJECTED','code':code}}));sys.exit(1)
PY
'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--carrier',required=True);parser.add_argument('--out',type=Path,required=True)
 parser.add_argument('--preflight',required=True)
 parser.add_argument('--preflight-sha256',required=True)
 parser.add_argument('--preflight-receipt',type=Path,required=True)
 parser.add_argument('--prepared-receipt',type=Path);a=parser.parse_args()
 if not re.fullmatch('[a-f0-9]{40}',a.carrier) or not re.fullmatch('[a-f0-9]{64}',a.preflight_sha256) or not re.fullmatch('/opt/t24-crm/releases/[a-zA-Z0-9_.-]+\\.json',a.preflight):raise RuntimeError('EXACT_CARRIER_AND_PREFLIGHT_REQUIRED')
 proof=a.preflight_receipt.read_bytes()
 if len(proof)>262144 or H(proof)!=a.preflight_sha256:raise RuntimeError('EXACT_PREFLIGHT_RECEIPT_REQUIRED')
 directory=Path(DIRECTORY);manifest=json.loads((directory/'artifacts/manifest.json').read_bytes());source=manifest['source_sha'];version=manifest['frontend_version']
 if not re.fullmatch('[a-f0-9]{40}',source) or not re.fullmatch('[a-f0-9]{12}',version):raise RuntimeError('FROZEN_SOURCE_REQUIRED')
 release='/opt/t24-crm/releases/stripe-history-charge-id-compat-'+source[:12]+'-20261018'
 files={name:(target,H((directory/name).read_bytes()),len((directory/name).read_bytes())) for name,target in [('release.py','release.py'),('artifacts/manifest.json','manifest.json'),('artifacts/payload.tar.gz','payload.tar.gz')]}
 common=['--release',release,'--manifest-sha256',files['artifacts/manifest.json'][1],'--payload-sha256',files['artifacts/payload.tar.gz'][1],'--preflight',a.preflight,'--preflight-sha256',a.preflight_sha256]
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
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 carrier={a.carrier!r};files={files!r};release=Path({release!r})
 for parent in release.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED')
 selected={{}}
 for name,(target,expected,size) in files.items():
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  with urllib.request.build_opener(NoRedirect()).open(url,timeout=60) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'CARRIER_MEMBER_HASH_DRIFT');selected[target]=body
 m=json.loads(selected['manifest.json'])
 need(m['source_sha']=={source!r} and m['frontend_version']=={version!r} and m['credentials_included'] is False and m['backend_only'] is False and m['static_transition'] is True and m['schema_revision']=='d1a5b9e7f234' and all(m['preserved'].values()),'SOURCE_SCOPE_DRIFT')
 release.mkdir(mode=0o700)
 for target,body in selected.items():
  fd=os.open(release/target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 helper=release/'release.py';body=helper.read_bytes();need(H(body)==files['release.py'][1],'HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase','prepare',*{common!r}]
 namespace={{'__name__':'pinned_service_followthrough_prepare','__file__':str(helper)}}
 exec(compile(body,str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_PREPARE_REJECTED','code':code}}));sys.exit(1)
PY
'''
 a.out.mkdir(parents=True,exist_ok=True);(a.out/'prepare-command.sh').write_text(prepare);(a.out/'prepare-command.sh').chmod(0o755)
 installer=a.out/'receipt-install-command.sh';installer.write_text(receipt_installer(a.preflight,proof,a.preflight_sha256));installer.chmod(0o755)
 pins={'carrier':a.carrier,'source':source,'version':version,'files':files,'release':release,'preflight':a.preflight,'preflight_sha256':a.preflight_sha256}
 if a.prepared_receipt:
  receipt_bytes=a.prepared_receipt.read_bytes();receipt=json.loads(receipt_bytes)
  if receipt['stage']!='STRIPE_HISTORY_CHARGE_ID_COMPAT_PREPARED_OFFLINE_VERIFIED' or receipt['source_sha']!=source or receipt['frontend_version']!=version or receipt['manifest_sha256']!=files['artifacts/manifest.json'][1] or receipt['payload_sha256']!=files['artifacts/payload.tar.gz'][1] or receipt['preflight_sha256']!=a.preflight_sha256:raise RuntimeError('PREPARED_RECEIPT_IDENTITY_DRIFT')
  review=H(receipt_bytes);pins['prepared_sha256']=review
  for phase in ('activate','recover'):
   code=f'''#!/bin/bash
set -eu
sudo python3 -B - <<'PY'
import hashlib,json,re,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True
 helper=Path({(release+'/release.py')!r});body=helper.read_bytes()
 if hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase',{phase!r},*{common!r},'--review-sha256',{review!r}]
 namespace={{'__name__':'pinned_service_followthrough_{phase}','__file__':str(helper)}}
 exec(compile(body,str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_{phase.upper()}_REJECTED','code':code}}));sys.exit(1)
PY
'''
   path=a.out/(phase+'-command.sh');path.write_text(code);path.chmod(0o755)
 (a.out/'package-pins.json').write_text(json.dumps(pins,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'commands_generated':True,'source':source,'version':version,'activation_generated':bool(a.prepared_receipt)}))
if __name__=='__main__':main()
