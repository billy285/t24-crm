"""Generate, never execute, a bounded media-automation read-only baseline capture command."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
    if not ok:raise RuntimeError(code)
def identity(row):return (row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_mode,row.st_nlink)

def generate():
    path=HERE/'preflight.py';before=path.lstat()
    need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<65536,'EXACT_LOCAL_PREFLIGHT_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(65537);after=os.fstat(stream.fileno())
    need(identity(before)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==before.st_size,'LOCAL_PREFLIGHT_READ_DRIFT')
    sha=H(body);encoded=base64.b64encode(zlib.compress(body,9)).decode()
    command="""#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'CAPTURE'
import base64,hashlib,zlib
payload=%r
expected=%r
decoder=zlib.decompressobj();body=decoder.decompress(base64.b64decode(payload,validate=True),65537)
if len(body)>65536 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_REVIEWED_CAPTURE_REQUIRED')
exec(compile(body,'<reviewed-read-only-media-automation-preflight>','exec'),{'__name__':'__main__'})
CAPTURE
"""%(encoded,sha)
    need(len(command.encode())<14000,'BOUNDED_READ_ONLY_CAPTURE_COMMAND_REQUIRED')
    return command,{'preflight_sha256':sha,'preflight_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'database_writes':False,'provider_requests':False,'writes_only_new_root_private_aggregate':True}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();command,pins=generate()
    args.out.mkdir(parents=True,exist_ok=True);need(args.out.resolve()==args.out.absolute() and not args.out.is_symlink(),'CANONICAL_OUTPUT_DIRECTORY_REQUIRED')
    for name,body in (('capture-command.sh',command.encode()),('capture-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(args.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))

if __name__=='__main__':main()
