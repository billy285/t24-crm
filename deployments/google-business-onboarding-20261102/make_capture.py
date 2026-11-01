"""Emit the reviewed short read-only current158 capture command, never run it."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()


def generate(body):
    if not 0<len(body)<65536:raise RuntimeError('BOUNDED_CAPTURE_SOURCE_REQUIRED')
    packed=base64.b64encode(zlib.compress(body,9)).decode();sha=H(body)
    command=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'GOOGLE_ONBOARDING_READONLY_CAPTURE'
import base64,hashlib,json,os,re,resource,socket,sys,zlib
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 decoder=zlib.decompressobj();body=decoder.decompress(base64.b64decode({packed!r},validate=True),65537)
 if len(body)!={len(body)} or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_READONLY_CAPTURE_BYTES_REQUIRED')
 namespace={{'__name__':'reviewed_google_onboarding_capture','__file__':'<reviewed-google-onboarding-capture>'}}
 exec(compile(body,namespace['__file__'],'exec'),namespace);print(json.dumps(namespace['capture'](),sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'GOOGLE_ONBOARDING_PREFLIGHT_REJECTED'
 print(json.dumps({{'stage':'GOOGLE_ONBOARDING_PREFLIGHT_REJECTED','code':code}}));sys.exit(1)
GOOGLE_ONBOARDING_READONLY_CAPTURE
'''
    if len(command.encode())>=14000:raise RuntimeError('SHORT_CAPTURE_COMMAND_REQUIRED')
    return command,{'preflight_sha256':sha,'preflight_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'business_writes':False,'provider_requests':False,'installation_performed':False,'worker_started':False,'credential_file_content_read':False,'private_content_read':False,'only_writes':'new root-private aggregate current158 baseline receipt'}


def main():
    command,pins=generate((HERE/'preflight.py').read_bytes())
    for name,body in [('capture-command.sh',command.encode()),('capture-freeze.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())]:
        fd=os.open(HERE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
