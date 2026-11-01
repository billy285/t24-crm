"""Stage public Debian rendering dependencies in a NEW image only.

Fetch runs without application entrypoint, business data or credential mounts.
The installation build has no network and consumes a verified local .deb closure.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PREFLIGHT_SHA = '33e3ced927bc7fd872d5f8b1395ec46f14db48ebb4c8ac4e8199fc067b5b88a9'
ACTUAL_PROOF_SHA = 'bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
TOP = {'ffmpeg': '7:7.1.5-0+deb13u1', 'fonts-noto-cjk': '1:20240730+repack1-1', 'fonts-dejavu-core': '2.37-8'}
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value: raise RuntimeError(code)


def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


FETCH = r'''import hashlib,json,os,re,subprocess
from pathlib import Path
os.umask(0o077)
TOP=__TOP__
OUT=Path('/out');PACKAGES=OUT/'packages';PACKAGES.mkdir(mode=0o755)
H=lambda b:hashlib.sha256(b).hexdigest()
ENV={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','DEBIAN_FRONTEND':'noninteractive','PYTHONDONTWRITEBYTECODE':'1'}
def run(argv,timeout=300):
 p=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=ENV,timeout=timeout,check=False)
 if len(p.stdout)>1048576:raise RuntimeError('BOUNDED_APT_OUTPUT_REQUIRED')
 if p.returncode:raise RuntimeError('OFFICIAL_DEBIAN_PACKAGE_RESOLUTION_FAILED')
 return p.stdout.decode('utf-8',errors='strict')
def packages():
 text=run(['/usr/bin/dpkg-query','--show','--showformat=${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'],30)
 result={}
 for line in text.splitlines():
  fields=line.split('\t')
  if len(fields)==4 and fields[3]=='installed':
   name,version,arch,_=fields
   if name in result or not re.fullmatch('[a-z0-9][a-z0-9+.-]+',name):raise RuntimeError('UNIQUE_BASE_PACKAGES_REQUIRED')
   result[name]={'version':version,'architecture':arch}
 return result
if run(['/usr/bin/dpkg','--print-architecture'],10).strip()!='amd64' or run(['/usr/bin/dpkg','--print-foreign-architectures'],10).strip():raise RuntimeError('EXACT_AMD64_NO_FOREIGN_ARCH_REQUIRED')
before=packages()
if set(TOP)&set(before):raise RuntimeError('RENDER_ROOT_PACKAGES_MUST_BE_NEW')
for p in [Path('/etc/apt/sources.list')]+list(Path('/etc/apt/sources.list.d').glob('*.list'))+list(Path('/etc/apt/sources.list.d').glob('*.sources')):
 if p.exists():p.unlink()
source='deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian trixie main\ndeb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian trixie-updates main\ndeb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian-security trixie-security main\n'
Path('/etc/apt/sources.list').write_text(source)
options=['-o','Acquire::Retries=2','-o','Acquire::http::Timeout=30','-o','Acquire::https::Timeout=30','-o','Acquire::http::Proxy=DIRECT','-o','Acquire::https::Proxy=DIRECT','-o','APT::Get::AllowUnauthenticated=false','-o','Acquire::AllowInsecureRepositories=false','-o','Acquire::AllowDowngradeToInsecureRepositories=false']
run(['/usr/bin/apt-get',*options,'update'])
roots=[name+'='+version for name,version in sorted(TOP.items())]
flags=['--no-install-recommends','--no-remove','--no-upgrade']
simulation=run(['/usr/bin/apt-get',*options,'--simulate',*flags,'install',*roots])
selected={}
for line in simulation.splitlines():
 if line.startswith(('Remv ','Purg ')):raise RuntimeError('NO_REMOVAL_PERMITTED')
 if not line.startswith('Inst '):continue
 match=re.fullmatch(r'Inst ([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9_-]+)?(?: \[[^\]]+\])? \(([^ ]+) .+\)',line)
 if not match:raise RuntimeError('EXACT_APT_PLAN_FORMAT_REQUIRED')
 name,version=match.groups()
 if name in before or name in selected:raise RuntimeError('EXISTING_PACKAGE_UPGRADE_OR_DUPLICATE_REJECTED')
 selected[name]=version
if not 3<=len(selected)<=180 or any(selected.get(n)!=v for n,v in TOP.items()):raise RuntimeError('BOUNDED_EXACT_RENDER_CLOSURE_REQUIRED')
download_options=['-o','Dir::Cache::archives='+str(PACKAGES)+'/',*options]
run(['/usr/bin/apt-get',*download_options,'--download-only','--assume-yes',*flags,'install',*roots])
if packages()!=before:raise RuntimeError('FETCH_MUST_NOT_INSTALL_OR_UPGRADE')
files={};installed_bytes=0
for path in sorted(PACKAGES.glob('*.deb')):
 if path.is_symlink() or not path.is_file() or path.stat().st_size>134217728:raise RuntimeError('BOUNDED_REGULAR_DEB_REQUIRED')
 fields=run(['/usr/bin/dpkg-deb','--show','--showformat=${Package}\t${Version}\t${Architecture}\n',str(path)],30).strip().split('\t')
 if len(fields)!=3:raise RuntimeError('EXACT_DEB_FIELDS_REQUIRED')
 name,version,arch=fields
 if selected.get(name)!=version or name in files or name in before or arch not in {'all','amd64'}:raise RuntimeError('EXACT_NEW_CLOSURE_MEMBER_REQUIRED')
 paragraphs=run(['/usr/bin/apt-cache','show',name+'='+version],30).strip().split('\n\n');matches=[]
 for paragraph in paragraphs:
  row={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in paragraph.splitlines() if ': ' in line and not line.startswith(' ')}
  if row.get('Package')==name and row.get('Version')==version and row.get('Architecture')==arch:matches.append(row)
 actual=H(path.read_bytes());matching=[row for row in matches if row.get('SHA256')==actual and row.get('Size')==str(path.stat().st_size)]
 if not matching:raise RuntimeError('SIGNED_APT_SHA256_REQUIRED')
 row=matching[0];filename=row.get('Filename','')
 if not re.fullmatch(r'pool/[A-Za-z0-9/_.+:%~-]+[.]deb',filename):raise RuntimeError('OFFICIAL_POOL_PATH_REQUIRED')
 installed_bytes+=int(row.get('Installed-Size','0'))*1024
 files[name]={'version':version,'architecture':arch,'file':path.name,'bytes':path.stat().st_size,'sha256':actual,'official_pool_path':filename}
 os.chown(path,0,0);path.chmod(0o600)
if set(files)!=set(selected) or sum(row['bytes'] for row in files.values())>536870912 or installed_bytes>1073741824:raise RuntimeError('COMPLETE_BOUNDED_DOWNLOADED_CLOSURE_REQUIRED')
indices={path.name:H(path.read_bytes()) for path in Path('/var/lib/apt/lists').glob('*InRelease') if path.is_file() and not path.is_symlink() and path.stat().st_size<1048576}
if not indices or len(indices)>4:raise RuntimeError('SIGNED_OFFICIAL_INRELEASE_REQUIRED')
result={'stage':'OFFICIAL_DEBIAN_RENDER_PACKAGES_FROZEN','base_packages':before,'packages':files,'top_packages':TOP,'signed_inrelease_sha256':indices,'official_sources':source,'total_download_bytes':sum(row['bytes'] for row in files.values()),'estimated_installed_bytes':installed_bytes,'base_packages_unchanged':True,'installation_performed':False,'business_or_credentials_mounted':False}
Path('/out/packages.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
'''


INSTALL = r'''import hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path('/tmp/t24-render-deps');manifest=json.loads((ROOT/'packages.json').read_text())
def query():
 text=subprocess.check_output(['/usr/bin/dpkg-query','--show','--showformat=${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'],text=True)
 result={}
 for line in text.splitlines():
  f=line.split('\t')
  if len(f)==4 and f[3]=='installed':result[f[0]]={'version':f[1],'architecture':f[2]}
 return result
before=query()
if before!=manifest['base_packages']:raise RuntimeError('EXACT_BASE_PACKAGE_INVENTORY_REQUIRED')
paths=[]
for name,row in sorted(manifest['packages'].items()):
 path=ROOT/'packages'/row['file']
 if path.is_symlink() or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('EXACT_FROZEN_DEB_REQUIRED')
 paths.append(str(path))
env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','DEBIAN_FRONTEND':'noninteractive','PYTHONDONTWRITEBYTECODE':'1'}
subprocess.run(['/usr/bin/apt-get','--assume-yes','--no-download','--no-remove','--no-upgrade','--no-install-recommends','install',*paths],env=env,check=True,stdin=subprocess.DEVNULL,timeout=240)
after=query();expected={**before,**{name:{'version':row['version'],'architecture':row['architecture']} for name,row in manifest['packages'].items()}}
if after!=expected:raise RuntimeError('ONLY_REVIEWED_ADDED_PACKAGES_REQUIRED')
Path('/usr/local/share/t24-render-toolchain').mkdir(mode=0o755)
(Path('/usr/local/share/t24-render-toolchain')/'packages.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
'''


PROBE = r'''import hashlib,io,json,os,subprocess,tempfile
from pathlib import Path
import PIL
from PIL import Image,ImageDraw,ImageFont,features
fontpath=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc');latin=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
font=ImageFont.truetype(str(fontpath),32,index=2,layout_engine=ImageFont.Layout.BASIC)
H=lambda b:hashlib.sha256(b).hexdigest()
missing=H(bytes(font.getmask('\U0010ffff')))
if any(H(bytes(font.getmask(c)))==missing for c in ('北','面','A')):raise RuntimeError('CJK_AND_LATIN_GLYPHS_REQUIRED')
env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','OMP_NUM_THREADS':'1'}
with tempfile.TemporaryDirectory(prefix='t24-render-capability-') as temp:
 root=Path(temp)
 for i,color in enumerate(((30,80,150),(80,150,30))):
  image=Image.new('RGB',(32,32),color);ImageDraw.Draw(image).text((0,0),'面',font=font,fill=(255,255,255));image.save(root/f'frame{i:02}.png')
 subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-framerate','2','-i',str(root/'frame%02d.png'),'-t','1','-an','-map_metadata','-1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(root/'sample.mp4')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=env,check=True,timeout=15)
 meta=json.loads(subprocess.check_output(['/usr/bin/ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name,width,height,pix_fmt','-of','json',str(root/'sample.mp4')],env=env,timeout=5))
 row=meta['streams'][0]
 if row!={'codec_name':'h264','width':32,'height':32,'pix_fmt':'yuv420p'}:raise RuntimeError('EXACT_H264_MP4_CANARY_REQUIRED')
 video=(root/'sample.mp4').read_bytes()
 if not 0<len(video)<1048576:raise RuntimeError('BOUNDED_MP4_REQUIRED')
 result={'python_pillow':PIL.__version__,'freetype2':features.check('freetype2'),'font':{'path':str(fontpath),'sha256':H(fontpath.read_bytes()),'collection_index':2,'name':font.getname()},'latin_font':{'path':str(latin),'sha256':H(latin.read_bytes())},'cjk_and_latin_glyphs_verified':True,'actual_h264_mp4':{'sha256':H(video),'bytes':len(video),**row},'license_files':{str(p):H(p.read_bytes()) for p in (Path('/usr/share/doc/fonts-noto-cjk/copyright'),Path('/usr/share/doc/fonts-dejavu-core/copyright'),Path('/usr/share/doc/ffmpeg/copyright'))},'ffmpeg_version':subprocess.check_output(['/usr/bin/ffmpeg','-version'],env=env,timeout=5).decode().splitlines()[0],'no_business_data_credentials_or_provider_requests':True}
 if result['python_pillow']!='12.3.0' or not result['freetype2']:raise RuntimeError('EXISTING_PILLOW_MUST_BE_PRESERVED')
 backend=Path('/app/backend');inventory={}
 for folder,dirs,files in os.walk(backend,followlinks=False):
  dirs[:]=[name for name in dirs if name not in {'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules'}]
  for child in dirs+files:
   if (Path(folder)/child).is_symlink():raise RuntimeError('BACKEND_SOURCE_SYMLINK_REJECTED')
  for child in files:
   path=Path(folder)/child
   if not child.endswith(('.pyc','.pyo')) and path.is_file():inventory[str(path.relative_to(backend))]=H(path.read_bytes())
 result['backend_file_count']=len(inventory);result['backend_inventory_sha256']=H(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode())
 print(json.dumps(result,sort_keys=True))
'''


def copy_public_package(source, target, expected_sha, expected_size):
    """Stream only a verified public .deb; credential helper limits stay intact."""
    need(source.resolve() == source and target.resolve() == target and re.fullmatch('[a-f0-9]{64}', expected_sha) and
        type(expected_size) is int and 0 < expected_size <= 134217728 and source.suffix == target.suffix == '.deb', 'BOUNDED_PUBLIC_PACKAGE_COPY_REQUIRED')
    for path in (source.parent, target.parent):
        for parent in (path, *path.parents):
            row = parent.lstat()
            need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_PUBLIC_PACKAGE_PARENT_REQUIRED')
    before = source.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size == expected_size, 'EXACT_PUBLIC_PACKAGE_SOURCE_REQUIRED')
    src = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(src, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        fields = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns, row.st_uid, row.st_mode, row.st_nlink)
        need(fields(before) == fields(opened), 'PUBLIC_PACKAGE_SOURCE_OPEN_DRIFT')
        dst = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(dst, 'wb') as output:
            target_before = os.fstat(output.fileno()); digest = hashlib.sha256(); count = 0
            for chunk in iter(lambda: stream.read(1048576), b''):
                count += len(chunk); need(count <= expected_size, 'PUBLIC_PACKAGE_SIZE_DRIFT')
                digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno()); target_after = os.fstat(output.fileno())
            need(count == expected_size and digest.hexdigest() == expected_sha and fields(before) == fields(source.lstat()), 'EXACT_PUBLIC_PACKAGE_HASH_AND_IDENTITY_REQUIRED')
            need(target_after.st_uid == 0 and target_after.st_nlink == 1 and stat.S_IMODE(target_after.st_mode) == 0o600 and target_after.st_size == count and
                (target_before.st_dev, target_before.st_ino) == (target_after.st_dev, target_after.st_ino) == (target.lstat().st_dev, target.lstat().st_ino), 'PUBLIC_PACKAGE_DESTINATION_DRIFT')
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def run(pf, tool_sha, source):
    need(re.fullmatch('[a-f0-9]{64}', tool_sha) and H(source) == tool_sha, 'EXACT_TOOLCHAIN_TOOL_REQUIRED')
    _, flow, inventory = pf.dependencies(); c = flow.c; m = flow.m
    path = pf.ROOT / ('media-asset-studio-preflight-' + ACTUAL_PROOF_SHA[:12] + '.json')
    proof = c.strict_json(c.read(path, sha=ACTUAL_PROOF_SHA))
    def baseline():
        observed = pf.sample()
        need({**observed, 'database_metadata': proof['database_metadata']} == {key: value for key, value in proof.items() if key != 'render_capacity'}, 'EXACT_CURRENT155_BASELINE_REQUIRED')
        flow.retained.live_sequence_boundary(proof['database_metadata'], observed['database_metadata'])
    baseline()
    need(proof['render_capacity']['container']['system']['os_release'] == {'ID': 'debian', 'VERSION_ID': '13', 'VERSION_CODENAME': 'trixie'}, 'EXACT_DEBIAN13_BASE_REQUIRED')
    scope = 'media-asset-studio-toolchain-' + tool_sha[:12] + '-20261101'; work = pf.ROOT / scope
    need(not work.exists() and not work.is_symlink(), 'FRESH_TOOLCHAIN_STAGING_REQUIRED')
    for parent in work.parents:
        row = parent.lstat(); need(parent.resolve() == parent and row.st_uid == 0 and stat.S_ISDIR(row.st_mode) and not row.st_mode & 0o022, 'PROTECTED_TOOLCHAIN_PARENT_REQUIRED')
    name = 't24-asset-fetch-' + tool_sha[:12]; probe_name = 't24-asset-toolchain-probe-' + tool_sha[:12]
    need(not m.inspect_optional(name) and not m.inspect_optional(probe_name), 'FRESH_TOOLCHAIN_CONTAINER_NAMES_REQUIRED')
    tag = 't24-crm:asset-toolchain-' + tool_sha[:12]
    need(m.image_id(tag) is None and m.image_id(pf.RUNTIME['image']) == pf.RUNTIME['image'], 'FRESH_EXACT_TOOLCHAIN_IMAGE_REQUIRED')
    need(os.statvfs('/opt/t24-crm').f_frsize * os.statvfs('/opt/t24-crm').f_bavail >= 6 * 1024**3, 'TOOLCHAIN_MINIMUM_DISK_REQUIRED')
    work.mkdir(mode=0o700); data = work / 'fetch-data'; data.mkdir(mode=0o700)
    c.write(work / 'toolchain.py', source)
    fetch = FETCH.replace('__TOP__', repr(TOP))
    m.run(['docker', 'run', '--name', name, '--network', 'bridge', '--memory', '768m', '--memory-swap', '768m', '--cpus', '1', '--pids-limit', '128', '--restart', 'no', '--no-healthcheck', '--security-opt', 'no-new-privileges', '--mount', 'type=bind,src=' + str(data) + ',dst=/out', '--entrypoint', '/usr/bin/env', pf.RUNTIME['image'], '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1', '/usr/local/bin/python', '-I', '-B', '-c', fetch], 'ISOLATED_DEBIAN_FETCH_FAILED', 900)
    info = m.inspect(name)
    need(info['State']['Running'] is False and info['State']['ExitCode'] == 0 and info['Image'] == pf.RUNTIME['image'] and len(info['Mounts']) == 1 and info['Mounts'][0]['Source'] == str(data) and info['Mounts'][0]['Destination'] == '/out', 'EXACT_DATAFREE_FETCH_CONTAINER_REQUIRED')
    manifest_body = c.read(data / 'packages.json'); manifest = c.strict_json(manifest_body)
    need(manifest['top_packages'] == TOP and manifest['base_packages_unchanged'] is True and manifest['installation_performed'] is False and manifest['business_or_credentials_mounted'] is False, 'EXACT_PUBLIC_PACKAGE_CLOSURE_REQUIRED')
    packages = manifest['packages']; need(3 <= len(packages) <= 180 and not set(packages).intersection(manifest['base_packages']) and all(packages.get(name, {}).get('version') == version for name, version in TOP.items()), 'ADDED_PACKAGES_ONLY_REQUIRED')
    need(all(re.fullmatch('[a-z0-9][a-z0-9+.-]+', name) and re.fullmatch('[A-Za-z0-9.+:~_-]{1,100}', row['version']) and row['architecture'] in {'all', 'amd64'} and re.fullmatch('[a-f0-9]{64}', row['sha256']) and type(row['bytes']) is int and 0 < row['bytes'] <= 134217728 for name, row in packages.items()), 'EXACT_BOUNDED_PACKAGE_FIELDS_REQUIRED')
    need(sum(row['bytes'] for row in packages.values()) == manifest['total_download_bytes'] <= 536870912 and manifest['estimated_installed_bytes'] <= 1073741824, 'EXACT_BOUNDED_PUBLIC_DOWNLOADS_REQUIRED')
    members = {row['file'] for row in packages.values()}
    need({p.name for p in (data / 'packages').glob('*.deb')} == members and all(re.fullmatch('[A-Za-z0-9_.+:%~-]+[.]deb', n) for n in members), 'EXACT_REGULAR_DEB_MEMBER_SET_REQUIRED')
    context = work / 'build'; context.mkdir(mode=0o700); (context / 'packages').mkdir(mode=0o700)
    for row in packages.values(): copy_public_package(data / 'packages' / row['file'], context / 'packages' / row['file'], row['sha256'], row['bytes'])
    c.write(context / 'packages.json', manifest_body); c.write(context / 'install.py', INSTALL.encode())
    dockerfile = 'FROM ' + pf.RUNTIME['image'] + '\nCOPY packages /tmp/t24-render-deps/packages\nCOPY packages.json install.py /tmp/t24-render-deps/\nRUN /usr/local/bin/python -I -B /tmp/t24-render-deps/install.py && rm -rf /tmp/t24-render-deps\n'
    c.write(context / 'Dockerfile', dockerfile.encode())
    m.run(['docker', 'build', '--network=none', '--pull=false', '--memory', '768m', '--cpu-period', '100000', '--cpu-quota', '100000', '-t', tag, str(context)], 'OFFLINE_RENDER_TOOLCHAIN_BUILD_FAILED', 900)
    image = m.image_id(tag); need(re.fullmatch('sha256:[a-f0-9]{64}', image or ''), 'EXACT_NEW_TOOLCHAIN_IMAGE_REQUIRED')
    probe = json.loads(m.run(['docker', 'run', '--name', probe_name, '--network', 'none', '--memory', '768m', '--memory-swap', '768m', '--cpus', '1', '--pids-limit', '64', '--restart', 'no', '--no-healthcheck', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=67108864', '--entrypoint', '/usr/bin/env', image, '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1', '/usr/local/bin/python', '-I', '-B', '-c', PROBE], 'OFFLINE_RENDER_ENGINE_CANARY_FAILED', 60))
    info = m.inspect(probe_name)
    need(info['State']['Running'] is False and info['State']['ExitCode'] == 0 and info['Image'] == image and info['HostConfig']['NetworkMode'] == 'none' and all(row['Type'] == 'tmpfs' and row['Destination'] == '/tmp' for row in info['Mounts']), 'OFFLINE_NO_CREDENTIAL_OR_DATA_MOUNTS_REQUIRED')
    need(probe['backend_file_count'] == 408 and probe['backend_inventory_sha256'] == proof['backend_inventory_sha256'], 'TOOLCHAIN_MUST_NOT_CHANGE_408_BACKEND_FILES')
    baseline()
    result = {'stage': 'MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED', 'tool_sha256': tool_sha, 'preflight_sha256': ACTUAL_PROOF_SHA, 'source_sha': pf.SOURCE, 'frontend_version': pf.FRONTEND,
        'base_image': pf.RUNTIME['image'], 'toolchain_image': image, 'image_tag': tag, 'packages_manifest_sha256': H(manifest_body), 'base_package_inventory_sha256': pf.digest(manifest['base_packages']),
        'added_package_count': len(packages), 'top_packages': TOP, 'total_download_bytes': manifest['total_download_bytes'], 'estimated_installed_bytes': manifest['estimated_installed_bytes'],
        'engine_canary': probe, 'all155_current_rows_and_private_packet_preserved': True, 'all408_backend_files_unchanged': True, 'no_existing_package_upgraded_or_removed': True,
        'fetch_only_official_signed_debian': True, 'install_and_engine_probe_network_none': True, 'production_or_host_installation': False, 'production_container_changed': False,
        'credentials_or_business_data_mounted': False, 'api_or_worker_started': False, 'official_debian_package_network_fetch_performed': True, 'social_ai_or_payment_provider_requests': False, 'publications_performed': False}
    body = encoded(result); c.write(work / 'toolchain-prepared.json', body)
    return {**result, 'receipt_sha256': H(body), 'receipt_path': str(work / 'toolchain-prepared.json')}
