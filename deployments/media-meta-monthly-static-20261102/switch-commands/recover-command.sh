#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-meta-monthly-static-eec3d1d02a97-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(19682)
 if len(body)!=19681 or hashlib.sha256(body).hexdigest()!='cd277633fd751576d85ec8d9bd49685df7e4bb98ddfffebbf8ceae508d3e4284':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/media-meta-monthly-static-eec3d1d02a97-20261102', '--manifest-sha256', 'ef228b776044f74651d8c397283b70ea8eaf3a5443a829eb11fe5048ce52c632', '--payload-sha256', '8a3a4b1be14c2d508a9c57aef3206e52a4a1008abaa750f65fce0c940e71601e', '--preflight', '/opt/t24-crm/releases/media-meta-monthly-static-preflight-78bb1249abca.json', '--preflight-sha256', '78bb1249abca9506a9158c88fcbc31edf36c0eef6926c07ddc07f6235e0a9143'],'--review-sha256','eedb0a0bd08bd7d46cf2bf206b9c50aae8d2487dcf93a5619b23a8eb6b44f285'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_META_MONTHLY_UI_STATIC_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_META_MONTHLY_UI_STATIC_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
