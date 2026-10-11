#!/usr/bin/env python3
"""Local deterministic static-only carrier; never packages backend or secrets."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

SOURCE = '30d9748a43f7a5d021968b2bc69704172b6487c4'
VERSION = '54da68143ed2'
SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico', '.txt', '.woff', '.woff2', '.ttf', '.webmanifest'}

def need(condition, code):
    if not condition:
        raise RuntimeError(code)

def main(args):
    need(re.fullmatch('[a-f0-9]{40}',SOURCE) and re.fullmatch('[a-f0-9]{12}',VERSION),'REVIEWED_CONSTANTS_REQUIRED')
    repo=args.repo.resolve(); output=args.output.resolve(); dist=repo/'app/frontend/dist'
    need(output.is_dir() and not output.is_symlink(),'OUTPUT_DIRECTORY_REQUIRED')
    need(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==SOURCE,'EXACT_SOURCE_REQUIRED')
    need(not subprocess.check_output(['git','status','--porcelain','--untracked-files=no','--','app/frontend'],cwd=repo,text=True).strip(),'TRACKED_FRONTEND_CHANGES_REJECTED')
    css=repo/'app/frontend/src/pages/private-workspace.css'
    need(css.read_bytes()==subprocess.check_output(['git','show',SOURCE+':app/frontend/src/pages/private-workspace.css'],cwd=repo),'CSS_SOURCE_DRIFT')
    need(json.loads((dist/'app-version.json').read_text())=={'version':VERSION},'BUILD_VERSION_DRIFT')
    files={}
    for path in sorted(dist.rglob('*')):
        need(not path.is_symlink(),'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir(): continue
        relative=path.relative_to(dist)
        need(path.is_file() and path.suffix in SUFFIXES and not any(p.startswith('.') for p in relative.parts),'NON_STATIC_FILE')
        need(path.suffix!='.html' or relative.as_posix() in {'index.html','offline.html'},'UNEXPECTED_HTML')
        files[relative.as_posix()]=path.read_bytes()
    need({'index.html','app-version.json'}<=set(files) and len(files)<10000 and sum(map(len,files.values()))<64*1024**2,'STATIC_PAYLOAD_LIMIT')
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w') as archive:
        for name,blob in sorted(files.items()):
            info=tarfile.TarInfo('payload/'+name); info.size=len(blob); info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(blob))
    target=output/'static-payload.tar.gz'
    with target.open('xb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as encoded: encoded.write(buffer.getvalue())
    target.chmod(0o600)
    manifest={'source_sha':SOURCE,'frontend_version':VERSION,'payload_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'payload_files':{n:hashlib.sha256(b).hexdigest() for n,b in sorted(files.items())},
              'backend_changes':False,'credentials_included':False,'static_only':True}
    destination=output/'static-manifest.json'
    with destination.open('x') as stream: stream.write(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    destination.chmod(0o600)
    print(json.dumps({'manifest_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'payload_sha256':manifest['payload_sha256'],'static_files':len(files),'backend_changes':False}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args())
