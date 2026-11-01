"""Emit an exact-prepared, read-only synthetic preview reader; never run it."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("asset_visual_export_receipts",HERE/"make_commands.py")
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
H=lambda body:hashlib.sha256(body).hexdigest()


SERVER=r'''import base64,hashlib,json,os,re,resource,socket,stat,struct,sys
from pathlib import Path
ROOT=Path(__ROOT__);EXPECTED=__RESULT__;HOST=__HOST__;SOURCE=__SOURCE__
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def fields(s):return(s.st_dev,s.st_ino,s.st_uid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def read(path,maximum,sha=None):
 need(path.is_absolute() and path.resolve()==path,'CANONICAL_FIXED_FILE_REQUIRED')
 for p in path.parents:
  s=p.lstat();need(p.resolve()==p and stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'ROOT_PRIVATE_PARENT_REQUIRED')
 before=path.lstat();need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum,'ROOT600_REGULAR_FILE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno());body=f.read(maximum+1);after=os.fstat(f.fileno())
 need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)==before.st_size and (sha is None or H(body)==sha),'EXACT_UNCHANGED_HASHED_FILE_REQUIRED')
 return body
def pairs(rows):
 out={}
 for k,v in rows:need(k not in out,'DUPLICATE_JSON_KEY_REJECTED');out[k]=v
 return out
def constant(_):raise RuntimeError('NONFINITE_JSON_REJECTED')
def validate(v):
 need(v.get('stage')=='FINAL_ASSET_RENDERER_OFFLINE_VERIFIED' and v.get('source_sha')==SOURCE,'EXACT_FINAL_RENDERER_RESULT_REQUIRED')
 need(all(type(v.get(k)) is int and v[k]==n for k,n in [('database_calls',0),('provider_calls',0),('business_writes',0),('process_launches',9)]),'ZERO_BUSINESS_AND_PROVIDER_ACTIONS_REQUIRED')
 need(all(v.get(k) is True for k in ['synthetic_pixels_only','all_private_temporary_trees_removed','one_core_low_priority_minimal_environment']),'SYNTHETIC_ONLY_VERIFIED_RESULT_REQUIRED')
 cases=v.get('cases');need(isinstance(cases,list) and len(cases)==8 and len({x.get('name') for x in cases})==8,'EXACT_EIGHT_RENDER_CASES_REQUIRED')
 samples=v.get('visual_samples');need(isinstance(samples,list) and len(samples)==2,'EXACT_TWO_SYNTHETIC_PREVIEWS_REQUIRED')
 expected={'chinese-poster.png':'chinese_long_poster','collage-four.png':'whole_photo_collage_4'};seen=set()
 for x in samples:
  name=x.get('file_name');need(name in expected and name not in seen and x.get('case')==expected[name] and x.get('synthetic_only') is True and x.get('mime_type')=='image/png','FIXED_SYNTHETIC_PREVIEW_IDENTITY_REQUIRED');seen.add(name)
  need(type(x.get('byte_size')) is int and 0<x['byte_size']<=22528 and all(type(x.get(k)) is int and 0<x[k]<=360 for k in ['width','height']) and re.fullmatch('[a-f0-9]{64}',x.get('sha256','')),'BOUNDED_PREVIEW_DESCRIPTOR_REQUIRED')
  original=next((a for a in cases if a.get('name')==x['case']),None);need(original is not None and x.get('original')=={k:original.get(k) for k in ['sha256','byte_size','width','height']},'ORIGINAL_RENDER_PROOF_REQUIRED')
 return samples
def main():
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 body=read(ROOT/'renderer-canary-result.json',131072,EXPECTED);result=json.loads(body,object_pairs_hook=pairs,parse_constant=constant);samples=validate(result);previews=[]
 for x in samples:
  body=read(ROOT/'probe-logs'/'asset-studio-canary'/x['file_name'],22528,x['sha256'])
  need(len(body)==x['byte_size'] and body[:8]==b'\x89PNG\r\n\x1a\n' and body[8:16]==b'\x00\x00\x00\rIHDR' and struct.unpack('>II',body[16:24])==(x['width'],x['height']),'EXACT_PNG_HEADER_AND_DIMENSIONS_REQUIRED')
  previews.append({**x,'base64':base64.b64encode(body).decode()})
 need(sum(len(x['base64']) for x in previews)<=61440,'BOUNDED_SYNTHETIC_EXPORT_REQUIRED')
 print(json.dumps({'stage':'ASSET_STUDIO_SYNTHETIC_VISUALS_EXPORTED','renderer_result_sha256':EXPECTED,'renderer_result':result,'previews':previews},sort_keys=True))
try:main()
except Exception as e:
 value=str(e);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'SYNTHETIC_VISUAL_EXPORT_REJECTED'
 print(json.dumps({'stage':'SYNTHETIC_VISUAL_EXPORT_REJECTED','code':code},sort_keys=True));sys.exit(1)
'''


def generate(prepared_body):
    r=c.r;r.pins_ready();value=c.canonical_prepared(prepared_body)
    manifest=r.local_bytes(HERE/"artifacts/manifest.json",1048576);payload=r.local_bytes(HERE/"artifacts/payload.tar.gz")
    r.validate_prepared(value,H(manifest),H(payload),r.ACTUAL_PREFLIGHT_SHA)
    root="/opt/t24-crm/releases/"+r.SCOPE+"-"+r.SOURCE_SHA[:12]+"-20261101"
    code=SERVER.replace("__ROOT__",repr(root)).replace("__RESULT__",repr(value["renderer_canary_result_sha256"])).replace("__HOST__",repr(r.HOST)).replace("__SOURCE__",repr(r.SOURCE_SHA))
    command="#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'VISUAL'\n"+code+"VISUAL\n"
    r.need(len(command.encode())<6144,"BOUNDED_READ_ONLY_VISUAL_COMMAND_REQUIRED")
    return command,{"source_sha":r.SOURCE_SHA,"prepared_sha256":value["_canonical_sha256"],"renderer_result_sha256":value["renderer_canary_result_sha256"],"command_sha256":H(command.encode()),"executed":False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--prepared-receipt",type=Path,required=True);parser.add_argument("--out",type=Path,required=True);args=parser.parse_args()
    command,pins=generate(c.r.local_bytes(args.prepared_receipt,1048576))
    args.out.mkdir(parents=True,exist_ok=True)
    c.r.need(args.out.resolve()==args.out.absolute() and not args.out.is_symlink(),"CANONICAL_NEW_COMMAND_DIRECTORY_REQUIRED")
    for name,body in (("visual-export-command.sh",command.encode()),("visual-export-pins.json",c.r.encoded(pins))):
        fd=os.open(args.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"wb") as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps(pins,sort_keys=True))


if __name__=="__main__":main()
