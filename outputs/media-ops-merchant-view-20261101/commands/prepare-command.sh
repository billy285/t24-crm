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
 release=Path('/opt/t24-crm/releases/media-ops-merchant-view-5a904dd925f0-20261101');files={'release.py': ('release.py', '485ac303342b486a589697d514ee7a1b7bb237bf23b61585d4eb32197b8398c4', 34862), 'preflight.py': ('preflight.py', 'ef93dc311c7706c8d06ca16673724cd608158f7963ea3e8899764db2fec14ac2', 9102), 'artifacts/manifest.json': ('manifest.json', '83abbc803879894490afbdc4836d19d82bd90df0580d94109619f0478a71fa8b', 139242), 'artifacts/payload.tar.gz': ('payload.tar.gz', '3bd98d9ea2ab84f81cf4f5e48399d36fba5ceec3e2bf53ffce1e308f0edae6b9', 2207594)};carrier='56c0454a105c844967c84f0b2310e0dc9295eeb6'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-ops-merchant-view-20261101/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-ops-merchant-view-5a904dd925f0-20261101', '--manifest-sha256', '83abbc803879894490afbdc4836d19d82bd90df0580d94109619f0478a71fa8b', '--payload-sha256', '3bd98d9ea2ab84f81cf4f5e48399d36fba5ceec3e2bf53ffce1e308f0edae6b9', '--preflight', '/opt/t24-crm/releases/media-ops-merchant-view-preflight-1f47d56afc3c.json', '--preflight-sha256', '1f47d56afc3c79de9b905ad5d95a0e15617a3ca53c934fb2e8a1d24327a7ead9']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MERCHANT_VIEW_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MERCHANT_VIEW_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
