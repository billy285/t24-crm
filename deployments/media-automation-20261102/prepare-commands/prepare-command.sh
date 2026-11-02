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
 release=Path('/opt/t24-crm/releases/media-automation-53d66ebb6c69-20261102');files={'release.py': ('release.py', '9c7a0fb049625e9550ff38a405c0f69389555a988c01191e87e7af38a61279ec', 42813), 'preflight.py': ('preflight.py', '57deb06c6c9ebd11336cf9408887f36754ba2246d294faa5cbe38896a56f99ce', 9665), 'artifacts/manifest.json': ('manifest.json', '65fdf21e9d88273ee558354428346882a1b869fa4df857184e95430a7edadcd3', 151908), 'artifacts/payload.tar.gz': ('payload.tar.gz', '76eec467ac5c43d54b27dfdd9fbaa99bf1bd5728816d0e0481f8cf6e016010fc', 2310293)};carrier='dcfde534e1040a75a8a63826e347ed6f1e4257a4'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-automation-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-automation-53d66ebb6c69-20261102', '--manifest-sha256', '65fdf21e9d88273ee558354428346882a1b869fa4df857184e95430a7edadcd3', '--payload-sha256', '76eec467ac5c43d54b27dfdd9fbaa99bf1bd5728816d0e0481f8cf6e016010fc', '--preflight', '/opt/t24-crm/releases/media-automation-preflight-ecc7ae9cf9df.json', '--preflight-sha256', 'ecc7ae9cf9dfbdff68306b928b9b3a8f0ad98c90e5785611a061730f78a8beda']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_AUTOMATION_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
