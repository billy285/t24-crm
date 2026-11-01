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
 release=Path('/opt/t24-crm/releases/media-asset-studio-f595f3acfb5b-20261101');files={'release.py': ('release.py', '334d6bb4b5a45538d019a03df19b0cd6b2d49671969b1dd7ea288c06f0976108', 53628), 'preflight.py': ('preflight.py', '33e3ced927bc7fd872d5f8b1395ec46f14db48ebb4c8ac4e8199fc067b5b88a9', 20951), 'renderer_canary.py': ('renderer_canary.py', 'cf8961248786c816055ba62497b76e9baa515f586522903b4cbeb1bce9e04f15', 18546), 'artifacts/manifest.json': ('manifest.json', '2c526c73ec63ba59603fe304956c617f936ed53390c461890e959d98d413a504', 146426), 'artifacts/payload.tar.gz': ('payload.tar.gz', '006c469c89b50217a253139c05f21a289386b521915c29bad3117238ca1afc15', 2263273)};carrier='3056343e71487923e53afc5e1d0488a1c87e2628'
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/deployments/media-asset-studio-20261101/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')};sys.argv=[str(release/'release.py'),'--phase','prepare',*['--release', '/opt/t24-crm/releases/media-asset-studio-f595f3acfb5b-20261101', '--manifest-sha256', '2c526c73ec63ba59603fe304956c617f936ed53390c461890e959d98d413a504', '--payload-sha256', '006c469c89b50217a253139c05f21a289386b521915c29bad3117238ca1afc15', '--preflight', '/opt/t24-crm/releases/media-asset-studio-preflight-bed4a64393ad.json', '--preflight-sha256', 'bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2']]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_ASSET_STUDIO_PREPARE_REJECTED'
 print(json.dumps({'stage':'MEDIA_ASSET_STUDIO_PREPARE_REJECTED','code':code}));sys.exit(1)
WORKFLOW
