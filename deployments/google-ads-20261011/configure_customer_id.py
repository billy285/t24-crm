#!/usr/bin/env python3
"""Append only the selected direct Ads customer ID; never restart a service.
No credential value is printed, and existing environment bytes remain preserved
except the single explicitly allowed target key when it is empty.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
from uuid import uuid4
HOST='iZj6c4cj7edgnhdimts4l7Z'
CONFIG=Path('/opt/t24-crm/private-workspace/config')
ENV=CONFIG/'runtime.env'
BEFORE_ENV_SHA='6ebb9e3e1e947106bc8c25bdba782d631f5fd8c83ab1487120f5b16420470296'
TARGET_KEY='PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID'
TARGET_CUSTOMER='7539806760'


class SwitchError(RuntimeError):
    pass

def need(condition, code):
    if not condition:
        raise SwitchError(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())

def secure(path, directory=False, mode=None):
    info = path.lstat()
    need(path.resolve() == path and not stat.S_ISLNK(info.st_mode), 'PATH_ALIAS_REJECTED')
    need(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o077, 'PROTECTED_PATH_REQUIRED')
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'PROTECTED_TYPE_REQUIRED')
    if mode is not None:
        need(stat.S_IMODE(info.st_mode) == mode, 'PROTECTED_MODE_REQUIRED')
    return info

def read_protected(path, maximum=65536):
    before = secure(path, mode=0o600)
    need(before.st_size <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        need((before.st_ino, before.st_dev) == (observed.st_ino, observed.st_dev), 'PROTECTED_FILE_CHANGED')
        data = stream.read(maximum + 1)
    need(len(data) <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    return data

def parse_env(data):
    need(data and len(data)<=65536 and data.endswith(b'\n') and b'\r' not in data and b'\x00' not in data,'ENV_FORMAT_INVALID')
    result={}
    for row in data.decode('utf-8').splitlines():
        need('=' in row,'ENV_ROW_INVALID');name,value=row.split('=',1)
        need(re.fullmatch('[A-Z][A-Z0-9_]*',name) and name not in result,'ENV_KEY_INVALID')
        result[name]=value
    return result

def direct_customer_scope(values):
    need(not values.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID','').strip(),'DIRECT_CUSTOMER_MANAGER_ENV_REJECTED')
    for key in (TARGET_KEY,'GOOGLE_ADS_CUSTOMER_ID'):
        value=values.get(key,'').strip()
        if value:
            need(value.replace('-','')==TARGET_CUSTOMER,'DIRECT_CUSTOMER_CONFLICT_REJECTED')
    required={'PRIVATE_WORKSPACE_OWNER_IDS':'4','PRIVATE_WORKSPACE_PUBLIC_URL':'https://t24-crm.com',
              'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db','DATABASE_URL':'sqlite:///./data/crm_prod.db',
              'DATABASE_SCHEMA_MODE':'verify_only','ENFORCE_EMPLOYEE_STATUS':'true','ENFORCE_EMPLOYEE_SESSIONS':'true'}
    need(all(values.get(key)==value for key,value in required.items()),'PRIVATE_ENVIRONMENT_SCOPE_DRIFT')
    missing=[key for key in ('GOOGLE_WORKSPACE_CLIENT_ID','GOOGLE_WORKSPACE_CLIENT_SECRET') if not values.get(key,'').strip()]
    return {'direct_customer_only':True,'target_key_already_present':TARGET_KEY in values,'target_key_has_value':bool(values.get(TARGET_KEY,'').strip()),
            'missing_configuration_names':missing}


def new_environment(before):
    values=parse_env(before);direct_customer_scope(values)
    current=values.get(TARGET_KEY,'')
    if current.strip():
        need(current.strip().replace('-','')==TARGET_CUSTOMER,'TARGET_VALUE_CONFLICT_REJECTED')
        return before,0
    # Preserve every other line byte-for-byte and leave its ordering untouched.
    lines=before.decode('utf-8').splitlines(keepends=True)
    if TARGET_KEY in values:
        need(not current.strip(),'TARGET_VALUE_CONFLICT_REJECTED')
        result=''.join(TARGET_KEY+'='+TARGET_CUSTOMER+'\n' if row.startswith(TARGET_KEY+'=') else row for row in lines).encode()
    else:
        result=before+(TARGET_KEY+'='+TARGET_CUSTOMER+'\n').encode()
    after=parse_env(result)
    need(after.get(TARGET_KEY)==TARGET_CUSTOMER and
         {k:v for k,v in after.items() if k!=TARGET_KEY}=={k:v for k,v in values.items() if k!=TARGET_KEY},'ONLY_TARGET_KEY_CHANGE_ALLOWED')
    return result,1


def write_new(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())


def main(args):
    need(args.execute and os.geteuid()==0 and socket.gethostname()==HOST,'EXPLICIT_VERIFIED_SERVER_REQUIRED')
    need(args.expected_env_sha256==BEFORE_ENV_SHA,'PINNED_ORIGINAL_ENV_HASH_REQUIRED')
    os.umask(0o077);secure(CONFIG.parent,True,0o700);secure(CONFIG,True,0o700)
    lock=CONFIG/'gmail-upgrade.lock';fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        secure(lock,mode=0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=read_protected(ENV);need(sha(before)==args.expected_env_sha256,'ENVIRONMENT_BASELINE_DRIFT')
        after,count=new_environment(before);attempt=uuid4().hex
        backup=CONFIG/('runtime.env.before-google-ads-'+attempt);receipt=CONFIG/('google-ads-config-'+attempt+'.json')
        write_new(backup,before)
        if count:
            info=secure(ENV,mode=0o600);temporary=CONFIG/('.runtime.env.google-ads-'+attempt)
            write_new(temporary,after)
            current=read_protected(ENV);observed=ENV.lstat()
            need(sha(current)==args.expected_env_sha256 and (info.st_dev,info.st_ino)==(observed.st_dev,observed.st_ino),'ENVIRONMENT_CHANGED_BEFORE_REPLACE')
            os.replace(temporary,ENV)
            directory=os.open(CONFIG,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(directory)
            finally:os.close(directory)
        need(read_protected(ENV)==after,'ENVIRONMENT_POST_WRITE_DRIFT')
        value={'phase':'GOOGLE_ADS_CUSTOMER_CONFIGURED','before_env_sha256':sha(before),'after_env_sha256':sha(after),
               'backup_basename':backup.name,'backup_sha256':sha(before),'changed_keys':[TARGET_KEY] if count else [],
               'changed_key_count':count,'jwt_and_private_encryption_preserved':True,'existing_other_environment_values_preserved':True,
               'services_modified':False,'databases_modified':False}
        write_new(receipt,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
        print(json.dumps({'stage':value['phase'],'receipt_basename':receipt.name,'receipt_sha256':sha(receipt.read_bytes()),
                          'env_sha256':sha(after),'changed_keys':value['changed_keys'],'changed_key_count':count,
                          'services_modified':False,'databases_modified':False},sort_keys=True))
    finally:os.close(fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--expected-env-sha256',required=True)
    try:main(parser.parse_args())
    except BaseException as error:
        code=str(error) if isinstance(error,SwitchError) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'CUSTOMER_CONFIGURATION_FAILED'
        print('GOOGLE_ADS_CONFIG_ERROR '+code,flush=True);raise SystemExit(1) from None
