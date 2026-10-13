#!/usr/bin/env python3
"""Freeze a scoped commission release from an exact committed checkout."""
import argparse,gzip,hashlib,io,json,re,subprocess,tarfile
from pathlib import Path
BASE='6e2381a1b96465097e03c760d893f519133d733e'
BACKEND={'models/commissions.py','routers/commissions.py','routers/employees.py','services/commissions.py','services/partner_portal.py','alembic/versions/b3e7c1d9a614_commission_service_month_rules.py'}
FRONTEND={'pages/Commissions.tsx','pages/PartnerPortal.tsx','pages/Employees.tsx','pages/commissions.css','lib/commission-presentation.ts'}
H=lambda b:hashlib.sha256(b).hexdigest()
def static_path(name):
 p=Path(name)
 if not p.parts or p.is_absolute() or str(p)!=name or '\\' in name or any(part.startswith('.') for part in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch('workbox-[a-zA-Z0-9_-]+\\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}
def need(ok,code):
 if not ok:raise RuntimeError(code)
def git(*a):return subprocess.check_output(['git',*a])
def inventory(ref):
 return {n:H(git('show',ref+':'+n)) for n in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
 need(git('rev-parse','HEAD').decode().strip()==a.source,'HEAD_DRIFT')
 before,after=inventory(BASE),inventory(a.source)
 allowed={f'app/backend/{n}' for n in BACKEND}|{f'app/frontend/src/{n}' for n in FRONTEND}
 changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}
 tests={n for n in changed if n.startswith('app/backend/tests/test_') or n.startswith('app/frontend/tests/')}
 need(changed-tests==allowed,'SOURCE_SCOPE_DRIFT')
 for n,h in after.items():need(H(Path(n).read_bytes())==h,'WORKING_TREE_DRIFT')
 version=json.loads(Path('app/frontend/dist/app-version.json').read_text())['version']
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 script="""const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
 need(subprocess.check_output([node,'-e',script,str(Path('app/frontend/src').resolve())]).decode()==version,'BUILD_SOURCE_VERSION_DRIFT')
 payload={}
 for p in Path('app/frontend/dist').rglob('*'):
  need(not p.is_symlink(),'SYMLINK_REJECTED')
  if p.is_file():
   name=str(p.relative_to('app/frontend/dist'));need(static_path(name),'STATIC_PATH_REJECTED')
   payload['static/'+name]=p.read_bytes()
 for n in BACKEND:payload['backend/'+n]=Path('app/backend',n).read_bytes()
 need(sum(map(len,payload.values()))<64*1024**2,'PAYLOAD_LIMIT')
 need(all(len(value)<16*1024**2 for value in payload.values()),'PAYLOAD_MEMBER_LIMIT')
 buf=io.BytesIO()
 with gzip.GzipFile(fileobj=buf,mode='wb',mtime=0,filename='') as z:
  with tarfile.open(fileobj=z,mode='w',format=tarfile.USTAR_FORMAT) as t:
   for n,b in sorted(payload.items()):
    ti=tarfile.TarInfo(n);ti.size=len(b);ti.mode=0o644;ti.mtime=0;t.addfile(ti,io.BytesIO(b))
 manifest={'format_version':1,'source_sha':a.source,'baseline_source_sha':BASE,'frontend_version':version,'baseline_frontend_version':'2b5eb3d9a00f','payload_sha256':H(buf.getvalue()),'files':{n:H(b) for n,b in payload.items()},'backend_before':{n:before.get('app/backend/'+n) for n in BACKEND},'backend_after':{n:after['app/backend/'+n] for n in BACKEND},'changed_source_files':sorted(changed),'protected_source_inventory':{n:h for n,h in before.items() if n not in changed},'preserved':{'company_finance_formulas':True,'close_conditions':True,'private_workspace':True},'credentials_included':False}
 a.out.mkdir(parents=True,exist_ok=True)
 for n,b in {'payload.tar.gz':buf.getvalue(),'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
  with (a.out/n).open('xb') as f:f.write(b)
 print(json.dumps({'source':a.source,'version':version,'payload_sha256':manifest['payload_sha256'],'manifest_sha256':H((a.out/'manifest.json').read_bytes()),'protected_files':len(manifest['protected_source_inventory'])}))
if __name__=='__main__':main()
