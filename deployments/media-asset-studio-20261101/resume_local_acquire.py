"""Derive the two explicitly reviewed installer edits from frozen8f only."""
import ast
import hashlib
import os
from pathlib import Path
import resource
import socket
import stat
from types import ModuleType

BASE=Path('/opt/t24-crm/releases/media-asset-studio-toolchain-8f007897d478-20261101/resume_toolchain.py')
BASE_SHA='8f007897d478a08f3e8c0f189c0bbbe7354ec8c6c208ea2ac868934fe4624b86'
H=lambda body:hashlib.sha256(body).hexdigest()


def need(value,code):
    if not value:raise RuntimeError(code)


def derive(original):
    need(len(original)==13775 and H(original)==BASE_SHA,'EXACT_FROZEN8F_RESUMER_REQUIRED');value=original.decode()
    def replace(old,new):
        nonlocal value
        need(value.count(old)==1,'EXACT_COUNTED_LOCAL_ACQUIRE_SUBSTITUTION_REQUIRED');value=value.replace(old,new,1)
    replace('The sole installer edit supplies trusted sbin tools. Client-only legacy Docker\nbuild avoids remote interpretation of the already verified local base image.',
            'The two reviewed installer edits supply trusted sbin tools and local absolute\n.deb acquisition. Docker networknone preserves physical offline installation.')
    replace("    result=original.replace(OLD_PATH,NEW_PATH,1)\n    need(result.replace(NEW_PATH,OLD_PATH,1)==original,'ONLY_TRUSTED_INSTALLER_SBIN_ADDITION_REQUIRED')",
            "    need(original.count(\"'--no-download',\")==1,'EXACT_SINGLE_LOCAL_ACQUIRE_FLAG_REQUIRED')\n    result=original.replace(OLD_PATH,NEW_PATH,1).replace(\"'--no-download',\",'',1)\n    anchor=\"'--assume-yes','--no-remove'\"\n    need(result.count(anchor)==1,'EXACT_LOCAL_ABSOLUTE_ACQUIRE_ANCHOR_REQUIRED')\n    restored=result.replace(NEW_PATH,OLD_PATH,1).replace(anchor,\"'--assume-yes','--no-download','--no-remove'\",1)\n    need(restored==original,'ONLY_TRUSTED_SBIN_AND_LOCAL_ACQUIRE_EDITS_REQUIRED')")
    replace("'ONLY_APPROVED_INSTALLER_PATH_DIFF_REQUIRED'","'ONLY_TWO_APPROVED_INSTALLER_EDITS_REQUIRED'")
    replace("'trusted_install_path_sbin_added':True,'installer_before_sha256'",
            "'trusted_install_path_sbin_added':True,'local_absolute_deb_acquisition_without_no_download':True,'installer_edits':['trusted_sbin_path','local_absolute_deb_acquisition'],'physical_offline_build':True,'base_resumer_sha256':'8f007897d478a08f3e8c0f189c0bbbe7354ec8c6c208ea2ac868934fe4624b86','installer_before_sha256'")
    ast.parse(value);return value.encode()


def read_base():
    for parent in BASE.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_FROZEN8F_PARENT_REQUIRED')
    before=BASE.lstat();need(BASE.resolve()==BASE and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and before.st_size==13775,'EXACT_ROOT_PRIVATE_FROZEN8F_REQUIRED')
    fd=os.open(BASE,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(13776)
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(BASE.lstat()) and len(body)==13775 and H(body)==BASE_SHA,'EXACT_FROZEN8F_HASH_AND_IDENTITY_REQUIRED')
    return body


def run():
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
    os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    original=read_base();body=derive(original);scope=ModuleType('reviewed_offline_local_acquire_resumer');scope.__file__='<reviewed-offline-local-acquire-resumer>'
    exec(compile(body,scope.__file__,'exec'),scope.__dict__)
    return scope.run(body)
