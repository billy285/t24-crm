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
 release=Path('/opt/t24-crm/releases/google-business-onboarding-mobile-adb948da237f-20261102');files={'release.py': ('release.py', 'fb017adf5eaa00e7c873bc26471693cb54030494631390c7a85ad24891171b0c', 18040), 'preflight.py': ('preflight.py', 'edeff00ba7088c9a04081b2e397680ce39021e1e7ce11fea974188dc7e73e416', 11327), 'artifacts/manifest.json': ('manifest.json', 'a08a1c922981b0fe0fa91436b4061e5143f6769bfd9e0e03b89f6c852444a51b', 146199), 'artifacts/payload.tar.gz': ('payload.tar.gz', 'ff601095511c4e1573c49360b4e6833f46c0aa4a15ecb5c49b98fa5e6330e9f4', 2245573)};carrier='f80b958a2cae933c10f1ec5daa7e974a67890fe2'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/google-business-onboarding-mobile-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/google-business-onboarding-mobile-adb948da237f-20261102', '--manifest-sha256', 'a08a1c922981b0fe0fa91436b4061e5143f6769bfd9e0e03b89f6c852444a51b', '--payload-sha256', 'ff601095511c4e1573c49360b4e6833f46c0aa4a15ecb5c49b98fa5e6330e9f4', '--preflight', '/opt/t24-crm/releases/google-business-onboarding-mobile-preflight-b847750a7e81.json', '--preflight-sha256', 'b847750a7e816361fa13a166f4f24e4f23a97008e108f33da486d54239bece5b']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'GOOGLE_ONBOARDING_MOBILE_STATIC_PREPARE_REJECTED'
 print(json.dumps({'stage':'GOOGLE_ONBOARDING_MOBILE_STATIC_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
