"""Propose public dependencies in a fresh data-free container; never install."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import subprocess
from types import ModuleType

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
TOOL = Path('/opt/t24-crm/releases/media-asset-studio-toolchain-4fe7ee52647f-20261101/toolchain.py')
TOOL_SHA = '4fe7ee52647ff1775c8b3e7ac9bce60208aa66806324d3c4a51f80ff23f16fe7'
IMAGE = 'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'
RUNTIME = {'id':'3000cd73a62f0c852874c2124426ec45b47f26d128843fb56f5963ef9ef98058', 'image':IMAGE, 'restart':0, 'started':'2026-11-01T04:44:42.917603256Z', 'running':True}
TOP = {'ffmpeg':'7:7.1.5-0+deb13u1', 'fonts-noto-cjk':'1:20240730+repack1-1', 'fonts-dejavu-core':'2.37-8'}
MARKER = "\nif not 3<=len(selected)<=180 or any(selected.get(n)!=v for n,v in TOP.items()):raise RuntimeError('BOUNDED_EXACT_RENDER_CLOSURE_REQUIRED')\n"
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value: raise RuntimeError(code)


def secure_directory(path):
    for parent in (path, *path.parents):
        row = parent.lstat()
        need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_RESOLUTION_PARENT_REQUIRED')


def read_private(path, maximum=1048576, sha=None):
    secure_directory(path.parent)
    before = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= maximum, 'EXACT_PRIVATE_RESOLUTION_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); body = stream.read(maximum + 1)
    fields = lambda row: (row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before) == fields(opened) == fields(path.lstat()) and len(body) == before.st_size and len(body) <= maximum and (sha is None or H(body) == sha), 'RESOLUTION_FILE_HASH_OR_IDENTITY_DRIFT')
    return body


def write_private(path, body):
    secure_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream: stream.write(body); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


PROPOSAL = r'''
if not 1<=len(selected)<=400:raise RuntimeError('BOUNDED_RESOLUTION_PROPOSAL_REQUIRED')
metadata_text=run(['/usr/bin/apt-cache','show',*[name+'='+version for name,version in sorted(selected.items())]],60)
paragraphs=metadata_text.strip().split('\n\n');metadata={}
for paragraph in paragraphs:
 row={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in paragraph.splitlines() if ': ' in line and not line.startswith(' ')}
 name=row.get('Package');version=row.get('Version')
 if name not in selected or version!=selected[name]:continue
 if row.get('Architecture') not in {'all','amd64'}:continue
 if not re.fullmatch(r'pool/[A-Za-z0-9/_.+:%~-]+[.]deb',row.get('Filename','')) or not re.fullmatch('[a-f0-9]{64}',row.get('SHA256','')):raise RuntimeError('SIGNED_OFFICIAL_PACKAGE_METADATA_REQUIRED')
 if not row.get('Size','').isdigit() or not row.get('Installed-Size','').isdigit():raise RuntimeError('PACKAGE_ESTIMATE_FIELDS_REQUIRED')
 size,installed=int(row['Size']),int(row['Installed-Size'])*1024
 if not 0<size<=134217728 or not 0<=installed<=1073741824:raise RuntimeError('BOUNDED_PACKAGE_ESTIMATES_REQUIRED')
 item={'version':version,'architecture':row['Architecture'],'sha256':row['SHA256'],'download_bytes':size,'installed_bytes':installed,'official_pool_path':row['Filename']}
 if name in metadata and metadata[name]!=item:raise RuntimeError('AMBIGUOUS_SIGNED_PACKAGE_METADATA')
 metadata[name]=item
if set(metadata)!=set(selected):raise RuntimeError('COMPLETE_SIGNED_RESOLUTION_METADATA_REQUIRED')
indices={path.name:H(path.read_bytes()) for path in Path('/var/lib/apt/lists').glob('*InRelease') if path.is_file() and not path.is_symlink() and path.stat().st_size<1048576}
if not indices or len(indices)>4:raise RuntimeError('SIGNED_OFFICIAL_INRELEASE_REQUIRED')
if packages()!=before:raise RuntimeError('RESOLUTION_MUST_NOT_INSTALL_OR_UPGRADE')
total=sum(row['download_bytes'] for row in metadata.values());installed=sum(row['installed_bytes'] for row in metadata.values())
result={'stage':'PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED','selected_count':len(selected),'selected_top_versions':{name:selected.get(name) for name in TOP},'expected_top_versions':TOP,'top_versions_match':all(selected.get(name)==version for name,version in TOP.items()),'selected_new_versions':selected,'selected_packages':metadata,'base_package_count':len(before),'simulation_stdout_sha256':H(simulation.encode()),'signed_inrelease_sha256':indices,'total_download_bytes':total,'estimated_installed_bytes':installed,'within_original_package_count_bound':3<=len(selected)<=180,'within_original_download_bound':total<=536870912,'within_original_installed_bound':installed<=1073741824,'base_packages_unchanged':True,'installation_performed':False,'package_download_performed':False,'business_or_credentials_mounted':False,'official_sources':source}
Path('/out/proposal.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'stage':result['stage'],'selected_count':result['selected_count'],'selected_top_versions':result['selected_top_versions'],'top_versions_match':result['top_versions_match']},sort_keys=True))
'''


def probe_source(tool):
    need(tool.TOP == TOP and tool.FETCH.count(MARKER) == 1, 'EXACT_REVIEWED_FETCH_PREFIX_REQUIRED')
    prefix = tool.FETCH.split(MARKER, 1)[0].replace('__TOP__', repr(TOP))
    old = " if p.returncode:raise RuntimeError('OFFICIAL_DEBIAN_PACKAGE_RESOLUTION_FAILED')"
    replacement = " if p.returncode:\n  (OUT/'apt-error.log').write_bytes(p.stdout[:65536])\n  raise RuntimeError('OFFICIAL_DEBIAN_PACKAGE_RESOLUTION_FAILED')"
    need(prefix.count(old) == 1 and '--download-only' not in prefix and "'--simulate'" in prefix, 'SIMULATION_ONLY_PREFIX_REQUIRED')
    return prefix.replace(old, replacement, 1) + '\n' + PROPOSAL


def call(argv, code, timeout=30, maximum=131072):
    process = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False,
        env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
    need(len(process.stdout) <= maximum, 'BOUNDED_RESOLUTION_OUTPUT_REQUIRED')
    need(process.returncode == 0, code)
    return process.stdout


def current_runtime():
    fmt = '{"id":{{json .Id}},"image":{{json .Image}},"restart":{{json .RestartCount}},"started":{{json .State.StartedAt}},"running":{{json .State.Running}}}'
    value = json.loads(call(['docker','inspect','--format',fmt,'t24-crm'], 'CURRENT_RUNTIME_METADATA_REQUIRED'))
    need(value == RUNTIME, 'EXACT_UNCHANGED_CRM_RUNTIME_REQUIRED'); return value


def validate_proposal(value):
    need(value['stage'] == 'PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED' and type(value['selected_count']) is int and 1 <= value['selected_count'] <= 400 and value['expected_top_versions'] == TOP and set(value['selected_top_versions']) == set(TOP), 'EXACT_PUBLIC_RESOLUTION_PROPOSAL_REQUIRED')
    need(set(value['selected_packages']) == set(value['selected_new_versions']) and len(value['selected_packages']) == value['selected_count'], 'COMPLETE_PROPOSAL_MEMBER_SET_REQUIRED')
    need(value['top_versions_match'] == all(value['selected_top_versions'][name] == version for name,version in TOP.items()) and value['selected_top_versions'] == {name:value['selected_new_versions'].get(name) for name in TOP}, 'EXACT_TOP_VERSION_DIAGNOSTIC_REQUIRED')
    need(value['base_packages_unchanged'] is True and all(value[key] is False for key in ('installation_performed','package_download_performed','business_or_credentials_mounted')), 'NO_INSTALL_OR_DOWNLOAD_RESOLUTION_REQUIRED')


def run(source):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    os.umask(0o077); resource.setrlimit(resource.RLIMIT_CORE, (0,0)); before = current_runtime()
    body = read_private(TOOL, sha=TOOL_SHA); tool = ModuleType('reviewed_existing_public_toolchain'); exec(compile(body,str(TOOL),'exec'),tool.__dict__)
    code = probe_source(tool); digest = H(source); work = TOOL.parent.parent / ('media-asset-studio-resolution-' + digest[:12] + '-20261101')
    secure_directory(work.parent); need(not work.exists() and not work.is_symlink(), 'FRESH_PUBLIC_RESOLUTION_STAGE_REQUIRED')
    work.mkdir(mode=0o700); out = work/'out'; out.mkdir(mode=0o700); write_private(work/'apt_resolution_probe.py',source)
    name = 't24-asset-resolve-' + digest[:12]
    # No inherited application entrypoint/healthcheck, current DB or credential
    # mount. Only this NEW private output directory is available to the process.
    argv = ['docker','run','--name',name,'--network','bridge','--memory','768m','--memory-swap','768m','--cpus','1','--pids-limit','128','--restart','no','--no-healthcheck','--security-opt','no-new-privileges','--mount','type=bind,src='+str(out)+',dst=/out','--entrypoint','/usr/bin/env',IMAGE,'-i','PATH=/usr/local/bin:/usr/bin:/bin','LANG=C.UTF-8','PYTHONDONTWRITEBYTECODE=1','/usr/local/bin/python','-I','-B','-c',code]
    try:
        call(argv,'ISOLATED_PUBLIC_APT_RESOLUTION_FAILED',timeout=480)
    except BaseException:
        current_runtime()
        # The exact bounded APT output, when present, remains in this NEW
        # root-private public-data stage for a separate read-only diagnosis.
        raise
    current_runtime()
    fmt = '{"image":{{json .Image}},"running":{{json .State.Running}},"exit_code":{{json .State.ExitCode}},"mounts":{{json .Mounts}},"entrypoint":{{json .Config.Entrypoint}}}'
    info = json.loads(call(['docker','inspect','--format',fmt,name], 'RESOLUTION_CONTAINER_METADATA_REQUIRED'))
    need(info['image'] == IMAGE and info['running'] is False and info['exit_code'] == 0 and info['entrypoint'] == ['/usr/bin/env'] and len(info['mounts']) == 1 and info['mounts'][0]['Source'] == str(out) and info['mounts'][0]['Destination'] == '/out', 'EXACT_DATAFREE_RESOLUTION_CONTAINER_REQUIRED')
    proposal_body = read_private(out/'proposal.json'); proposal = json.loads(proposal_body); validate_proposal(proposal)
    need(current_runtime() == before, 'CRM_RUNTIME_CHANGED_DURING_RESOLUTION')
    return {'stage':'ASSET_STUDIO_PUBLIC_DEPENDENCY_PROPOSAL_CAPTURED','probe_sha256':digest,'original_toolchain_sha256':TOOL_SHA,'proposal_sha256':H(proposal_body),'proposal_path':str(out/'proposal.json'),'proposal_bytes':len(proposal_body),
        **{key:proposal[key] for key in ('selected_count','selected_top_versions','expected_top_versions','top_versions_match','base_package_count','simulation_stdout_sha256','total_download_bytes','estimated_installed_bytes','within_original_package_count_bound','within_original_download_bound','within_original_installed_bound')},
        'production_runtime_unchanged':True,'official_signed_apt_update_and_simulation_only':True,'installation_performed':False,'package_download_performed':False,'api_or_worker_started':False,'credentials_or_business_data_mounted':False,'old_fetch_container_changed':False,'old_toolchain_install_bounds_relaxed':False}
