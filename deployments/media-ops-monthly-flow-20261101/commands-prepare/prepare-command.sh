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
 release=Path('/opt/t24-crm/releases/media-ops-monthly-flow-d39337fccfd6-20261101');files={'release.py': ('release.py', 'd5efcfecb79859e595dec70a0e901abb1c5e86d52ba300a909dd73e44bfd24c7', 42527), 'preflight.py': ('preflight.py', '510e19de4f6d7674e9f790b960dd7ae364d58d7ee5a1207870c9efb69a3a6a9a', 9456), 'artifacts/manifest.json': ('manifest.json', 'd0953971efc1715dc0d68596e60e682e6c3748d8ccdbc10b5b393f044fdb0dc4', 144802), 'artifacts/payload.tar.gz': ('payload.tar.gz', '3c57bc3a60082031c563f7f67dfab9d8da8c99989206418829aa4ecea535fd05', 2275085)};carrier='78764a3fab9e0b905d4b978533bb99f92c8b554e'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-ops-monthly-flow-20261101/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-ops-monthly-flow-d39337fccfd6-20261101', '--manifest-sha256', 'd0953971efc1715dc0d68596e60e682e6c3748d8ccdbc10b5b393f044fdb0dc4', '--payload-sha256', '3c57bc3a60082031c563f7f67dfab9d8da8c99989206418829aa4ecea535fd05', '--preflight', '/opt/t24-crm/releases/media-ops-monthly-flow-preflight-42bc79e1b704.json', '--preflight-sha256', '42bc79e1b7041e3b376ca94ab8bef01d6dc6224e151821958cf48225f90faaaf']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MONTHLY_FLOW_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MONTHLY_FLOW_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
