#!/usr/bin/env python3
"""Freeze exactly three backend routers from a committed checkout."""
import argparse,gzip,hashlib,importlib.util,io,json,subprocess,tarfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('sales_account_release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
SOURCE=release.SOURCE;BASE=release.BASELINE;BACKEND=release.BACKEND
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def git(*args):return subprocess.check_output(['git',*args])
def inventory(ref):return {name:H(git('show',ref+':'+name)) for name in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 need(args.source==SOURCE and git('rev-parse','HEAD').decode().strip()==SOURCE,'EXACT_SOURCE_HEAD_REQUIRED')
 before,after=inventory(BASE),inventory(SOURCE);changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
 tests={name for name in changed if name.startswith('app/backend/tests/test_') and name.endswith('.py')}
 need(changed-tests=={'app/backend/'+path for path in BACKEND},'SOURCE_SCOPE_DRIFT')
 for path,value in after.items():need(H(Path(path).read_bytes())==value,'WORKING_TREE_DRIFT')
 payload={'backend/'+path:Path('app/backend',path).read_bytes() for path in BACKEND}
 need(sum(map(len,payload.values()))<4*1024**2,'PAYLOAD_LIMIT')
 buffer=io.BytesIO()
 with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for path,body in sorted(payload.items()):
    member=tarfile.TarInfo(path);member.size=len(body);member.mode=0o644;member.mtime=0;archive.addfile(member,io.BytesIO(body))
 manifest={'format_version':1,'source_sha':SOURCE,'baseline_source_sha':BASE,'baseline_application_source':release.BASELINE_APPLICATION_SOURCE,
  'frontend_version':release.FRONTEND_VERSION,'schema_revision':release.REVISION,'backend_only':True,
  'payload_sha256':H(buffer.getvalue()),'credentials_included':False,'preserved':release.PRESERVED,
  'files':{path:H(body) for path,body in payload.items()},
  'backend_before':{path:before['app/backend/'+path] for path in BACKEND},
  'backend_after':{path:after['app/backend/'+path] for path in BACKEND},'changed_source_files':sorted(changed),
  'protected_source_inventory':{path:value for path,value in before.items() if path not in changed}}
 args.out.mkdir(parents=True,exist_ok=True)
 for name,body in {'payload.tar.gz':buffer.getvalue(),'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
  with (args.out/name).open('xb') as stream:stream.write(body)
 print(json.dumps({'source':SOURCE,'backend_files':len(BACKEND),'payload_sha256':manifest['payload_sha256'],'manifest_sha256':H((args.out/'manifest.json').read_bytes())}))
if __name__=='__main__':main()
