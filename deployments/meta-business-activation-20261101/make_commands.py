"""Generate small reviewable commands; never execute server/account operations."""
import argparse
import base64
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
H = lambda value: hashlib.sha256(value).hexdigest()
DIRECTORY = 'deployments/meta-business-activation-20261101'
MEMBERS = ('core.py', 'baseline.py', 'transport.py', 'activation.py')


def local(name):
    path = HERE/name
    if path.is_symlink() or not path.is_file(): raise RuntimeError('REGULAR_REVIEWED_TOOL_REQUIRED')
    body = path.read_bytes()
    if not 0 < len(body) <= 131072: raise RuntimeError('BOUNDED_REVIEWED_TOOL_REQUIRED')
    return body


def identities():
    modules = {}
    for name in ('core.py', 'baseline.py'):
        spec = importlib.util.spec_from_file_location('_meta_commands_'+name[:-3], HERE/name)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
    core, baseline = modules['core.py'], modules['baseline.py']; core.pins_ready()
    if not re.fullmatch('[a-f0-9]{64}', baseline.BASELINE_SHA or '') or baseline.BASELINE_SHA == '0'*64:
        raise RuntimeError('ACTUAL_REVIEWED_BASELINE_REQUIRED')
    return core, baseline


def validate_summary(summary, core, baseline):
    expected = {'stage': 'META_ACTIVATION_BASELINE_CAPTURED', 'sha256': baseline.BASELINE_SHA, 'path': str(core.ROOT/'baseline.json'),
        'source_sha': core.SOURCE_SHA, 'frontend_version': core.FRONTEND, 'schema_revision': core.SCHEMA_REVISION, 'table_count': 141,
        'meta_environment_keys_absent': True, 'google_scheduler_enabled': True, 'google_scheduler_activation_from': core.ACTIVATION_FROM,
        'business_writes': False, 'credential_content_read': False, 'provider_requests': False, 'runtime_changed': False}
    if not all(summary.get(key) == value for key, value in expected.items()): raise RuntimeError('EXACT_ACTUAL_BASELINE_SUMMARY_REQUIRED')
    runtime = summary.get('runtime', {})
    if runtime.get('id') != core.ORIGINAL_ID or runtime.get('image') != core.IMAGE or runtime.get('restart') != 0 or not re.fullmatch('[a-f0-9]{64}', runtime.get('config', '')):
        raise RuntimeError('EXACT_DISABLED_ORIGINAL_RUNTIME_REQUIRED')


def prefix(core):
    # Bootstrap protects every component before executing even the pinned core.
    return f'''import hashlib,json,os,re,resource,socket,stat,sys,types
from pathlib import Path
sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
def need(ok,code):
 if not ok:raise RuntimeError(code)
need(os.geteuid()==0 and socket.gethostname()=={core.HOST!r},'EXACT_ROOT_SERVER_REQUIRED')
root=Path({str(core.ROOT)!r})
toolroot=root/'tools-activation-v1'
for parent in (root,*root.parents):
 row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TOOL_PARENT_REQUIRED')
need(stat.S_IMODE(root.lstat().st_mode)==0o700,'EXACT_PRIVATE_RELEASE_DIRECTORY_REQUIRED')
def read(path,sha,size):
 for parent in path.parents:
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TOOL_PARENT_REQUIRED')
 prior=path.lstat();need(path.resolve()==path and stat.S_ISREG(prior.st_mode) and prior.st_uid==0 and prior.st_nlink==1 and stat.S_IMODE(prior.st_mode)==0o600,'PROTECTED_EXACT_TOOL_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(size+1)
 after=path.lstat();fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
 need(fields(prior)==fields(opened)==fields(after) and len(body)==size and hashlib.sha256(body).hexdigest()==sha,'EXACT_PROTECTED_TOOL_BYTES_REQUIRED');return body
def load(files):
 modules={{}}
 for name in {MEMBERS!r}:
  module=types.ModuleType('_reviewed_meta_activation_'+name[:-3]);module.__file__=str(toolroot/name)
  if name=='core.py':sys.modules['core']=module
  exec(compile(files[name],module.__file__,'exec'),module.__dict__);modules[name]=module
 modules['baseline.py'].configure(modules['core.py']);modules['activation.py'].configure(modules['core.py'],modules['baseline.py'])
 return modules
'''


def wrap(code):
    value = "#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'META_ACTIVATION'\ntry:\n" + ''.join(' '+line+'\n' for line in code.splitlines()) + '''except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'META_ACTIVATION_COMMAND_REJECTED'
 print(json.dumps({'stage':'META_ACTIVATION_COMMAND_REJECTED','code':code,'credential_values_exported':False,'database_restored':False}));sys.exit(1)
META_ACTIVATION
'''
    if len(value.encode()) >= 11000: raise RuntimeError('SMALL_COMMAND_REQUIRED')
    return value


def entry_command(pins, phase, *, transfer_id=None, ciphertext=None):
    core, baseline = identities()
    if pins != {name: {'sha256': H(local(name)), 'bytes': len(local(name))} for name in MEMBERS}: raise RuntimeError('EXACT_CURRENT_FOUR_TOOL_PINS_REQUIRED')
    if phase not in {'prepare', 'receive', 'activate', 'recover'}: raise RuntimeError('EXACT_REVIEWED_PHASE_REQUIRED')
    if phase == 'receive':
        if not isinstance(transfer_id, str) or not re.fullmatch('[a-f0-9]{32}', transfer_id): raise RuntimeError('EXACT_TRANSFER_ID_REQUIRED')
        try: encrypted = base64.b64decode(ciphertext, validate=True)
        except (TypeError, ValueError): raise RuntimeError('BOUNDED_CIPHERTEXT_ONLY_REQUIRED') from None
        if len(encrypted) != 384 or base64.b64encode(encrypted).decode() != ciphertext: raise RuntimeError('BOUNDED_CIPHERTEXT_ONLY_REQUIRED')
    elif transfer_id is not None or ciphertext is not None: raise RuntimeError('CIPHERTEXT_ONLY_FOR_RECEIVE')
    code = prefix(core) + f"need(stat.S_IMODE(toolroot.lstat().st_mode)==0o700,'EXACT_PRIVATE_TOOL_DIRECTORY_REQUIRED')\npins={pins!r};files={{name:read(toolroot/name,pin['sha256'],pin['bytes']) for name,pin in pins.items()}}\nmodules=load(files)\nc=modules['core.py'];b=modules['baseline.py'];c.server_guard();c.pins_ready();b.proof()\n"
    if phase == 'prepare': call = "modules['transport.py'].prepare(b.verify)"
    elif phase == 'receive': call = f"modules['transport.py'].receive(b.verify,{transfer_id!r},{ciphertext!r})"
    else: call = f"modules['activation.py'].{phase}()"
    return wrap(code + 'print(json.dumps('+call+',sort_keys=True))\n')


def generate(carrier, summary):
    core, baseline = identities(); validate_summary(summary, core, baseline)
    if not re.fullmatch('[a-f0-9]{40}', carrier or ''): raise RuntimeError('EXACT_IMMUTABLE_CARRIER_REQUIRED')
    git = lambda *args: subprocess.check_output(['git', *args])
    if git('rev-parse', carrier+':app') != git('rev-parse', core.SOURCE_SHA+':app'): raise RuntimeError('CARRIER_APPLICATION_TREE_DRIFT')
    files = {}
    for name in MEMBERS:
        body = local(name)
        if git('show', carrier+':'+DIRECTORY+'/'+name) != body: raise RuntimeError('EXACT_COMMITTED_TOOL_REQUIRED')
        files[name] = {'sha256': H(body), 'bytes': len(body)}
    stage = prefix(core) + f'''import urllib.request
pins={files!r};carrier={carrier!r};selected={{}}
need(not toolroot.exists() and not toolroot.is_symlink(),'FRESH_ACTIVATION_TOOL_DIRECTORY_REQUIRED')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise RuntimeError('CARRIER_REDIRECT_REJECTED')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
for name,pin in pins.items():
 url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name
 with opener.open(url,timeout=60) as response:
  need(response.status==200 and response.geturl()==url,'EXACT_CARRIER_RESPONSE_REQUIRED');body=response.read(pin['bytes']+1)
 need(len(body)==pin['bytes'] and hashlib.sha256(body).hexdigest()==pin['sha256'],'EXACT_CARRIER_BYTES_REQUIRED');selected[name]=body
modules=load(selected);c=modules['core.py'];b=modules['baseline.py'];c.server_guard();c.pins_ready();b.verify('tool-staging-before')
c.mkdir(toolroot)
for name,body in selected.items():c.write(toolroot/name,body)
b.verify('tool-staging-after')
receipt={{'stage':'META_ACTIVATION_TOOLS_STAGED','carrier':carrier,'members':pins,'source_sha':c.SOURCE_SHA,'baseline_sha256':b.BASELINE_SHA,'config_id':c.CONFIG_ID,'configuration_freeze_sha256':c.CONFIG_FREEZE_SHA,'runtime_changed':False,'business_writes':False,'provider_requests':False}}
sha=c.write(toolroot/'staged-tools.json',receipt);print(json.dumps({{**receipt,'receipt_sha256':sha}},sort_keys=True))
'''
    outputs = {'stage-command.sh': wrap(stage)}
    for phase in ('prepare', 'activate', 'recover'): outputs[phase+'-command.sh'] = entry_command(files, phase)
    return outputs, {'carrier': carrier, 'members': files, 'source_sha': core.SOURCE_SHA, 'frontend_version': core.FRONTEND,
        'baseline_sha256': baseline.BASELINE_SHA, 'config_id': core.CONFIG_ID, 'graph_version': core.GRAPH_VERSION,
        'configuration_freeze_sha256': core.CONFIG_FREEZE_SHA, 'release': str(core.ROOT),
        'commands': {name: H(value.encode()) for name, value in outputs.items()}, 'executed': False}


def capture_command():
    files = {}
    for name in ('core.py', 'baseline.py'):
        path = HERE/name
        if path.is_symlink() or not path.is_file(): raise RuntimeError('REGULAR_CAPTURE_SOURCE_REQUIRED')
        body = path.read_bytes()
        if not 0 < len(body) < 131072: raise RuntimeError('BOUNDED_CAPTURE_SOURCE_REQUIRED')
        files[name] = (base64.b64encode(zlib.compress(body, 9)).decode(), H(body), len(body))
    value = f'''#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'META_CAPTURE'
import base64,hashlib,json,re,sys,types,zlib
try:
 sys.dont_write_bytecode=True
 files={files!r};modules={{}}
 for name,(packed,sha,size) in files.items():
  body=zlib.decompress(base64.b64decode(packed,validate=True))
  if len(body)!=size or hashlib.sha256(body).hexdigest()!=sha:raise RuntimeError('EXACT_CAPTURE_SOURCE_REQUIRED')
  module=types.ModuleType('_reviewed_meta_'+name[:-3]);module.__file__='<reviewed-'+name+'>'
  exec(compile(body,module.__file__,'exec'),module.__dict__);modules[name]=module
 modules['baseline.py'].configure(modules['core.py'])
 print(json.dumps(modules['baseline.py'].capture(),sort_keys=True))
except BaseException as error:
 value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',value) else 'META_BASELINE_CAPTURE_REJECTED'
 print(json.dumps({{'stage':'META_ACTIVATION_BASELINE_CAPTURE_REJECTED','code':code}}));sys.exit(1)
META_CAPTURE
'''
    if len(value.encode()) >= 11000: raise RuntimeError('SMALL_CAPTURE_COMMAND_REQUIRED')
    return value, {name: {'sha256': row[1], 'bytes': row[2]} for name, row in files.items()}


def main():
    parser = argparse.ArgumentParser(); mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture-out', type=Path); mode.add_argument('--out', type=Path); mode.add_argument('--receive-out', type=Path)
    parser.add_argument('--carrier'); parser.add_argument('--baseline-summary', type=Path); parser.add_argument('--command-pins', type=Path)
    parser.add_argument('--transfer-id'); parser.add_argument('--ciphertext-file', type=Path); args = parser.parse_args()
    if args.capture_out:
        command, pins = capture_command(); outputs = {args.capture_out.name: command}; directory = args.capture_out.parent
        report = {'path': str(args.capture_out), 'sha256': H(command.encode()), 'bytes': len(command.encode()), 'source_pins': pins, 'executed': False}
    elif args.out:
        if not args.carrier or not args.baseline_summary: parser.error('--out requires carrier and baseline-summary')
        outputs, report = generate(args.carrier, json.loads(args.baseline_summary.read_bytes())); directory = args.out
        outputs['command-pins.json'] = json.dumps(report, sort_keys=True, indent=2)+'\n'
    else:
        if not args.command_pins or not args.transfer_id or not args.ciphertext_file: parser.error('--receive-out requires command-pins, transfer-id and ciphertext-file')
        receipt = json.loads(args.command_pins.read_bytes())
        core, baseline = identities()
        if receipt.get('baseline_sha256') != baseline.BASELINE_SHA or receipt.get('configuration_freeze_sha256') != core.CONFIG_FREEZE_SHA:
            raise RuntimeError('EXACT_REVIEWED_COMMAND_PINS_REQUIRED')
        path = args.ciphertext_file
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024: raise RuntimeError('BOUNDED_CIPHERTEXT_FILE_REQUIRED')
        command = entry_command(receipt['members'], 'receive', transfer_id=args.transfer_id, ciphertext=path.read_text().strip())
        outputs = {args.receive_out.name: command}; directory = args.receive_out.parent
        report = {'path': str(args.receive_out), 'sha256': H(command.encode()), 'bytes': len(command.encode()), 'executed': False, 'plaintext_credential_included': False}
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        fd = os.open(directory/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(value.encode()); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__': main()
