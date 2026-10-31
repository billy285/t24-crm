"""Emit one exact embedded read-only preflight command; never execute it."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent

def generate():
    body=(HERE/'preflight.py').read_bytes();sha=hashlib.sha256(body).hexdigest();packed=base64.b64encode(zlib.compress(body,9)).decode()
    value=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'META_DIAGNOSTIC_PREFLIGHT'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True
 body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_DIAGNOSTIC_PREFLIGHT_REQUIRED')
 scope={{'__name__':'reviewed_meta_diagnostic_preflight','__file__':'<reviewed-meta-diagnostic-preflight>'}}
 exec(compile(body,scope['__file__'],'exec'),scope);scope['capture']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_DIAGNOSTIC_PREFLIGHT_REJECTED'
 print(json.dumps({{'stage':'META_OAUTH_DIAGNOSTICS_PREFLIGHT_REJECTED','code':code}}));sys.exit(1)
META_DIAGNOSTIC_PREFLIGHT
'''
    if len(value.encode())>=11000:raise RuntimeError('SMALL_PREFLIGHT_COMMAND_REQUIRED')
    return value

if __name__=='__main__':
    path=HERE/'preflight-command.sh';body=generate().encode()
    with path.open('xb') as stream:stream.write(body)
    print(json.dumps({'path':str(path),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'executed':False}))
