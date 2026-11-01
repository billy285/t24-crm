#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-operator-queue-e0f39295a912-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(43191)
 if len(body)!=43190 or hashlib.sha256(body).hexdigest()!='cd69c5c551cc270643e0b1f193539bf9e20b77d4e6cca32c8fcc8b09337cbfcf':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/media-operator-queue-e0f39295a912-20261102', '--manifest-sha256', '398c1d7fbd83200dece698d0c46a9185540fe26d09af9ec100f2ff26102a4c6a', '--payload-sha256', '296554f0a426dd8e190d245d98da6441d9e743f4a79a33a48e7690307c563916', '--preflight', '/opt/t24-crm/releases/media-operator-queue-preflight-8407a1e8596f.json', '--preflight-sha256', '8407a1e8596fb15b9937ae168cbbad5374e54bd653522a23d9360e2eeec3a508'],'--review-sha256','55586cffdbea74f52330cb68bbda90c1871d9ffc80013e44e7e0c953962a6945'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPERATOR_QUEUE_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPERATOR_QUEUE_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
