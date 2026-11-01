#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-ops-monthly-6ab1ded2e139-20261101');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(39979)
 if len(body)!=39978 or hashlib.sha256(body).hexdigest()!='7619cff40c9c7fa856fa9a8318cb544382aced8a08b95c8b5fb4b0f76be9e560':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/media-ops-monthly-6ab1ded2e139-20261101', '--manifest-sha256', '3891c1776653d2456ea2c3c1871f70571be621dff2578556fa3101ab6821b0f4', '--payload-sha256', '9d19a52e6bc838870146bd81e38c682fcf8ffb1a2b802cd19a4a5cfd30bf92fa', '--preflight', '/opt/t24-crm/releases/media-ops-monthly-preflight-d2129acab278.json', '--preflight-sha256', 'd2129acab27861e9b6270a47aee2b9258f9b77f1d9a72db1cee477f962ebe9a5'],'--review-sha256','a7642ea2a7827af7523e1adfe599eabd12888447b1567b0c7b3cfa37714d0f4b'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MONTHLY_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MONTHLY_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
