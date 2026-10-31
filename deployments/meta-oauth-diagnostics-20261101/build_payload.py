"""Build the exact reviewed application delta using only captured public summary."""
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

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('meta_diagnostic_build_scope', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()


def git(*args): return subprocess.check_output(['git', *args])


def inventory(ref):
    with tarfile.open(fileobj=io.BytesIO(git('archive', ref, 'app/'))) as archive:
        members = archive.getmembers(); r.need(all(item.isdir() or item.isfile() for item in members), 'SOURCE_LINK_OR_SPECIAL_REJECTED')
        r.need(len({item.name for item in members}) == len(members), 'DUPLICATE_SOURCE_MEMBER_REJECTED')
        return {item.name: H(archive.extractfile(item).read()) for item in members if item.isfile()}


def frozen_sources(after):
    blob=r.local_bytes(Path('outputs/meta-oauth-diagnostics-20261101/application-freeze.json'));r.need(H(blob)==r.APPLICATION_FREEZE_SHA,'EXACT_DIAGNOSTIC_APPLICATION_FREEZE_REQUIRED')
    value=json.loads(blob);rows=value['files'];r.need(value['source_sha']==r.SOURCE_SHA and value['frontend_version']==r.FRONTEND and value['baseline_source_sha']==r.BASE_SOURCE and set(rows)==r.SOURCE_FILES,'EXACT_FROZEN_SOURCE_IDENTITIES_REQUIRED')
    r.need(all(after.get(name)==pin and re.fullmatch('[a-f0-9]{64}',pin) for name,pin in rows.items()),'FROZEN_DIAGNOSTIC_SOURCE_DRIFT')
    r.need(value['schema_revision']==r.REVISION and all(value[key] is False for key in ('database_migration','frontend_changed','nginx_changed','runtime_environment_changed','production_seed_rows')),'EXACT_BACKEND_ONLY_FREEZE_REQUIRED')


def build(summary):
    r.pins_ready();r.validate_summary(summary);before,after=inventory(r.BASE_SOURCE),inventory(r.SOURCE_SHA)
    r.need(inventory('HEAD')==after,'HEAD_APPLICATION_TREE_DRIFT');changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
    r.need(changed==r.SOURCE_FILES and set(before)<=set(after),'EXACT_TWO_RUNTIME_AND_TEST_DELTA_REQUIRED');frozen_sources(after)
    for name,pin in after.items():r.need(H(r.local_bytes(Path(name),16*1024**2))==pin,'LOCAL_TRACKED_APPLICATION_SOURCE_DRIFT')
    expected={name for name in after if name.startswith('app/frontend/src/')};actual={str(path) for path in Path('app/frontend/src').rglob('*') if path.is_file() or path.is_symlink()};r.need(expected==actual,'UNTRACKED_FRONTEND_SOURCE_REJECTED')
    backend_before={name:before.get('app/backend/'+name) for name in sorted(r.BACKEND_FILES)};r.need(backend_before==summary['backend_changed_before'],'ACTUAL_BACKEND_BASELINE_DRIFT')
    payload={'backend/'+name:r.local_bytes(Path('app/backend',name),16*1024**2) for name in r.BACKEND_FILES};r.need(len(payload)==2 and sum(map(len,payload.values()))<1024**2,'BOUNDED_TWO_FILE_PAYLOAD_REQUIRED');output=io.BytesIO()
    with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,filename='') as compressed:
        with tarfile.open(fileobj=compressed,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for name,body in sorted(payload.items()):
                item=tarfile.TarInfo(name);item.size=len(body);item.mode=0o644;item.mtime=0;archive.addfile(item,io.BytesIO(body))
    blob=output.getvalue();manifest={'format_version':1,'source_sha':r.SOURCE_SHA,'baseline_source_sha':r.BASE_SOURCE,'frontend_version':r.FRONTEND,'schema_revision':r.REVISION,'application_freeze_sha256':r.APPLICATION_FREEZE_SHA,'preflight_sha256':summary['sha256'],'payload_sha256':H(blob),'changed_source_files':sorted(changed),'backend_before':backend_before,'backend_after':{name:after['app/backend/'+name] for name in sorted(r.BACKEND_FILES)},'files':{name:H(body) for name,body in payload.items()},'protected_source_inventory':{name:pin for name,pin in before.items() if name not in changed},'database_migration':False,'production_seed_rows':False,'credentials_included':False,'frontend_changed':False,'nginx_changed':False,'runtime_environment_changed':False,'existing_meta_and_google_data_preserved':True}
    return blob,manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args();blob,manifest=build(json.loads(r.local_bytes(a.preflight_summary)));a.out.mkdir(parents=True,exist_ok=True)
    for name,body in {'payload.tar.gz':blob,'manifest.json':r.encoded(manifest)}.items():
        with (a.out/name).open('xb') as stream:stream.write(body)
    print(json.dumps({'payload_sha256':H(blob),'manifest_sha256':H(r.encoded(manifest)),'member_count':2,'source_sha':r.SOURCE_SHA,'frontend_changed':False}))

if __name__=='__main__':main()
