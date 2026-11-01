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
 release=Path('/opt/t24-crm/releases/google-business-onboarding-8b429dad8a2f-20261102');files={'release.py': ('release.py', 'c07e2041379e5064d50b58d10a93717f6bda376737c4691ac3f7ce1cad6bc01a', 58002), 'preflight.py': ('preflight.py', '9e21360af95953adf9f705c9add9a968c381149e0a57038ac976f9b8fa34dee3', 14663), 'artifacts/manifest.json': ('manifest.json', '3c714aba0a597b1c46d66d8979bf43ec6464d0d5ff9c219dd0e47dd0ba816ad0', 147923), 'artifacts/payload.tar.gz': ('payload.tar.gz', '61cdb231e54302f44a13c59c42ee488f97e892c45bfbee50c2cfcced72db4bb1', 2283505)};carrier='6a2f0d1a5607b6c2edc8ff74061f3fd03805efae'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/google-business-onboarding-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/google-business-onboarding-8b429dad8a2f-20261102', '--manifest-sha256', '3c714aba0a597b1c46d66d8979bf43ec6464d0d5ff9c219dd0e47dd0ba816ad0', '--payload-sha256', '61cdb231e54302f44a13c59c42ee488f97e892c45bfbee50c2cfcced72db4bb1', '--preflight', '/opt/t24-crm/releases/google-business-onboarding-preflight-2b1a9dde5020.json', '--preflight-sha256', '2b1a9dde5020023ef33136b45bc54384745aeed30ab5f2c2e3312a59a8ebd485']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'GOOGLE_ONBOARDING_PREPARE_REJECTED'
 print(json.dumps({'stage':'GOOGLE_ONBOARDING_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
