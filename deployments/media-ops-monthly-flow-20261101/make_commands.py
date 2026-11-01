"""Emit immutable carrier commands; never execute a server phase."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
DIRECTORY = 'deployments/media-ops-monthly-flow-20261101'
spec = importlib.util.spec_from_file_location('media_ops_monthly_commands_scope', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()


def strict_json(body):
    def pairs(items):
        result = {}
        for key,value in items:
            r.need(key not in result, 'DUPLICATE_RECEIPT_KEY_REJECTED'); result[key] = value
        return result
    def constant(value): raise RuntimeError('NONFINITE_RECEIPT_VALUE_REJECTED')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def canonical_prepared(body):
    """Pin server prepared.json, not a transport envelope containing its SHA."""
    value = strict_json(body)
    r.need(isinstance(value,dict) and '_canonical_sha256' not in value, 'CANONICAL_RECEIPT_OBJECT_REQUIRED')
    marker = value.pop('receipt_sha256', None)
    canonical = r.encoded(value); sha = H(canonical)
    if marker is not None:
        r.need(isinstance(marker,str) and re.fullmatch('[a-f0-9]{64}',marker) and marker == sha, 'ENVELOPE_RECEIPT_HASH_MISMATCH')
    else:
        r.need(body == canonical, 'EXACT_CANONICAL_SERVER_RECEIPT_REQUIRED')
    value['_canonical_sha256'] = sha
    return value


def generate(carrier, summary, prepared=None):
    r.pins_ready(); r.validate_summary(summary)
    r.need(re.fullmatch('[a-f0-9]{40}', carrier or ''), 'EXACT_IMMUTABLE_CARRIER_REQUIRED')
    git = lambda *args: subprocess.check_output(['git', *args])
    r.need(git('rev-parse', carrier + ':app') == git('rev-parse', r.SOURCE_SHA + ':app'), 'CARRIER_APPLICATION_TREE_DRIFT')
    files = {}
    for name, target in [('release.py', 'release.py'), ('preflight.py', 'preflight.py'), ('artifacts/manifest.json', 'manifest.json'), ('artifacts/payload.tar.gz', 'payload.tar.gz')]:
        body = r.local_bytes(HERE / name); r.need(git('show', carrier + ':' + DIRECTORY + '/' + name) == body, 'EXACT_COMMITTED_MEMBER_REQUIRED'); files[name] = (target, H(body), len(body))
    r.need(files['preflight.py'][1] == r.PREFLIGHT_SHA, 'EXACT_REVIEWED_PREFLIGHT_REQUIRED')
    manifest = strict_json(r.local_bytes(HERE / 'artifacts/manifest.json', 1048576))
    r.need(manifest['source_sha'] == r.SOURCE_SHA and manifest['frontend_version'] == r.FRONTEND and manifest['baseline_source_sha'] == r.BASE_SOURCE and manifest['baseline_frontend_version'] == r.BASE_FRONTEND and manifest['schema_revision'] == r.NEW_REVISION and manifest['old_schema_revision'] == r.OLD_REVISION and manifest['additive_tables'] == sorted(r.NEW_TABLES) and manifest['preflight_sha256'] == summary['sha256'], 'EXACT_MANIFEST_IDENTITIES_REQUIRED')
    r.need(all(manifest[key] is True for key in r.TRUE_FLAGS) and all(manifest[key] is False for key in r.FALSE_FLAGS), 'EXACT_DRAFT_ONLY_ADDITIVE_MANIFEST_REQUIRED')
    r.need(set(manifest['changed_source_files']) == r.SOURCE_FILES and len(manifest['changed_source_files']) == len(r.SOURCE_FILES) and set(manifest['backend_before']) == set(manifest['backend_after']) == r.BACKEND_FILES and manifest['backend_before'] == r.ORIGINAL_BACKEND_HASHES and manifest['backend_after'] == r.FINAL_BACKEND_HASHES, 'EXACT_REVIEWED_SOURCE_ALLOWLIST_REQUIRED')
    r.need(manifest['payload_sha256'] == files['artifacts/payload.tar.gz'][1] and manifest['application_freeze_sha256'] == r.APPLICATION_FREEZE_SHA, 'EXACT_PAYLOAD_FREEZE_PINS_REQUIRED')
    release = '/opt/t24-crm/releases/' + r.SCOPE + '-' + r.SOURCE_SHA[:12] + '-20261101'
    common = ['--release', release, '--manifest-sha256', files['artifacts/manifest.json'][1], '--payload-sha256', files['artifacts/payload.tar.gz'][1], '--preflight', summary['path'], '--preflight-sha256', summary['sha256']]
    prepare = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys,urllib.request
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('CARRIER_REDIRECT_REJECTED')
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 need(os.geteuid()==0 and socket.gethostname()=={r.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
 release=Path({release!r});files={files!r};carrier={carrier!r}
 for parent in release.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 need(not release.exists() and not release.is_symlink(),'FRESH_RELEASE_REQUIRED');selected={{}}
 for name,(target,expected,size) in files.items():
  need(0<size<16777216,'BOUNDED_COMMITTED_MEMBER_REQUIRED');url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
  with opener.open(url,timeout=60) as response:
   need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and H(body)==expected,'EXACT_CARRIER_BYTES_REQUIRED');selected[target]=body
 release.mkdir(mode=0o700)
 for name,body in selected.items():
  fd=os.open(release/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 namespace={{'__name__':'reviewed_workflow_release','__file__':str(release/'release.py')}};sys.argv=[str(release/'release.py'),'--phase','prepare',*{common!r}]
 exec(compile(selected['release.py'],namespace['__file__'],'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_OPS_MONTHLY_FLOW_PREPARE_REJECTED'
 print(json.dumps({{'stage':'MEDIA_OPS_MONTHLY_FLOW_PREPARE_REJECTED','code':code}}));sys.exit(1)
WORKFLOW
'''
    outputs = {'prepare-command.sh': prepare}; review_sha = None
    if prepared is not None:
        r.validate_prepared(prepared, files['artifacts/manifest.json'][1], files['artifacts/payload.tar.gz'][1], summary['sha256'])
        review_sha = prepared.get('_canonical_sha256'); r.need(re.fullmatch('[a-f0-9]{64}', review_sha or ''), 'EXACT_CANONICAL_PREPARED_HASH_REQUIRED')
        for phase in ('activate', 'recover'):
            outputs[phase + '-command.sh'] = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'WORKFLOW'
import hashlib,json,os,re,resource,socket,stat,sys
from pathlib import Path
try:
 sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 if os.geteuid()!=0 or socket.gethostname()!={r.HOST!r}:raise RuntimeError('EXACT_ROOT_SERVER_REQUIRED')
 release=Path({release!r});path=release/'release.py'
 for parent in path.parents:
  row=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(row.st_mode) or row.st_uid!=0 or row.st_mode&0o022:raise RuntimeError('PROTECTED_HELPER_PARENT_REQUIRED')
 row=path.lstat()
 if path.resolve()!=path or not stat.S_ISREG(row.st_mode) or row.st_uid!=0 or row.st_nlink!=1 or stat.S_IMODE(row.st_mode)!=0o600:raise RuntimeError('PROTECTED_HELPER_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno())
  if (opened.st_dev,opened.st_ino)!=(row.st_dev,row.st_ino):raise RuntimeError('HELPER_OPEN_DRIFT')
  body=stream.read({files['release.py'][2] + 1})
 if len(body)!={files['release.py'][2]} or hashlib.sha256(body).hexdigest()!={files['release.py'][1]!r}:raise RuntimeError('EXACT_RELEASE_HELPER_REQUIRED')
 sys.argv=[str(path),'--phase',{phase!r},*{common!r},'--review-sha256',{review_sha!r}];namespace={{'__name__':'reviewed_workflow_release','__file__':str(path)}}
 exec(compile(body,str(path),'exec'),namespace);namespace['main']()
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'MEDIA_OPS_MONTHLY_FLOW_SWITCH_REJECTED'
 print(json.dumps({{'stage':'MEDIA_OPS_MONTHLY_FLOW_SWITCH_REJECTED','code':code}}));sys.exit(1)
WORKFLOW
'''
    r.need(all(len(command.encode()) < 11000 for command in outputs.values()), 'SMALL_WRAPPER_LIMIT_REQUIRED')
    return outputs, {'carrier': carrier, 'source_sha': r.SOURCE_SHA, 'frontend_version': r.FRONTEND, 'preflight_sha256': summary['sha256'], 'release': release, 'members': files, 'prepared_sha256': review_sha, 'command_sha256': {name: H(command.encode()) for name, command in outputs.items()}, 'executed': False}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--carrier', required=True); parser.add_argument('--preflight-summary', type=Path, required=True); parser.add_argument('--prepared-receipt', type=Path); parser.add_argument('--out', type=Path, required=True); args = parser.parse_args()
    summary = strict_json(r.local_bytes(args.preflight_summary, 1048576)); prepared = None
    if args.prepared_receipt:
        prepared = canonical_prepared(r.local_bytes(args.prepared_receipt, 1048576))
    commands, pins = generate(args.carrier, summary, prepared); args.out.mkdir(parents=True, exist_ok=True)
    for name, text in {**commands, 'command-pins.json': json.dumps(pins, sort_keys=True, indent=2) + '\n'}.items():
        fd = os.open(args.out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(text); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(pins, sort_keys=True))


if __name__ == '__main__': main()
