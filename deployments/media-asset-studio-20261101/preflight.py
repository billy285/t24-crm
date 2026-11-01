"""Read-only current-155 baseline and local rendering-capacity inventory.

Only a new root-private aggregate receipt is written. No installation, business
mutation, provider request, secret-file read or private-database read occurs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
from types import ModuleType, SimpleNamespace

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = 'd39337fccfd622e506ca3c1a655a126f5218dc42'
FRONTEND = '8113d14d204f'
REVISION = 'e10cb234c570'
OLD = Path('/opt/t24-crm/releases/media-ops-monthly-flow-d39337fccfd6-20261101')
ROOT = Path('/opt/t24-crm/releases')
RELEASE_SHA = 'd5efcfecb79859e595dec70a0e901abb1c5e86d52ba300a909dd73e44bfd24c7'
DEPLOYED_SHA = '8bc2907a55706ebc229faeb9b0f10ee24f08dd10de81c29412afce6e8a787197'
PREPARED_SHA = 'd07abd82d72dabdae727618fbb5ba0375c5cd05b61b691d0a06c1e4851578e43'
MANIFEST_SHA = 'd0953971efc1715dc0d68596e60e682e6c3748d8ccdbc10b5b393f044fdb0dc4'
PAYLOAD_SHA = '3c57bc3a60082031c563f7f67dfab9d8da8c99989206418829aa4ecea535fd05'
OLD_PREFLIGHT_SHA = '42bc79e1b7041e3b376ca94ab8bef01d6dc6224e151821958cf48225f90faaaf'
SCHEMA_SHA = 'b742c19790928c8fbc5bd1d5014c8e7aec219507ccac7c1e662bab8b71f39d12'
RUNTIME = {'id': '3000cd73a62f0c852874c2124426ec45b47f26d128843fb56f5963ef9ef98058',
    'config': '7224218131950ce106c764ae838f7cb7f4a33ed07530b869346763d226dc56d4',
    'image': 'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536',
    'restart': 0, 'started': '2026-11-01T04:44:42.917603256Z'}
H = lambda body: hashlib.sha256(body).hexdigest()
_CACHE = None


def need(value, code):
    if not value: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def protected(path, sha):
    for parent in path.parents:
        row = parent.lstat()
        need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_SOURCE_PARENT_REQUIRED')
    before = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, 'ROOT_PRIVATE_SOURCE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); body = stream.read(131073)
    fields = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns, row.st_uid, row.st_mode, row.st_nlink)
    need(fields(before) == fields(opened) == fields(path.lstat()) and len(body) <= 131072 and H(body) == sha, 'EXACT_PROTECTED_SOURCE_BYTES_REQUIRED')
    return body


def dependencies():
    global _CACHE
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)
    body = protected(OLD / 'release.py', RELEASE_SHA)
    if _CACHE is None:
        module = ModuleType('_asset_studio_current_monthly_flow'); module.__file__ = str(OLD / 'release.py')
        exec(compile(body, module.__file__, 'exec'), module.__dict__)
        need(module.SOURCE_SHA == SOURCE and module.FRONTEND == FRONTEND and module.NEW_REVISION == REVISION, 'EXACT_CURRENT_DEPLOYED_SOURCE_REQUIRED')
        args = SimpleNamespace(release=OLD, manifest_sha256=MANIFEST_SHA, payload_sha256=PAYLOAD_SHA,
            preflight=ROOT / ('media-ops-monthly-flow-preflight-' + OLD_PREFLIGHT_SHA[:12] + '.json'), preflight_sha256=OLD_PREFLIGHT_SHA, review_sha256=PREPARED_SHA)
        flow = module.Release(args); c = flow.c
        deployed = c.strict_json(c.read(OLD / 'deployed.json', sha=DEPLOYED_SHA))
        prepared = c.strict_json(c.read(OLD / 'prepared.json', sha=PREPARED_SHA))
        need(deployed['stage'] == 'MEDIA_OPS_MONTHLY_FLOW_DEPLOYED' and deployed['source_sha'] == SOURCE and deployed['frontend_version'] == FRONTEND and deployed['crm'] == RUNTIME and deployed['schema_revision'] == REVISION and deployed['table_count'] == 155 and deployed['schema_sha256'] == SCHEMA_SHA, 'EXACT_DEPLOYMENT_RECEIPT_REQUIRED')
        need(all(deployed[key] is True for key in ('all153_original_tables_preserved_except_reviewed_schema_head', 'existing_full_environment_preserved', 'existing_ops_credentials_preserved', 'private_boundary_preserved', 'old_meta_google_cutoff_preserved')) and
            all(deployed[key] is False for key in ('operations_execution_enabled', 'operations_scheduler_enabled', 'database_restored', 'provider_requests', 'credentials_journaled')), 'EXACT_EXISTING_AUTHORITY_REQUIRED')
        inventory = c.strict_json(c.read(OLD / 'backend-candidate-inventory.json', sha=prepared['candidate_inventory_sha256']))
        _CACHE = (module, flow, inventory)
    return _CACHE


def public_security_policy(m, expected_sha):
    # Public SPA header only: no cookie, authenticated API, provider or body.
    argv = ['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--http1.1', '--max-time', '5', '--max-redirs', '0', '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', 'https://t24-crm.com/media-ops']
    body = m.run(argv, 'PUBLIC_CSP_HEADER_READ_FAILED', 10)
    need(isinstance(body, bytes) and len(body) < 16384, 'BOUNDED_PUBLIC_HEADERS_REQUIRED')
    lines = body.decode('iso-8859-1').splitlines()
    need(lines and re.fullmatch(r'HTTP/1[.]1 200(?: .*)?', lines[0]), 'EXACT_PUBLIC_SPA_200_REQUIRED')
    values = [line.split(':', 1)[1].strip() for line in lines[1:] if ':' in line and line.split(':', 1)[0].lower() == 'content-security-policy']
    need(len(values) == 1 and 0 < len(values[0]) < 8192 and H(values[0].encode()) == expected_sha, 'EXACT_EXISTING_PUBLIC_CSP_REQUIRED')
    return values[0]


def sample():
    module, flow, inventory = dependencies(); m = flow.m; c = flow.c
    current = m.inspect('t24-crm')
    need(current['State']['Running'] is True and m.runtime(current) == RUNTIME, 'EXACT_CURRENT_CONFIGURED_RUNTIME_REQUIRED')
    environment_sha, ops_sha = flow.environment(current)
    flow.ctx.workflow.pf.google_environment(current); m.verify_secret_mount(current); m.verify_production_worker_enabled(current); m.retained().require_safe_original_restart(current)
    flow.source_boundary(current, inventory)
    # Post-release private preparation is legitimate. Preserve its current rows;
    # do not reuse the empty-table assumption from deployment acceptance.
    flow.protections(updated=True, recovery=True, head=REVISION, schema=SCHEMA_SHA)
    rows = flow.retained.evidence(flow.rows())
    need(len(rows) == 155 and rows['media_monthly_workflows']['count'] == 1 and rows['media_monthly_workflow_requests']['count'] >= 1, 'CURRENT155_WITH_PREPARED_PRIVATE_PACKET_REQUIRED')
    need(len(inventory) == 408, 'EXACT_CURRENT_BACKEND_INVENTORY_REQUIRED')
    old = flow.ctx.workflow
    credentials = {'ops': flow.safe.protected_metadata(c.ENV_FILE), 'google': flow.safe.protected_metadata(flow.safe.GBP_ENV),
        'meta_read': flow.safe.protected_metadata(old.core.ENV_FILE), 'meta_legacy': flow.safe.protected_metadata(old.core.LEGACY_ENV_FILE)}
    policy = public_security_policy(m, flow.proof['content_security_policy_sha256'])
    return {'stage': 'MEDIA_ASSET_STUDIO_READONLY_PREFLIGHT', 'host': HOST, 'source_sha': SOURCE, 'frontend_version': FRONTEND, 'schema_revision': REVISION,
        'deployed_receipt_sha256': DEPLOYED_SHA, 'crm': m.runtime(current), 'environment_sha256': environment_sha, 'ops_environment_sha256': ops_sha,
        'schema_sha256': m.schema_signature(m.BUSINESS, REVISION), 'rows': rows, 'database_identity': flow.proof['database_identity'], 'database_metadata': flow.metadata(m.BUSINESS),
        'backend_inventory': inventory, 'backend_inventory_sha256': digest(inventory), 'backend_file_count': len(inventory),
        'credential_boundary': m.credential_boundary(), 'credential_metadata': credentials, 'private_boundary': flow.proof['private_boundary'],
        'public_root': str(flow.public), 'public_inventory_sha256': m.verify_public(flow.public, flow.manifest), 'nginx_sha256': H(m.NGINX.read_bytes()),
        'active_nginx_sha256': H(m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')), 'content_security_policy_sha256': flow.proof['content_security_policy_sha256'],
        'public_content_security_policy': policy, 'csp_environment_override_present': any(entry.split('=', 1)[0] == 'CONTENT_SECURITY_POLICY' for entry in current['Config']['Env']),
        'all155_current_tables_preserved': True, 'prepared_private_packet_preserved': True, 'ops_execution_enabled': False, 'ops_scheduler_enabled': False,
        'google_scheduler_enabled': True, 'google_scheduler_activation_from': '2026-10-30T19:42:04Z',
        'schema_changed': False, 'permissions_changed': False, 'credential_file_content_read': False, 'private_content_read': False,
        'business_writes': False, 'provider_requests': False, 'runtime_changed': False}


ENGINE_PROBE = r'''import hashlib,io,json,os,re,shutil,socket,stat,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit
def blocked(*a,**k):raise RuntimeError('NO_RENDER_INVENTORY_NETWORK')
socket.socket.connect=blocked
H=lambda body:hashlib.sha256(body).hexdigest()
def small(path,limit=65536):
 try:
  with open(path,'rb') as stream:body=stream.read(limit+1)
  return body.decode('ascii') if len(body)<=limit else None
 except (OSError,UnicodeError):return None
def filehash(path,limit=67108864):
 row=path.lstat()
 if not stat.S_ISREG(row.st_mode) or row.st_size>limit or row.st_uid!=0 or row.st_mode&0o022:return None
 h=hashlib.sha256();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno())
  if (row.st_dev,row.st_ino,row.st_size)!=(opened.st_dev,opened.st_ino,opened.st_size):raise RuntimeError('SYSTEM_FILE_OPEN_DRIFT')
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 after=path.lstat()
 if (row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise RuntimeError('SYSTEM_FILE_READ_DRIFT')
 return {'path':str(path),'bytes':row.st_size,'sha256':h.hexdigest()}
result={'python':'.'.join(map(str,sys.version_info[:3])),'cpu_count':os.cpu_count(),'affinity_cpu_count':len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None}
system={'os_release':{},'apt_sources':[]}
for line in (small('/etc/os-release',16384) or '').splitlines():
 key,_,value=line.partition('=');value=value.strip('\"\'')
 if key in {'ID','VERSION_ID','VERSION_CODENAME','ID_LIKE'} and re.fullmatch(r'[A-Za-z0-9._ -]{1,80}',value):system['os_release'][key]=value
sources=[Path('/etc/apt/sources.list')]+sorted(Path('/etc/apt/sources.list.d').glob('*.sources'))+sorted(Path('/etc/apt/sources.list.d').glob('*.list'))
allowed_hosts={'deb.debian.org','security.debian.org','snapshot.debian.org','archive.debian.org','archive.ubuntu.com','security.ubuntu.com','ports.ubuntu.com'}
for path in sources[:16]:
 if not path.exists() or path.is_symlink():continue
 metadata=filehash(path,65536)
 if not metadata:continue
 public=[];withheld=0;schemes=[]
 for line in (small(path,65536) or '').splitlines():
  stripped=line.strip()
  if stripped.startswith('#'):continue
  candidates=stripped.partition(':')[2].split() if stripped.startswith('URIs:') else re.findall(r'https?://[^\s\]]+',stripped) if stripped.startswith(('deb ','deb-src ')) else []
  for raw in candidates:
   try:
    uri=urlsplit(raw)
    if uri.scheme in {'http','https'} and uri.hostname in allowed_hosts and uri.port in {None,80,443} and uri.username is None and uri.password is None and not uri.query and not uri.fragment and re.fullmatch(r'/[A-Za-z0-9/._-]*',uri.path):public.append(raw)
    else:withheld+=1
   except ValueError:withheld+=1
 system['apt_sources'].append({**metadata,'official_public_uris':sorted(set(public)),'other_or_credentialed_uri_count_withheld':withheld})
for name in ('apt-get','dpkg-query'):
 raw=shutil.which(name,path='/usr/local/bin:/usr/bin:/bin');system[name]={'available':bool(raw)}
 if raw:
  path=Path(raw).resolve()
  if path.parent in {Path('/usr/local/bin'),Path('/usr/bin'),Path('/bin')}:
   metadata=filehash(path,16777216)
   if metadata:system[name].update(metadata)
system['installed_render_packages']=[]
query=system['dpkg-query']
if query.get('sha256'):
 proc=subprocess.run([query['path'],'--show','--showformat=${binary:Package} ${Version}\n','ffmpeg','fonts-noto-cjk'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},timeout=5,check=False)
 if len(proc.stdout)>16384:raise RuntimeError('BOUNDED_PACKAGE_QUERY_REQUIRED')
 for line in proc.stdout.decode('ascii',errors='replace').splitlines():
  if re.fullmatch(r'(?:ffmpeg|fonts-noto-cjk)(?::[A-Za-z0-9_-]+)? [A-Za-z0-9.+:~_-]{1,100}',line):system['installed_render_packages'].append(line)
result['system']=system
mem={}
for line in (small('/proc/meminfo') or '').splitlines():
 key,_,value=line.partition(':')
 if key in {'MemTotal','MemAvailable','SwapTotal','SwapFree'} and re.fullmatch(r'\s*\d+ kB',value):mem[key+'_bytes']=int(value.strip().split()[0])*1024
result['memory']=mem
cg={}
for name in ('memory.max','memory.current','cpu.max','pids.max','memory/memory.limit_in_bytes','memory/memory.usage_in_bytes','cpu/cpu.cfs_quota_us','cpu/cpu.cfs_period_us'):
 value=small('/sys/fs/cgroup/'+name,4096)
 if value is not None and re.fullmatch(r'(?:max|-?\d+)(?: (?:max|-?\d+))?\n?',value):cg[name]=value.strip()
result['cgroup']=cg
disks={}
for raw in ('/','/opt/t24-crm','/var/www'):
 if Path(raw).is_dir():
  row=os.statvfs(raw);disks[raw]={'total_bytes':row.f_frsize*row.f_blocks,'available_bytes':row.f_frsize*row.f_bavail}
result['disk']=disks
try:
 import PIL
 from PIL import Image,ImageFont,features
 buf=io.BytesIO();Image.new('RGB',(8,8),(30,60,90)).save(buf,format='PNG')
 result['pillow']={'available':True,'version':PIL.__version__,'in_memory_png_probe':buf.getvalue().startswith(b'\x89PNG\r\n\x1a\n'),'features':{k:bool(features.check(k)) for k in ('jpg','freetype2','raqm','webp','zlib')}}
except ImportError:result['pillow']={'available':False}
fonts=[];visited=0;overflow=False
for raw in ('/usr/share/fonts','/usr/local/share/fonts'):
 root=Path(raw)
 if not root.is_dir() or root.is_symlink():continue
 for directory,dirs,files in os.walk(root,followlinks=False):
  dirs[:]=sorted(n for n in dirs if not (Path(directory)/n).is_symlink() and len((Path(directory)/n).relative_to(root).parts)<=8)
  for name in sorted(files):
   visited+=1
   if visited>2048:overflow=True;break
   path=Path(directory)/name
   if path.suffix.lower() in {'.ttf','.ttc','.otf'} and not path.is_symlink():fonts.append(path)
  if overflow:break
 if overflow:break
fonts=sorted(set(fonts),key=lambda p:(not bool(re.search('cjk|wqy|noto|unicode|dejavu|liberation',p.name,re.I)),str(p)))
limited=len(fonts)>64;inventory=[];total=0
for path in fonts[:64]:
 if total+path.stat().st_size>268435456:limited=True;break
 row=filehash(path)
 if row:
  total+=row['bytes']
  if result['pillow']['available'] and len(inventory)<12:
   try:
    f=ImageFont.truetype(str(path),32);missing=H(bytes(f.getmask('\U0010ffff')))
    row['font_name']=list(f.getname());row['sample_glyphs_differ_from_missing']={text:H(bytes(f.getmask(text)))!=missing for text in ('北','面','A')};del f
   except OSError:row['pillow_loadable']=False
  inventory.append(row)
result['fonts']={'files':inventory,'count':len(inventory),'truncated':overflow or limited,'total_hashed_bytes':total}
licenses=[]
for directory in sorted(Path('/usr/share/doc').glob('fonts-*'))[:64]:
 if directory.is_dir() and not directory.is_symlink():
  for name in ('copyright','LICENSE','LICENSE.txt','OFL.txt'):
   path=directory/name
   if path.exists() and not path.is_symlink():
    row=filehash(path,262144)
    if row:licenses.append(row)
result['font_license_metadata']=licenses[:32]
bins={}
for name in ('ffmpeg','ffprobe'):
 raw=shutil.which(name,path='/usr/local/bin:/usr/bin:/bin')
 if not raw:bins[name]={'available':False};continue
 path=Path(raw).resolve()
 if path.parent not in {Path('/usr/local/bin'),Path('/usr/bin'),Path('/bin')}:bins[name]={'available':False,'untrusted_path':True};continue
 row=filehash(path,134217728)
 if not row:bins[name]={'available':False,'untrusted_file':True};continue
 proc=subprocess.Popen([str(path),'-version'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'},close_fds=True)
 try:
  body,_=proc.communicate(timeout=5);code=proc.returncode
  if len(body)>65536 or code!=0:raise RuntimeError('BOUNDED_VERSION_PROBE_REQUIRED')
  lines=[line.strip()[:240] for line in body.decode('utf-8',errors='replace').splitlines() if re.match(r'^(?:ffmpeg version|ffprobe version|libav\w+\s|libsw\w+\s|libpostproc\s)',line)]
  bins[name]={'available':True,**row,'version_lines':lines[:10]}
 finally:
  if proc.poll() is None:proc.kill();proc.wait(timeout=5)
  proc.stdout.close()
result['binaries']=bins
result['writes']=False;result['network_requests']=False;result['credentials_read']=False
print(json.dumps(result,sort_keys=True))
'''


def capacity():
    _, flow, _ = dependencies(); m = flow.m
    info = m.inspect('t24-crm')
    need(m.runtime(info) == RUNTIME, 'CAPACITY_REQUIRES_EXACT_CURRENT_RUNTIME')
    code = ENGINE_PROBE
    host = json.loads(m.run(['python3', '-I', '-B', '-c', code], 'HOST_CAPACITY_INVENTORY_FAILED', 90))
    container = json.loads(m.run(['docker', 'exec', RUNTIME['id'], 'python', '-I', '-B', '-c', code], 'CONTAINER_CAPACITY_INVENTORY_FAILED', 90))
    need(container['python'].startswith('3.10.') and all(row['writes'] is False and row['network_requests'] is False and row['credentials_read'] is False for row in (host, container)), 'READONLY_CAPACITY_PROBE_REQUIRED')
    allowed = ('Memory', 'MemorySwap', 'NanoCpus', 'CpuQuota', 'CpuPeriod', 'CpuShares', 'PidsLimit', 'OomKillDisable', 'ReadonlyRootfs')
    limits = {name: info['HostConfig'].get(name) for name in allowed}
    need(all(value is None or type(value) in (int, bool) for value in limits.values()), 'RESOURCE_METADATA_TYPES_REQUIRED')
    need(m.runtime(m.inspect('t24-crm')) == RUNTIME, 'RUNTIME_CHANGED_DURING_CAPACITY_CAPTURE')
    return {'host': host, 'container': container, 'container_resource_limits': limits,
        'installation_performed': False, 'container_changed': False, 'worker_started': False, 'provider_requests': False}


def capture():
    first = sample(); engines = capacity(); current = sample()
    _, flow, _ = dependencies(); c = flow.c
    flow.retained.live_sequence_boundary(first['database_metadata'], current['database_metadata'])
    need({**current, 'database_metadata': first['database_metadata']} == first, 'CURRENT155_BOUNDARIES_CHANGED_DURING_CAPTURE')
    proof = {**current, 'render_capacity': engines}
    body = (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode(); sha = H(body)
    path = ROOT / ('media-asset-studio-preflight-' + sha[:12] + '.json')
    if path.exists(): c.read(path, sha=sha)
    else: c.write(path, body)
    compact = lambda row: {**{key: row[key] for key in ('python', 'cpu_count', 'affinity_cpu_count', 'memory', 'cgroup', 'disk', 'pillow', 'binaries', 'system')},
        'fonts': {**{key: row['fonts'][key] for key in ('count', 'truncated', 'total_hashed_bytes')}, 'files': row['fonts']['files'][:16]}, 'font_license_metadata': row['font_license_metadata'][:16]}
    keys = ('host', 'source_sha', 'frontend_version', 'schema_revision', 'deployed_receipt_sha256', 'crm', 'environment_sha256', 'ops_environment_sha256', 'schema_sha256',
        'backend_inventory_sha256', 'backend_file_count', 'public_root', 'public_inventory_sha256', 'nginx_sha256', 'active_nginx_sha256', 'content_security_policy_sha256', 'public_content_security_policy', 'csp_environment_override_present',
        'all155_current_tables_preserved', 'prepared_private_packet_preserved', 'ops_execution_enabled', 'ops_scheduler_enabled', 'google_scheduler_enabled', 'google_scheduler_activation_from')
    return {'stage': 'MEDIA_ASSET_STUDIO_PREFLIGHT_CAPTURED', 'sha256': sha, 'path': str(path), 'bytes': len(body), 'table_count': 155, 'rows_sha256': digest(current['rows']),
        'prepared_private_packet_count': current['rows']['media_monthly_workflows']['count'], **{key: current[key] for key in keys},
        'render_capacity': {'host': compact(engines['host']), 'container': compact(engines['container']), 'container_resource_limits': engines['container_resource_limits']},
        'installation_performed': False, 'worker_started': False, 'schema_changed': False, 'permissions_changed': False, 'credential_file_content_read': False,
        'private_content_read': False, 'business_writes': False, 'provider_requests': False, 'runtime_changed': False}
