"""Generate immutable prepare commands, and activation only after receipt review."""
import argparse
import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIRECTORY = "deployments/media-ops-management-20261031"
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def installer(path, body, expected):
    encoded = base64.b64encode(zlib.compress(body, 9)).decode()
    return f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PY'
import base64,hashlib,json,os,re,resource,socket,stat,sys,zlib
from pathlib import Path
def need(ok,code):
 if not ok:raise RuntimeError(code)
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 target=Path({path!r});expected={expected!r}
 need(target.parent==Path('/opt/t24-crm/releases') and target.resolve()==target,'EXACT_PROOF_PATH_REQUIRED')
 for parent in target.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 body=zlib.decompress(base64.b64decode({encoded!r}));need(hashlib.sha256(body).hexdigest()==expected,'PREFLIGHT_BODY_HASH_DRIFT')
 if target.exists() or target.is_symlink():
  info=target.lstat();need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'PROTECTED_PROOF_FILE_REQUIRED')
  fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as stream:actual=stream.read(len(body)+1)
  need(hashlib.sha256(actual).hexdigest()==expected,'EXISTING_PROOF_HASH_DRIFT')
 else:
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 print(json.dumps({{'stage':'MEDIA_OPS_MANAGEMENT_PREFLIGHT_INSTALLED','sha256':expected,'database_modified':False,'configuration_modified':False}}))
except BaseException as error:
 code=str(error) if re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'MEDIA_OPS_MANAGEMENT_PREFLIGHT_INSTALL_REJECTED','code':code}}));sys.exit(1)
PY
'''


def receipt_installers(path, body, expected):
    direct = installer(path, body, expected)
    if len(direct.encode()) < 11000:
        return {"receipt-install-command.sh": direct}
    compressed = zlib.compress(body, 9)
    parts = [compressed[index:index + 3600] for index in range(0, len(compressed), 3600)]
    need(len(parts) <= 40 and len(body) <= 262144 and H(body) == expected, 'BOUNDED_RECEIPT_PARTS_REQUIRED')
    outputs = {}; pins = []
    guard = """import base64,hashlib,json,os,re,resource,socket,stat,sys,zlib
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
def checked(path,maximum):
 info=path.lstat();need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'PROTECTED_PROOF_FILE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'PROOF_FILE_OPEN_DRIFT');value=stream.read(maximum+1)
 need(len(value)<=maximum,'PROOF_FILE_LIMIT');return value
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
"""
    for index, part in enumerate(parts):
        target = path + '.zpart-' + str(index)
        pins.append((target, H(part), len(part)))
        code = guard + f""" target=Path({target!r});value=base64.b64decode({base64.b64encode(part).decode()!r})
 need(target.parent==Path('/opt/t24-crm/releases') and target.resolve()==target,'EXACT_PROOF_PATH_REQUIRED')
 for parent in target.parents:
  info=parent.lstat();need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(H(value)=={H(part)!r},'PROOF_PART_HASH_DRIFT')
 if target.exists() or target.is_symlink():need(checked(target,{len(part)})==value,'EXISTING_PROOF_PART_DRIFT')
 else:
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
 print(json.dumps({{'stage':'MEDIA_OPS_PROOF_PART_INSTALLED','index':{index},'proof_sha256':{expected!r}}}))
"""
        code += "except BaseException:\n print(json.dumps({'stage':'MEDIA_OPS_PROOF_PART_REJECTED'}));sys.exit(1)\n"
        outputs['receipt-install-part-' + str(index + 1).zfill(2) + '.sh'] = "#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'PY'\n" + code + "PY\n"
    code = guard + f""" target=Path({path!r});pins={pins!r}
 need(target.parent==Path('/opt/t24-crm/releases') and target.resolve()==target,'EXACT_PROOF_PATH_REQUIRED')
 for parent in target.parents:
  info=parent.lstat();need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 pieces=[]
 for name,expected,size in pins:
  value=checked(Path(name),size);need(H(value)==expected,'PROOF_PART_HASH_DRIFT');pieces.append(value)
 value=zlib.decompress(b''.join(pieces));need(len(value)=={len(body)} and H(value)=={expected!r},'EXACT_FULL_PROOF_REQUIRED')
 if target.exists() or target.is_symlink():need(checked(target,{len(body)})==value,'EXISTING_PROOF_DRIFT')
 else:
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
 print(json.dumps({{'stage':'MEDIA_OPS_MANAGEMENT_PREFLIGHT_INSTALLED','sha256':{expected!r}}}))
"""
    code += "except BaseException:\n print(json.dumps({'stage':'MEDIA_OPS_FULL_PROOF_REJECTED'}));sys.exit(1)\n"
    outputs['receipt-install-command.sh'] = "#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'PY'\n" + code + "PY\n"
    need(all(len(value.encode()) < 11000 for value in outputs.values()), 'RECEIPT_COMMAND_TOO_LARGE')
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--carrier", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight-receipt", type=Path, required=True)
    parser.add_argument("--prepared-receipt", type=Path)
    args = parser.parse_args()
    need(bool(re.fullmatch("[a-f0-9]{40}", args.carrier)), "EXACT_IMMUTABLE_CARRIER_REQUIRED")
    proof_body = args.preflight_receipt.read_bytes()
    proof_sha = H(proof_body)
    proof = json.loads(proof_body)
    need(proof.get("stage") == "MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT" and proof.get("gbp_feature_enabled") is True and proof.get("scheduler_disabled") is True, "ENABLED_GBP_DISABLED_SCHEDULER_PREFLIGHT_REQUIRED")
    need(len(proof_body) < 262144, "COMPACT_READONLY_PREFLIGHT_REQUIRED")
    manifest = json.loads((ROOT / "artifacts/manifest.json").read_bytes())
    need(manifest["preflight_sha256"] == proof_sha and manifest["production_seed_rows"] is False and manifest["credentials_included"] is False, "EXACT_PREFLIGHT_AND_SCOPE_REQUIRED")
    source, version = manifest["source_sha"], manifest["frontend_version"]
    need(subprocess.check_output(['git','rev-parse',args.carrier+':app']) == subprocess.check_output(['git','rev-parse',source+':app']), 'CARRIER_APPLICATION_TREE_DRIFT')
    need(bool(re.fullmatch("[a-f0-9]{40}", source)) and bool(re.fullmatch("[a-f0-9]{12}", version)), "EXACT_APPLICATION_PINS_REQUIRED")
    files = {}
    for name, target in (("release.py", "release.py"), ("preflight.py", "preflight.py"), ("artifacts/manifest.json", "manifest.json"), ("artifacts/payload.tar.gz", "payload.tar.gz")):
        body = (ROOT / name).read_bytes()
        committed = subprocess.check_output(["git", "show", args.carrier + ":" + DIRECTORY + "/" + name])
        need(body == committed, "IMMUTABLE_CARRIER_MEMBER_DRIFT")
        files[name] = (target, H(body), len(body))
    release = "/opt/t24-crm/releases/media-ops-management-" + source[:12] + "-20261031"
    preflight = "/opt/t24-crm/releases/media-ops-management-preflight-" + proof_sha[:12] + ".json"
    common = ["--release", release, "--manifest-sha256", files["artifacts/manifest.json"][1],
        "--payload-sha256", files["artifacts/payload.tar.gz"][1], "--preflight", preflight, "--preflight-sha256", proof_sha]
    prepare = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PY'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
 carrier={args.carrier!r};files={files!r};release=Path({release!r})
 for parent in release.parents:
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED')
 selected={{}}
 for name,(target,expected,size) in files.items():
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  with urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect()).open(url,timeout=60) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'CARRIER_MEMBER_HASH_DRIFT');selected[target]=body
 m=json.loads(selected['manifest.json'])
 need(m['source_sha']=={source!r} and m['frontend_version']=={version!r} and m['preflight_sha256']=={proof_sha!r} and m['production_seed_rows'] is False and m['credentials_included'] is False,'SOURCE_SCOPE_DRIFT')
 release.mkdir(mode=0o700)
 for target,body in selected.items():
  fd=os.open(release/target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 helper=release/'release.py';body=helper.read_bytes();need(H(body)==files['release.py'][1],'HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase','prepare',*{common!r}]
 namespace={{'__name__':'pinned_google_business_prepare','__file__':str(helper)}}
 exec(compile(body,str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'MEDIA_OPS_MANAGEMENT_PREPARE_REJECTED','code':code}}));sys.exit(1)
PY
'''
    args.out.mkdir(parents=True, exist_ok=True)
    outputs = {**receipt_installers(preflight, proof_body, proof_sha), "prepare-command.sh": prepare}
    pins = {"carrier": args.carrier, "source_sha": source, "frontend_version": version,
        "release": release, "preflight": preflight, "preflight_sha256": proof_sha, "files": files}
    if args.prepared_receipt:
        body = args.prepared_receipt.read_bytes()
        receipt = json.loads(body)
        need(receipt["stage"] == "MEDIA_OPS_MANAGEMENT_PREPARED_OFFLINE_VERIFIED" and receipt["source_sha"] == source and receipt["frontend_version"] == version, "PREPARED_SOURCE_DRIFT")
        need(receipt["manifest_sha256"] == files["artifacts/manifest.json"][1] and receipt["payload_sha256"] == files["artifacts/payload.tar.gz"][1] and receipt["preflight_sha256"] == proof_sha, "PREPARED_IDENTITIES_DRIFT")
        need(receipt.get("gbp_disabled_unconfigured_verified") is True and receipt.get("offline_google_secrets_absent") is True, "DISABLED_GBP_PREPARED_PROOF_REQUIRED")
        review = H(body)
        pins["prepared_sha256"] = review
        for phase in ("activate", "recover"):
            outputs[phase + "-command.sh"] = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'PY'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!='iZj6c4cj7edgnhdimts4l7Z':raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 helper=Path({(release + '/release.py')!r})
 for parent in helper.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=helper.lstat()
 if not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(helper,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:body=stream.read({files['release.py'][2]+1})
 if hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('HELPER_HASH_DRIFT')
 sys.argv=[str(helper),'--phase',{phase!r},*{common!r},'--review-sha256',{review!r}]
 namespace={{'__name__':'pinned_google_business_{phase}','__file__':str(helper)}}
 exec(compile(body,str(helper),'exec'),namespace);namespace['main']()
except BaseException as error:
 code=str(error) if re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'stage':'MEDIA_OPS_MANAGEMENT_{phase.upper()}_REJECTED','code':code}}));sys.exit(1)
PY
'''
    for name, body in outputs.items():
        (args.out / name).write_text(body)
        (args.out / name).chmod(0o600)
    (args.out / "package-pins.json").write_text(json.dumps(pins, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"commands_generated": True, "source_sha": source, "frontend_version": version,
        "activation_generated": bool(args.prepared_receipt), "preflight_sha256": proof_sha}))


if __name__ == "__main__":
    main()
