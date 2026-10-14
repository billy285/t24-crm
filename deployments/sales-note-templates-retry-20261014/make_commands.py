#!/usr/bin/env python3
"""Generate pinned acquisition/activation commands; never run them."""
import argparse
import hashlib
import json
import re
from pathlib import Path

DIRECTORY = 'deployments/sales-note-templates-retry-20261014'
H = lambda body: hashlib.sha256(body).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--carrier', required=True)
    parser.add_argument('--preflight', required=True)
    parser.add_argument('--preflight-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared-receipt', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{40}', args.carrier) or not re.fullmatch(r'[a-f0-9]{64}', args.preflight_sha256):
        raise RuntimeError('EXACT_CARRIER_AND_PREFLIGHT_REQUIRED')
    if not re.fullmatch(r'/opt/t24-crm/releases/[a-zA-Z0-9_.-]+\.json', args.preflight):
        raise RuntimeError('PROTECTED_PREFLIGHT_PATH_REQUIRED')
    directory = Path(DIRECTORY)
    manifest = json.loads((directory / 'artifacts/manifest.json').read_bytes())
    source = manifest['source_sha']
    if not re.fullmatch(r'[a-f0-9]{40}', source):
        raise RuntimeError('EXACT_SOURCE_REQUIRED')
    release = '/opt/t24-crm/releases/sales-note-templates-retry-' + source[:12] + '-20261014'
    files = {}
    for source_path, target in [('release.py', 'release.py'), ('artifacts/manifest.json', 'manifest.json'), ('artifacts/payload.tar.gz', 'payload.tar.gz')]:
        body = (directory / source_path).read_bytes()
        files[source_path] = (target, H(body), len(body))
    args.out.mkdir(parents=True, exist_ok=True)
    common = ['--release', release, '--manifest-sha256', files['artifacts/manifest.json'][1],
              '--payload-sha256', files['artifacts/payload.tar.gz'][1], '--preflight', args.preflight,
              '--preflight-sha256', args.preflight_sha256]
    script = f'''#!/bin/bash
set -eu
sudo python3 - <<'PY'
import hashlib,json,os,re,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
try:
 sys.dont_write_bytecode=True;os.umask(0o077)
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 carrier={args.carrier!r};files={files!r};release=Path({release!r})
 for parent in release.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED')
 selected={{}}
 for name,(target,expected,size) in files.items():
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  with urllib.request.build_opener(NoRedirect()).open(url,timeout=60) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'CARRIER_MEMBER_HASH_DRIFT');selected[target]=body
 manifest=json.loads(selected['manifest.json'])
 need(manifest['source_sha']=={source!r} and manifest['frontend_version']=={manifest['frontend_version']!r} and manifest['credentials_included'] is False and manifest['database_schema_changes'] is False and manifest['production_row_changes'] is False and manifest['static_only'] is True and manifest['backend_changes'] is False and manifest['services_modified'] is False and manifest['environment_modified'] is False and all(manifest['preserved'].values()),'SCOPE_DRIFT')
 release.mkdir(mode=0o700)
 for target,body in selected.items():
  descriptor=os.open(release/target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(descriptor,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 helper=release/'release.py';need(H(helper.read_bytes())==files['release.py'][1],'HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase','prepare',*{common!r}]
 namespace={{'__name__':'pinned_merchant_industry_release','__file__':str(helper)}}
 exec(compile(helper.read_bytes(),str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'SALES_NOTE_TEMPLATES_RETRY_ACQUISITION_REJECTED','code':code}}));sys.exit(1)
PY
'''
    (args.out / 'prepare-command.sh').write_text(script)
    pins = {'carrier': args.carrier, 'source': source, 'version': manifest['frontend_version'], 'files': files,
            'release': release, 'preflight': args.preflight, 'preflight_sha256': args.preflight_sha256}
    if args.prepared_receipt:
        receipt_bytes = args.prepared_receipt.read_bytes()
        receipt = json.loads(receipt_bytes)
        if receipt['source_sha'] != source or receipt['version'] != manifest['frontend_version'] or receipt['manifest_sha256'] != files['artifacts/manifest.json'][1] or receipt['payload_sha256'] != files['artifacts/payload.tar.gz'][1] or receipt['preflight_sha256'] != args.preflight_sha256:
            raise RuntimeError('PREPARED_RECEIPT_IDENTITY_DRIFT')
        # The caller must save prepared.json's exact bytes, without stdout wrappers.
        review = H(receipt_bytes)
        pins['prepared_sha256'] = review
        for phase in ('activate', 'recover'):
            code = f'''#!/bin/bash
set -eu
sudo python3 - <<'PY'
import hashlib,json,re,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True
 helper=Path({(release + '/release.py')!r});body=helper.read_bytes()
 if hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase',{phase!r},*{common!r},'--review-sha256',{review!r}]
 namespace={{'__name__':'pinned_merchant_industry_{phase}','__file__':str(helper)}}
 exec(compile(body,str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'SALES_NOTE_TEMPLATES_RETRY_{phase.upper()}_REJECTED','code':code}}));sys.exit(1)
PY
'''
            (args.out / (phase + '-command.sh')).write_text(code)
    (args.out / 'package-pins.json').write_text(json.dumps(pins, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'commands_generated': True, 'source': source, 'version': manifest['frontend_version'], 'activation_generated': bool(args.prepared_receipt)}))


if __name__ == '__main__':
    main()
