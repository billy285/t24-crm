#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/media-ops-merchant-view-5a904dd925f0-20261101');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(34863)
 if len(body)!=34862 or hashlib.sha256(body).hexdigest()!='485ac303342b486a589697d514ee7a1b7bb237bf23b61585d4eb32197b8398c4':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/media-ops-merchant-view-5a904dd925f0-20261101', '--manifest-sha256', '83abbc803879894490afbdc4836d19d82bd90df0580d94109619f0478a71fa8b', '--payload-sha256', '3bd98d9ea2ab84f81cf4f5e48399d36fba5ceec3e2bf53ffce1e308f0edae6b9', '--preflight', '/opt/t24-crm/releases/media-ops-merchant-view-preflight-1f47d56afc3c.json', '--preflight-sha256', '1f47d56afc3c79de9b905ad5d95a0e15617a3ca53c934fb2e8a1d24327a7ead9'],'--review-sha256','572d0848eafb8eb17d79167452ca971cfd82156de646d046a1131dd89bf20cc9'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_OPS_MERCHANT_VIEW_SWITCH_REJECTED'
 print(json.dumps({'stage':'MEDIA_OPS_MERCHANT_VIEW_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
