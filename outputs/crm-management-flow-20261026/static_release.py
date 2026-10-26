"""Reviewed CRM presentation changes: stage assets and CAS one Nginx root only."""
import argparse,fcntl,io,json,os,re,socket,stat,sys,tarfile
from pathlib import Path
sys.dont_write_bytecode=True

def ui_source(name):
 if not isinstance(name,str):return False
 p=Path(name)
 return name in {'app/frontend/src/App.tsx','app/frontend/vite.config.ts'} or str(p)==name and '\\' not in name and not p.is_absolute() and len(p.parts)>=5 and p.parts[:3]==('app','frontend','src') and p.parts[3] in {'components','pages'} and p.suffix in {'.tsx','.ts','.css'} and not any(part.startswith('.') for part in p.parts) and not any(token in name.lower() for token in ('private','auth','token','session','payment-utils','subscription-utils'))
def need(ok,code):
 if not ok:raise RuntimeError(code)
def json_bytes(v):return (json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
def write(path,body):
 body=body if isinstance(body,bytes) else json_bytes(body)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
 return body
def main(a):
 import hashlib
 H=lambda b:hashlib.sha256(b).hexdigest()
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_SERVER_ROOT_REQUIRED')
 os.umask(0o077)
 release=a.release;s=release.lstat()
 need(release.resolve()==release and release.parent==Path('/opt/t24-crm/releases') and stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 for v in (a.module_sha256,a.baseline_sha256,a.allowlist_sha256,a.manifest_sha256,a.payload_sha256):need(bool(re.fullmatch('[a-f0-9]{64}',v)),'EXACT_HASH_ARGUMENT_REQUIRED')
 module=release/'baseline.py';need(module.resolve()==module and module.is_file() and not module.is_symlink(),'BASELINE_MODULE_LINK_REJECTED')
 body=module.read_bytes();need(H(body)==a.module_sha256,'BASELINE_MODULE_HASH_DRIFT')
 m={'__name__':'crm_ui_system_boundary','__file__':str(module)};exec(compile(body,str(module),'exec'),m)
 read=m['read'];baseline=json.loads(read(release/'baseline.json',a.baseline_sha256));manifest=json.loads(read(release/'manifest.json',a.manifest_sha256))
 allowed=json.loads(read(release/'source-allowlist.json',a.allowlist_sha256))
 need(isinstance(allowed,list) and 0<len(allowed)<=96 and all(ui_source(n) for n in allowed) and len(allowed)==len(set(allowed)),'EXACT_SAFE_UI_ALLOWLIST_REQUIRED')
 read(release/'payload.tar.gz',a.payload_sha256)
 need(a.baseline_sha256=='aa4155fe58a22f60f8b6a5e8acc985fd6a9381e5861e83c43b0449848fbcff22' and baseline['frontend_version']=='2908954fe44e','EXACT_REVIEWED_SERVER_BASELINE_REQUIRED')
 need(baseline['stage']=='CRM_UI_SYSTEM_FRESH_READONLY_BASELINE' and baseline['host']==m['HOST'] and all(baseline[k] is False for k in ('financial_rows_read','environment_or_key_files_read','provider_requests','database_or_service_mutations')),'FRESH_READONLY_BASELINE_REQUIRED')
 need(manifest['stage']=='CRM_MANAGEMENT_FLOW_STATIC_PACKAGE' and set(manifest['changed_source_files'])==set(allowed) and manifest['source_allowlist_sha256']==a.allowlist_sha256 and manifest['static_only'] is True and all(manifest[k] is False for k in ('backend_changes','database_changes','service_changes','credentials_included','private_source_changes','authorization_logic_changes')) and manifest['protected_behavior']['unchanged'] is True and manifest['protected_behavior']['mutation_calls_unchanged'] is True and manifest['protected_behavior']['original_api_requests_unchanged'] is True and manifest['protected_behavior']['authorization_gates_unchanged'] is True and manifest['protected_behavior']['unknown_semantic_drift'] is False and manifest['approved_deltas_sha256']==manifest['protected_behavior']['approved_deltas_sha256'] and bool(re.fullmatch('[a-f0-9]{64}',manifest['approved_deltas_sha256'])) and manifest['baseline_source_sha']=='69666997496e57189e6e2f32f33467a584fe37c5','EXACT_REVIEWED_UI_STATIC_SCOPE_REQUIRED')
 need(manifest['baseline_sha256']==a.baseline_sha256 and manifest['payload_sha256']==a.payload_sha256 and manifest['previous_frontend_version']==baseline['frontend_version'],'EXACT_PACKAGE_BASELINE_REQUIRED')
 source=manifest['source_sha'];version=manifest['frontend_version']
 need(bool(re.fullmatch('[a-f0-9]{40}',source)) and bool(re.fullmatch('[a-f0-9]{12}',version)) and version!=baseline['frontend_version'],'FROZEN_NEW_SOURCE_VERSION_REQUIRED')
 need(release.name=='crm-management-flow-'+source[:12]+'-20261026','EXACT_RELEASE_PATH_REQUIRED')
 old=Path(baseline['public_root']);public=Path('/var/www/t24-crm-public')/release.name
 files=manifest['files'];need({'static/index.html','static/app-version.json'}<=set(files) and all(n.startswith('static/') and m['static_path'](n[7:]) and re.fullmatch('[a-f0-9]{64}',v) for n,v in files.items()),'STATIC_PAYLOAD_SCOPE_REJECTED')
 boundary_keys=('roles','databases')
 expected={k:baseline[k] for k in boundary_keys}
 def backend():need(m['backend_boundary']()==expected,'RUNTIME_OR_DATABASE_SCHEMA_IDENTITY_CHANGED')
 def old_static():
  now=m['static_boundary']();need(all(now[k]==baseline[k] for k in ('public_root','frontend_version','nginx_sha256','public_inventory_sha256','public_file_count')),'CURRENT_STATIC_BASELINE_CHANGED')
 def public_files():
  result={n[7:]:v for n,v in files.items()}
  for n,v in m['tree'](old).items():
   if n.startswith('assets/'):
    need(n not in result or result[n]==v,'HASHED_ASSET_COLLISION');result[n]=v
  return result
 def verify_public():
  need(m['digest'](m['tree'](old))==baseline['public_inventory_sha256'],'OLD_STATIC_ASSETS_CHANGED')
  actual=m['tree'](public);need(actual==public_files(),'PREPARED_STATIC_FILES_CHANGED')
  need(json.loads((public/'app-version.json').read_bytes())=={'version':version},'STATIC_VERSION_DRIFT')
  return m['digest'](actual)
 def nginx_next(original):
  need(H(original)==baseline['nginx_sha256'],'OLD_NGINX_HASH_DRIFT')
  matches=list(re.finditer(rb'(?m)^\s*root\s+([^;]+);',original));need(len(matches)==1 and os.fsdecode(matches[0][1])==str(old),'EXACT_NGINX_ROOT_REQUIRED')
  start,end=matches[0].span(1);changed=original[:start]+str(public).encode()+original[end:]
  need(changed!=original and changed[:start]+str(old).encode()+changed[start+len(str(public).encode()):]==original,'NONROOT_NGINX_CHANGE_REJECTED')
  return changed
 def replace(original,changed):
  path=m['NGINX'];need(read(path)==original,'NGINX_CONCURRENT_CHANGE')
  temp=path.parent/'.t24-crm-management-flow-next';fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
  try:
   with os.fdopen(fd,'wb') as f:f.write(changed);f.flush();os.fsync(f.fileno())
   temp.chmod(0o644);need(read(path)==original,'NGINX_CONCURRENT_CHANGE');os.replace(temp,path)
  except BaseException:
   if temp.exists():temp.unlink()
   raise
 def reload():m['run'](['nginx','-t'],'NGINX_TEST_FAILED');m['run'](['systemctl','reload','nginx'],'NGINX_RELOAD_FAILED')
 def public_version():return json.loads(m['run'](['curl','-fsS','--max-time','20','https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_READ_FAILED',25))
 def rollback(original,changed):
  current=read(m['NGINX'])
  if current==changed:replace(changed,original)
  else:need(current==original,'UNKNOWN_NGINX_CHANGE_REQUIRES_REVIEW')
  # Recovery must reload even when an interrupted prior rollback already put
  # original bytes on disk but failed to update Nginx's running configuration.
  reload();old_static();need(public_version()=={'version':baseline['frontend_version']},'RECOVERED_PUBLIC_VERSION_DRIFT')
 lock=os.open('/opt/t24-crm/releases/.stripe-autopost-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if a.phase=='prepare':
  need(set(p.name for p in release.iterdir())=={'baseline.py','baseline.json','source-allowlist.json','manifest.json','payload.tar.gz','static_release.py'},'FRESH_STAGING_REQUIRED')
  backend();old_static();original=read(m['NGINX']);changed=nginx_next(original)
  need(not public.exists() and not public.is_symlink(),'FRESH_PUBLIC_DIRECTORY_REQUIRED');public.mkdir(mode=0o755);public.chmod(0o755)
  def directory(path):
   need(path==public or public in path.parents,'PUBLIC_PATH_ESCAPE_REJECTED')
   path.mkdir(parents=True,exist_ok=True,mode=0o755)
   for parent in (path,*path.parents):
    if parent==public:break
    need(not parent.is_symlink(),'PUBLIC_DIRECTORY_LINK_REJECTED');parent.chmod(0o755)
  wanted=public_files();seen=set()
  with tarfile.open(fileobj=io.BytesIO(read(release/'payload.tar.gz',a.payload_sha256)),mode='r:gz') as archive:
   for item in archive:
    need(item.isfile() and not item.pax_headers and item.name in files and item.name not in seen and 0<=item.size<16*1024**2,'STATIC_ARCHIVE_MEMBER_REJECTED')
    b=archive.extractfile(item).read();need(H(b)==files[item.name],'STATIC_MEMBER_HASH_DRIFT')
    destination=public/item.name[7:];directory(destination.parent)
    write(destination,b);destination.chmod(0o644);seen.add(item.name)
  need(seen==set(files),'STATIC_PAYLOAD_INCOMPLETE')
  for n,v in wanted.items():
   if 'static/'+n not in files:
    destination=public/n;directory(destination.parent);b=(old/n).read_bytes();need(H(b)==v,'RETAINED_ASSET_CHANGED');write(destination,b);destination.chmod(0o644)
  inventory=verify_public();backend();old_static();write(release/'nginx-before.conf',original)
  result={'stage':'CRM_MANAGEMENT_FLOW_STATIC_PREPARED','source_sha':source,'frontend_version':version,'baseline_sha256':a.baseline_sha256,'source_allowlist_sha256':a.allowlist_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'public_root':str(public),'public_inventory_sha256':inventory,'nginx_next_sha256':H(changed),'runtime_and_schema_identity_unchanged':True,'old_assets_preserved':True,'database_mutations':False,'services_modified':False,'provider_requests':False}
  receipt=write(release/'prepared.json',result);print(json.dumps({**result,'receipt_sha256':H(receipt)}));return
 need(bool(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or '')),'INDEPENDENT_PREPARE_REVIEW_REQUIRED')
 prepared=json.loads(read(release/'prepared.json',a.review_sha256))
 need(prepared['stage']=='CRM_MANAGEMENT_FLOW_STATIC_PREPARED' and all(prepared[k]==v for k,v in {'source_sha':source,'frontend_version':version,'baseline_sha256':a.baseline_sha256,'source_allowlist_sha256':a.allowlist_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'public_root':str(public),'runtime_and_schema_identity_unchanged':True,'old_assets_preserved':True,'database_mutations':False,'services_modified':False,'provider_requests':False}.items()),'PREPARED_SCOPE_DRIFT')
 original=read(release/'nginx-before.conf',baseline['nginx_sha256']);changed=nginx_next(original);need(H(changed)==prepared['nginx_next_sha256'],'REVIEWED_NGINX_HASH_DRIFT')
 if a.phase=='recover':rollback(original,changed);print(json.dumps({'stage':'CRM_MANAGEMENT_FLOW_STATIC_ROOT_RECOVERED','database_mutations':False,'services_modified':False}));return
 need(not (release/'deployed.json').exists() and not (release/'activation-started.json').exists(),'FRESH_ACTIVATION_REQUIRED')
 backend();old_static();need(verify_public()==prepared['public_inventory_sha256'],'REVIEWED_STATIC_INVENTORY_DRIFT')
 write(release/'activation-started.json',{'prepared_sha256':a.review_sha256,'source_sha':source})
 try:
  replace(original,changed);reload();backend()
  need(read(m['NGINX'])==changed and verify_public()==prepared['public_inventory_sha256'],'PUBLIC_STATIC_SWITCH_DRIFT')
  actual=public_version()
  need(actual=={'version':version},'PUBLIC_FRONTEND_VERSION_DRIFT')
  result={**prepared,'stage':'CRM_MANAGEMENT_FLOW_STATIC_DEPLOYED_VERIFIED','deployed':True,'prepared_sha256':a.review_sha256,'nginx_only_public_root_changed':True,'database_restored':False}
  receipt=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':H(receipt)}))
 except BaseException:rollback(original,changed);raise

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--phase',choices=['prepare','activate','recover'],required=True);p.add_argument('--release',type=Path,required=True)
 for n in ('module-sha256','baseline-sha256','allowlist-sha256','manifest-sha256','payload-sha256'):p.add_argument('--'+n,required=True)
 p.add_argument('--review-sha256');a=p.parse_args()
 try:main(a)
 except BaseException as e:
  v=str(e);print(json.dumps({'stage':'CRM_MANAGEMENT_FLOW_STATIC_REJECTED','code':v if re.fullmatch('[A-Z0-9_]+',v) else type(e).__name__.upper(),'database_mutations':False,'services_modified':False}));raise SystemExit(1)
