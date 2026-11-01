#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'ASSET_TOOLCHAIN_PROTECTED_TRANSPORT'
import base64,hashlib,json,os,re,resource,socket,stat,sys,zlib
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
def secure(path,mode=None):
 for parent in (path,*path.parents):
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TRANSPORT_PARENT_REQUIRED')
 if mode is not None:need(stat.S_IMODE(path.lstat().st_mode)==mode,'EXACT_TRANSPORT_DIRECTORY_MODE_REQUIRED')
def read(path,size,sha):
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600 and row.st_size==size,'EXACT_TRANSPORT_FILE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno());body=f.read(size+1)
 after=path.lstat();fields=lambda r:(r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_uid,r.st_mode,r.st_nlink)
 need(fields(row)==fields(opened)==fields(after) and len(body)==size and H(body)==sha,'TRANSPORT_HASH_OR_IDENTITY_DRIFT');return body
def write(path,body):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)
root=Path('/opt/t24-crm/releases/media-asset-toolchain-transport-c1b0cbbeaa33-20261101');secure(root.parent)
if not root.exists():
 need(2==0 and not root.is_symlink(),'ORDERED_TRANSPORT_STAGING_REQUIRED');root.mkdir(mode=0o700)
secure(root,0o700);prior=[('part-00.bin', 6000, 'c3714dbe27cd94d0d4669996359c322757d8ac42458debf89345c1fc177817f9'), ('part-01.bin', 6000, '6e186484255d45f7ab03304c3442f5db71225f044b4531eb3c7728581815668d')];current=('part-02.bin', 3612, '828c85033e33214da7350f11f20f160b17a7582692925e4a414561112276f5ec');expected={name for name,_,_ in prior};actual={p.name for p in root.iterdir()}
need(actual in (expected,expected|{current[0]}),'ORDERED_APPEND_ONLY_TRANSPORT_REQUIRED')
for name,size,sha in prior:read(root/name,size,sha)
body=base64.b64decode('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',validate=True)
need(len(body)==current[1] and H(body)==current[2],'EXACT_TRANSPORT_CHUNK_REQUIRED')
if current[0] in actual:read(root/current[0],current[1],current[2])
else:write(root/current[0],body)
need({p.name for p in root.iterdir()}==expected|{current[0]},'EXACT_TRANSPORT_MEMBER_SET_REQUIRED')
print(json.dumps({'stage':'ASSET_TOOLCHAIN_CHUNK_STAGED','chunk':2,'chunk_sha256':current[2],'next_chunk':3,'toolchain_executed':False}))
ASSET_TOOLCHAIN_PROTECTED_TRANSPORT
