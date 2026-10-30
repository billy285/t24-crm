"""Generate a bounded read-only no-query callback/header diagnostic command."""
import base64
import hashlib
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()


def command():
    members = {}
    for name in ('core', 'callback_headers_probe'):
        blob = (ROOT / (name + '.py')).read_bytes()
        members[name] = {'sha256': H(blob), 'body': base64.b64encode(zlib.compress(blob, 9)).decode()}
    text = f'''#!/bin/bash
set -eu
sudo python3 -B - <<'GBP_CALLBACK_NOQUERY_READONLY_PINNED'
import base64,hashlib,json,sys,types,zlib
sys.dont_write_bytecode=True
members={members!r}
loaded={{}}
try:
 for name,member in members.items():
  blob=zlib.decompress(base64.b64decode(member['body']))
  if hashlib.sha256(blob).hexdigest()!=member['sha256']:raise RuntimeError('TOOL_MEMBER_HASH_DRIFT')
  module=types.ModuleType(name);module.__file__='hash-pinned-gbp-headers/'+name+'.py';module.__tool_sha256__=member['sha256']
  sys.modules[name]=module;loaded[name]=module;exec(compile(blob,module.__file__,'exec'),module.__dict__)
 loaded['core'].server_guard();loaded['callback_headers_probe'].main()
except BaseException as error:
 code=loaded['core'].safe_code(error) if 'core' in loaded else 'PINNED_READONLY_HEADERS_REJECTED'
 print(json.dumps({{'stage':'GBP_HEADERS_READONLY_REJECTED','code':code}}));sys.exit(1)
GBP_CALLBACK_NOQUERY_READONLY_PINNED
'''
    if len(text.encode()) >= 15000: raise ValueError('READONLY_HEADER_COMMAND_TOO_LARGE')
    return text


if __name__ == '__main__':
    path = ROOT / 'callback-headers-command.sh'
    blob = command().encode();path.write_bytes(blob);path.chmod(0o600)
    print(json.dumps({'command_created': True, 'command_bytes': len(blob), 'command_sha256': H(blob), 'server_executed': False}))
