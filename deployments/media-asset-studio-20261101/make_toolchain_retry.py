"""Generate the short exact194 retry loader; never execute server operations."""
import base64
import hashlib
import importlib.util
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
sudo python3 -I -S -B - <<'EXACT194_PUBLIC_TOOLCHAIN_RETRY'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True;body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={H(body)!r}:raise RuntimeError('EXACT194_RETRY_LOADER_REQUIRED')
 scope={{'__name__':'reviewed_exact194_retry','__file__':'<reviewed-exact194-retry>'}};exec(compile(body,scope['__file__'],'exec'),scope);print(json.dumps(scope['run'](),sort_keys=True))
except BaseException as error:
 text=str(error);code=text if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',text) else 'ASSET_EXACT194_TOOLCHAIN_REJECTED'
 print(json.dumps({{'stage':'ASSET_EXACT194_TOOLCHAIN_REJECTED','code':code,'production_or_host_installation':False}}));sys.exit(1)
EXACT194_PUBLIC_TOOLCHAIN_RETRY
'''
    if len(command.encode())>=14000:raise RuntimeError('CONSOLE_SAFE_EXACT194_RETRY_REQUIRED')
    spec=importlib.util.spec_from_file_location('derive_exact194_variant',HERE/'toolchain_retry.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    variant=module.derive_variant((HERE/'toolchain.py').read_bytes())
    return command,{'loader_sha256':H(body),'loader_bytes':len(body),'variant_sha256':H(variant),'variant_bytes':len(variant),'original_toolchain_sha256':module.TOOL_SHA,'original_command_sha256':module.COMMAND_SHA,'preflight_sha256':module.PREFLIGHT_SHA,'approved_proposal_sha256':module.APPROVED_SHA,'approved_package_count':194,'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'production_or_host_installation':False,'old_source_modified':False}


def main():
    command,pins=generate((HERE/'toolchain_retry.py').read_bytes())
    for name,body in (('toolchain-retry-command.sh',command.encode()),('toolchain-retry-freeze.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(HERE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
