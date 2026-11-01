"""Generate a bounded, read-only aggregate checker; never execute it."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()


def generate():
    path=HERE/'postpilot_check.py';body=path.read_bytes()
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1 or not 0<len(body)<65536:raise RuntimeError('EXACT_LOCAL_CHECKER_REQUIRED')
    payload=base64.b64encode(zlib.compress(body,9)).decode();sha=H(body)
    command="""#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'POSTPILOT'
import base64,hashlib,zlib
payload=%r
expected=%r
decoder=zlib.decompressobj();body=decoder.decompress(base64.b64decode(payload,validate=True),65537)
if len(body)>65536 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_POSTPILOT_CHECKER_REQUIRED')
exec(compile(body,'<reviewed-read-only-postpilot>','exec'),{'__name__':'__main__'})
POSTPILOT
"""%(payload,sha)
    if len(command.encode())>=14336:raise RuntimeError('BOUNDED_READ_ONLY_COMMAND_REQUIRED')
    return command,{'checker_sha256':sha,'checker_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'database_writes':False,'provider_requests':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();command,pins=generate()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.out.resolve()!=args.out.absolute() or args.out.is_symlink():raise RuntimeError('CANONICAL_COMMAND_DIRECTORY_REQUIRED')
    for name,body in (('postpilot-command.sh',command.encode()),('postpilot-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(args.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
