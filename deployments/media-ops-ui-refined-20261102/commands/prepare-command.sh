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
 release=Path('/opt/t24-crm/releases/media-ops-ui-refined-835be7a06d61-20261102');files={'release.py': ('release.py', '6df39ea24eefc3e607bc8d55d9a125d2ef15901d1093e4044cdfef0b37487403', 21433), 'preflight.py': ('preflight.py', 'd75c6008ea00ac190c61c3b58d4a0cc7b843b688d03001b7b5a77ad8f2ec3c77', 9007), 'artifacts/manifest.json': ('manifest.json', 'd5f60508fc44627facd81702eff2605363d4d54cc5c75a24a0a42a0824373e9d', 151412), 'artifacts/payload.tar.gz': ('payload.tar.gz', 'fef3fc7d8646324d206e39ebecec7e159d9a1b02e98ed392cfe1a46c5e55a19b', 2292500)};carrier='3c132016e231e89cd3e8ada4b0bca6b1d3ce0fa5'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-ops-ui-refined-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-ops-ui-refined-835be7a06d61-20261102', '--manifest-sha256', 'd5f60508fc44627facd81702eff2605363d4d54cc5c75a24a0a42a0824373e9d', '--payload-sha256', 'fef3fc7d8646324d206e39ebecec7e159d9a1b02e98ed392cfe1a46c5e55a19b', '--preflight', '/opt/t24-crm/releases/media-ops-ui-refined-baseline-338bef135632.json', '--preflight-sha256', '338bef1356329348180bcab4648921687047d4bf464ece3f38cdf46fec7d0c33']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_UI_REFINED_STATIC_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_UI_REFINED_STATIC_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
