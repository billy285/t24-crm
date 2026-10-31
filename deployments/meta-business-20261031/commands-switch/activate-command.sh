#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(71911)
 if len(body)!=71910 or hashlib.sha256(body).hexdigest()!='a14f6d41eb6089e1a124c8326a27031280af4dbc9f58c5a73e797565d0135c98':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031', '--manifest-sha256', '9d8f26821cd42cd2816af4bcb7a1805e1b9879d103453445f0580da64002869d', '--payload-sha256', '2d499a18199822e807a67bf96cf4425fa36f7e6fedcfc701cabc0213c4b1948a', '--preflight', '/opt/t24-crm/releases/meta-business-preflight-8f4995bb3e8a.json', '--preflight-sha256', '8f4995bb3e8a100869ba01a26c59f5d8f49ba78127cd82066279539adb20f71e'],'--review-sha256','c31ada6e5febf06251e242066236ba47cc4bbdc2b32f032987e9267bb1872382'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_SWITCH_REJECTED'
 print(json.dumps({'stage':'META_BUSINESS_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
