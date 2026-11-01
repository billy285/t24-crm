#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'READ_FIXED_PUBLIC_BUILD_ERROR'
import hashlib,json,os,socket,stat
from pathlib import Path
assert os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z'
p=Path('/opt/t24-crm/releases/media-asset-studio-toolchain-8f007897d478-20261101/docker-build-public.log')
for parent in p.parents:
 s=parent.lstat();assert parent.resolve()==parent and stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022
s=p.lstat();assert p.resolve()==p and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and s.st_size==18293
fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as stream:
 opened=os.fstat(stream.fileno());body=stream.read(18294)
fields=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_uid,x.st_mode,x.st_nlink)
assert fields(s)==fields(opened)==fields(p.lstat()) and len(body)==18293 and hashlib.sha256(body).hexdigest()=='361e05f6803ee8c50edd2c6881491453625886c15124c19869777838817c3d55'
lines=body.decode('utf-8',errors='replace').splitlines()
cut=next((i for i,x in enumerate(lines) if 'Traceback (most recent call last)' in x),len(lines))
print(json.dumps({'stage':'EXACT_PUBLIC_INSTALLER_LOG_READ','sha256':hashlib.sha256(body).hexdigest(),'lines_before_python_traceback':lines[:cut],'network_or_writes_performed':False},ensure_ascii=True))
READ_FIXED_PUBLIC_BUILD_ERROR
