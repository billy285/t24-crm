#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(42922)
 if len(body)!=42921 or hashlib.sha256(body).hexdigest()!='b9d954130b99802bf444fe1ce99b73ba869c21ca95d1387ebb6d124d06ea109e':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102', '--manifest-sha256', '0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3', '--payload-sha256', '64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439', '--preflight', '/opt/t24-crm/releases/media-unified-settings-baseline-0dd43fefcf43.json', '--preflight-sha256', '0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83'],'--review-sha256','c96bb2707cfd7c1c83a0bc01e7e17671a5997b20f09d27b44bbb42801ab91482'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_UNIFIED_SETTINGS_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_UNIFIED_SETTINGS_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
