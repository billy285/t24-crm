#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-ops-ui-refined-835be7a06d61-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(21434)
 if len(body)!=21433 or hashlib.sha256(body).hexdigest()!='6df39ea24eefc3e607bc8d55d9a125d2ef15901d1093e4044cdfef0b37487403':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-ops-ui-refined-835be7a06d61-20261102', '--manifest-sha256', 'd5f60508fc44627facd81702eff2605363d4d54cc5c75a24a0a42a0824373e9d', '--payload-sha256', 'fef3fc7d8646324d206e39ebecec7e159d9a1b02e98ed392cfe1a46c5e55a19b', '--preflight', '/opt/t24-crm/releases/media-ops-ui-refined-baseline-338bef135632.json', '--preflight-sha256', '338bef1356329348180bcab4648921687047d4bf464ece3f38cdf46fec7d0c33'],'--review-sha256','e4998c3917f4e8ded7b3d03929565ef7ebff7eae5c6c49a671f83a1c9528486b'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_UI_REFINED_STATIC_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_UI_REFINED_STATIC_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
