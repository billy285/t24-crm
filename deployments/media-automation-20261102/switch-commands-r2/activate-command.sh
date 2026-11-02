#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(42814)
 if len(body)!=42813 or hashlib.sha256(body).hexdigest()!='9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102', '--manifest-sha256', '96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8', '--payload-sha256', '7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45', '--preflight', '/opt/t24-crm/releases/media-automation-preflight-b130a39759f3.json', '--preflight-sha256', 'b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0'],'--review-sha256','29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_AUTOMATION_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
