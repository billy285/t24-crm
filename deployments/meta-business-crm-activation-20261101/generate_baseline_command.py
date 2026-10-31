"""Emit current-state baseline capture only; no provider or credential action."""
import base64
import hashlib
import json
from pathlib import Path
import zlib
HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()

def capture_command():
    files = {}
    for name in ('core.py', 'baseline.py'):
        path = HERE/name
        if path.is_symlink() or not path.is_file(): raise RuntimeError('REGULAR_CAPTURE_SOURCE_REQUIRED')
        body = path.read_bytes()
        if not 0 < len(body) < 131072: raise RuntimeError('BOUNDED_CAPTURE_SOURCE_REQUIRED')
        files[name] = (base64.b64encode(zlib.compress(body, 9)).decode(), H(body), len(body))
    value = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'META_CAPTURE'
import base64,hashlib,json,re,sys,types,zlib
try:
 sys.dont_write_bytecode=True
 files={files!r};modules={{}}
 for name,(packed,sha,size) in files.items():
  body=zlib.decompress(base64.b64decode(packed,validate=True))
  if len(body)!=size or hashlib.sha256(body).hexdigest()!=sha:raise RuntimeError('EXACT_CAPTURE_SOURCE_REQUIRED')
  module=types.ModuleType('_reviewed_meta_'+name[:-3]);module.__file__='<reviewed-'+name+'>'
  exec(compile(body,module.__file__,'exec'),module.__dict__);modules[name]=module
 modules['baseline.py'].configure(modules['core.py'])
 print(json.dumps(modules['baseline.py'].capture(),sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_BASELINE_CAPTURE_REJECTED'
 print(json.dumps({{'stage':'META_CRM_ROTATION_BASELINE_CAPTURE_REJECTED','code':code}}));sys.exit(1)
META_CAPTURE
'''
    if len(value.encode()) >= 11000: raise RuntimeError('SMALL_CAPTURE_COMMAND_REQUIRED')
    return value, {name: {'sha256': row[1], 'bytes': row[2]} for name, row in files.items()}


if __name__=='__main__':
    command,pins=capture_command();path=HERE/'capture-baseline-command.sh'
    with path.open('xb') as stream:stream.write(command.encode())
    print(json.dumps({'path':str(path),'sha256':H(command.encode()),'bytes':len(command.encode()),'source_pins':pins,'executed':False},sort_keys=True))
