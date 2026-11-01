"""Emit the isolated official-package staging command; never execute it."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()


def generate(preflight, toolchain):
    pf_sha = H(preflight); tool_sha = H(toolchain)
    packed = base64.b64encode(zlib.compress(json.dumps({'preflight': preflight.decode(), 'toolchain': toolchain.decode()}, separators=(',', ':')).encode(), 9)).decode()
    command = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'ASSET_STUDIO_ISOLATED_TOOLCHAIN'
import base64,hashlib,json,os,re,resource,socket,sys,types,zlib
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 packed=zlib.decompress(base64.b64decode({packed!r},validate=True));data=json.loads(packed)
 modules={{}}
 for name,expected in (('preflight',{pf_sha!r}),('toolchain',{tool_sha!r})):
  body=data[name].encode()
  if len(body)>65536 or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_REVIEWED_TOOLCHAIN_BYTES_REQUIRED')
  module=types.ModuleType('reviewed_asset_studio_'+name);module.__file__='<reviewed-asset-studio-'+name+'>';exec(compile(body,module.__file__,'exec'),module.__dict__);modules[name]=module
 if modules['toolchain'].PREFLIGHT_SHA!={pf_sha!r}:raise RuntimeError('EXACT_TOOLCHAIN_PREFLIGHT_REQUIRED')
 print(json.dumps(modules['toolchain'].run(modules['preflight'],{tool_sha!r},data['toolchain'].encode()),sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'ASSET_STUDIO_TOOLCHAIN_REJECTED'
 print(json.dumps({{'stage':'ASSET_STUDIO_TOOLCHAIN_REJECTED','code':code,'production_or_host_installation':False}}));sys.exit(1)
ASSET_STUDIO_ISOLATED_TOOLCHAIN
'''
    if len(command.encode()) >= 24000: raise RuntimeError('BOUNDED_TOOLCHAIN_COMMAND_REQUIRED')
    return command, {'preflight_sha256': pf_sha, 'toolchain_sha256': tool_sha, 'command_sha256': H(command.encode()), 'command_bytes': len(command.encode()),
        'executed': False, 'only_network_phase': 'official signed Debian package resolution and download in a new isolated container', 'build_and_probe_network': 'none',
        'production_or_host_installation': False, 'business_or_credential_mounts': False, 'api_or_worker_started': False}


def main():
    command, pins = generate((HERE / 'preflight.py').read_bytes(), (HERE / 'toolchain.py').read_bytes())
    for name, body in (('toolchain-command.sh', command.encode()), ('toolchain-freeze.json', (json.dumps(pins, sort_keys=True, indent=2) + '\n').encode())):
        fd = os.open(HERE / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(body); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(pins, sort_keys=True))


if __name__ == '__main__': main()
