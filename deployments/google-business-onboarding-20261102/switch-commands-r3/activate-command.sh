#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path('/opt/t24-crm/releases/google-business-onboarding-r3-8b429dad8a2f-20261102');path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read(61026)
 if len(body)!=61025 or hashlib.sha256(body).hexdigest()!='0ac3a706567118506831853d425983f119d469451aea32c31f07d6f23a4b69a8':raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase','activate',*['--release', '/opt/t24-crm/releases/google-business-onboarding-r3-8b429dad8a2f-20261102', '--manifest-sha256', '3c714aba0a597b1c46d66d8979bf43ec6464d0d5ff9c219dd0e47dd0ba816ad0', '--payload-sha256', '61cdb231e54302f44a13c59c42ee488f97e892c45bfbee50c2cfcced72db4bb1', '--preflight', '/opt/t24-crm/releases/google-business-onboarding-preflight-2b1a9dde5020.json', '--preflight-sha256', '2b1a9dde5020023ef33136b45bc54384745aeed30ab5f2c2e3312a59a8ebd485'],'--review-sha256','ef9ea86c6f12c59c18fc508aaa5028f476ba0187a74f19e06df23b06a188d4ff'];namespace={'__name__':'reviewed_workflow_release','__file__':str(path)}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'GOOGLE_ONBOARDING_SWITCH_REJECTED'
 print(json.dumps({'stage':'GOOGLE_ONBOARDING_SWITCH_REJECTED','code':code}));sys.exit(1)
WORKFLOW
