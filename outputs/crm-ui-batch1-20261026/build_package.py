"""Freeze the explicitly reviewed UI sources and a fresh static payload."""
import argparse,base64,gzip,hashlib,importlib.util,io,json,re,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('crm_ui_batch1_baseline',ROOT/'baseline.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
H=lambda x:hashlib.sha256(x).hexdigest()
BEFORE='02b9b6c6533d9141e43b94ab0b51393d19d1e6b6'
def ui_source(name):
 if not isinstance(name,str):return False
 p=Path(name)
 return str(p)==name and '\\' not in name and not p.is_absolute() and len(p.parts)>=5 and p.parts[:3]==('app','frontend','src') and p.parts[3] in {'components','pages'} and p.suffix in {'.tsx','.ts','.css'} and not any(part.startswith('.') for part in p.parts) and not any(token in name.lower() for token in ('private','permission','auth','token','session','payment-utils','subscription-utils','commission','payroll'))
def read_allowlist(path):
 names=json.loads(path.read_bytes());b.need(isinstance(names,list) and 0<len(names)<=32 and all(ui_source(n) for n in names) and len(names)==len(set(names)),'EXACT_SAFE_UI_ALLOWLIST_REQUIRED')
 return sorted(names)
def git(*args):return subprocess.check_output(['git',*args])
def inventory(ref):
 with tarfile.open(fileobj=io.BytesIO(git('archive',ref,'app/'))) as archive:
  return {f.name:H(archive.extractfile(f).read()) for f in archive if f.isfile()}
def source_version(ref=None):
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 if ref:
  prefix='app/frontend/src/'
  with tarfile.open(fileobj=io.BytesIO(git('archive',ref,prefix))) as archive:
   files={f.name[len(prefix):]:base64.b64encode(archive.extractfile(f).read()).decode() for f in archive if f.isfile() and f.name.startswith(prefix)}
  code="const fs=require('node:fs'),c=require('node:crypto'),h=c.createHash('sha256'),files=JSON.parse(fs.readFileSync(0,'utf8'));function walk(prefix){const entries=new Map();for(const name of Object.keys(files)){if(!name.startsWith(prefix))continue;const rest=name.slice(prefix.length),slash=rest.indexOf('/');entries.set(slash<0?rest:rest.slice(0,slash),slash>=0);}for(const [name,dir] of [...entries].sort((a,b)=>a[0].localeCompare(b[0]))){const full=prefix+name;if(dir)walk(full+'/');else{h.update(full);h.update(Buffer.from(files[full],'base64'));}}}walk('');process.stdout.write(h.digest('hex').slice(0,12));"
  return subprocess.check_output([node,'-e',code],input=json.dumps(files).encode()).decode()
 code="const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"
 return subprocess.check_output([node,'-e',code,str(Path('app/frontend/src').resolve())]).decode()
def main(a):
 b.need(all(re.fullmatch('[a-f0-9]{40}',v) for v in (a.source,a.before)),'FROZEN_COMMIT_REQUIRED')
 b.need(a.before==BEFORE,'EXACT_REVIEWED_BEFORE_COMMIT_REQUIRED')
 allowed=read_allowlist(a.allowlist);allowlist_body=(json.dumps(allowed,sort_keys=True,indent=2)+'\n').encode()
 before,after=inventory(a.before),inventory(a.source);b.need(inventory('HEAD')==after,'HEAD_APPLICATION_DRIFT')
 changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)};b.need(changed==set(allowed),'EXACT_REVIEWED_UI_FILES_REQUIRED')
 b.need(set(allowed)<=set(after),'UI_SOURCE_DELETIONS_REJECTED')
 b.need(git('rev-parse',a.before+':app/backend')==git('rev-parse',a.source+':app/backend'),'UNCHANGED_BACKEND_TREE_REQUIRED')
 for n,v in after.items():
  path=Path(n);b.need(path.is_file() and not path.is_symlink() and H(path.read_bytes())==v,'WORKING_SOURCE_DIFFERS_FROM_COMMIT')
 version=source_version();b.need(json.loads(Path('app/frontend/dist/app-version.json').read_bytes())=={'version':version},'FRESH_EXACT_BUILD_REQUIRED')
 b.need(source_version(a.source)==version,'WORKING_SOURCE_FINGERPRINT_DIFFERS_FROM_COMMIT')
 baseline_body=a.baseline.read_bytes();baseline=json.loads(baseline_body)
 b.need(baseline['stage']=='CRM_UI_BATCH1_FRESH_READONLY_BASELINE' and baseline['frontend_version']!=version,'FRESH_BASELINE_AND_NEW_BUILD_REQUIRED')
 b.need(source_version(a.before)==baseline['frontend_version'],'BEFORE_COMMIT_MUST_MATCH_ACTUAL_PUBLISHED_FRONTEND')
 behavior_input={'files':{name:{'before':git('show',a.before+':'+name).decode() if name in before else '', 'after':git('show',a.source+':'+name).decode()} for name in allowed if name.endswith(('.ts','.tsx'))}}
 behavior=json.loads(subprocess.check_output(['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')],input=json.dumps(behavior_input).encode()))
 b.need(behavior['unchanged'] is True,'PROTECTED_UI_BEHAVIOR_DRIFT')
 files={}
 for p in Path('app/frontend/dist').rglob('*'):
  b.need(not p.is_symlink(),'STATIC_LINK_REJECTED')
  if p.is_file():
   name=str(p.relative_to('app/frontend/dist'));b.need(b.static_path(name),'STATIC_PATH_REJECTED');files['static/'+name]=p.read_bytes()
 b.need(sum(map(len,files.values()))<64*1024**2 and all(len(v)<16*1024**2 for v in files.values()),'STATIC_PACKAGE_TOO_LARGE')
 stream=io.BytesIO()
 with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for name,body in sorted(files.items()):
    entry=tarfile.TarInfo(name);entry.mode=0o644;entry.size=len(body);entry.mtime=0;archive.addfile(entry,io.BytesIO(body))
 payload=stream.getvalue()
 manifest={'stage':'CRM_UI_BATCH1_STATIC_PACKAGE','source_sha':a.source,'baseline_source_sha':a.before,'frontend_version':version,'previous_frontend_version':baseline['frontend_version'],
  'changed_source_files':{n:after[n] for n in sorted(changed)},'protected_source_inventory':{n:v for n,v in before.items() if n not in changed},
  'source_allowlist_sha256':H(allowlist_body),'protected_behavior':behavior,'private_source_changes':False,'permission_source_changes':False,
  'backend_tree_sha':git('rev-parse',a.source+':app/backend').decode().strip(),'baseline_sha256':H(baseline_body),'payload_sha256':H(payload),
  'files':{n:H(v) for n,v in files.items()},'static_only':True,'backend_changes':False,'database_changes':False,'service_changes':False,'credentials_included':False}
 a.out.mkdir(parents=True,exist_ok=True)
 for n,body in {'baseline.json':baseline_body,'source-allowlist.json':allowlist_body,'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode(),'payload.tar.gz':payload}.items():
  with (a.out/n).open('xb') as f:f.write(body)
 print(json.dumps({'source_sha':a.source,'frontend_version':version,'manifest_sha256':H((a.out/'manifest.json').read_bytes()),'payload_sha256':H(payload),'baseline_sha256':H(baseline_body),'payload_bytes':len(payload)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--before',required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--allowlist',type=Path,required=True);p.add_argument('--out',type=Path,required=True);main(p.parse_args())
