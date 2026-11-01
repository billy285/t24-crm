"""Produce a small in-memory-pinned quarantine wrapper; never contact a server."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
H=lambda value:hashlib.sha256(value).hexdigest()


def generate(body):
    sha=H(body);packed=base64.b64encode(zlib.compress(body,9)).decode('ascii')
    command=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'QUARANTINE'
import base64,hashlib,json,os,re,resource,socket,sys,zlib
namespace={{}}
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_QUARANTINE_HELPER_REQUIRED')
 namespace={{'__name__':'reviewed_stale_prepare_quarantine','__file__':'<reviewed-stale-prepare-quarantine>'}}
 exec(compile(body,namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_OPERATIONS_QUARANTINE_REJECTED'
 print(json.dumps({{'stage':'META_OPERATIONS_QUARANTINE_REJECTED','code':code,'archive_completed':namespace.get('ARCHIVED',False)}}));sys.exit(1)
QUARANTINE
'''
    if len(command.encode())>=11000:raise RuntimeError('SMALL_QUARANTINE_WRAPPER_REQUIRED')
    return command,{'helper_sha256':sha,'helper_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'business_rows_or_credentials_read':False,'only_mutation':'no-overwrite rename of exact rejected four-file staging'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    body=(HERE/'quarantine_stale_prepare.py').read_bytes();command,pins=generate(body)
    fd=os.open(args.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(command);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
