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
 release=Path('/opt/t24-crm/releases/meta-operations-read-polish-1db2a91e6d9b-20261101');files={'release.py': ('release.py', '5f0d006aa0a469863b05aa01d3a497ef11a85655ced8f92f61d68d0495a50ad4', 30137), 'preflight.py': ('preflight.py', '6e12f110a6cf02172e41cdb91305fb2dc2c5b80fb4e64b545ccf7829556d0814', 9189), 'artifacts/manifest.json': ('manifest.json', '9c2a7b7075f373fb75aa53bc7a5d09632d46ff373dd9430d479f347465e27dbc', 138941), 'artifacts/payload.tar.gz': ('payload.tar.gz', 'bd3039b962fd7fc515762cb9e59422ea864142dcaa5e824db2c61dd533aa9f91', 2194129)};carrier='68ca98d6ff519ea7f57fc5117c1d6de47f3c3c1c'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/meta-operations-read-polish-20261101/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/meta-operations-read-polish-1db2a91e6d9b-20261101', '--manifest-sha256', '9c2a7b7075f373fb75aa53bc7a5d09632d46ff373dd9430d479f347465e27dbc', '--payload-sha256', 'bd3039b962fd7fc515762cb9e59422ea864142dcaa5e824db2c61dd533aa9f91', '--preflight', '/opt/t24-crm/releases/meta-operations-read-polish-preflight-4792c2350a25.json', '--preflight-sha256', '4792c2350a251e545ec2da15fb95d24dc2261fab002f2a63f5f5b76e974f8088']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_OPERATIONS_READ_POLISH_PREPARE_REJECTED'
 print(json.dumps({'stage':'META_OPERATIONS_READ_POLISH_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
