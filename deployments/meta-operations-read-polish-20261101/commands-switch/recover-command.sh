#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/meta-operations-read-polish-1db2a91e6d9b-20261101');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(30138)
 if len(body)!=30137 or hashlib.sha256(body).hexdigest()!='5f0d006aa0a469863b05aa01d3a497ef11a85655ced8f92f61d68d0495a50ad4':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','recover',*['--release', '/opt/t24-crm/releases/meta-operations-read-polish-1db2a91e6d9b-20261101', '--manifest-sha256', '9c2a7b7075f373fb75aa53bc7a5d09632d46ff373dd9430d479f347465e27dbc', '--payload-sha256', 'bd3039b962fd7fc515762cb9e59422ea864142dcaa5e824db2c61dd533aa9f91', '--preflight', '/opt/t24-crm/releases/meta-operations-read-polish-preflight-4792c2350a25.json', '--preflight-sha256', '4792c2350a251e545ec2da15fb95d24dc2261fab002f2a63f5f5b76e974f8088'],'--review-sha256','cd1937919b184d24df8bf2a4ebfa70f53642f74658dea7926de9333b799779e2'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_OPERATIONS_READ_POLISH_SWITCH_REJECTED'
 print(json.dumps({'stage':'META_OPERATIONS_READ_POLISH_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
