#!/bin/bash
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
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-operator-queue-e0f39295a912-20261102');files={'release.py': ('release.py', 'cd69c5c551cc270643e0b1f193539bf9e20b77d4e6cca32c8fcc8b09337cbfcf', 43190), 'preflight.py': ('preflight.py', 'a55b0f01f1d2bd098ab0efe9a1762e272babdf835e52aef9d3ae314ce911423c', 10097), 'artifacts/manifest.json': ('manifest.json', '398c1d7fbd83200dece698d0c46a9185540fe26d09af9ec100f2ff26102a4c6a', 147437), 'artifacts/payload.tar.gz': ('payload.tar.gz', '296554f0a426dd8e190d245d98da6441d9e743f4a79a33a48e7690307c563916', 2301500)};carrier='7cf80213e6eebb8f2b39ad9839797b122f1ae21a'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-operator-queue-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-operator-queue-e0f39295a912-20261102', '--manifest-sha256', '398c1d7fbd83200dece698d0c46a9185540fe26d09af9ec100f2ff26102a4c6a', '--payload-sha256', '296554f0a426dd8e190d245d98da6441d9e743f4a79a33a48e7690307c563916', '--preflight', '/opt/t24-crm/releases/media-operator-queue-preflight-8407a1e8596f.json', '--preflight-sha256', '8407a1e8596fb15b9937ae168cbbad5374e54bd653522a23d9360e2eeec3a508']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPERATOR_QUEUE_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPERATOR_QUEUE_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
