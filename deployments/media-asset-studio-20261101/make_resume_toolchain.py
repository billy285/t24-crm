"""Emit the bounded exact194 local-only resume command; never execute it."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()


def generate(body):
    packed=base64.b64encode(zlib.compress(body,9)).decode()
    command=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'EXACT194_LOCAL_TOOLCHAIN_RESUME'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True;body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={H(body)!r}:raise RuntimeError('EXACT_LOCAL_TOOLCHAIN_RESUME_SOURCE_REQUIRED')
 scope={{'__name__':'reviewed_local_toolchain_resume','__file__':'<reviewed-local-toolchain-resume>'}};exec(compile(body,scope['__file__'],'exec'),scope);result=scope['run'](body);print(json.dumps(result,sort_keys=True))
 if result['stage']!='MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED':sys.exit(2)
except Exception as error:
 text=str(error);code=text if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',text) else 'ASSET_LOCAL_TOOLCHAIN_RESUME_REJECTED'
 print(json.dumps({{'stage':'ASSET_LOCAL_TOOLCHAIN_RESUME_REJECTED','code':code,'production_or_host_installation':False}}));sys.exit(1)
EXACT194_LOCAL_TOOLCHAIN_RESUME
'''
    if len(command.encode())>=14000:raise RuntimeError('CONSOLE_SAFE_LOCAL_TOOLCHAIN_RESUME_REQUIRED')
    return command,{'resume_sha256':H(body),'resume_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'scope':'media-asset-studio-toolchain-'+H(body)[:12]+'-20261101','executed':False,'client_docker_buildkit':'0','installer_path_added':['/usr/sbin','/sbin'],'network_fetch_performed':False,'production_or_host_installation':False}


def main():
    command,pins=generate((HERE/'resume_toolchain.py').read_bytes())
    for name,body in (('resume-toolchain-command.sh',command.encode()),('resume-toolchain-freeze.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(HERE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
