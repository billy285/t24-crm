#!/usr/bin/env python3
"""Freeze exactly one committed backend service and no frontend or database changes."""
import argparse,gzip,hashlib,importlib.util,io,json,re,subprocess,tarfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('sales_account_release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
SOURCE=release.SOURCE;BASE=release.BASELINE;BACKEND=release.BACKEND
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def git(*args):return subprocess.check_output(['git',*args])
def inventory(ref):return {name:H(git('show',ref+':'+name)) for name in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}
def source_version():
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 script="""const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
 return subprocess.check_output([node,'-e',script,str(Path('app/frontend/src').resolve())]).decode()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 need(bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{64}',release.LIVE_PREFLIGHT_SHA)) and args.source==SOURCE and bool(re.fullmatch('[a-f0-9]{12}',release.FRONTEND_VERSION)) and git('rev-parse','HEAD').decode().strip()==SOURCE,'EXACT_SOURCE_HEAD_REQUIRED')
 before,after=inventory(BASE),inventory(SOURCE);changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
 tests=release.TESTS;frontend={'app/frontend/src/'+path for path in release.FRONTEND}
 need(changed=={'app/backend/'+path for path in BACKEND}|frontend|tests,'EXACT_SOURCE_SCOPE_REQUIRED')
 need(changed-tests=={'app/backend/'+path for path in BACKEND}|frontend,'SOURCE_SCOPE_DRIFT')
 for path,value in after.items():need(H(Path(path).read_bytes())==value,'WORKING_TREE_DRIFT')
 need(before['app/frontend/src/pages/Finance.tsx']==after['app/frontend/src/pages/Finance.tsx'],'ORIGINAL_FINANCE_SOURCE_CHANGED')
 need(source_version()==release.FRONTEND_VERSION==json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version'],'EXACT_FRONTEND_BUILD_REQUIRED')
 payload={'backend/'+path:Path('app/backend',path).read_bytes() for path in BACKEND}
 for path in Path('app/frontend/dist').rglob('*'):
  need(not path.is_symlink(),'DIST_LINK_REJECTED')
  if path.is_file():
   name=str(path.relative_to('app/frontend/dist'));need(release.static_path(name),'DIST_PATH_REJECTED');payload['static/'+name]=path.read_bytes()
 need(sum(map(len,payload.values()))<64*1024**2 and all(len(body)<16*1024**2 for body in payload.values()),'PAYLOAD_LIMIT')
 buffer=io.BytesIO()
 with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for path,body in sorted(payload.items()):
    member=tarfile.TarInfo(path);member.size=len(body);member.mode=0o644;member.mtime=0;archive.addfile(member,io.BytesIO(body))
 manifest={'format_version':1,'source_sha':SOURCE,'baseline_source_sha':BASE,'baseline_application_source':release.BASELINE_APPLICATION_SOURCE,
  'frontend_version':release.FRONTEND_VERSION,'baseline_frontend_version':release.BASELINE_FRONTEND,'schema_revision':release.REVISION,'backend_only':False,'static_transition':True,
  'live_preflight_sha256':release.LIVE_PREFLIGHT_SHA,'baseline_backend_inventory_sha256':release.BASE_BACKEND_SHA,
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
