import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()


def generate(body):
    packed = base64.b64encode(zlib.compress(body, 9)).decode()
    command = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'ASSET_READONLY_FETCH_DIAGNOSTIC'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True;body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={H(body)!r}:raise RuntimeError('EXACT_READONLY_DIAGNOSTIC_REQUIRED')
 scope={{'__name__':'reviewed_fetch_diagnostic','__file__':'<reviewed-fetch-diagnostic>'}};exec(compile(body,scope['__file__'],'exec'),scope);print(json.dumps(scope['diagnostic'](),sort_keys=True))
except BaseException as error:
 text=str(error);code=text if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',text) else 'ASSET_FETCH_DIAGNOSTIC_REJECTED'
 print(json.dumps({{'stage':'ASSET_FETCH_DIAGNOSTIC_REJECTED','code':code}}));sys.exit(1)
ASSET_READONLY_FETCH_DIAGNOSTIC
'''
    if len(command.encode()) >= 14000: raise RuntimeError('CONSOLE_SAFE_DIAGNOSTIC_REQUIRED')
    return command


def main():
    spec = importlib.util.spec_from_file_location('exact_failed_fetch', HERE / 'toolchain.py'); tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
    path = HERE / 'diagnose_fetch.py'; body = path.read_bytes()
    need = b'FETCH_SHA = None'; assert body.count(need) == 1
    body = body.replace(need, ('FETCH_SHA = ' + repr(H(tool.FETCH.replace('__TOP__', repr(tool.TOP)).encode()))).encode())
    path.write_bytes(body)
    command = generate(body)
    fd = os.open(HERE / 'fetch-diagnostic-command.sh', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'w') as f:f.write(command);f.flush();os.fsync(f.fileno())
    print(json.dumps({'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'diagnostic_sha256':H(body),'executed':False}))


if __name__ == '__main__': main()
