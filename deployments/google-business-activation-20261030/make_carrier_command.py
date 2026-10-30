"""Small immutable-carrier bootstrap; no changes to reviewed activation modules."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIRECTORY = 'deployments/google-business-activation-20261030'
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SERVER_ROOT = '/opt/t24-crm/releases/google-business-activation-7431d1986b81-20261030'
PHASES = {'plan': 'plan-nginx', 'protect': 'protect-callback', 'enable': 'enable', 'rollback': 'rollback'}
PINS = {
    'core.py': ('903081856fbdb042b9af74295cbebd6745b57e019e7039a7fce26c23bddde107', 7521),
    'preflight.py': ('df6a02ab394c10ab81f4f6c2a6c153a370cfa91648961ccaf9392c8f9df02b8d', 5873),
    'activation.py': ('7adb2fee1ca255c6b91827cefe72cbbbd023c59dc24ff573d2526055a92edc70', 37538),
    'make_commands.py': ('70dae35f8c7afbf5ede695b02983c139423685d7ac2447a074e70c98be30cd31', 5956),
}
H = lambda body: hashlib.sha256(body).hexdigest()


class PackagingError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise PackagingError('ARGUMENTS_REJECTED')


def need(ok, code):
    if not ok:
        raise PackagingError(code)


def strict_json(blob):
    def pairs(rows):
        result = {}
        for name, value in rows:
            need(name not in result, 'DUPLICATE_PUBLIC_ARGUMENT_FIELD')
            result[name] = value
        return result
    return json.loads(blob, object_pairs_hook=pairs)


def git_output(arguments):
    result = subprocess.run(['git', '-C', str(ROOT), *arguments], capture_output=True,
        env={**os.environ, 'GIT_NO_REPLACE_OBJECTS': '1'})
    need(result.returncode == 0, 'LOCAL_IMMUTABLE_CARRIER_LOOKUP_FAILED')
    return result.stdout


def verified_tools(carrier):
    need(isinstance(carrier, str) and bool(re.fullmatch('[a-f0-9]{40}', carrier)), 'FULL_IMMUTABLE_CARRIER_REQUIRED')
    need(set(PINS) == {'core.py', 'preflight.py', 'activation.py', 'make_commands.py'}, 'EXACT_LOCAL_MEMBER_SET_REQUIRED')
    need(git_output(['rev-parse', '--verify', carrier + '^{commit}']).decode().strip() == carrier, 'EXACT_CARRIER_COMMIT_REQUIRED')
    members = {}
    for name, (digest, size) in PINS.items():
        local = (ROOT / name).read_bytes()
        need(len(local) == size and H(local) == digest, 'REVIEWED_LOCAL_TOOL_BYTES_DRIFT')
        committed = git_output(['show', carrier + ':' + DIRECTORY + '/' + name])
        need(committed == local, 'IMMUTABLE_CARRIER_TOOL_BYTES_DRIFT')
        members[name] = (digest, size)
    own_name = Path(__file__).name
    need(own_name == 'make_carrier_command.py', 'EXACT_GENERATOR_NAME_REQUIRED')
    need(git_output(['show', carrier + ':' + DIRECTORY + '/' + own_name]) == (ROOT / own_name).read_bytes(), 'IMMUTABLE_GENERATOR_BYTES_DRIFT')
    return members


def public_arguments(phase, value):
    need(phase in PHASES and isinstance(value, dict), 'PUBLIC_PHASE_AND_OBJECT_REQUIRED')
    if phase == 'plan':
        need(not value, 'PLAN_ACCEPTS_NO_ARGUMENTS')
        return
    path = ROOT / 'make_commands.py'
    body = path.read_bytes()
    need(H(body) == PINS[path.name][0], 'REVIEWED_PUBLIC_VALIDATOR_DRIFT')
    spec = importlib.util.spec_from_file_location('_reviewed_carrier_public_validator', path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    try:
        validator.validate_review_arguments(PHASES[phase], value)
    except (ValueError, TypeError, KeyError):
        raise PackagingError('EXACT_PUBLIC_REVIEW_ARGUMENTS_REQUIRED') from None
    expected = {name: PINS[name][0] for name in ('core.py', 'preflight.py', 'activation.py')}
    need(value['review']['tool_sha256'] == expected, 'PUBLIC_REVIEW_TOOL_HASH_DRIFT')


def command(carrier, phase, arguments):
    members = verified_tools(carrier)
    public_arguments(phase, arguments)
    downloaded = {name[:-3]: members[name] for name in ('core.py', 'preflight.py', 'activation.py')}
    text = f'''#!/bin/bash
set -eu
sudo python3 -B - <<'GBP_IMMUTABLE_CARRIER_BOOTSTRAP'
import hashlib,json,os,re,resource,socket,stat,sys,types,urllib.request
from pathlib import Path
sys.dont_write_bytecode=True
loaded={{}}
def need(ok,code):
 if not ok:raise RuntimeError(code)
try:
 need(os.geteuid()==0 and socket.gethostname()=={HOST!r},'EXACT_SERVER_ROOT_REQUIRED')
 os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 root=Path({SERVER_ROOT!r})
 need(root.resolve()==root,'EXACT_RELEASE_PATH_REQUIRED')
 for parent in root.parents:
  row=parent.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
 if root.exists() or root.is_symlink():
  row=root.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'PROTECTED_RELEASE_ROOT_REQUIRED')
 carrier={carrier!r};phase={PHASES[phase]!r};arguments={arguments!r};members={downloaded!r}
 need(re.fullmatch('[a-f0-9]{{40}}',carrier) and phase in ('plan-nginx','protect-callback','enable','rollback'),'EXACT_CARRIER_PHASE_REQUIRED')
 need(set(members)=={{'core','preflight','activation'}},'EXACT_THREE_MEMBERS_REQUIRED')
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):return None
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
 bodies={{}}
 for name,(expected,size) in members.items():
  need(name in ('core','preflight','activation') and re.fullmatch('[a-f0-9]{{64}}',expected) and type(size) is int and 1<=size<=65536,'EXACT_MEMBER_PIN_REQUIRED')
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{DIRECTORY}/'+name+'.py'
  with opener.open(url,timeout=20) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and hashlib.sha256(body).hexdigest()==expected,'IMMUTABLE_SOURCE_BYTES_DRIFT');bodies[name]=body
 for name,body in bodies.items():
  module=types.ModuleType(name);module.__file__='immutable-carrier/'+carrier+'/'+name+'.py';module.__tool_sha256__=members[name][0]
  sys.modules[name]=module;loaded[name]=module;exec(compile(body,module.__file__,'exec'),module.__dict__)
 result=loaded['activation'].dispatch(phase,arguments)
 print(json.dumps(result,sort_keys=True))
except BaseException as error:
 code=loaded['core'].safe_code(error) if 'core' in loaded else (str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',str(error)) else 'CARRIER_BOOTSTRAP_REJECTED')
 print(json.dumps({{'stage':'GBP_CARRIER_BOOTSTRAP_REJECTED','code':code}}));sys.exit(1)
GBP_IMMUTABLE_CARRIER_BOOTSTRAP
'''
    need(len(text.encode()) < 8192, 'WRAPPER_EXCEEDS_EIGHT_KIB')
    return text


def main():
    parser = SafeParser()
    parser.add_argument('--carrier', required=True)
    parser.add_argument('--phase', choices=sorted(PHASES), required=True)
    parser.add_argument('--public-arguments', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    value = strict_json(args.public_arguments.read_bytes()) if args.public_arguments else {}
    text = command(args.carrier, args.phase, value)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    args.out.chmod(0o600)
    print(json.dumps({'command_created': True, 'phase': args.phase, 'carrier': args.carrier,
        'command_bytes': len(text.encode()), 'command_sha256': H(text.encode()), 'server_executed': False}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print(json.dumps({'stage': 'CARRIER_COMMAND_GENERATION_REJECTED', 'code': 'PUBLIC_PINS_OR_ARGUMENTS_REJECTED'}))
        raise SystemExit(1)
