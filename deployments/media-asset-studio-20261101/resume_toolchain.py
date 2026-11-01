"""Resume the exact194 local-only toolchain in a fresh append-only scope.

The sole installer edit supplies trusted sbin tools. Client-only legacy Docker
build avoids remote interpretation of the already verified local base image.
"""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
from types import ModuleType
import zlib

ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-asset-studio-toolchain-8c51c8a7c0d7-20261101'
OLD_SHA='8c51c8a7c0d79434a0b4686a57a3f697637f3a763f1e4152bad5a7240af7ceb6'
ORIGINAL=ROOT/'media-asset-studio-toolchain-4fe7ee52647f-20261101/toolchain.py'
ORIGINAL_SHA='4fe7ee52647ff1775c8b3e7ac9bce60208aa66806324d3c4a51f80ff23f16fe7'
COMMAND=ROOT/'media-asset-toolchain-transport-c1b0cbbeaa33-20261101/toolchain-reviewed.sh'
COMMAND_SHA='c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075'
DIAGNOSTIC=ROOT/'media-asset-build-diagnostic-aace71c6bd53-20261101/diagnose_toolchain_build.py'
DIAGNOSTIC_SHA='aace71c6bd5384e47cb73e2665f1298d0d29d1f00c95ef751f83d3ae672cb302'
PREFLIGHT_SHA='33e3ced927bc7fd872d5f8b1395ec46f14db48ebb4c8ac4e8199fc067b5b88a9'
PROOF_SHA='bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
APPROVED_SHA='9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3'
IMAGE='sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'
H=lambda body:hashlib.sha256(body).hexdigest()
ENCODE=lambda value:(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
OLD_PATH="'PATH':'/usr/local/bin:/usr/bin:/bin'"
NEW_PATH="'PATH':'/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'"


def need(value,code):
    if not value:raise RuntimeError(code)


def read_protected(path,sha,expected_size=None):
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RESUME_PARENT_REQUIRED')
    before=path.lstat()
    need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=1048576 and (expected_size is None or before.st_size==expected_size),'EXACT_ROOT_PRIVATE_RESUME_INPUT_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(1048577)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(path.lstat()) and len(body)==before.st_size and H(body)==sha,'EXACT_RESUME_INPUT_HASH_AND_IDENTITY_REQUIRED')
    return body


def module(body,name):
    value=ModuleType(name);value.__file__='<'+name+'>';exec(compile(body,value.__file__,'exec'),value.__dict__);return value


def recover_preflight(command,original):
    need(len(command)==20834 and H(command)==COMMAND_SHA and H(original)==ORIGINAL_SHA,'EXACT_FROZEN_PREFLIGHT_CARRIER_REQUIRED')
    marker="<<'ASSET_STUDIO_ISOLATED_TOOLCHAIN'\n";tail='\nASSET_STUDIO_ISOLATED_TOOLCHAIN\n';text=command.decode()
    need(text.count(marker)==1 and text.endswith(tail),'EXACT_DATA_ONLY_CARRIER_ENVELOPE_REQUIRED')
    tree=ast.parse(text.split(marker,1)[1].rsplit(tail,1)[0])
    values=[row.value for row in ast.walk(tree) if isinstance(row,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='packed' for target in row.targets)]
    need(len(values)==1,'EXACT_PREFLIGHT_DATA_ASSIGNMENT_REQUIRED');call=values[0]
    need(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='decompress' and len(call.args)==1 and isinstance(call.args[0],ast.Call) and isinstance(call.args[0].func,ast.Attribute) and call.args[0].func.attr=='b64decode' and len(call.args[0].args)==1,'EXACT_PREFLIGHT_LITERAL_DATA_REQUIRED')
    packed=ast.literal_eval(call.args[0].args[0]);need(isinstance(packed,str) and len(packed)<24000,'BOUNDED_PREFLIGHT_LITERAL_REQUIRED')
    value=json.loads(zlib.decompress(base64.b64decode(packed,validate=True)))
    need(set(value)=={'preflight','toolchain'} and value['toolchain'].encode()==original and H(value['preflight'].encode())==PREFLIGHT_SHA,'EXACT_UNMODIFIED_PREFLIGHT33E_REQUIRED')
    return value['preflight'].encode()


def installer(tool):
    original=tool.INSTALL
    need(original.count(OLD_PATH)==1 and NEW_PATH not in original,'EXACT_SINGLE_INSTALLER_PATH_REQUIRED')
    result=original.replace(OLD_PATH,NEW_PATH,1)
    need(result.replace(NEW_PATH,OLD_PATH,1)==original,'ONLY_TRUSTED_INSTALLER_SBIN_ADDITION_REQUIRED')
    ast.parse(result);return result.encode()


def dockerfile():
    return ('FROM '+IMAGE+'\nCOPY packages /tmp/t24-render-deps/packages\nCOPY packages.json install.py /tmp/t24-render-deps/\nRUN /usr/local/bin/python -I -B /tmp/t24-render-deps/install.py && rm -rf /tmp/t24-render-deps\n').encode()


def copy_context(tool,d,work,manifest_body):
    manifest=json.loads(manifest_body);context=work/'build';context.mkdir(mode=0o700);(context/'packages').mkdir(mode=0o700)
    for row in manifest['packages'].values():
        tool.copy_public_package(OLD/'build/packages'/row['file'],context/'packages'/row['file'],row['sha256'],row['bytes'])
    d.write_private(context/'packages.json',manifest_body);d.write_private(context/'install.py',installer(tool));d.write_private(context/'Dockerfile',dockerfile())
    return context


def verify_copy(tool,d,context,manifest_body):
    manifest=json.loads(manifest_body);d.secure(context);d.secure(context/'packages')
    need({path.name for path in context.iterdir()}=={'Dockerfile','install.py','packages.json','packages'},'EXACT_NEW_RESUME_CONTEXT_REQUIRED')
    need(d.read_private(context/'packages.json')==manifest_body and d.read_private(context/'install.py')==installer(tool) and d.read_private(context/'Dockerfile')==dockerfile(),'ONLY_APPROVED_INSTALLER_PATH_DIFF_REQUIRED')
    need({path.name for path in (context/'packages').iterdir()}=={row['file'] for row in manifest['packages'].values()},'EXACT194_COPIED_PACKAGE_SET_REQUIRED')
    for row in manifest['packages'].values():d.hash_package(context/'packages'/row['file'],row['sha256'],row['bytes'])


def baseline(pf,flow,proof):
    observed=pf.sample()
    need({**observed,'database_metadata':proof['database_metadata']}=={key:value for key,value in proof.items() if key!='render_capacity'},'EXACT_CURRENT155_AND_PRIVATE_PACKET_REQUIRED')
    flow.retained.live_sequence_boundary(proof['database_metadata'],observed['database_metadata'])


def probe_command(name,image,script):
    return ['docker','run','--name',name,'--network','none','--memory','768m','--memory-swap','768m','--cpus','1','--pids-limit','64','--restart','no','--no-healthcheck','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=67108864','--entrypoint','/usr/bin/env',image,'-i','PATH=/usr/local/bin:/usr/bin:/bin','LANG=C.UTF-8','PYTHONDONTWRITEBYTECODE=1','/usr/local/bin/python','-I','-B','-c',script]


def validate_probe(probe,info,image,proof):
    need(info['State']['Running'] is False and info['State']['ExitCode']==0 and info['Image']==image and info['HostConfig']['NetworkMode']=='none' and info['HostConfig']['ReadonlyRootfs'] is True and all(row['Type']=='tmpfs' and row['Destination']=='/tmp' for row in info['Mounts']),'OFFLINE_READONLY_DATAFREE_PROBE_REQUIRED')
    need(probe['python_pillow']=='12.3.0' and probe['freetype2'] is True and probe['cjk_and_latin_glyphs_verified'] is True and probe['no_business_data_credentials_or_provider_requests'] is True,'ACTUAL_CJK_PILLOW_PROBE_REQUIRED')
    video=probe['actual_h264_mp4']
    need(video['codec_name']=='h264' and video['width']==video['height']==32 and video['pix_fmt']=='yuv420p' and re.fullmatch('[a-f0-9]{64}',video['sha256']) and 0<video['bytes']<1048576,'ACTUAL_BOUNDED_H264_PROBE_REQUIRED')
    need(probe['backend_file_count']==408 and probe['backend_inventory_sha256']==proof['backend_inventory_sha256'],'ALL408_BACKEND_FILES_MUST_REMAIN_UNCHANGED')


def save_result(d,work,result,name):
    body=ENCODE(result);path=work/name;d.write_private(path,body)
    return {**result,'receipt_sha256':H(body),'receipt_path':str(path)}


def perform(pf,tool,d,source):
    _,flow,_=pf.dependencies();c=flow.c;m=flow.m
    proof=c.strict_json(c.read(ROOT/('media-asset-studio-preflight-'+PROOF_SHA[:12]+'.json'),sha=PROOF_SHA))
    baseline(pf,flow,proof);before=d.runtime();old_context=d.validate_context(tool)
    need(old_context['approved_proposal_sha256']==APPROVED_SHA and old_context['package_count']==194,'EXACT_VERIFIED194_OLD_CONTEXT_REQUIRED')
    need(d.image_id(IMAGE)==IMAGE and pf.RUNTIME['image']==IMAGE,'EXACT_LOCAL_BASE_IMAGE_REQUIRED')
    sha=H(source);work=ROOT/('media-asset-studio-toolchain-'+sha[:12]+'-20261101');tag='t24-crm:asset-toolchain-'+sha[:12];probe_name='t24-asset-toolchain-probe-'+sha[:12]
    d.secure(ROOT);need(not work.exists() and not work.is_symlink() and d.image_id(tag) is None and not m.inspect_optional(probe_name),'FRESH_RESUME_CONTEXT_IMAGE_AND_PROBE_REQUIRED')
    need(os.statvfs('/opt/t24-crm').f_frsize*os.statvfs('/opt/t24-crm').f_bavail>=6*1024**3,'RESUME_MINIMUM_DISK_REQUIRED')
    work.mkdir(mode=0o700);d.write_private(work/'resume_toolchain.py',source)
    manifest_body=d.read_private(OLD/'fetch-data/packages.json',sha=old_context['packages_manifest_sha256']);manifest=json.loads(manifest_body)
    context=copy_context(tool,d,work,manifest_body);verify_copy(tool,d,context,manifest_body)
    # Client env only: no current container/image Env or render env is changed.
    d.ENV={**d.ENV,'DOCKER_BUILDKIT':'0'};d.TAG=tag
    build=d.capture_build(d.build_command(context),work/'docker-build-public.log')
    baseline(pf,flow,proof);need(d.runtime()==before and d.image_id(IMAGE)==IMAGE,'CURRENT_RUNTIME_AND_LOCAL_BASE_MUST_STAY_UNCHANGED')
    need(d.validate_context(tool)==old_context,'FROZEN_OLD194_CONTEXT_MUST_STAY_UNCHANGED');verify_copy(tool,d,context,manifest_body)
    image=d.image_id(tag)
    facts={'tool_sha256':sha,'base_toolchain_sha256':OLD_SHA,'approved_proposal_sha256':APPROVED_SHA,'build':build,'public_build_log_path':str(work/'docker-build-public.log'),'legacy_builder_enabled':True,'trusted_install_path_sbin_added':True,'installer_before_sha256':H(tool.INSTALL.encode()),'installer_after_sha256':H(installer(tool)),'original_context_unchanged':True,'production_runtime_unchanged':True,'production_or_host_installation':False,'production_container_changed':False,'credentials_or_business_data_mounted':False,'api_or_worker_started':False,'official_debian_package_network_fetch_performed':False,'social_ai_or_payment_provider_requests':False,'publications_performed':False}
    if build['exit_code']!=0 or not build['build_daemon_result_known']:
        return save_result(d,work,{'stage':'MEDIA_ASSET_STUDIO_TOOLCHAIN_RESUME_BUILD_NOT_CONFIRMED','toolchain_image':image,'image_tag':tag,**facts},'resume-build-failed.json')
    need(re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_NEW_RESUMED_IMAGE_REQUIRED')
    probe_log=work/'engine-probe-public.log';probe_result=d.capture_build(probe_command(probe_name,image,tool.PROBE),probe_log,timeout=90,maximum=1048576)
    baseline(pf,flow,proof);need(d.runtime()==before and d.image_id(IMAGE)==IMAGE and d.image_id(tag)==image,'CURRENT_RUNTIME_AND_TOOLCHAIN_IMAGE_MUST_STAY_UNCHANGED')
    need(d.validate_context(tool)==old_context,'ORIGINAL194_CONTEXT_CHANGED_DURING_PROBE');verify_copy(tool,d,context,manifest_body)
    if probe_result['exit_code']!=0 or not probe_result['build_daemon_result_known']:
        return save_result(d,work,{'stage':'MEDIA_ASSET_STUDIO_TOOLCHAIN_RESUME_PROBE_NOT_CONFIRMED','toolchain_image':image,'image_tag':tag,'engine_probe':probe_result,'public_probe_log_path':str(probe_log),**facts},'resume-probe-failed.json')
    probe=json.loads(d.read_private(probe_log,maximum=1048576,sha=probe_result['log_sha256']));validate_probe(probe,m.inspect(probe_name),image,proof)
    result={'stage':'MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED','preflight_sha256':PROOF_SHA,'source_sha':pf.SOURCE,'frontend_version':pf.FRONTEND,'base_image':IMAGE,'toolchain_image':image,'image_tag':tag,'packages_manifest_sha256':H(manifest_body),'base_package_inventory_sha256':pf.digest(manifest['base_packages']),'added_package_count':194,'top_packages':tool.TOP,'total_download_bytes':manifest['total_download_bytes'],'estimated_installed_bytes':manifest['estimated_installed_bytes'],'engine_canary':probe,'engine_probe_log_sha256':probe_result['log_sha256'],'all155_current_rows_and_private_packet_preserved':True,'all408_backend_files_unchanged':True,'no_existing_package_upgraded_or_removed':True,'fetch_only_official_signed_debian':True,'install_and_engine_probe_network_none':True,**facts}
    return save_result(d,work,result,'toolchain-prepared.json')


def run(source):
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
    os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    d=module(read_protected(DIAGNOSTIC,DIAGNOSTIC_SHA,12259),'reviewed_bounded_public_build_capture')
    tool=module(read_protected(OLD/'toolchain.py',OLD_SHA,25883),'reviewed_exact194_toolchain')
    original=read_protected(ORIGINAL,ORIGINAL_SHA);command=read_protected(COMMAND,COMMAND_SHA,20834)
    pf=module(recover_preflight(command,original),'reviewed_unchanged_preflight33e')
    need(tool.PREFLIGHT_SHA==PREFLIGHT_SHA and tool.ACTUAL_PROOF_SHA==PROOF_SHA and tool.APPROVED_PROPOSAL_SHA==APPROVED_SHA and d.WORK==OLD and d.TOOL_SHA==OLD_SHA and d.IMAGE==IMAGE and d.APPROVED_SHA==APPROVED_SHA,'EXACT_ALL_FROZEN_RESUME_DEPENDENCIES_REQUIRED')
    return perform(pf,tool,d,source)
