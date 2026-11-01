#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/google-business-onboarding-mobile-adb948da237f-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(18041)
 if len(body)!=18040 or hashlib.sha256(body).hexdigest()!='fb017adf5eaa00e7c873bc26471693cb54030494631390c7a85ad24891171b0c':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/google-business-onboarding-mobile-adb948da237f-20261102', '--manifest-sha256', 'a08a1c922981b0fe0fa91436b4061e5143f6769bfd9e0e03b89f6c852444a51b', '--payload-sha256', 'ff601095511c4e1573c49360b4e6833f46c0aa4a15ecb5c49b98fa5e6330e9f4', '--preflight', '/opt/t24-crm/releases/google-business-onboarding-mobile-preflight-b847750a7e81.json', '--preflight-sha256', 'b847750a7e816361fa13a166f4f24e4f23a97008e108f33da486d54239bece5b'],'--review-sha256','648f59c27576e06164b9a2db4d295606ed340e710591965d12b201db24e86cd8'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'GOOGLE_ONBOARDING_MOBILE_STATIC_SWITCH_REJECTED'
 print(json.dumps({'stage':'GOOGLE_ONBOARDING_MOBILE_STATIC_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
