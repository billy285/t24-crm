#!/usr/bin/env python3
"""Static-only customer-dialog repair; no backend, schema or service mutations."""
import argparse,fcntl,hashlib,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time,types
from pathlib import Path

SOURCE='b2655953a2d909ba3fd79dd37e7dddbe4dfc54bd'
FRONTEND_VERSION='3361045efa5f'
BASELINE='df6c86e8a821bef26cd2e4d6a960fc93fa55002d'
BASELINE_FRONTEND='f38ebb7b07a9'
HOST='iZj6c4cj7edgnhdimts4l7Z'
CRM_ID='2dd800e1616754eb86c968ba9f514d2d57e0ab3576d14157f43f88fd82dbf7b3'
CRM_IMAGE='sha256:f3551e83890493f75982ba772db7aacfc6a85e49ddaf22acd447dcc7ec4bab7d'
CRM_CONFIG='72fe1312be2c134e4fa25b4e0e5790f09a7921fafa90cff3b66c0001b9f421ed'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
SCHEMA_REVISION='f7d1c5a9b027'
SCHEMA_SHA='066610fb963ff52809f1e09f63806802c5c6380d5589ad1c3deb657062bdc8e8'
OLD_PUBLIC=Path('/var/www/t24-crm-public/sales-dossier-3aaae9f6b13a-20261016')
OLD_STATIC_SHA='8426e37505973c7fc5b166e9f8f1c88c0d780cdd5a09e497b8aeff62143ba1a0'
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='4eb5f5df2bcc68f9aa1ee60ea8273b914d2b62d36f580aada260bba49876a295'
RETAINED=Path('/opt/t24-crm/releases/sales-dossier-3aaae9f6b13a-20261016/release.py')
RETAINED_SHA='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
PRESERVED={'backend':True,'schema':True,'business_rows':True,'company_finance_formulas':True,
 'close_conditions':True,'commission_attribution':True,'customer_invitation_rules':True,
 'private_workspace':True,'environment':True,'services':True}
FALSE_FLAGS=('backend_changes','database_schema_changes','production_row_changes','services_modified','environment_modified','credentials_included')
H=lambda body:hashlib.sha256(body).hexdigest()
_RETAINED=None

def need(ok,code):
 if not ok:raise RuntimeError(code)
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def read(path,expected=None):
 path=Path(path);info=path.lstat()
 need(path.resolve()==path and stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and not info.st_mode&0o077,'PROTECTED_FILE_REQUIRED')
 body=path.read_bytes();need(expected is None or H(body)==expected,'FILE_HASH_DRIFT');return body
def write(path,value):
 body=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
 descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(descriptor,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 return H(body)
def run(args,code):
 result=subprocess.run(args,capture_output=True,timeout=60);need(result.returncode==0,code);return result.stdout
def retained():
 global _RETAINED
 body=read(RETAINED,RETAINED_SHA)
 if _RETAINED is None:
  module=types.ModuleType('_customer_close_retained');module.__file__=str(RETAINED)
  exec(compile(body,str(RETAINED),'exec'),module.__dict__);_RETAINED=module
 return _RETAINED
def inspect(name):return json.loads(run(['docker','inspect',name],'CRM_INSPECTION_FAILED'))[0]
def schema_signature():
 con=sqlite3.connect(f'file:{BUSINESS}?mode=ro',uri=True)
 try:
  con.execute('BEGIN');need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(SCHEMA_REVISION,)],'SCHEMA_REVISION_DRIFT')
  return digest(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall())
 finally:con.close()
def protected_boundary(pins):
 retained().private_boundary(pins)
 crm=inspect('t24-crm');runtime=retained().runtime(crm)
 need(crm['Id']==CRM_ID and crm['Image']==CRM_IMAGE and crm['State']['Running'],'CRM_IDENTITY_DRIFT')
 need(runtime['config']==CRM_CONFIG,'CRM_CONFIGURATION_DRIFT')
 need(schema_signature()==SCHEMA_SHA,'SCHEMA_OBJECT_DRIFT');retained().verify_sales_schema(BUSINESS)
 return runtime
def static_path(name):
 path=Path(name)
 if not path.parts or path.is_absolute() or str(path)!=name or '\\' in name or any(part.startswith('.') for part in path.parts):return False
 if len(path.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or path.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch('workbox-[a-zA-Z0-9_-]+\\.js',name))
 return path.parts[0]=='assets' and path.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}
def tree_inventory(root):
 files={}
 for path in root.rglob('*'):
  need(not path.is_symlink(),'STATIC_LINK_REJECTED')
  if path.is_file():
   name=str(path.relative_to(root));need(static_path(name),'STATIC_PATH_REJECTED');files[name]=H(path.read_bytes())
 need(bool(files),'STATIC_FILES_REQUIRED');return files
def old_public_boundary():
 need(H(NGINX.read_bytes())==NGINX_SHA,'NGINX_BASELINE_DRIFT')
 need(NGINX.read_bytes().count(('root '+str(OLD_PUBLIC)+';').encode())==1,'EXACT_STATIC_ROOT_REQUIRED')
 need(json.loads((OLD_PUBLIC/'app-version.json').read_bytes())['version']==BASELINE_FRONTEND,'BASELINE_FRONTEND_DRIFT')
 need(digest(tree_inventory(OLD_PUBLIC))==OLD_STATIC_SHA,'BASELINE_STATIC_DRIFT')
def public_root():return Path('/var/www/t24-crm-public/customer-dialog-close-'+SOURCE[:12]+'-20261016')
def checked_manifest(release,args):
 need(bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{12}',FRONTEND_VERSION)),'FROZEN_SOURCE_VERSION_REQUIRED')
 manifest=json.loads(read(release/'manifest.json',args.manifest_sha256));read(release/'payload.tar.gz',args.payload_sha256)
 need(manifest['source_sha']==SOURCE and manifest['baseline_source_sha']==BASELINE,'SOURCE_PINS_REQUIRED')
 need(manifest['frontend_version']==FRONTEND_VERSION and manifest['baseline_frontend_version']==BASELINE_FRONTEND,'FRONTEND_PINS_REQUIRED')
 need(manifest['payload_sha256']==args.payload_sha256 and manifest['static_only'] is True,'STATIC_PAYLOAD_REQUIRED')
 need(manifest['preserved']==PRESERVED and all(manifest[name] is False for name in FALSE_FLAGS),'UNCHANGED_BOUNDARY_REQUIRED')
 need(set(manifest['changed_source_files'])=={'app/frontend/src/pages/Customers.tsx','app/frontend/tests/customers-dialog-close.spec.ts'},'SOURCE_SCOPE_REQUIRED')
 need(manifest['files'] and all(name.startswith('static/') and static_path(name[7:]) and re.fullmatch('[a-f0-9]{64}',value) for name,value in manifest['files'].items()),'STATIC_SCOPE_REQUIRED')
 need({'static/index.html','static/app-version.json'}<=set(manifest['files']),'STATIC_ENTRYPOINTS_REQUIRED');return manifest
def extract(release,manifest):
 seen=set()
 with tarfile.open(fileobj=io.BytesIO(read(release/'payload.tar.gz')),mode='r:gz') as archive:
  for member in archive:
   need(member.isfile() and member.name in manifest['files'] and member.name not in seen and 0<=member.size<16*1024**2,'PAYLOAD_MEMBER_REJECTED')
   body=archive.extractfile(member).read();need(H(body)==manifest['files'][member.name],'PAYLOAD_HASH_DRIFT')
   target=release/member.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   need(target.parent.resolve()==target.parent,'STAGING_LINK_REJECTED');write(target,body);seen.add(member.name)
 need(seen==set(manifest['files']),'PAYLOAD_INCOMPLETE')
def public_directory(path,root):
 need(path==root or root in path.parents,'PUBLIC_DIRECTORY_SCOPE_REJECTED');path.mkdir(parents=True,exist_ok=True,mode=0o755)
 for directory in (path,*path.parents):
  need(not directory.is_symlink(),'PUBLIC_LINK_REJECTED');directory.chmod(0o755)
  if directory==root:break
def publish_file(path,body,root):
 public_directory(path.parent,root)
 with path.open('xb') as stream:stream.write(body)
 path.chmod(0o644)
def verify_public(root,manifest):
 need(root==public_root(),'EXACT_PUBLIC_ROOT_REQUIRED')
 for name,value in manifest['files'].items():need(H((root/name[7:]).read_bytes())==value,'PUBLIC_FILE_DRIFT')
 need(json.loads((root/'app-version.json').read_bytes())['version']==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT')
 return digest(tree_inventory(root))
def prepare(release,args,manifest,pins):
 runtime=protected_boundary(pins);old_public_boundary()
 need(set(path.name for path in release.iterdir())=={'release.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED')
 extract(release,manifest);write(release/'nginx-before.conf',NGINX.read_bytes())
 root=public_root();need(not root.exists() and not root.is_symlink(),'FRESH_PUBLIC_ROOT_REQUIRED');public_directory(root,root)
 for name in manifest['files']:publish_file(root/name[7:],read(release/name),root)
 # Existing browser tabs retain access to their immutable hashed chunks.
 for path in (OLD_PUBLIC/'assets').rglob('*'):
  need(not path.is_symlink(),'OLD_ASSET_LINK_REJECTED')
  if path.is_file():
   name='assets/'+str(path.relative_to(OLD_PUBLIC/'assets'));need(static_path(name),'OLD_ASSET_PATH_REJECTED')
   target=root/name
   if target.exists():need(H(target.read_bytes())==H(path.read_bytes()),'STATIC_ASSET_COLLISION')
   else:publish_file(target,path.read_bytes(),root)
 fingerprint=verify_public(root,manifest)
 need(protected_boundary(pins)==runtime,'CRM_RUNTIME_CHANGED_DURING_PREPARE');old_public_boundary()
 result={'stage':'CUSTOMER_DIALOG_STATIC_PREPARED','source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,
  'public_root':str(root),'public_inventory_sha256':fingerprint,'crm':runtime,'schema_sha256':SCHEMA_SHA,
  'manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,'preflight_sha256':args.preflight_sha256,
  'static_only':True,'backend_unchanged':True,'private_runtime_unchanged':True,'database_modified':False,'services_restarted':False}
 proof=write(release/'prepared.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
def reviewed_receipt(release,args,manifest):
 receipt=json.loads(read(release/'prepared.json',args.review_sha256))
 need(receipt['stage']=='CUSTOMER_DIALOG_STATIC_PREPARED' and receipt['source_sha']==SOURCE and receipt['frontend_version']==FRONTEND_VERSION,'PREPARED_SOURCE_DRIFT')
 need(receipt['manifest_sha256']==args.manifest_sha256 and receipt['payload_sha256']==args.payload_sha256 and receipt['preflight_sha256']==args.preflight_sha256,'PREPARED_PIN_DRIFT')
 need(receipt['public_root']==str(public_root()) and receipt['schema_sha256']==SCHEMA_SHA,'PREPARED_TARGET_DRIFT')
 need(receipt['static_only'] is True and receipt['backend_unchanged'] is True and receipt['private_runtime_unchanged'] is True and receipt['database_modified'] is False and receipt['services_restarted'] is False,'PREPARED_BOUNDARY_REQUIRED')
 return receipt
def nginx_pair(release):
 original=read(release/'nginx-before.conf',NGINX_SHA);old=('root '+str(OLD_PUBLIC)+';').encode()
 need(original.count(old)==1,'EXACT_STATIC_ROOT_REQUIRED')
 return original,original.replace(old,('root '+str(public_root())+';').encode())
def cleanup_nginx_temp(original,updated):
 temp=NGINX.parent/'.t24-customer-dialog-next'
 if not temp.exists() and not temp.is_symlink():return
 need(NGINX.read_bytes() in (original,updated),'NGINX_RECOVERY_DRIFT');before=temp.lstat()
 need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and not before.st_mode&0o022,'UNKNOWN_NGINX_RECOVERY_TEMP')
 descriptor=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(descriptor,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'NGINX_TEMP_CHANGED')
  body=stream.read(max(len(original),len(updated))+1)
 need(any(value.startswith(body) for value in (original,updated)),'UNKNOWN_NGINX_RECOVERY_TEMP');after=temp.lstat()
 need((after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)==(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns),'NGINX_TEMP_CHANGED');temp.unlink()
def replace_nginx(original,updated):
 need(NGINX.read_bytes()==original,'NGINX_CONCURRENT_CHANGE');temp=NGINX.parent/'.t24-customer-dialog-next'
 descriptor=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 with os.fdopen(descriptor,'wb') as stream:stream.write(updated);stream.flush();os.fsync(stream.fileno())
 temp.chmod(0o644);os.replace(temp,NGINX)
def reload_nginx():run(['nginx','-t'],'NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'NGINX_RELOAD_FAILED')
def swap_nginx(original,updated):
 replace_nginx(original,updated)
 try:reload_nginx()
 except BaseException:
  try:replace_nginx(updated,original);reload_nginx()
  except BaseException as error:raise RuntimeError('NGINX_SWAP_AND_RESTORE_FAILED') from error
  raise
def rollback(release,receipt,pins,original,updated,reason):
 errors=[]
 try:
  cleanup_nginx_temp(original,updated);current=NGINX.read_bytes()
  if current==updated:swap_nginx(updated,original)
  else:need(current==original,'ROLLBACK_NGINX_DRIFT');reload_nginx()
 except BaseException as error:errors.append(safe_error(error))
 try:
  need(protected_boundary(pins)==receipt['crm'],'CRM_RUNTIME_CHANGED');old_public_boundary()
 except BaseException as error:errors.append(safe_error(error))
 result={'stage':'CUSTOMER_DIALOG_ROLLBACK_INCOMPLETE' if errors else 'CUSTOMER_DIALOG_ROLLED_BACK',
  'source_sha':SOURCE,'database_modified':False,'services_restarted':False,'backend_modified':False,'reason':reason,'failures':errors}
 write(release/('rollback-'+str(time.time_ns())+'.json'),result);need(not errors,'ROLLBACK_INCOMPLETE');return result
def public_check(root):
 _,_,base,_,_=retained().tools();base.public_check(base.file_map(root),FRONTEND_VERSION,root,verify_services=False)
def activate(release,args,manifest,pins):
 receipt=reviewed_receipt(release,args,manifest);need(protected_boundary(pins)==receipt['crm'],'CRM_RUNTIME_CHANGED_AFTER_REVIEW');old_public_boundary()
 need(verify_public(public_root(),manifest)==receipt['public_inventory_sha256'],'PUBLIC_CHANGED_AFTER_REVIEW')
 original,updated=nginx_pair(release);need(not (release/'deployed.json').exists(),'ALREADY_DEPLOYED')
 write(release/'activation-started.json',{'source_sha':SOURCE,'review_sha256':args.review_sha256,'next_nginx_sha256':H(updated)})
 try:
  swap_nginx(original,updated);public_check(public_root())
  need(H(NGINX.read_bytes())==H(updated) and verify_public(public_root(),manifest)==receipt['public_inventory_sha256'],'LIVE_PUBLIC_DRIFT')
  need(protected_boundary(pins)==receipt['crm'],'CRM_RUNTIME_CHANGED_DURING_ACTIVATION')
  result={'stage':'CUSTOMER_DIALOG_STATIC_DEPLOYED','deployed':True,'source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,
   'public_root':str(public_root()),'nginx_sha256':H(updated),'crm':receipt['crm'],'schema_unchanged':True,
   'private_runtime_unchanged':True,'backend_unchanged':True,'database_modified':False,'services_restarted':False}
  proof=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
 except BaseException as error:rollback(release,receipt,pins,original,updated,safe_error(error));raise
def recover(release,args,manifest,pins):
 receipt=reviewed_receipt(release,args,manifest);need(not (release/'deployed.json').exists(),'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW')
 original,updated=nginx_pair(release);started=json.loads(read(release/'activation-started.json'))
 need(started=={'source_sha':SOURCE,'review_sha256':args.review_sha256,'next_nginx_sha256':H(updated)},'ACTIVATION_IDENTITY_DRIFT')
 print(json.dumps(rollback(release,receipt,pins,original,updated,'INTERRUPTED_ACTIVATION')))
def safe_error(error):return str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True)
 parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True)
 parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
 need(socket.gethostname()==HOST and os.geteuid()==0,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.release.stat().st_uid==0 and stat.S_IMODE(args.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.customer-dialog-close-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=checked_manifest(args.release,args);pins=json.loads(read(args.preflight,args.preflight_sha256))
 if args.phase=='prepare':prepare(args.release,args,manifest,pins)
 else:
  need(bool(args.review_sha256),'INDEPENDENT_PREPARE_REVIEW_REQUIRED');(activate if args.phase=='activate' else recover)(args.release,args,manifest,pins)
if __name__=='__main__':
 try:main()
 except BaseException as error:
  print(json.dumps({'stage':'CUSTOMER_DIALOG_RELEASE_REJECTED','code':safe_error(error)}));sys.exit(1)
