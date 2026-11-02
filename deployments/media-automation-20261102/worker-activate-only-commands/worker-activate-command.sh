#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKER'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('WORKER_CARRIER_REDIRECT_REJECTED')
try:
 os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0));sys.dont_write_bytecode=True
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 path=Path('/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102')/'worker_enable.py'
 for parent in path.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_WORKER_PARENT_REQUIRED')
 if not path.exists():
  need('activate'=='prepare','REVIEWED_WORKER_HELPER_MUST_ALREADY_EXIST');url='https://raw.githubusercontent.com/billy285/t24-crm/904603fcf809ed7cc27bd20ee2c68a64f0bb9c7a/deployments/media-automation-20261102/worker_enable.py';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_WORKER_CARRIER_RESPONSE_REQUIRED');body=response.read(16079)
  need(len(body)==16078 and hashlib.sha256(body).hexdigest()=='c5acd2d20de6ef07e1f417849b07ff6a0a28b6934cb6a590d08913207f5e66f9','EXACT_WORKER_CARRIER_BYTES_REQUIRED')
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_WORKER_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(row.st_dev,row.st_ino),'WORKER_HELPER_OPEN_DRIFT');body=stream.read(16079)
 need(len(body)==16078 and hashlib.sha256(body).hexdigest()=='c5acd2d20de6ef07e1f417849b07ff6a0a28b6934cb6a590d08913207f5e66f9','EXACT_REVIEWED_WORKER_HELPER_REQUIRED')
 sys.argv=[str(path),*['--phase', 'activate', '--release', '/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102', '--main-release-sha256', '9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe', '--main-prepared-sha256', '29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d', '--main-deployed-sha256', 'bea765503d909b4ad5f7b1899cb040016ff44fdbe07970da3d82b0b4fbf1f212', '--manifest-sha256', '96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8', '--payload-sha256', '7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45', '--preflight', '/opt/t24-crm/releases/media-automation-preflight-b130a39759f3.json', '--preflight-sha256', 'b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0', '--review-sha256', 'bef104a103f0a5dfc9b7cd010eb3a649af5626bb6e07fa7113eda9a8cc425297']];namespace={'__name__':'reviewed_worker_enable','__file__':str(path)};exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_WORKER_COMMAND_REJECTED'
 print(json.dumps({'stage':'MEDIA_AUTOMATION_WORKER_COMMAND_REJECTED','code':code,'database_restored':False}));sys.exit(1)
WORKER
