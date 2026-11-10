"""Static-only filter-state repair. No image build, container restart or DB write.

capture/prepare stage assets without changing the live root. activate requires
the independently reviewed prepared SHA. recover CAS-restores only nginx bytes.
"""
import argparse, fcntl, hashlib, io, itertools, json, os, re, socket, stat, time, types
from pathlib import Path, PurePosixPath

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SCOPE = 'merchant-pool-filter-state'
BASE_SOURCE = '9878ca0654b82e7cd9150e7b8628c04aa3cc5eae'
BASE_FRONTEND = '206ef6fe0fe7'
PRIOR = Path('/opt/t24-crm/releases/sales-center-five-improvements-9878ca0654b8-20261110')
OLD_PUBLIC = Path('/var/www/t24-crm-public/sales-center-five-improvements-9878ca0654b8-20261110')
BASE_RUNTIME = {'id':'f94582e507c00846088667307f356ec52a130578916a77a0218928ecf438ea12',
 'image':'sha256:5679c46f3a78f852c1bf9544e4d1ab8c75acaa0e45df0fb529655644166a5518',
 'config':'2358f89373d634572a826f62e4f8a1831c925789e982a6b2858e8d026985141b',
 'started':'2026-11-10T11:09:36.65962259Z'}
SCHEMA = 'j65bc789b025'
SCHEMA_SHA = 'ca15d3cb51c5cb99a68865c6a0c0d5aadd32ee1c5a5cfbc70dee7bfbbf4baa6a'
DATABASE_ID = [64515, 262854]
LEGACY = Path('/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109/release.py')
LEGACY_SHA = '922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85'
FALSE_FLAGS = ('backend_changes','database_migration','database_writes_by_release','container_restarts','environment_changes','credentials_included','provider_actions')
H = lambda body: hashlib.sha256(body).hexdigest()

def need(value, code):
 if not value: raise RuntimeError(code)

def protected(path, expected=None):
 row=path.lstat()
 need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and not row.st_mode&0o077,'ROOT_PRIVATE_FILE_REQUIRED')
 body=path.read_bytes();need(expected is None or H(body)==expected,'STATE_HASH_MISMATCH');return body

def static_path(name):
 p=PurePosixPath(name)
 if not name or str(p)!=name or p.is_absolute() or '\\' in name or any(x.startswith('.') for x in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}

def inventory(root):
 need(root.resolve()==root and root.is_dir(),'CANONICAL_PUBLIC_ROOT_REQUIRED');result={}
 for path in root.rglob('*'):
  need(not path.is_symlink(),'STATIC_SYMLINK_REJECTED')
  if path.is_file():
   name=str(path.relative_to(root));need(static_path(name),'STATIC_PATH_REJECTED');result[name]=H(path.read_bytes())
 return result

def validate_manifest(value):
 need(re.fullmatch('[a-f0-9]{40}',value.get('source_sha','')) and value['source_sha']!=BASE_SOURCE,'NEW_SOURCE_REQUIRED')
 need(value.get('baseline_source_sha')==BASE_SOURCE and value.get('baseline_frontend_version')==BASE_FRONTEND,'EXACT_BASELINE_REQUIRED')
 need(re.fullmatch('[a-f0-9]{12}',value.get('frontend_version','')) and value['frontend_version']!=BASE_FRONTEND,'NEW_FRONTEND_REQUIRED')
 need(value.get('static_only') is True and all(value.get(k) is False for k in FALSE_FLAGS),'STATIC_ONLY_REQUIRED')
 files=value.get('files',{});need(files and {'static/index.html','static/app-version.json'}<=set(files),'STATIC_ENTRYPOINTS_REQUIRED')
 need(all(n.startswith('static/') and static_path(n[7:]) and re.fullmatch('[a-f0-9]{64}',h) for n,h in files.items()),'ONLY_STATIC_PAYLOAD_ALLOWED')
 need(bool(value.get('backend_before')) and all(re.fullmatch('[a-f0-9]{64}',h) for h in value['backend_before'].values()),'EXISTING_BACKEND_PROOF_REQUIRED')
 need(set(value.get('expected_private',{}))=={'t24-private-api','t24-private-worker'},'EXACT_PRIVATE_BASELINE_REQUIRED')
 return value

def install_observation_guards(m, root):
 original=m.runtime
 def runtime(info):
  if info['Id']!=BASE_RUNTIME['id']:return original(info)
  need(len(info['Mounts'])==3,'CRM_MOUNT_COUNT_DRIFT')
  value=original({**info,'Mounts':sorted(info['Mounts'],key=m.canonical)})
  need(value['config']==BASE_RUNTIME['config'],'CRM_CONFIGURATION_DRIFT');return value
 m.runtime=runtime
 original_private=m.private_runtimes
 def private_runtimes():
  expected=m.read(root/'baseline.json')['private_runtimes'] if (root/'baseline.json').exists() else getattr(m,'STATIC_EXPECTED_PRIVATE',None)
  if expected is None:return original_private()
  actual={}
  for name in ('t24-private-api','t24-private-worker'):
   info=m.optional(name)
   if info is None:continue
   need(name in expected and info['State']['Running'] and len(info['Mounts'])==2,'PRIVATE_SERVICE_IDENTITY_DRIFT')
   observed=original(info);need(all(observed[k]==expected[name][k] for k in ('id','image','started')),'PRIVATE_RUNTIME_IDENTITY_DRIFT')
   for order in itertools.permutations(info['Mounts']):
    candidate={**info,'Mounts':list(order)}
    if original(candidate)['config']==expected[name]['config']:
     actual[name]=expected[name];break
   else:raise RuntimeError('PRIVATE_CONFIGURATION_DRIFT')
  need(set(actual)==set(expected),'PRIVATE_SERVICE_SET_DRIFT');return actual
 m.private_runtimes=private_runtimes

def load_tools(root):
 row=LEGACY.lstat();need(LEGACY.resolve()==LEGACY and stat.S_ISREG(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_LEGACY_REQUIRED')
 body=LEGACY.read_bytes();need(H(body)==LEGACY_SHA,'LEGACY_HASH_MISMATCH')
 m=types.ModuleType('static_filter_primitives');m.__file__=str(LEGACY);exec(compile(body,str(LEGACY),'exec'),m.__dict__)
 need(m.NEW==SCHEMA and m.SOURCE=='18240e28774a1ce6043d06d1f7f913af2e9a369e','EXACT_LEGACY_REQUIRED')
 m.OLD=m.NEW=SCHEMA;m.RUNTIME_PATHS=set();m.ERROR_LOG=root/'diagnostics-private.log';install_observation_guards(m,root);return m

def make_release(m,args):
 manifest=validate_manifest(json.loads(protected(args.release/'manifest.json',args.manifest_sha256)))
 source=manifest['source_sha'];m.SOURCE=source;m.STATIC_EXPECTED_PRIVATE=manifest['expected_private']
 class Release(m.Release):
  def __init__(self):
   self.root=args.release;self.args=args;self.manifest=manifest
   need(self.root==Path('/opt/t24-crm/releases/'+SCOPE+'-'+source[:12]+'-20261110'),'EXACT_STATIC_NAMESPACE_REQUIRED')
   row=self.root.stat();need(self.root.resolve()==self.root and self.root.is_dir() and row.st_uid==0 and not row.st_mode&0o077,'PRIVATE_RELEASE_REQUIRED')
   self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+source[:12]+'-20261110')
  def capture(self):
   prior=m.read(PRIOR/'deployed.json');live=m.inspect('t24-crm')
   need(prior['stage']=='DEPLOYED' and prior['source_sha']==BASE_SOURCE and prior['runtime']==BASE_RUNTIME,'EXACT_DEPLOYED_BASELINE_REQUIRED')
   need(live['State']['Running'] and m.runtime(live)==BASE_RUNTIME,'EXACT_RUNNING_RUNTIME_REQUIRED')
   need(m.public_root()==OLD_PUBLIC and json.loads((OLD_PUBLIC/'app-version.json').read_bytes())=={'version':BASE_FRONTEND},'EXACT_OLD_PUBLIC_REQUIRED')
   need(m.revision(m.DB)==SCHEMA and m.digest(m.schema(m.DB))==SCHEMA_SHA and [m.DB.stat().st_dev,m.DB.stat().st_ino]==DATABASE_ID,'EXACT_DATABASE_BOUNDARY_REQUIRED')
   old=inventory(OLD_PUBLIC);value=super().capture();m.write(self.root/'static-baseline.json',{'files':old,'schema_sha256':SCHEMA_SHA});return value
  def nginx_pair(self):
   old=protected(self.root/'nginx-before.conf');needle=os.fsencode(OLD_PUBLIC)
   need(old.count(needle)==1,'ONE_STATIC_ROOT_REPLACEMENT_REQUIRED');return old,old.replace(needle,os.fsencode(self.public),1)
  def boundary(self,updated=False):
   b=self.baseline();live=m.inspect('t24-crm');old,new=self.nginx_pair()
   need(live['State']['Running'] and m.runtime(live)==b['runtime']==BASE_RUNTIME,'RUNTIME_ENV_OR_RESTART_DRIFT')
   need(m.inventory(live['Id'])==b['backend_inventory'],'FULL_BACKEND_INVENTORY_DRIFT')
   need(m.revision(m.DB)==SCHEMA and m.schema(m.DB)==b['schema'] and m.digest(b['schema'])==SCHEMA_SHA,'SCHEMA_DRIFT')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==b['database_identity']==DATABASE_ID,'DATABASE_FILE_IDENTITY_DRIFT')
   need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_DRIFT')
   need(inventory(OLD_PUBLIC)==m.read(self.root/'static-baseline.json')['files'],'OLD_STATIC_DRIFT')
   need(m.NGINX.read_bytes()==(new if updated else old) and m.public_root()==(self.public if updated else OLD_PUBLIC),'EXACT_NGINX_BYTES_REQUIRED')
   m.ready(live['Id']);return b['runtime']
  def prepare(self):
   self.boundary();need(not(self.root/'prepared.json').exists(),'FRESH_PREPARE_REQUIRED')
   self.extract();self.stage_public();self.static_check();self.boundary()
   value={'stage':'STATIC_PREPARED','source_sha':source,'frontend_version':manifest['frontend_version'],'manifest_sha256':args.manifest_sha256,'public_root':str(self.public),'public_inventory':inventory(self.public),'next_nginx_sha256':H(self.nginx_pair()[1]),'runtime':BASE_RUNTIME,'static_only':True,'database_writes':False,'container_restarts':False}
   m.write(self.root/'prepared.json',value);return {**value,'prepared_sha256':H((self.root/'prepared.json').read_bytes())}
  def reviewed(self):
   need(bool(re.fullmatch('[a-f0-9]{64}',args.prepared_sha256 or '')),'REVIEWED_PREPARED_SHA_REQUIRED')
   p=json.loads(protected(self.root/'prepared.json',args.prepared_sha256))
   need(p['stage']=='STATIC_PREPARED' and p['source_sha']==source and p['manifest_sha256']==args.manifest_sha256 and p['runtime']==BASE_RUNTIME,'PREPARED_SCOPE_DRIFT')
   need(p['static_only'] is True and p['database_writes'] is False and p['container_restarts'] is False,'PREPARED_STATIC_FLAGS_REQUIRED')
   need(inventory(self.public)==p['public_inventory'] and H(self.nginx_pair()[1])==p['next_nginx_sha256'],'PREPARED_ASSET_OR_NGINX_DRIFT');return p
  def swap(self,expected,body):
   path=Path(self.baseline()['nginx_path']);need(m.NGINX.read_bytes()==expected and m.NGINX.resolve()==path,'NGINX_COMPARE_AND_SWAP_FAILED')
   info=path.stat();need(info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_NGINX_REQUIRED')
   tmp=path.with_name('.'+path.name+'.merchant-pool-filter-next')
   fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,stat.S_IMODE(info.st_mode))
   with os.fdopen(fd,'wb') as stream:
    os.fchown(stream.fileno(),info.st_uid,info.st_gid);stream.write(body);stream.flush();os.fsync(stream.fileno())
   os.replace(tmp,path);m.run(['nginx','-t'],'NGINX_TEST_FAILED');m.run(['systemctl','reload','nginx'],'NGINX_RELOAD_FAILED')
  def public_check_version(self,version):
   for attempt in range(8):
    try:
     url='https://t24-crm.com/app-version.json?filter-static='+str(time.time_ns())
     body=m.run(['curl','-q','--silent','--show-error','--fail','--http1.1','--max-time','5','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','-H','Cache-Control: no-cache',url],'PUBLIC_VERSION_FAILED',8)
     need(json.loads(body)=={'version':version},'PUBLIC_VERSION_MISMATCH');return
    except RuntimeError:
     if attempt==7:raise
     time.sleep(1)
  def finish(self):
   self.reviewed();self.boundary(True);self.static_check();self.public_check_version(manifest['frontend_version']);self.boundary(True)
   value={'stage':'STATIC_DEPLOYED','source_sha':source,'backend_source_sha':BASE_SOURCE,'frontend_version':manifest['frontend_version'],'runtime':BASE_RUNTIME,'public_root':str(self.public),'prepared_sha256':args.prepared_sha256,'schema_unchanged':True,'backend_unchanged':True,'environment_preserved':True,'private_services_preserved':True,'static_only':True,'database_writes':False,'container_restarts':False,'nginx_reload_only':True}
   if (self.root/'deployed.json').exists():need(m.read(self.root/'deployed.json')==value,'DEPLOYED_RECEIPT_DRIFT')
   else:m.write(self.root/'deployed.json',value)
   return value
  def activate(self):
   need(not(self.root/'activation-started.json').exists(),'ACTIVATION_ALREADY_STARTED');self.reviewed();self.boundary()
   m.write(self.root/'activation-started.json',{'prepared_sha256':args.prepared_sha256,'source_sha':source});old,new=self.nginx_pair()
   try:self.swap(old,new);return self.finish()
   except BaseException:self.recover();raise
  def recover(self):
   self.reviewed();marker=m.read(self.root/'activation-started.json');need(marker=={'prepared_sha256':args.prepared_sha256,'source_sha':source},'ACTIVATION_SCOPE_DRIFT')
   old,new=self.nginx_pair();current=m.NGINX.read_bytes();need(current in (old,new),'UNKNOWN_NGINX_NOT_REPLACED')
   self.boundary(current==new)
   if current==new:self.swap(new,old)
   self.boundary();self.public_check_version(BASE_FRONTEND)
   value={'stage':'STATIC_RECOVERED','source_sha':source,'frontend_version':BASE_FRONTEND,'runtime':BASE_RUNTIME,'database_restored':False,'database_writes':False,'container_restarts':False}
   if not(self.root/'recovered.json').exists():m.write(self.root/'recovered.json',value)
   return value
  def status(self):
   if (self.root/'recovered.json').exists():self.boundary();return m.read(self.root/'recovered.json')
   if (self.root/'activation-started.json').exists():
    if not args.prepared_sha256:args.prepared_sha256=m.read(self.root/'activation-started.json')['prepared_sha256']
    return self.finish()
   self.boundary();return {'stage':'STATIC_NOT_DEPLOYED','runtime':BASE_RUNTIME,'frontend_version':BASE_FRONTEND}
 return Release()

def main():
 p=argparse.ArgumentParser();p.add_argument('--phase',choices=('capture','prepare','activate','status','recover'),required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--prepared-sha256');args=p.parse_args()
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_HOST_REQUIRED');os.umask(0o077)
 fd=os.open('/opt/t24-crm/releases/.merchant-pool-filter-state-static.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and not row.st_mode&0o077,'PRIVATE_RELEASE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  m=load_tools(args.release);release=make_release(m,args);print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
 except BaseException as error:
  code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
  print(json.dumps({'stage':'STATIC_RELEASE_REJECTED','phase':args.phase,'code':code}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
