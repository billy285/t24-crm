#!/usr/bin/env python3
"""Freeze a scoped customer authorization release from an exact committed checkout."""
import argparse,gzip,hashlib,io,json,re,subprocess,tarfile
from pathlib import Path
BASE='9bbdb299feb0e24a04bf31400cc094e88e48ba56'
BACKEND={'alembic/versions/c4a8f2d6e714_customer_permission_boundaries.py', 'dependencies/auth.py', 'models/customer_access_grants.py', 'models/customer_materials.py', 'models/customer_record_audits.py', 'models/customers.py', 'routers/app_config.py', 'routers/commissions.py', 'routers/company_roadmap.py', 'routers/customer_ai_copies.py', 'routers/customer_callbacks.py', 'routers/customer_contacts.py', 'routers/customer_finance_access.py', 'routers/customer_lifecycle.py', 'routers/customer_materials.py', 'routers/customer_menu_items.py', 'routers/customers.py', 'routers/deals.py', 'routers/emp_auth.py', 'routers/employees.py', 'routers/follow_ups.py', 'routers/management_decisions.py', 'routers/media_accounts.py', 'routers/operation_logs.py', 'routers/opportunities.py', 'routers/payroll.py', 'routers/sales_leads.py', 'routers/service_progresses.py', 'routers/service_tasks.py', 'routers/settings.py', 'routers/subscriptions.py', 'routers/tasks.py', 'services/customer_ai_context.py', 'services/customer_ai_copies.py', 'services/customer_callbacks.py', 'services/customer_contacts.py', 'services/customer_materials.py', 'services/customer_menu_items.py', 'services/customer_permissions.py', 'services/customer_record_audit.py', 'services/customer_scope.py', 'services/customers.py', 'services/deals.py', 'services/follow_ups.py', 'services/media_accounts.py', 'services/operation_logs.py', 'services/role_permissions.py', 'services/service_progresses.py', 'services/service_tasks.py', 'services/subscriptions.py', 'services/tasks.py'}
FRONTEND={'components/CustomerAccessPanel.tsx', 'components/CustomerAiCopyTab.tsx', 'components/CustomerFinanceSummary.tsx', 'components/CustomerMaterialsTab.tsx', 'components/CustomerOpportunitiesTab.tsx', 'components/CustomerPrivateNote.tsx', 'components/CustomerRecordHistory.tsx', 'components/ExportButton.tsx', 'components/MediaAccountsTab.tsx', 'components/MobileAppHome.tsx', 'components/customer-access.css', 'lib/app-navigation.ts', 'lib/customer-permissions.ts', 'lib/permissions.ts', 'lib/use-customer-permissions.ts', 'pages/Customers.tsx', 'pages/Employees.tsx', 'pages/Permissions.tsx', 'pages/Settings.tsx'}
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
 manifest={'format_version':1,'source_sha':a.source,'baseline_source_sha':BASE,'frontend_version':version,'baseline_frontend_version':'b1e7a42a7656','payload_sha256':H(buf.getvalue()),'files':{n:H(b) for n,b in payload.items()},'backend_before':{n:before.get('app/backend/'+n) for n in BACKEND},'backend_after':{n:after['app/backend/'+n] for n in BACKEND},'changed_source_files':sorted(changed),'protected_source_inventory':{n:h for n,h in before.items() if n not in changed},'preserved':{'company_finance_formulas':True,'close_conditions':True,'private_workspace':True},'credentials_included':False}
 a.out.mkdir(parents=True,exist_ok=True)
 for n,b in {'payload.tar.gz':buf.getvalue(),'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
  with (a.out/n).open('xb') as f:f.write(b)
 print(json.dumps({'source':a.source,'version':version,'payload_sha256':manifest['payload_sha256'],'manifest_sha256':H((a.out/'manifest.json').read_bytes()),'protected_files':len(manifest['protected_source_inventory'])}))
if __name__=='__main__':main()
