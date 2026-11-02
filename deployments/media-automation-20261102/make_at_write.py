"""Generate pinned at-write controller wrappers, never execute them."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
DIRECTORY='deployments/media-automation-20261102'
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def main():
    p=argparse.ArgumentParser();p.add_argument('--carrier',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();need(re.fullmatch('[a-f0-9]{40}',a.carrier or ''),'EXACT_CARRIER_REQUIRED');body=(HERE/'at_write_release.py').read_bytes();need(subprocess.check_output(['git','show',a.carrier+':'+DIRECTORY+'/at_write_release.py'])==body,'EXACT_COMMITTED_AT_WRITE_HELPER_REQUIRED');need(subprocess.check_output(['git','rev-parse',a.carrier+':app'])==subprocess.check_output(['git','rev-parse','c78b50a11e020674ad53b34fbbfb5b1badd4a9a5:app']),'APPLICATION_TREE_CHANGED');sha=H(body);outputs={}
    for phase in ('activate','recover'):
        outputs['at-write-'+phase+'-command.sh']=f'''#!/bin/bash
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
  need({phase!r}=='activate','EXISTING_REVIEWED_CONTROLLER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/{a.carrier}/{DIRECTORY}/at_write_release.py';opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CONTROLLER_RESPONSE_REQUIRED');body=response.read({len(body)+1})
  need(len(body)=={len(body)} and hashlib.sha256(body).hexdigest()=={sha!r},'EXACT_CONTROLLER_CARRIER_BYTES_REQUIRED');fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT600_CONTROLLER_REQUIRED');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(row.st_dev,row.st_ino),'CONTROLLER_OPEN_DRIFT');body=stream.read({len(body)+1})
 need(len(body)=={len(body)} and hashlib.sha256(body).hexdigest()=={sha!r},'EXACT_REVIEWED_CONTROLLER_REQUIRED');sys.argv=[str(path),'--phase',{phase!r}];namespace={{'__name__':'reviewed_at_write_controller','__file__':str(path)}};exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_AUTOMATION_AT_WRITE_COMMAND_REJECTED';print(json.dumps({{'stage':'MEDIA_AUTOMATION_AT_WRITE_COMMAND_REJECTED','code':code,'database_restored':False}}));sys.exit(1)
ATWRITE
'''
    need(all(len(v.encode())<11000 for v in outputs.values()),'BOUNDED_CONTROLLER_WRAPPERS_REQUIRED');pins={'carrier':a.carrier,'controller_sha256':sha,'controller_bytes':len(body),'application_source_sha':'c78b50a11e020674ad53b34fbbfb5b1badd4a9a5','prepared_sha256':'29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d','command_sha256':{n:H(v.encode()) for n,v in outputs.items()},'executed':False};a.out.mkdir(parents=True,exist_ok=True)
    for name,data in [(n,v.encode()) for n,v in outputs.items()]+[('command-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())]:
        fd=os.open(a.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))
if __name__=='__main__':main()
