#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-meta-monthly-5fd379d625d6-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(47747)
 if len(body)!=47746 or hashlib.sha256(body).hexdigest()!='b11362093b66d5bbefc62d0907f8217f389735b7ffa5da7d091ad4e132bc2247':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/media-meta-monthly-5fd379d625d6-20261102', '--manifest-sha256', '7a94c774a72a8402559b97d49e3693c8e7a6e72b20d45da10b4389b6ef5e3abc', '--payload-sha256', '55a2d2e5c6447c15cc33f83bb1a9af69f0bcb14f39bca5fa821d707f94b7b704', '--preflight', '/opt/t24-crm/releases/media-meta-monthly-preflight-6199dc87be59.json', '--preflight-sha256', '6199dc87be59bb86693f2e1b0a06278624b1faac112db5598e43aee78464a7d2'],'--review-sha256','09ec24d26f267137bf5dcc6e5e9e563224da99fe553a4d7b9b986804afae2ac3'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_META_MONTHLY_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_META_MONTHLY_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
