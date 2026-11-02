#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'ATWRITE'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('CONTROLLER_REDIRECT_REJECTED')
try:
 os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0));sys.dont_write_bytecode=True
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED');path=Path('/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102/at_write_release.py')
 for parent in path.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_CONTROLLER_PARENT_REQUIRED')
 if not path.exists():
  need('recover'=='activate','EXISTING_REVIEWED_CONTROLLER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/904603fcf809ed7cc27bd20ee2c68a64f0bb9c7a/deployments/media-automation-20261102/at_write_release.py';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CONTROLLER_RESPONSE_REQUIRED');body=response.read(20488)
  need(len(body)==20487 and hashlib.sha256(body).hexdigest()=='8727edc4ae5ef1a99ef1276f7f337412ec1de67526d3eeb5a5baf9664853cd78','EXACT_CONTROLLER_CARRIER_BYTES_REQUIRED');fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT600_CONTROLLER_REQUIRED');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(row.st_dev,row.st_ino),'CONTROLLER_OPEN_DRIFT');body=stream.read(20488)
 need(len(body)==20487 and hashlib.sha256(body).hexdigest()=='8727edc4ae5ef1a99ef1276f7f337412ec1de67526d3eeb5a5baf9664853cd78','EXACT_REVIEWED_CONTROLLER_REQUIRED');sys.argv=[str(path),'--phase','recover'];namespace={'__name__':'reviewed_at_write_controller','__file__':str(path)};exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_AT_WRITE_COMMAND_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_AT_WRITE_COMMAND_REJECTED','code':code,'database_restored':False}));sys.exit(1)
ATWRITE
