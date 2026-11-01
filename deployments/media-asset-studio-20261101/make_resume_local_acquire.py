"""Emit the small derived physical-offline local-acquire command only."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()


def generate(body,variant):
    packed=base64.b64encode(zlib.compress(body,9)).decode()
    command=f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'EXACT194_PHYSICAL_OFFLINE_LOCAL_ACQUIRE'
import base64,hashlib,json,re,sys,zlib
try:
 sys.dont_write_bytecode=True;body=zlib.decompress(base64.b64decode({packed!r},validate=True))
 if len(body)!={len(body)} or hashlib.sha256(body).hexdigest()!={H(body)!r}:raise RuntimeError('EXACT_LOCAL_ACQUIRE_LOADER_REQUIRED')
 scope={{'__name__':'reviewed_local_acquire_loader','__file__':'<reviewed-local-acquire-loader>'}};exec(compile(body,scope['__file__'],'exec'),scope)
 original=scope['read_base']();variant=scope['derive'](original)
 if len(variant)!={len(variant)} or hashlib.sha256(variant).hexdigest()!={H(variant)!r}:raise RuntimeError('EXACT_DERIVED_LOCAL_ACQUIRE_RESUMER_REQUIRED')
 result=scope['run']();print(json.dumps(result,sort_keys=True))
 if result['stage']!='MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED':sys.exit(2)
except Exception as error:
 text=str(error);code=text if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',text) else 'ASSET_OFFLINE_LOCAL_ACQUIRE_REJECTED'
 print(json.dumps({{'stage':'ASSET_OFFLINE_LOCAL_ACQUIRE_REJECTED','code':code,'production_or_host_installation':False}}));sys.exit(1)
EXACT194_PHYSICAL_OFFLINE_LOCAL_ACQUIRE
'''
    if len(command.encode())>=14000:raise RuntimeError('CONSOLE_SAFE_OFFLINE_LOCAL_ACQUIRE_REQUIRED')
    return command,{'loader_sha256':H(body),'loader_bytes':len(body),'derived_resumer_sha256':H(variant),'derived_resumer_bytes':len(variant),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'scope':'media-asset-studio-toolchain-'+H(variant)[:12]+'-20261101','executed':False,'network_fetch_performed':False,'installer_edits':['trusted_sbin_path','local_absolute_deb_acquisition'],'physical_offline_build':True,'production_or_host_installation':False}


def main():
    spec=importlib.util.spec_from_file_location('reviewed_local_acquire_derivation',HERE/'resume_local_acquire.py');scope=importlib.util.module_from_spec(spec);spec.loader.exec_module(scope)
    variant=scope.derive((HERE/'resume_toolchain.py').read_bytes());command,pins=generate((HERE/'resume_local_acquire.py').read_bytes(),variant)
    for name,body in (('resume-local-acquire-command.sh',command.encode()),('resume-local-acquire-freeze.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(HERE/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=='__main__':main()
