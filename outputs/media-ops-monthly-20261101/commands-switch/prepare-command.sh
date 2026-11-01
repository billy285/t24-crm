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
 release=Path('/opt/t24-crm/releases/media-ops-monthly-6ab1ded2e139-20261101');files={'release.py': ('release.py', '7619cff40c9c7fa856fa9a8318cb544382aced8a08b95c8b5fb4b0f76be9e560', 39978), 'preflight.py': ('preflight.py', 'e7df079112d11603114c4acb7dc1917b59983b25af0544c583d5a39c0686445f', 9174), 'artifacts/manifest.json': ('manifest.json', '3891c1776653d2456ea2c3c1871f70571be621dff2578556fa3101ab6821b0f4', 142126), 'artifacts/payload.tar.gz': ('payload.tar.gz', '9d19a52e6bc838870146bd81e38c682fcf8ffb1a2b802cd19a4a5cfd30bf92fa', 2230434)};carrier='c760b9c7a39c50acd239406bf6b120093303bea1'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-ops-monthly-20261101/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-ops-monthly-6ab1ded2e139-20261101', '--manifest-sha256', '3891c1776653d2456ea2c3c1871f70571be621dff2578556fa3101ab6821b0f4', '--payload-sha256', '9d19a52e6bc838870146bd81e38c682fcf8ffb1a2b802cd19a4a5cfd30bf92fa', '--preflight', '/opt/t24-crm/releases/media-ops-monthly-preflight-d2129acab278.json', '--preflight-sha256', 'd2129acab27861e9b6270a47aee2b9258f9b77f1d9a72db1cee477f962ebe9a5']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MONTHLY_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MONTHLY_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
