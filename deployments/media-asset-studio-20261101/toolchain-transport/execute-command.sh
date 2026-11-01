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
root=Path('/opt/t24-crm/releases/media-asset-toolchain-transport-c1b0cbbeaa33-20261101');secure(root,0o700);rows=[('part-00.bin', 6000, 'c3714dbe27cd94d0d4669996359c322757d8ac42458debf89345c1fc177817f9'), ('part-01.bin', 6000, '6e186484255d45f7ab03304c3442f5db71225f044b4531eb3c7728581815668d'), ('part-02.bin', 3612, '828c85033e33214da7350f11f20f160b17a7582692925e4a414561112276f5ec')]
need({p.name for p in root.iterdir()}=={name for name,_,_ in rows},'FRESH_COMPLETE_TRANSPORT_REQUIRED')
packed=b''.join(read(root/name,size,sha) for name,size,sha in rows)
need(len(packed)==15612 and H(packed)=='4beef4f8202e4a78884be6825643d90108c1d16aff8fe97457123d25c021756b','EXACT_COMPLETE_PACKED_TRANSPORT_REQUIRED')
body=zlib.decompress(packed)
need(len(body)==20834 and H(body)=='c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075','EXACT_REVIEWED_TOOLCHAIN_COMMAND_REQUIRED')
script=root/'toolchain-reviewed.sh';write(script,body)
write(root/'execution-started.json',(json.dumps({'command_sha256':'c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075','toolchain_sha256':'4fe7ee52647ff1775c8b3e7ac9bce60208aa66806324d3c4a51f80ff23f16fe7'},sort_keys=True,indent=2)+'\n').encode())
os.execve('/bin/bash',['/bin/bash',str(script)],{'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
ASSET_TOOLCHAIN_PROTECTED_TRANSPORT
