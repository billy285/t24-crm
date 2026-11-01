"""Emit a read-only checker only after exact real prepared/deployed receipts."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import zlib

HERE=Path(__file__).resolve().parent
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
    if not ok:raise RuntimeError(code)

def local(path,maximum=1048576):
    need(path.resolve()==path.absolute() and path.is_file() and not path.is_symlink() and path.stat().st_nlink==1,'EXACT_LOCAL_INPUT_REQUIRED')
    body=path.read_bytes();need(0<len(body)<=maximum,'BOUNDED_LOCAL_INPUT_REQUIRED');return body

def strict_json(body):
    def pairs(items):
        result={}
        for key,value in items:
            need(key not in result,'DUPLICATE_RECEIPT_KEY_REJECTED');result[key]=value
        return result
    def constant(value):raise RuntimeError('NONFINITE_RECEIPT_REJECTED')
    return json.loads(body,object_pairs_hook=pairs,parse_constant=constant)

def canonical(body):
    need(isinstance(body,bytes) and 0<len(body)<1048576,'ACTUAL_RECEIPT_BYTES_REQUIRED')
    value=strict_json(body);need(isinstance(value,dict) and '_canonical_sha256' not in value,'CANONICAL_RECEIPT_OBJECT_REQUIRED')
    marker=value.pop('receipt_sha256',None);encoded=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();sha=H(encoded)
    need(marker==sha if marker is not None else body==encoded,'EXACT_CANONICAL_RECEIPT_HASH_REQUIRED')
    return value,sha

def generate(prepared_body,deployed_body,*,customer_id=None,allow_connection_refresh=False):
    need(customer_id is None or type(customer_id)is int and customer_id>0,'EXACT_OPTIONAL_CUSTOMER_SCOPE_REQUIRED')
    need(type(allow_connection_refresh)is bool,'EXPLICIT_CONNECTION_REFRESH_FLAG_REQUIRED')
    prepared,prepared_sha=canonical(prepared_body);deployed,deployed_sha=canonical(deployed_body)
    path=HERE/'release.py';helper=local(path);spec=importlib.util.spec_from_file_location('_postpilot_local_release',path);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    r.pins_ready();manifest=local(HERE/'artifacts'/'manifest.json');payload=local(HERE/'artifacts'/'payload.tar.gz',16777216)
    r.validate_prepared(prepared,H(manifest),H(payload),r.ACTUAL_PREFLIGHT_SHA)
    need(deployed.get('stage')=='GOOGLE_ONBOARDING_DEPLOYED' and deployed.get('source_sha')==r.SOURCE_SHA and deployed.get('frontend_version')==r.FRONTEND and deployed.get('schema_revision')==r.NEW_REVISION and deployed.get('table_count')==162 and deployed.get('original_table_count')==158 and deployed.get('additive_tables')==sorted(r.NEW_TABLES) and deployed.get('prepared_sha256')==prepared_sha and deployed.get('preflight_sha256')==r.ACTUAL_PREFLIGHT_SHA and deployed.get('schema_sha256')==prepared['schema_after_sha256'],'EXACT_ACTUAL_DEPLOYMENT_REQUIRED')
    for key in ('all158_original_tables_preserved_except_reviewed_schema_head','four_new_onboarding_tables_empty','existing_full_environment_preserved','private_boundary_preserved','content_security_policy_unchanged'):
        need(deployed.get(key) is True,'DEPLOYMENT_PROTECTION_PROOF_REQUIRED')
    for key in ('operations_execution_enabled','operations_scheduler_enabled','database_restored','provider_requests','credentials_journaled','publications_or_ai_generation_executed'):
        need(deployed.get(key) is False,'DEPLOYMENT_NO_PUBLIC_ACTIONS_REQUIRED')
    runtime=deployed.get('crm');need(isinstance(runtime,dict) and set(runtime)=={'id','config','image','restart','started'} and all(isinstance(runtime[x],str) and re.fullmatch('[a-f0-9]{64}',runtime[x]) for x in ('id','config')) and isinstance(runtime['image'],str) and re.fullmatch('sha256:[a-f0-9]{64}',runtime['image']) and runtime['image']==prepared['candidate_image'] and type(runtime['restart'])is int and runtime['restart']==0 and isinstance(runtime['started'],str) and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z',runtime['started']),'EXACT_ACTUAL_RUNTIME_PINS_REQUIRED')
    release='/opt/t24-crm/releases/'+r.SCOPE+'-'+r.SOURCE_SHA[:12]+'-20261102'
    pins={'source_sha':r.SOURCE_SHA,'release':release,'helper_sha256':H(helper),'prepared_sha256':prepared_sha,'deployed_sha256':deployed_sha,'runtime':runtime,'customer_id':customer_id,'allow_connection_refresh':allow_connection_refresh}
    body=local(HERE/'postpilot.py',65536);sha=H(body);encoded=base64.b64encode(zlib.compress(body,9)).decode()
    command="""#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'POSTPILOT'
import base64,hashlib,zlib
payload=%r
expected=%r
pins=%r
decoder=zlib.decompressobj();body=decoder.decompress(base64.b64decode(payload,validate=True),65537)
if len(body)>65536 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_POSTPILOT_CHECKER_REQUIRED')
exec(compile(body,'<reviewed-read-only-postpilot>','exec'),{'__name__':'__main__','PINS':pins})
POSTPILOT
"""%(encoded,sha,pins)
    need(len(command.encode())<15000,'BOUNDED_READ_ONLY_COMMAND_REQUIRED')
    return command,{**pins,'checker_sha256':sha,'checker_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'database_writes':False,'provider_requests':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepared',type=Path,required=True);parser.add_argument('--deployed',type=Path,required=True);parser.add_argument('--customer-id',type=int);parser.add_argument('--allow-connection-refresh',action='store_true');parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    command,pins=generate(local(args.prepared),local(args.deployed),customer_id=args.customer_id,allow_connection_refresh=args.allow_connection_refresh)
    args.out.mkdir(parents=True,exist_ok=True);need(args.out.resolve()==args.out.absolute() and not args.out.is_symlink(),'CANONICAL_OUTPUT_DIRECTORY_REQUIRED')
    for name,body in (('postpilot-command.sh',command.encode()),('postpilot-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(args.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))

if __name__=='__main__':main()
