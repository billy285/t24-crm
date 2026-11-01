"""Exact approved194 public-package closure; frozen original helpers stay intact."""
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

TOOL = Path('/opt/t24-crm/releases/media-asset-studio-toolchain-4fe7ee52647f-20261101/toolchain.py')
TOOL_SHA = '4fe7ee52647ff1775c8b3e7ac9bce60208aa66806324d3c4a51f80ff23f16fe7'
COMMAND = Path('/opt/t24-crm/releases/media-asset-toolchain-transport-c1b0cbbeaa33-20261101/toolchain-reviewed.sh')
COMMAND_SHA = 'c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075'
PREFLIGHT_SHA = '33e3ced927bc7fd872d5f8b1395ec46f14db48ebb4c8ac4e8199fc067b5b88a9'
APPROVED_PATH = '/opt/t24-crm/releases/media-asset-studio-resolution-223a9e30375c-20261101/out/proposal.json'
APPROVED_SHA = '9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3'
APPROVED_COUNT = 194
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value: raise RuntimeError(code)


def read_protected(path, sha, expected_size=None, maximum=1048576):
    for parent in path.parents:
        row=parent.lstat(); need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_EXACT_RETRY_PARENT_REQUIRED')
    before=path.lstat()
    need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum and (expected_size is None or before.st_size==expected_size),'EXACT_PRIVATE_RETRY_SOURCE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(path.lstat()) and len(body)==before.st_size and H(body)==sha,'EXACT_RETRY_SOURCE_HASH_AND_IDENTITY_REQUIRED')
    return body


HOST_HELPERS = '''
APPROVED_PROPOSAL_SHA = '9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3'
APPROVED_PROPOSAL_PATH = Path('/opt/t24-crm/releases/media-asset-studio-resolution-223a9e30375c-20261101/out/proposal.json')
APPROVED_PACKAGE_COUNT = 194
def validate_approved_proposal(approved):
    need(approved['stage']=='PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED' and approved['selected_count']==APPROVED_PACKAGE_COUNT and approved['expected_top_versions']==approved['selected_top_versions']==TOP and approved['top_versions_match'] is True,'EXACT_APPROVED194_PROPOSAL_REQUIRED')
    proposed=approved['selected_packages']
    need(len(proposed)==APPROVED_PACKAGE_COUNT and set(proposed)==set(approved['selected_new_versions']) and all(row['version']==approved['selected_new_versions'][name] for name,row in proposed.items()),'EXACT_APPROVED194_PACKAGE_SET_REQUIRED')
    need(all(approved[key] is False for key in ('installation_performed','package_download_performed','business_or_credentials_mounted')) and approved['base_packages_unchanged'] is True,'PUBLIC_PROPOSAL_MUST_NOT_HAVE_INSTALLED')
    need(approved['total_download_bytes']==sum(row['download_bytes'] for row in proposed.values())<=536870912 and approved['estimated_installed_bytes']==sum(row['installed_bytes'] for row in proposed.values())<=1073741824,'ORIGINAL_DOWNLOAD_AND_INSTALL_BOUNDS_REQUIRED')
    return proposed
def validate_downloaded_proposal(packages,approved):
    proposed=validate_approved_proposal(approved)
    need(len(packages)==APPROVED_PACKAGE_COUNT and set(packages)==set(proposed),'ONLY_EXACT_APPROVED194_DOWNLOADED_PACKAGES')
    need(all({'version':row['version'],'architecture':row['architecture'],'sha256':row['sha256'],'download_bytes':row['bytes'],'official_pool_path':row['official_pool_path']}=={key:proposed[name][key] for key in ('version','architecture','sha256','download_bytes','official_pool_path')} for name,row in packages.items()),'DOWNLOADED_PACKAGE_DIFFERS_FROM_APPROVED_PROPOSAL')
'''

FETCH_APPROVAL = '''
APPROVED_SHA='9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3'
approved_body=Path('/approved/proposal.json').read_bytes()
if len(approved_body)>1048576 or H(approved_body)!=APPROVED_SHA:raise RuntimeError('EXACT_RO_APPROVED_PROPOSAL_REQUIRED')
approved=json.loads(approved_body)
if approved['stage']!='PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED' or approved['selected_count']!=194 or approved['expected_top_versions']!=TOP or approved['selected_top_versions']!=TOP or approved['top_versions_match'] is not True or len(approved['selected_packages'])!=194:raise RuntimeError('EXACT_APPROVED194_ROOT_VERSIONS_REQUIRED')
'''


def derive_variant(original):
    need(H(original)==TOOL_SHA,'EXACT_FROZEN4FE_SOURCE_REQUIRED'); value=original.decode()
    def replace(old,new):
        nonlocal value
        need(value.count(old)==1,'EXACT_COUNTED_RETRY_SUBSTITUTION_REQUIRED');value=value.replace(old,new,1)
    replace('H = lambda body: hashlib.sha256(body).hexdigest()\n','H = lambda body: hashlib.sha256(body).hexdigest()\n'+HOST_HELPERS)
    replace("H=lambda b:hashlib.sha256(b).hexdigest()\nENV=", "H=lambda b:hashlib.sha256(b).hexdigest()\n"+FETCH_APPROVAL+"\nENV=")
    replace("if not 3<=len(selected)<=180 or any(selected.get(n)!=v for n,v in TOP.items()):raise RuntimeError('BOUNDED_EXACT_RENDER_CLOSURE_REQUIRED')", "if len(selected)!=194 or selected!=approved['selected_new_versions'] or any(selected.get(n)!=v for n,v in TOP.items()):raise RuntimeError('EXACT_APPROVED194_RESOLUTION_REQUIRED')")
    replace(" files[name]={'version':version,'architecture':arch,'file':path.name,'bytes':path.stat().st_size,'sha256':actual,'official_pool_path':filename}", " expected=approved['selected_packages'].get(name)\n if expected!={'version':version,'architecture':arch,'sha256':actual,'download_bytes':path.stat().st_size,'installed_bytes':int(row.get('Installed-Size','0'))*1024,'official_pool_path':filename}:raise RuntimeError('SIGNED_DOWNLOAD_DIFFERS_FROM_APPROVED_PROPOSAL')\n files[name]={'version':version,'architecture':arch,'file':path.name,'bytes':path.stat().st_size,'sha256':actual,'official_pool_path':filename}")
    replace("'installation_performed':False,'business_or_credentials_mounted':False}","'installation_performed':False,'business_or_credentials_mounted':False,'approved_proposal_sha256':APPROVED_SHA}")
    replace("ROOT=Path('/tmp/t24-render-deps');manifest=json.loads((ROOT/'packages.json').read_text())", "ROOT=Path('/tmp/t24-render-deps');manifest=json.loads((ROOT/'packages.json').read_text())\nif manifest.get('approved_proposal_sha256')!='9c7545b0cb443f56f9b897dfa441cfc3c3ce74dcfe50891725676698f864a1b3' or len(manifest['packages'])!=194:raise RuntimeError('EXACT_APPROVED194_INSTALL_MANIFEST_REQUIRED')")
    replace("proof = c.strict_json(c.read(path, sha=ACTUAL_PROOF_SHA))", "proof = c.strict_json(c.read(path, sha=ACTUAL_PROOF_SHA))\n    approved=c.strict_json(c.read(APPROVED_PROPOSAL_PATH,sha=APPROVED_PROPOSAL_SHA));validate_approved_proposal(approved)")
    replace("'--mount', 'type=bind,src=' + str(data) + ',dst=/out', '--entrypoint'", "'--mount', 'type=bind,src=' + str(data) + ',dst=/out', '--mount', 'type=bind,src=' + str(APPROVED_PROPOSAL_PATH) + ',dst=/approved/proposal.json,readonly', '--entrypoint'")
    replace("len(info['Mounts']) == 1 and info['Mounts'][0]['Source'] == str(data) and info['Mounts'][0]['Destination'] == '/out'", "len(info['Mounts']) == 2 and {(row['Source'],row['Destination'],row['RW'],row['Type']) for row in info['Mounts']} == {(str(data),'/out',True,'bind'),(str(APPROVED_PROPOSAL_PATH),'/approved/proposal.json',False,'bind')}")
    replace("packages = manifest['packages']; need(3 <= len(packages) <= 180 and", "packages = manifest['packages']; validate_downloaded_proposal(packages,approved); need(len(packages) == APPROVED_PACKAGE_COUNT and manifest.get('approved_proposal_sha256') == APPROVED_PROPOSAL_SHA and")
    replace("    need(sum(row['bytes'] for row in packages.values()) == manifest['total_download_bytes'] <= 536870912", "    need(manifest['total_download_bytes']==approved['total_download_bytes'] and manifest['estimated_installed_bytes']==approved['estimated_installed_bytes'],'EXACT_APPROVED194_AGGREGATE_SIZES_REQUIRED')\n    need(sum(row['bytes'] for row in packages.values()) == manifest['total_download_bytes'] <= 536870912")
    replace("result = {'stage': 'MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED', 'tool_sha256': tool_sha,", "result = {'stage': 'MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED', 'approved_proposal_sha256':APPROVED_PROPOSAL_SHA, 'tool_sha256': tool_sha,")
    ast.parse(value); return value.encode()


def recover_preflight(command, original):
    need(len(command)==20834 and H(command)==COMMAND_SHA and H(original)==TOOL_SHA,'EXACT_FROZEN_ORIGINAL_COMMAND_REQUIRED')
    text=command.decode(); marker="<<'ASSET_STUDIO_ISOLATED_TOOLCHAIN'\n"
    need(text.count(marker)==1 and text.endswith('\nASSET_STUDIO_ISOLATED_TOOLCHAIN\n'),'EXACT_REVIEWED_COMMAND_ENVELOPE_REQUIRED')
    tree=ast.parse(text.split(marker,1)[1].rsplit('\nASSET_STUDIO_ISOLATED_TOOLCHAIN\n',1)[0])
    assignments=[row for row in ast.walk(tree) if isinstance(row,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='packed' for target in row.targets)]
    need(len(assignments)==1,'EXACT_ORIGINAL_PREFLIGHT_PAYLOAD_REQUIRED')
    call=assignments[0].value
    need(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='decompress' and len(call.args)==1 and isinstance(call.args[0],ast.Call) and isinstance(call.args[0].func,ast.Attribute) and call.args[0].func.attr=='b64decode','EXACT_DATA_ONLY_PREFLIGHT_EXTRACTION_REQUIRED')
    encoded=ast.literal_eval(call.args[0].args[0]);need(isinstance(encoded,str) and len(encoded)<24000,'BOUNDED_ORIGINAL_PREFLIGHT_DATA_REQUIRED')
    data=json.loads(zlib.decompress(base64.b64decode(encoded,validate=True)))
    need(set(data)=={'preflight','toolchain'} and data['toolchain'].encode()==original and H(data['preflight'].encode())==PREFLIGHT_SHA,'EXACT_EXTRACTED_PREFLIGHT33E_REQUIRED')
    return data['preflight'].encode()


def run():
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
    os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    original=read_protected(TOOL,TOOL_SHA);command=read_protected(COMMAND,COMMAND_SHA,expected_size=20834)
    approved_body=read_protected(Path(APPROVED_PATH),APPROVED_SHA); approved=json.loads(approved_body)
    variant=derive_variant(original);preflight=recover_preflight(command,original)
    tool=ModuleType('reviewed_exact194_toolchain');exec(compile(variant,'<reviewed-exact194-toolchain>','exec'),tool.__dict__);tool.validate_approved_proposal(approved)
    pf=ModuleType('reviewed_unchanged_preflight33e');exec(compile(preflight,'<reviewed-unchanged-preflight33e>','exec'),pf.__dict__)
    need(tool.PREFLIGHT_SHA==PREFLIGHT_SHA,'EXACT_UNCHANGED_PREFLIGHT_REQUIRED')
    return tool.run(pf,H(variant),variant)
