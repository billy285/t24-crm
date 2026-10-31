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
 release=Path('/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031');files={'release.py': ('release.py', 'a14f6d41eb6089e1a124c8326a27031280af4dbc9f58c5a73e797565d0135c98', 71910), 'preflight.py': ('preflight.py', 'b4f672ed78d5743027ad99dce0a95b222c3059bd8868866a8314bff7734a1483', 13574), 'artifacts/manifest.json': ('manifest.json', '9d8f26821cd42cd2816af4bcb7a1805e1b9879d103453445f0580da64002869d', 137627), 'artifacts/payload.tar.gz': ('payload.tar.gz', '2d499a18199822e807a67bf96cf4425fa36f7e6fedcfc701cabc0213c4b1948a', 2190442)};carrier='de741ea14613c489704f4c3db5db5c6e6018de3e'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/meta-business-20261031/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031', '--manifest-sha256', '9d8f26821cd42cd2816af4bcb7a1805e1b9879d103453445f0580da64002869d', '--payload-sha256', '2d499a18199822e807a67bf96cf4425fa36f7e6fedcfc701cabc0213c4b1948a', '--preflight', '/opt/t24-crm/releases/meta-business-preflight-8f4995bb3e8a.json', '--preflight-sha256', '8f4995bb3e8a100869ba01a26c59f5d8f49ba78127cd82066279539adb20f71e']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_PREPARE_REJECTED'
 print(json.dumps({'stage':'META_BUSINESS_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
