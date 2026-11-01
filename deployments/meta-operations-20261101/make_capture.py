"""Produce a small, byte-pinned current-runtime read-only capture command."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent


def generate():
    source = (HERE/'preflight.py').read_bytes(); ast.parse(source)
    sha = hashlib.sha256(source).hexdigest(); packed = base64.b64encode(zlib.compress(source,9)).decode()
    code = "#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'META_OPERATIONS_PREFLIGHT'\n" + f'''import base64,hashlib,json,re,sys,types,zlib
sys.dont_write_bytecode=True
try:
 body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(source)} or hashlib.sha256(body).hexdigest()!={sha!r}:raise RuntimeError('EXACT_PREFLIGHT_SOURCE_REQUIRED')
 module=types.ModuleType('_reviewed_meta_operations_preflight');module.__file__='<reviewed-meta-operations-preflight>'
 exec(compile(body,module.__file__,'exec'),module.__dict__)
 print(json.dumps(module.capture(),sort_keys=True))
except BaseException as exc:
 value=str(exc);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_OPERATIONS_PREFLIGHT_REJECTED'
 print(json.dumps({{'stage':'META_OPERATIONS_PREFLIGHT_REJECTED','code':code}}));sys.exit(1)
META_OPERATIONS_PREFLIGHT
'''
    if len(code.encode()) > 11000: raise RuntimeError('SMALL_CAPTURE_REQUIRED')
    return code, {'source_sha256':sha,'source_bytes':len(source),'command_sha256':hashlib.sha256(code.encode()).hexdigest(),'command_bytes':len(code.encode()),'executed':False}


if __name__ == '__main__':
    command, report = generate()
    (HERE/'capture-preflight-command.sh').write_text(command)
    (HERE/'capture-freeze.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True))
