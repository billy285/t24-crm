"""Emit the bounded offline-build log command only; never execute it."""
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
sudo python3 -I -S -B - <<'EXACT194_OFFLINE_BUILD_DIAGNOSTIC'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True;body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={H(body)!r}:raise RuntimeError('EXACT_OFFLINE_BUILD_DIAGNOSTIC_REQUIRED')
 scope={{'__name__':'reviewed_offline_build_diagnostic','__file__':'<reviewed-offline-build-diagnostic>'}};exec(compile(body,scope['__file__'],'exec'),scope);print(json.dumps(scope['run'](body),sort_keys=True))
except BaseException as error:
 text=str(error);code=text if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',text) else 'ASSET_OFFLINE_BUILD_DIAGNOSTIC_REJECTED'
 print(json.dumps({{'stage':'ASSET_OFFLINE_BUILD_DIAGNOSTIC_REJECTED','code':code,'production_or_host_installation':False}}));sys.exit(1)
EXACT194_OFFLINE_BUILD_DIAGNOSTIC
'''
    if len(command.encode())>=14000:raise RuntimeError('CONSOLE_SAFE_BUILD_DIAGNOSTIC_REQUIRED')
    return command,{'diagnostic_sha256':H(body),'diagnostic_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'installer_or_network_flags_changed':False,'production_or_host_installation':False}


def main():
    command,pins=generate((HERE/'diagnose_toolchain_build.py').read_bytes())
    for name,body in (('toolchain-build-diagnostic-command.sh',command.encode()),('toolchain-build-diagnostic-freeze.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(HERE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
