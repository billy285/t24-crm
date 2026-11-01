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
 release=Path('/opt/t24-crm/releases/media-meta-monthly-5fd379d625d6-20261102');files={'release.py': ('release.py', 'b11362093b66d5bbefc62d0907f8217f389735b7ffa5da7d091ad4e132bc2247', 47746), 'preflight.py': ('preflight.py', '4ccf6f34fcf117b7477204bdfd1e5cdd1ef2a981bb6e545ac1b695768386687a', 10054), 'artifacts/manifest.json': ('manifest.json', '7a94c774a72a8402559b97d49e3693c8e7a6e72b20d45da10b4389b6ef5e3abc', 148594), 'artifacts/payload.tar.gz': ('payload.tar.gz', '55a2d2e5c6447c15cc33f83bb1a9af69f0bcb14f39bca5fa821d707f94b7b704', 2342050)};carrier='7d850032243ffec7f19f6263b421ca8ccbae075d'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-meta-monthly-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-meta-monthly-5fd379d625d6-20261102', '--manifest-sha256', '7a94c774a72a8402559b97d49e3693c8e7a6e72b20d45da10b4389b6ef5e3abc', '--payload-sha256', '55a2d2e5c6447c15cc33f83bb1a9af69f0bcb14f39bca5fa821d707f94b7b704', '--preflight', '/opt/t24-crm/releases/media-meta-monthly-preflight-6199dc87be59.json', '--preflight-sha256', '6199dc87be59bb86693f2e1b0a06278624b1faac112db5598e43aee78464a7d2']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_META_MONTHLY_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_META_MONTHLY_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
