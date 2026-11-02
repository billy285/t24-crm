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
 release=Path('/opt/t24-crm/releases/media-navigation-sticky-68fa8589101f-20261102');files={'release.py': ('release.py', 'eba0044e3ab176be9cd7235da48cb41d67d2940c617e226f30c80d6eeb756181', 19546), 'preflight.py': ('preflight.py', 'd0804c7a35074f7e71206ade76b8b428021e366da428c4fb151c1bdc7fb812ff', 8844), 'artifacts/manifest.json': ('manifest.json', 'b4139c1fb240c7a6d1bfe913be1b78aabba3457c1fa9543304dbe29b3dade0bf', 150636), 'artifacts/payload.tar.gz': ('payload.tar.gz', '7b5b12340dcedcaf52260db4296e15e75c6043d7a36f028389ed752ff747c73f', 2288125)};carrier='928f517be094541434594212ad4a5ca3d5044ed0'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-navigation-sticky-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-navigation-sticky-68fa8589101f-20261102', '--manifest-sha256', 'b4139c1fb240c7a6d1bfe913be1b78aabba3457c1fa9543304dbe29b3dade0bf', '--payload-sha256', '7b5b12340dcedcaf52260db4296e15e75c6043d7a36f028389ed752ff747c73f', '--preflight', '/opt/t24-crm/releases/media-navigation-sticky-baseline-6c8dcf5954a5.json', '--preflight-sha256', '6c8dcf5954a5ccac79b323dc40a67e001034e232d27505a55d101c451a103216']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_NAVIGATION_STICKY_STATIC_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_NAVIGATION_STICKY_STATIC_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
