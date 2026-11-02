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
 release=Path('/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102');files={'release.py': ('release.py', 'b9d954130b99802bf444fe1ce99b73ba869c21ca95d1387ebb6d124d06ea109e', 42921), 'preflight.py': ('preflight.py', '89f9685f829f96c94f1fe3c84f07b33f604948f375fc52edbb963feaadb76669', 10640), 'artifacts/manifest.json': ('manifest.json', '0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3', 152926), 'artifacts/payload.tar.gz': ('payload.tar.gz', '64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439', 2325724)};carrier='89a83ab0e0a595b29c56d7e6d4fa04553d4969f5'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-unified-settings-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102', '--manifest-sha256', '0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3', '--payload-sha256', '64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439', '--preflight', '/opt/t24-crm/releases/media-unified-settings-baseline-0dd43fefcf43.json', '--preflight-sha256', '0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_UNIFIED_SETTINGS_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_UNIFIED_SETTINGS_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
