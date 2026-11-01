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
 release=Path('/opt/t24-crm/releases/media-meta-monthly-static-eec3d1d02a97-20261102');files={'release.py': ('release.py', 'cd277633fd751576d85ec8d9bd49685df7e4bb98ddfffebbf8ceae508d3e4284', 19681), 'preflight.py': ('preflight.py', '8161ec8181fdc3bbfbed1f0063d01890618ee24b94fc6c19c3329d90cad3fa64', 10077), 'artifacts/manifest.json': ('manifest.json', 'ef228b776044f74651d8c397283b70ea8eaf3a5443a829eb11fe5048ce52c632', 147563), 'artifacts/payload.tar.gz': ('payload.tar.gz', '8a3a4b1be14c2d508a9c57aef3206e52a4a1008abaa750f65fce0c940e71601e', 2268630)};carrier='7d3f9e1e762099e3d5db1d15e545ba87f985a925'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-meta-monthly-static-20261102/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-meta-monthly-static-eec3d1d02a97-20261102', '--manifest-sha256', 'ef228b776044f74651d8c397283b70ea8eaf3a5443a829eb11fe5048ce52c632', '--payload-sha256', '8a3a4b1be14c2d508a9c57aef3206e52a4a1008abaa750f65fce0c940e71601e', '--preflight', '/opt/t24-crm/releases/media-meta-monthly-static-preflight-78bb1249abca.json', '--preflight-sha256', '78bb1249abca9506a9158c88fcbc31edf36c0eef6926c07ddc07f6235e0a9143']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_META_MONTHLY_UI_STATIC_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_META_MONTHLY_UI_STATIC_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
