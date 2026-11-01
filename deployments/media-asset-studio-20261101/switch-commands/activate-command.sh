#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-asset-studio-f595f3acfb5b-20261101');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(53629)
 if len(body)!=53628 or hashlib.sha256(body).hexdigest()!='334d6bb4b5a45538d019a03df19b0cd6b2d49671969b1dd7ea288c06f0976108':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-asset-studio-f595f3acfb5b-20261101', '--manifest-sha256', '2c526c73ec63ba59603fe304956c617f936ed53390c461890e959d98d413a504', '--payload-sha256', '006c469c89b50217a253139c05f21a289386b521915c29bad3117238ca1afc15', '--preflight', '/opt/t24-crm/releases/media-asset-studio-preflight-bed4a64393ad.json', '--preflight-sha256', 'bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'],'--review-sha256','aaded73460dff6689af78c5b7f90f6d4f39024c340bcde1e0bdfa2713308a274'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_ASSET_STUDIO_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_ASSET_STUDIO_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
