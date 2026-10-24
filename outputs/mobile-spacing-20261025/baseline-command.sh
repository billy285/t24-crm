#!/bin/sh
python3 - <<'T24_MOBILE_BASELINE'
"""Fresh presentation-only boundary. Reads container metadata, DDL and assets only."""
import copy,hashlib,json,os,re,socket,sqlite3,stat,subprocess
from datetime import datetime,timezone
from pathlib import Path

HOST='iZj6c4cj7edgnhdimts4l7Z'
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
DATABASES={'business':Path('/opt/t24-crm/app/data/crm_prod.db'),'private':Path('/opt/t24-crm/private-workspace/data/workspace.db')}
CONTAINERS={'crm':'t24-crm','private_api':'t24-private-api','private_worker':'t24-private-worker'}
H=lambda b:hashlib.sha256(b).hexdigest()
def digest(v):return H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def need(ok,code):
 if not ok:raise RuntimeError(code)
def run(args,code,timeout=40):
 r=subprocess.run(args,capture_output=True,timeout=timeout);need(r.returncode==0,code);return r.stdout
def protected(path):
 p=Path(path);s=p.lstat()
 need(p.resolve()==p and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode&0o022,'PROTECTED_FILE_REQUIRED')
 return s
def read(path,expected=None):
 protected(path);body=Path(path).read_bytes();need(expected is None or H(body)==expected,'FILE_HASH_DRIFT');return body

# Reused from the accepted static publisher: reject links, hidden paths and
# arbitrary extensions; keep old hashed assets for already-open application tabs.
def static_path(name):
 p=Path(name)
 if not p.parts or p.is_absolute() or str(p)!=name or '\\' in name or any(x.startswith('.') for x in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}
def tree(root):
 need(root.is_absolute() and root.resolve()==root and root.is_dir(),'CANONICAL_STATIC_ROOT_REQUIRED')
 result={}
 for p in root.rglob('*'):
  need(not p.is_symlink(),'STATIC_LINK_REJECTED')
  if p.is_file():
   n=str(p.relative_to(root));need(static_path(n),'STATIC_PATH_REJECTED');result[n]=H(p.read_bytes())
 need(bool(result),'STATIC_FILES_REQUIRED');return result
def clone_networks(info):
 result={}
 for name,e in info.get('NetworkSettings',{}).get('Networks',{}).items():
  result[name]={k:copy.deepcopy(e[k]) for k in ('Aliases','Links','DriverOpts','GwPriority') if e.get(k) is not None}
  if 'Aliases' in result[name]:result[name]['Aliases']=[a for a in result[name]['Aliases'] if a not in {info['Id'],info['Id'][:12]}]
 return result
def runtime(name):
 info=json.loads(run(['docker','inspect',name],'CONTAINER_INSPECTION_FAILED'))[0]
 need(info['State']['Running'] and not info['State'].get('Restarting') and not info['State'].get('Dead'),'CONTAINER_NOT_STABLE')
 mounts=sorted(info['Mounts'],key=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')))
 labels=info['Config'].get('Labels') or {}
 return {'id':info['Id'],'image':info['Image'],'started':info['State']['StartedAt'],'restart':info['RestartCount'],
  'config_sha256':digest({'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':mounts,'networks':clone_networks(info)}),
  'source_labels':{k:labels[k] for k in ('t24.release.source','t24.release.scope','t24.private.source.sha','t24.private.role') if k in labels}}
def schema(path):
 s=protected(path);c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=8)
 try:
  c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
  objects=c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
  versions=c.execute('SELECT version_num FROM alembic_version ORDER BY version_num').fetchall() if any(r[0]=='table' and r[1]=='alembic_version' for r in objects) else []
  need(c.total_changes==0,'DDL_READONLY_REQUIRED')
  return {'identity':{'device':s.st_dev,'inode':s.st_ino,'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)},
   'schema_sha256':digest(objects),'table_count':sum(r[0]=='table' for r in objects),'revisions':[v[0] for v in versions]}
 finally:c.close()
def backend_boundary():return {'roles':{k:runtime(v) for k,v in CONTAINERS.items()},'databases':{k:schema(v) for k,v in DATABASES.items()}}
def static_boundary():
 body=read(NGINX);roots=re.findall(rb'(?m)^\s*root\s+([^;]+);',body)
 need(len(roots)==1,'EXACT_SINGLE_PUBLIC_ROOT_REQUIRED');root=Path(os.fsdecode(roots[0]));need(root.parent==Path('/var/www/t24-crm-public'),'KNOWN_PUBLIC_PARENT_REQUIRED')
 files=tree(root);version=json.loads((root/'app-version.json').read_bytes()).get('version')
 need(bool(re.fullmatch('[a-f0-9]{12}',version or '')),'FRONTEND_VERSION_REQUIRED')
 return {'public_root':str(root),'frontend_version':version,'nginx_sha256':H(body),'public_inventory_sha256':digest(files),'public_file_count':len(files)}
def capture():
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_SERVER_ROOT_REQUIRED')
 before=backend_boundary();static=static_boundary();after=backend_boundary()
 need(before==after and static==static_boundary(),'BOUNDARY_CHANGED_DURING_CAPTURE')
 return {'stage':'MOBILE_SPACING_FRESH_READONLY_BASELINE','host':HOST,'observed_at':datetime.now(timezone.utc).isoformat(),
  **static,**after,'financial_rows_read':False,'environment_or_key_files_read':False,'provider_requests':False,'database_or_service_mutations':False}
def safe_error(e):
 v=str(e);return v if re.fullmatch('[A-Z0-9_]+',v) else type(e).__name__.upper()
if __name__=='__main__':
 try:
  result=capture();body=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
  print(json.dumps({'stage':result['stage'],'baseline_sha256':H(body),'baseline':result},sort_keys=True,separators=(',',':')))
 except BaseException as e:print(json.dumps({'stage':'MOBILE_SPACING_BASELINE_REJECTED','code':safe_error(e),'database_or_service_mutations':False}));raise SystemExit(1)

T24_MOBILE_BASELINE
