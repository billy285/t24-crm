#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-navigation-sticky-68fa8589101f-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(19547)
 if len(body)!=19546 or hashlib.sha256(body).hexdigest()!='eba0044e3ab176be9cd7235da48cb41d67d2940c617e226f30c80d6eeb756181':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-navigation-sticky-68fa8589101f-20261102', '--manifest-sha256', 'b4139c1fb240c7a6d1bfe913be1b78aabba3457c1fa9543304dbe29b3dade0bf', '--payload-sha256', '7b5b12340dcedcaf52260db4296e15e75c6043d7a36f028389ed752ff747c73f', '--preflight', '/opt/t24-crm/releases/media-navigation-sticky-baseline-6c8dcf5954a5.json', '--preflight-sha256', '6c8dcf5954a5ccac79b323dc40a67e001034e232d27505a55d101c451a103216'],'--review-sha256','1958c97791a8785ed95e65f6548486f761a09b8c9fddd561ec432e7571e31e4d'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_NAVIGATION_STICKY_STATIC_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_NAVIGATION_STICKY_STATIC_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
