"""Build only the exact two backend patches plus compiled static bundle."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('review_refresh_scope',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
H=lambda value:hashlib.sha256(value).hexdigest()


def git(*args):return subprocess.check_output(['git',*args])


def inventory(ref):
    with tarfile.open(fileobj=io.BytesIO(git('archive',ref,'app/'))) as archive:
        members=archive.getmembers();r.need(all(m.isdir() or m.isfile() for m in members),'SOURCE_LINK_OR_SPECIAL_REJECTED')
        return {m.name:H(archive.extractfile(m).read()) for m in members if m.isfile()}


def frontend_version():
    node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    code="const fs=require('node:fs'),p=require('node:path'),h=require('node:crypto').createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){const q=p.join(d,e.name);if(e.isSymbolicLink())throw Error('link');if(e.isDirectory())walk(q);else if(e.isFile()){h.update(p.relative(root,q));h.update(fs.readFileSync(q));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"
    return subprocess.check_output([node,'-e',code,str(Path('app/frontend/src').resolve())]).decode()


def static_path(name):
    parts=Path(name).parts
    if not parts or Path(name).is_absolute() or '\\' in name or any(p.startswith('.') for p in parts):return False
    if len(parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or Path(name).suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js',name))
    return parts[0]=='assets' and Path(name).suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}


def build(summary):
    r.need(summary['stage']=='MEDIA_OPS_REVIEW_REFRESH_PREFLIGHT_CAPTURED' and summary['source_sha']==r.BASE_SOURCE and summary['frontend_version']==r.BASE_FRONTEND and summary['schema_revision']==r.REVISION and summary['table_count']==129,'EXACT_ACTUAL_PREFLIGHT_SUMMARY_REQUIRED')
    r.need(summary['deployed_sha256']==r.BASE_DEPLOYED_SHA and summary['private_boundary_verified'] is True and summary['credential_content_read'] is False and summary['private_content_read'] is False,'EXACT_BASE_DEPLOYMENT_PRIVACY_REQUIRED')
    r.need(summary['scheduler_disabled'] is True and summary['gbp_feature_enabled'] is True and summary['callback_logging_protection_retained'] is True and summary['executed_business_writes'] is False,'EXACT_PREFLIGHT_BOUNDARIES_REQUIRED')
    proof_sha=summary['sha256'];r.need(re.fullmatch('[a-f0-9]{64}',proof_sha) and summary['path']=='/opt/t24-crm/releases/media-ops-review-refresh-preflight-'+proof_sha[:12]+'.json','EXACT_SERVER_PROOF_PATH_REQUIRED')
    before,after=inventory(r.BASE_SOURCE),inventory(r.SOURCE_SHA);r.need(inventory('HEAD')==after,'SOURCE_HEAD_APPLICATION_DRIFT')
    changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)};r.need(changed==r.SOURCE_FILES,'EXACT_FOUR_APPLICATION_FILES_REQUIRED')
    for n,pin in after.items():
        p=Path(n);r.need(p.is_file() and not p.is_symlink() and H(p.read_bytes())==pin,'LOCAL_APPLICATION_SOURCE_DRIFT')
    expected={n for n in after if n.startswith('app/frontend/src/')};actual={str(p) for p in Path('app/frontend/src').rglob('*') if p.is_file() or p.is_symlink()}
    r.need(actual==expected,'UNCOMMITTED_FRONTEND_SOURCE_REJECTED')
    backend_before={n:before['app/backend/'+n] for n in sorted(r.BACKEND_FILES)};r.need(summary['backend_changed_before']==backend_before,'ACTUAL_RUNTIME_SOURCE_BASELINE_DRIFT')
    r.need(frontend_version()==r.FRONTEND and json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version']==r.FRONTEND,'EXACT_NEW_FRONTEND_BUILD_REQUIRED')
    payload={'backend/'+n:Path('app/backend',n).read_bytes() for n in r.BACKEND_FILES}
    for p in Path('app/frontend/dist').rglob('*'):
        r.need(not p.is_symlink(),'DIST_LINK_REJECTED')
        if p.is_file():
            name=str(p.relative_to('app/frontend/dist'));r.need(static_path(name),'DIST_PATH_REJECTED');payload['static/'+name]=p.read_bytes()
    r.need(sum(map(len,payload.values()))<64*1024**2 and all(len(b)<16*1024**2 for b in payload.values()),'EXACT_PAYLOAD_LIMIT')
    output=io.BytesIO()
    with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,filename='') as compressed:
        with tarfile.open(fileobj=compressed,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for n,b in sorted(payload.items()):
                info=tarfile.TarInfo(n);info.size=len(b);info.mode=0o644;info.mtime=0;archive.addfile(info,io.BytesIO(b))
    blob=output.getvalue();manifest={'format_version':1,'source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'baseline_source_sha':r.BASE_SOURCE,'baseline_frontend_version':r.BASE_FRONTEND,'schema_revision':r.REVISION,'database_migration':False,'production_seed_rows':False,'credentials_included':False,'preflight_sha256':proof_sha,'payload_sha256':H(blob),'changed_source_files':sorted(changed),'backend_before':backend_before,'backend_after':{n:after['app/backend/'+n] for n in sorted(r.BACKEND_FILES)},'files':{n:H(b) for n,b in payload.items()},'protected_source_inventory':{n:pin for n,pin in before.items() if n not in changed}}
    return blob,manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    blob,manifest=build(json.loads(a.preflight_summary.read_bytes()));a.out.mkdir(parents=True,exist_ok=True)
    for n,b in {'payload.tar.gz':blob,'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
        with (a.out/n).open('xb') as stream:stream.write(b)
    print(json.dumps({'source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'backend_files':sorted(r.BACKEND_FILES),'payload_sha256':H(blob),'manifest_sha256':H((a.out/'manifest.json').read_bytes()),'database_migration':False}))


if __name__=='__main__':main()
