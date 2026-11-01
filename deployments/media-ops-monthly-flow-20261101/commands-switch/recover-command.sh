#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-ops-monthly-flow-d39337fccfd6-20261101');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(42528)
 if len(body)!=42527 or hashlib.sha256(body).hexdigest()!='d5efcfecb79859e595dec70a0e901abb1c5e86d52ba300a909dd73e44bfd24c7':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/media-ops-monthly-flow-d39337fccfd6-20261101', '--manifest-sha256', 'd0953971efc1715dc0d68596e60e682e6c3748d8ccdbc10b5b393f044fdb0dc4', '--payload-sha256', '3c57bc3a60082031c563f7f67dfab9d8da8c99989206418829aa4ecea535fd05', '--preflight', '/opt/t24-crm/releases/media-ops-monthly-flow-preflight-42bc79e1b704.json', '--preflight-sha256', '42bc79e1b7041e3b376ca94ab8bef01d6dc6224e151821958cf48225f90faaaf'],'--review-sha256','d07abd82d72dabdae727618fbb5ba0375c5cd05b61b691d0a06c1e4851578e43'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MONTHLY_FLOW_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MONTHLY_FLOW_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
