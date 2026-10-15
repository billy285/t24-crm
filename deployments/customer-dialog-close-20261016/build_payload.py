#!/usr/bin/env python3
"""Freeze one customer dialog source edit as a static-only release."""
import argparse,gzip,hashlib,importlib.util,io,json,subprocess,tarfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('customer_close_release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
SOURCE=release.SOURCE;FRONTEND_VERSION=release.FRONTEND_VERSION;BASE=release.BASELINE
FRONTEND={'pages/Customers.tsx'}
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def git(*args):return subprocess.check_output(['git',*args])
def inventory(ref):return {name:H(git('show',ref+':'+name)) for name in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 need(args.source==SOURCE and git('rev-parse','HEAD').decode().strip()==SOURCE,'EXACT_SOURCE_HEAD_REQUIRED')
 before,after=inventory(BASE),inventory(SOURCE);changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
 tests={name for name in changed if name=='app/frontend/tests/customers-dialog-close.spec.ts'}
 need(changed-tests=={'app/frontend/src/'+path for path in FRONTEND},'SOURCE_SCOPE_DRIFT')
 need(len(tests)==1,'EXACT_REGRESSION_TEST_REQUIRED')
 for path,value in after.items():need(H(Path(path).read_bytes())==value,'WORKING_TREE_DRIFT')
 need(json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version']==FRONTEND_VERSION,'EXACT_FRONTEND_REQUIRED')
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 script="""const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
 need(subprocess.check_output([node,'-e',script,str(Path('app/frontend/src').resolve())]).decode()==FRONTEND_VERSION,'BUILD_SOURCE_VERSION_DRIFT')
 payload={}
 for path in Path('app/frontend/dist').rglob('*'):
  need(not path.is_symlink(),'SYMLINK_REJECTED')
  if path.is_file():
   name=str(path.relative_to('app/frontend/dist'));need(release.static_path(name),'STATIC_PATH_REJECTED');payload['static/'+name]=path.read_bytes()
 need(sum(map(len,payload.values()))<64*1024**2 and all(len(body)<16*1024**2 for body in payload.values()),'PAYLOAD_LIMIT')
 buffer=io.BytesIO()
 with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for path,body in sorted(payload.items()):
    member=tarfile.TarInfo(path);member.size=len(body);member.mode=0o644;member.mtime=0;archive.addfile(member,io.BytesIO(body))
 manifest={'format_version':1,'source_sha':SOURCE,'baseline_source_sha':BASE,'frontend_version':FRONTEND_VERSION,
  'baseline_frontend_version':release.BASELINE_FRONTEND,'static_only':True,'payload_sha256':H(buffer.getvalue()),
  'files':{path:H(body) for path,body in payload.items()},'preserved':release.PRESERVED,
  **dict.fromkeys(release.FALSE_FLAGS,False),'changed_source_files':sorted(changed),
  'protected_source_inventory':{path:value for path,value in before.items() if path not in changed}}
 args.out.mkdir(parents=True,exist_ok=True)
 for name,body in {'payload.tar.gz':buffer.getvalue(),'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
  with (args.out/name).open('xb') as stream:stream.write(body)
 print(json.dumps({'source':SOURCE,'frontend_version':FRONTEND_VERSION,'payload_sha256':manifest['payload_sha256'],'manifest_sha256':H((args.out/'manifest.json').read_bytes())}))
if __name__=='__main__':main()
