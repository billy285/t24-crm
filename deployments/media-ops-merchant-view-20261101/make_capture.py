"""Emit the exact read-only capture wrapper; never contact or change a server."""
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
    text=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'MERCHANT_VIEW_CAPTURE'
import base64,hashlib,json,os,re,resource,socket,sys,zlib
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_READONLY_PREFLIGHT_BYTES_REQUIRED')
 namespace={{'__name__':'reviewed_merchant_view_capture','__file__':'<reviewed-merchant-view-capture>'}}
 exec(compile(body,namespace['__file__'],'exec'),namespace);print(json.dumps(namespace['capture'](),sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MERCHANT_VIEW_PREFLIGHT_REJECTED'
 print(json.dumps({{'stage':'MERCHANT_VIEW_PREFLIGHT_REJECTED','code':code}}));sys.exit(1)
MERCHANT_VIEW_CAPTURE
'''
    if len(text.encode())>=11000:raise RuntimeError('SMALL_CAPTURE_COMMAND_REQUIRED')
    return text,{'preflight_sha256':sha,'preflight_bytes':len(body),'command_sha256':H(text.encode()),'command_bytes':len(text.encode()),'executed':False,'provider_requests':False,'business_writes':False,'credential_file_content_read':False,'only_writes':'new protected aggregate proof receipt'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    text,pins=generate((HERE/'preflight.py').read_bytes())
    fd=os.open(a.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
