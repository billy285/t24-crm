"""Package the exact committed timezone-only frontend correction, locally."""
import argparse,gzip,hashlib,importlib.util,io,json,re,subprocess,tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('timezone_static_scope',ROOT/'static_release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
H=lambda body:hashlib.sha256(body).hexdigest()

def git(*args):return subprocess.check_output(['git',*args])

def inventory(ref):
 return {name:H(git('show',ref+':'+name)) for name in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}

def source_version():
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 code="""const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
 return subprocess.check_output([node,'-e',code,str(Path('app/frontend/src').resolve())]).decode()

def static_name(name):
 p=Path(name)
 if not p.parts or p.is_absolute() or str(p)!=name or '\\' in name or any(x.startswith('.') for x in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--version',required=True);p.add_argument('--post-pilot',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 r.need(bool(re.fullmatch('[a-f0-9]{40}',a.source)) and bool(re.fullmatch('[a-f0-9]{12}',a.version)),'FROZEN_SOURCE_AND_VERSION_REQUIRED')
 before,after=inventory(r.BASE_SOURCE),inventory(a.source)
 r.need(inventory('HEAD')==after,'HEAD_APPLICATION_DRIFT')
 changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
 r.need(changed==r.ALLOWED_SOURCE_FILES,'EXACT_FOUR_TIMEZONE_FILES_REQUIRED')
 r.need(git('rev-parse',r.BASE_SOURCE+':app/backend')==git('rev-parse',a.source+':app/backend'),'BACKEND_TREE_MUST_BE_IDENTICAL')
 for name,value in after.items():
  target=Path(name);r.need(target.is_file() and not target.is_symlink() and H(target.read_bytes())==value,'WORKING_APPLICATION_DRIFT')
 r.need(source_version()==a.version==json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version'],'FRESH_EXACT_FRONTEND_BUILD_REQUIRED')
 proof_body=a.post_pilot.read_bytes();proof=json.loads(proof_body)
 r.need(H(proof_body)==r.POST_PILOT_SHA and proof['verified'] is True and proof['enabled_pilot_binding_ids']==[2,14,18],'EXACT_SUCCESSFUL_REAL_PILOT_PROOF_REQUIRED')
 payload={}
 for path in Path('app/frontend/dist').rglob('*'):
  r.need(not path.is_symlink(),'STATIC_LINK_REJECTED')
  if path.is_file():
   name=str(path.relative_to('app/frontend/dist'));r.need(static_name(name),'STATIC_FILE_SCOPE_REJECTED');payload['static/'+name]=path.read_bytes()
 r.need(sum(map(len,payload.values()))<64*1024**2 and all(len(body)<16*1024**2 for body in payload.values()),'STATIC_PAYLOAD_LIMIT')
 stream=io.BytesIO()
 with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for name,body in sorted(payload.items()):
    member=tarfile.TarInfo(name);member.size=len(body);member.mode=0o644;member.mtime=0;archive.addfile(member,io.BytesIO(body))
 manifest={'format_version':1,'stage':'STRIPE_AUTO_TIMEZONE_STATIC_PACKAGE','source_sha':a.source,'backend_source_sha':r.BASE_SOURCE,'frontend_version':a.version,'previous_frontend_version':r.BASE_VERSION,'changed_source_files':{name:after[name] for name in sorted(changed)},'protected_source_inventory':{name:value for name,value in before.items() if name not in changed},'backend_tree_sha':git('rev-parse',a.source+':app/backend').decode().strip(),'post_pilot_sha256':r.POST_PILOT_SHA,'base_deployed_sha256':r.BASE_DEPLOYED_SHA,'base_public_inventory_sha256':r.BASE_STATIC_SHA,'base_nginx_sha256':r.BASE_NGINX_SHA,'static_only':True,'backend_changes':False,'database_changes':False,'credentials_included':False,'service_changes':False,'environment_changes':False,'payload_sha256':H(stream.getvalue()),'files':{name:H(body) for name,body in payload.items()}}
 a.out.mkdir(parents=True,exist_ok=True)
 for name,body in {'static-payload.tar.gz':stream.getvalue(),'static-manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode(),'post-pilot-baseline.json':proof_body}.items():
  with (a.out/name).open('xb') as target:target.write(body)
 print(json.dumps({'source_sha':a.source,'backend_source_sha':r.BASE_SOURCE,'frontend_version':a.version,'backend_tree_unchanged':True,'changed_files':sorted(changed),'payload_sha256':manifest['payload_sha256'],'manifest_sha256':H((a.out/'static-manifest.json').read_bytes()),'payload_bytes':len(stream.getvalue())}))

if __name__=='__main__':main()
