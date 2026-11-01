"""Verify the public194 context and capture one exact isolated offline build."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import socket
import stat
import subprocess
import time
from types import ModuleType

WORK=Path('/opt/t24-crm/releases/media-asset-studio-toolchain-8c51c8a7c0d7-20261101')
TOOL_SHA='8c51c8a7c0d79434a0b4686a57a3f697637f3a763f1e4152bad5a7240af7ceb6'
APPROVED=Path('/opt/t24-crm/releases/media-asset-studio-resolution-223a9e30375c-20261101/out/proposal.json')
APPROVED_SHA='9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3'
IMAGE='sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'
TAG='t24-crm:asset-toolchain-8c51c8a7c0d7'
RUNTIME={'id':'3000cd73a62f0c852874c2124426ec45b47f26d128843fb56f5963ef9ef98058','image':IMAGE,'restart':0,'started':'2026-11-01T04:44:42.917603256Z','running':True}
ENV={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}
MAX_LOG=4*1024*1024
H=lambda body:hashlib.sha256(body).hexdigest()


def need(value,code):
    if not value:raise RuntimeError(code)


def secure(path):
    for parent in (path,*path.parents):
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PUBLIC_BUILD_PARENT_REQUIRED')


def read_private(path,maximum=1048576,sha=None):
    secure(path.parent);before=path.lstat()
    need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum,'EXACT_PUBLIC_BUILD_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(path.lstat()) and len(body)==before.st_size and (sha is None or H(body)==sha),'PUBLIC_BUILD_FILE_HASH_OR_IDENTITY_DRIFT')
    return body


def hash_package(path,expected_sha,size):
    need(re.fullmatch('[a-f0-9]{64}',expected_sha) and type(size) is int and 0<size<=134217728,'BOUNDED_PUBLIC_BUILD_PACKAGE_REQUIRED')
    secure(path.parent);before=path.lstat()
    need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and before.st_size==size,'EXACT_PUBLIC_BUILD_PACKAGE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);digest=hashlib.sha256();count=0
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno())
        for chunk in iter(lambda:stream.read(1048576),b''):
            count+=len(chunk);need(count<=size,'PUBLIC_BUILD_PACKAGE_SIZE_DRIFT');digest.update(chunk)
        after=os.fstat(stream.fileno())
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and count==size and digest.hexdigest()==expected_sha,'PUBLIC_BUILD_PACKAGE_HASH_OR_IDENTITY_DRIFT')


def write_private(path,body):
    secure(path.parent);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def call(argv,code,allow_absent=False):
    process=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=False,env=ENV)
    need(len(process.stdout)+len(process.stderr)<=65536,'BOUNDED_PUBLIC_BUILD_METADATA_REQUIRED')
    if process.returncode:
        if allow_absent and (b'No such image' in process.stderr or b'No such object' in process.stderr):return None
        raise RuntimeError(code)
    return process.stdout


def runtime():
    fmt='{"id":{{json .Id}},"image":{{json .Image}},"restart":{{json .RestartCount}},"started":{{json .State.StartedAt}},"running":{{json .State.Running}}}'
    value=json.loads(call(['docker','inspect','--format',fmt,'t24-crm'],'CURRENT_CRM_METADATA_REQUIRED'));need(value==RUNTIME,'EXACT_UNCHANGED_CURRENT_CRM_REQUIRED');return value


def image_id(tag):
    body=call(['docker','image','inspect','--format','{{json .Id}}',tag],'PUBLIC_IMAGE_METADATA_REQUIRED',allow_absent=True)
    if body is None:return None
    value=json.loads(body);need(re.fullmatch('sha256:[a-f0-9]{64}',value or ''),'EXACT_PUBLIC_IMAGE_ID_REQUIRED');return value


def validate_context(tool):
    approved=json.loads(read_private(APPROVED,sha=APPROVED_SHA));tool.validate_approved_proposal(approved)
    manifest_body=read_private(WORK/'fetch-data/packages.json');manifest=json.loads(manifest_body)
    need(manifest.get('approved_proposal_sha256')==APPROVED_SHA and manifest['top_packages']==tool.TOP and manifest['base_packages_unchanged'] is True and manifest['installation_performed'] is False and manifest['business_or_credentials_mounted'] is False,'EXACT_SIGNED_PUBLIC_FETCH_MANIFEST_REQUIRED')
    tool.validate_downloaded_proposal(manifest['packages'],approved)
    need(not set(manifest['packages']).intersection(manifest['base_packages']) and manifest['total_download_bytes']==approved['total_download_bytes'] and manifest['estimated_installed_bytes']==approved['estimated_installed_bytes'],'EXACT_APPROVED194_CLOSURE_AND_ESTIMATES_REQUIRED')
    need(1<=len(manifest['signed_inrelease_sha256'])<=4 and all(re.fullmatch('[a-f0-9]{64}',value) for value in manifest['signed_inrelease_sha256'].values()),'SIGNED_PUBLIC_INDICES_REQUIRED')
    context=WORK/'build';secure(context);secure(context/'packages')
    need({p.name for p in context.iterdir()}=={'Dockerfile','install.py','packages.json','packages'},'EXACT_PUBLIC_BUILD_CONTEXT_MEMBERS_REQUIRED')
    need(read_private(context/'packages.json')==manifest_body and read_private(context/'install.py')==tool.INSTALL.encode(),'EXACT_FROZEN_INSTALLER_AND_MANIFEST_REQUIRED')
    dockerfile=('FROM '+IMAGE+'\nCOPY packages /tmp/t24-render-deps/packages\nCOPY packages.json install.py /tmp/t24-render-deps/\nRUN /usr/local/bin/python -I -B /tmp/t24-render-deps/install.py && rm -rf /tmp/t24-render-deps\n').encode()
    need(read_private(context/'Dockerfile')==dockerfile,'EXACT_ORIGINAL_OFFLINE_DOCKERFILE_REQUIRED')
    files={row['file'] for row in manifest['packages'].values()}
    need(len(files)==194 and all(re.fullmatch('[A-Za-z0-9_.+:%~-]+[.]deb',name) for name in files) and {p.name for p in (context/'packages').iterdir()}==files and {p.name for p in (WORK/'fetch-data/packages').glob('*.deb')}==files,'EXACT194_PUBLIC_DEB_MEMBER_SET_REQUIRED')
    for row in manifest['packages'].values():
        hash_package(context/'packages'/row['file'],row['sha256'],row['bytes'])
        hash_package(WORK/'fetch-data/packages'/row['file'],row['sha256'],row['bytes'])
    return {'approved_proposal_sha256':APPROVED_SHA,'packages_manifest_sha256':H(manifest_body),'package_count':194,'total_download_bytes':manifest['total_download_bytes'],'estimated_installed_bytes':manifest['estimated_installed_bytes'],'dockerfile_sha256':H(dockerfile),'installer_sha256':H(tool.INSTALL.encode()),'context':str(context)}


def build_command(context):
    return ['docker','build','--network=none','--pull=false','--memory','768m','--cpu-period','100000','--cpu-quota','100000','-t',TAG,str(context)]


def capture_build(argv,path,timeout=900,maximum=MAX_LOG):
    secure(path.parent);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    process=None;selector=selectors.DefaultSelector();count=0;digest=hashlib.sha256();tail=b'';reason=None;started=time.monotonic()
    try:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=ENV,start_new_session=True)
        selector.register(process.stdout,selectors.EVENT_READ)
        with os.fdopen(fd,'wb',closefd=False) as log:
            while True:
                if time.monotonic()-started>=timeout:reason='BUILD_CLIENT_TIMEOUT_RESULT_UNKNOWN';break
                events=selector.select(timeout=1)
                if not events and process.poll() is None:continue
                chunk=os.read(process.stdout.fileno(),65536)
                if not chunk:
                    if process.poll() is not None:break
                    continue
                if count+len(chunk)>maximum:
                    chunk=chunk[:max(0,maximum-count)];reason='BUILD_PUBLIC_LOG_LIMIT_RESULT_UNKNOWN'
                if chunk:log.write(chunk);count+=len(chunk);digest.update(chunk);tail=(tail+chunk)[-8192:]
                if reason:break
            log.flush();os.fsync(log.fileno())
        if reason:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        code=process.wait(timeout=10)
        safe=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',tail.decode('utf-8',errors='replace'))
        safe=''.join(c for c in safe if ord(c)>=32 or c in '\n\t')[-8192:]
        return {'exit_code':code,'client_status':reason or 'BUILD_CLIENT_FINISHED','log_sha256':digest.hexdigest(),'log_bytes':count,'public_tail':safe,'elapsed_seconds':round(time.monotonic()-started,3),'build_daemon_result_known':reason is None}
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=10)
            if process.stdout is not None:process.stdout.close()
        os.close(fd)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)


def run(source):
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);before=runtime()
    body=read_private(WORK/'toolchain.py',sha=TOOL_SHA);tool=ModuleType('reviewed_exact194_build_toolchain');exec(compile(body,'<reviewed-exact194-build-toolchain>','exec'),tool.__dict__)
    proof=validate_context(tool);need(image_id(IMAGE)==IMAGE,'EXACT_ORIGINAL_BASE_IMAGE_REQUIRED');present=image_id(TAG)
    if present:
        need(runtime()==before,'CURRENT_CRM_CHANGED_DURING_METADATA_CHECK')
        return {'stage':'ASSET_TOOLCHAIN_EXISTING_CANDIDATE_NOT_REBUILT','toolchain_image':present,'image_tag':TAG,'context':proof,'rebuild_performed':False,'production_mutation_performed':False,'offline_engine_probe_still_required':True}
    diagnostic=WORK.parent/('media-asset-build-diagnostic-'+H(source)[:12]+'-20261101');secure(diagnostic.parent)
    need(not diagnostic.exists() and not diagnostic.is_symlink(),'FRESH_APPEND_ONLY_BUILD_DIAGNOSTIC_REQUIRED');diagnostic.mkdir(mode=0o700)
    write_private(diagnostic/'diagnose_toolchain_build.py',source);log=diagnostic/'docker-build-public.log'
    # The reviewed installer, package context and original resource/network
    # flags stay byte-identical. This is a NEW image build, never host install.
    build=capture_build(build_command(WORK/'build'),log)
    need(runtime()==before,'CURRENT_CRM_CHANGED_DURING_ISOLATED_BUILD')
    image=image_id(TAG);validate_context(tool)
    need(build['log_bytes']==log.stat().st_size,'EXACT_BOUNDED_PUBLIC_BUILD_LOG_REQUIRED')
    result={'stage':'ASSET_TOOLCHAIN_OFFLINE_BUILD_DIAGNOSTIC_CAPTURED','toolchain_helper_sha256':TOOL_SHA,'image_tag':TAG,'toolchain_image':image,'context':proof,'build':build,'public_log_path':str(log),'context_unchanged':True,'production_runtime_unchanged':True,'production_or_host_installation':False,'api_or_worker_started':False,'credentials_or_business_data_mounted':False,'network':'none','offline_engine_probe_still_required':True}
    encoded=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode();path=diagnostic/'build-diagnostic-result.json';write_private(path,encoded)
    return {**result,'receipt_sha256':H(encoded),'receipt_path':str(path)}
