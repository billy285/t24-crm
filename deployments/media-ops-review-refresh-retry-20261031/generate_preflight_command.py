"""Generate a bounded read-only current-baseline capture command, never execute."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent


def command():
    body=(HERE/'preflight.py').read_bytes();sha=hashlib.sha256(body).hexdigest();packed=base64.b64encode(zlib.compress(body,9)).decode()
    code=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PYCODE'
import base64,hashlib,json,os,re,resource,socket,sys,types,zlib
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 body=zlib.decompress(base64.b64decode({packed!r}))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_PREFLIGHT_TOOL_REQUIRED')
 module=types.ModuleType('_readonly_review_refresh');module.__file__='<reviewed-readonly-preflight>'
 exec(compile(body,module.__file__,'exec'),module.__dict__);module.capture()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'PREFLIGHT_REJECTED'
 print(json.dumps({{'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_PREFLIGHT_REJECTED','code':code}}));sys.exit(1)
PYCODE
'''
    assert len(code.encode())<11000
    return code


if __name__=='__main__':
    target=HERE/'preflight-command.sh';body=command().encode();fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(body)
    print(json.dumps({'path':str(target),'size':len(body),'sha256':hashlib.sha256(body).hexdigest(),'executed':False}))
