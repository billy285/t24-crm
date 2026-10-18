#!/usr/bin/env python3
"""Freeze only this committed handoff source and its matching frontend build."""
import argparse,gzip,hashlib,importlib.util,io,json,re,subprocess,tarfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('handoff_release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
TESTS=release.TESTS
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def git(*args):return subprocess.check_output(['git',*args])
def inventory(ref):return {p:H(git('show',ref+':'+p)) for p in git('ls-tree','-r','--name-only',ref,'--','app/').decode().splitlines()}
def scope(before,after):
 changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
 allowed={'app/backend/'+p for p in release.BACKEND}|{'app/frontend/src/'+p for p in release.FRONTEND}
 need(changed==allowed|TESTS,'EXACT_SOURCE_SCOPE_REQUIRED');return changed
def source_version():
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 script="""const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
 return subprocess.check_output([node,'-e',script,str(Path('app/frontend/src').resolve())]).decode()
def finance_body(source,name):
 node='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
 script="""const ts=require(process.argv[1]),name=process.argv[2];let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{const sf=ts.createSourceFile('Finance.tsx',s,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),found=sf.statements.filter(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);if(found.length!==1||!found[0].body)process.exit(2);process.stdout.write(s.slice(found[0].body.pos,found[0].body.end));});"""
 return subprocess.check_output([node,'-e',script,str(Path('app/frontend/node_modules/typescript').resolve()),name],input=source)
def finance_source_unchanged(before,after):
 # Remove only the exact approved import and routing wrapper, then compare all original bytes.
 added_import=b"import StripeHistoryReconciliation from '@/components/StripeHistoryReconciliation';\n"
 wrapper=b"export default function Finance() {\n  const [params] = useSearchParams();\n  if (params.get('tab') === 'stripe_reconciliation') return <div className=\"app-page\"><StripeHistoryReconciliation /></div>;\n  return <FinanceWorkspace />;\n}\n\nfunction FinanceWorkspace() {"
 need(after.count(added_import)==1 and after.count(wrapper)==1,'EXACT_FINANCE_WRAPPER_REQUIRED')
 need(after.replace(added_import,b'',1).replace(wrapper,b'export default function Finance() {',1)==before,'ORIGINAL_FINANCE_SOURCE_CHANGED')
def finance_unchanged():
 path='app/frontend/src/pages/Finance.tsx'
 original_source=git('show',release.BASELINE+':'+path);current_source=git('show',release.SOURCE+':'+path)
 finance_source_unchanged(original_source,current_source)
 before=finance_body(original_source,'Finance')
 after=finance_body(current_source,release.FINANCE_LEGACY_NAME)
 need(before==after and H(before)==release.FINANCE_BODY_SHA,'LEGACY_FINANCE_BODY_CHANGED');return H(before)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
 need(re.fullmatch('[a-f0-9]{40}',release.SOURCE) and args.source==release.SOURCE and git('rev-parse','HEAD').decode().strip()==release.SOURCE,'EXACT_COMMITTED_HEAD_REQUIRED')
 need('UNFROZEN' not in TESTS and 'UNFROZEN' not in release.FRONTEND and bool(release.NEW_SCHEMA),'EXACT_TEST_SCOPE_REQUIRED')
 provider_proof=Path('outputs/stripe-history-reconciliation-20261018/provider-self-context-capabilities.json').read_bytes();need(H(provider_proof)==release.PROVIDER_CAPABILITY_SHA,'EXACT_PROVIDER_CAPABILITY_PROOF_REQUIRED')
 before,after=inventory(release.BASELINE),inventory(release.SOURCE);changed=scope(before,after);finance_sha=finance_unchanged()
 for p,h in after.items():need(not Path(p).is_symlink() and H(Path(p).read_bytes())==h,'WORKING_TREE_DRIFT')
 need(source_version()==release.FRONTEND_VERSION==json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version'],'EXACT_FRONTEND_BUILD_REQUIRED')
 payload={'backend/'+p:Path('app/backend',p).read_bytes() for p in release.BACKEND}
 for p in Path('app/frontend/dist').rglob('*'):
  need(not p.is_symlink(),'DIST_LINK_REJECTED')
  if p.is_file():
   name=str(p.relative_to('app/frontend/dist'));need(release.static_path(name),'DIST_PATH_REJECTED');payload['static/'+name]=p.read_bytes()
 need(sum(map(len,payload.values()))<64*1024**2 and all(len(b)<16*1024**2 for b in payload.values()),'PAYLOAD_SIZE_LIMIT')
 buffer=io.BytesIO()
 with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as zipped:
  with tarfile.open(fileobj=zipped,mode='w',format=tarfile.USTAR_FORMAT) as archive:
   for name,body in sorted(payload.items()):
    member=tarfile.TarInfo(name);member.size=len(body);member.mode=0o644;member.mtime=0;archive.addfile(member,io.BytesIO(body))
 manifest={'format_version':1,'source_sha':release.SOURCE,'baseline_source_sha':release.BASELINE,
  'frontend_version':release.FRONTEND_VERSION,'baseline_frontend_version':release.BASELINE_FRONTEND,
  'live_preflight_sha256':release.LIVE_PREFLIGHT_SHA,'baseline_backend_inventory_sha256':release.BASE_BACKEND_SHA,
  'old_schema_revision':release.OLD_REVISION,'new_schema_revision':release.NEW_REVISION,
  'additive_tables':sorted(release.NEW_SCHEMA),'production_seed_rows':False,
  'payload_sha256':H(buffer.getvalue()),'files':{p:H(b) for p,b in payload.items()},
  'backend_before':{p:before.get('app/backend/'+p) for p in release.BACKEND},
  'backend_after':{p:after['app/backend/'+p] for p in release.BACKEND},
  'changed_source_files':sorted(changed),'protected_source_inventory':{p:h for p,h in before.items() if p not in changed},
  'preserved':release.PRESERVED,'credentials_included':False,'configuration_extension':release.CONFIG_EXTENSION,'finance_legacy_body_sha256':finance_sha,'provider_capabilities_sha256':release.PROVIDER_CAPABILITY_SHA,'provisioning_proof_sha256':release.PROVISIONING_PROOF_SHA}
 args.out.mkdir(parents=True,exist_ok=True)
 for name,body in {'payload.tar.gz':buffer.getvalue(),'manifest.json':(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()}.items():
  with (args.out/name).open('xb') as stream:stream.write(body)
 print(json.dumps({'source':release.SOURCE,'version':release.FRONTEND_VERSION,'manifest_sha256':H((args.out/'manifest.json').read_bytes()),'payload_sha256':manifest['payload_sha256'],'protected_files':len(manifest['protected_source_inventory'])}))
if __name__=='__main__':main()
