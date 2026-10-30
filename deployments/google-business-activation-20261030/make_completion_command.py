"""Small completion bootstrap: fixed frozen V3 carrier + reviewed tools carrier."""
import hashlib
import json
import re
from pathlib import Path
import make_carrier_command as frozen

ROOT = Path(__file__).resolve().parent
CARRIER = 'b37565afba522e26b2f5ded47d8aafc24237b028'
COMPLETION_SHA = '15d9eef573bbd72e8fb73507e4acbe476894d91e78c8b5ab34a45464812a3152'
COMPLETION_SIZE = 25042
H = lambda body: hashlib.sha256(body).hexdigest()


def verified_completion(carrier):
    frozen.need(isinstance(carrier, str) and bool(re.fullmatch('[a-f0-9]{40}', carrier)), 'FULL_COMPLETION_CARRIER_REQUIRED')
    frozen.need(frozen.git_output(['rev-parse', '--verify', carrier + '^{commit}']).decode().strip() == carrier, 'EXACT_COMPLETION_CARRIER_REQUIRED')
    blob = (ROOT / 'completion.py').read_bytes()
    frozen.need(len(blob) == COMPLETION_SIZE and H(blob) == COMPLETION_SHA, 'REVIEWED_COMPLETION_LOCAL_BYTES_DRIFT')
    for name in ('completion.py', 'make_completion_command.py'):
        committed = frozen.git_output(['show', carrier + ':' + frozen.DIRECTORY + '/' + name])
        frozen.need(committed == (ROOT / name).read_bytes(), 'IMMUTABLE_COMPLETION_TOOL_BYTES_DRIFT')
    return COMPLETION_SHA, COMPLETION_SIZE


def command(phase, completion_carrier):
    frozen.need(phase in {'audit', 'complete', 'rollback'}, 'EXACT_COMPLETION_PHASE_REQUIRED')
    members = frozen.verified_tools(CARRIER)
    downloaded = {name[:-3]: (CARRIER, *members[name]) for name in ('core.py', 'preflight.py', 'activation.py')}
    downloaded['completion'] = (completion_carrier, *verified_completion(completion_carrier))
    text = f'''#!/bin/bash
set -eu
sudo python3 -B - <<'GBP_EXISTING_CANDIDATE_COMPLETION_PINNED'
import hashlib,json,os,re,resource,socket,stat,sys,types,urllib.request
from pathlib import Path
sys.dont_write_bytecode=True
loaded={{}}
def need(ok,code):
 if not ok:raise RuntimeError(code)
try:
 need(os.geteuid()==0 and socket.gethostname()=={frozen.HOST!r},'EXACT_SERVER_ROOT_REQUIRED')
 os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
 root=Path({frozen.SERVER_ROOT!r})
 need(root.resolve()==root,'EXACT_RELEASE_PATH_REQUIRED')
 for parent in (root,*root.parents):
  row=parent.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
 need(stat.S_IMODE(root.lstat().st_mode)==0o700,'PROTECTED_RELEASE_ROOT_REQUIRED')
 phase={phase!r};members={downloaded!r}
 need(phase in ('audit','complete','rollback') and set(members)=={{'core','preflight','activation','completion'}},'EXACT_COMPLETION_PHASE_REQUIRED')
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):return None
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({{}}),NoRedirect())
 bodies={{}}
 for name,(carrier,expected,size) in members.items():
  need(name in ('core','preflight','activation','completion') and re.fullmatch('[a-f0-9]{{40}}',carrier) and re.fullmatch('[a-f0-9]{{64}}',expected) and type(size) is int and 1<=size<=65536,'EXACT_MEMBER_PIN_REQUIRED')
  url='https://raw.githubusercontent.com/billy285/t24-crm/'+carrier+'/{frozen.DIRECTORY}/'+name+'.py'
  with opener.open(url,timeout=20) as response:
   need(response.code==200 and response.geturl()==url,'IMMUTABLE_SOURCE_RESPONSE_REQUIRED');body=response.read(size+1)
  need(len(body)==size and hashlib.sha256(body).hexdigest()==expected,'IMMUTABLE_SOURCE_BYTES_DRIFT');bodies[name]=body
 for name,body in bodies.items():
  module=types.ModuleType(name);module.__file__='hash-pinned-completion/'+name+'.py';module.__tool_sha256__=members[name][1]
  sys.modules[name]=module;loaded[name]=module;exec(compile(body,module.__file__,'exec'),module.__dict__)
 result=loaded['completion'].dispatch(phase)
 print(json.dumps(result,sort_keys=True))
except BaseException as error:
 code=loaded['core'].safe_code(error) if 'core' in loaded else (str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z][A-Z0-9_]{{0,95}}',str(error)) else 'COMPLETION_BOOTSTRAP_REJECTED')
 print(json.dumps({{'stage':'GBP_COMPLETION_REJECTED','code':code}}));sys.exit(1)
GBP_EXISTING_CANDIDATE_COMPLETION_PINNED
'''
    frozen.need(len(text.encode()) < 8192, 'COMPLETION_WRAPPER_EXCEEDS_EIGHT_KIB')
    return text


if __name__ == '__main__':
    parser = frozen.SafeParser()
    parser.add_argument('--phase', choices=('audit', 'complete', 'rollback'), required=True)
    parser.add_argument('--carrier', required=True)
    parser.add_argument('--out', type=Path, required=True)
    try:
        args = parser.parse_args()
        blob = command(args.phase, args.carrier).encode()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(blob);args.out.chmod(0o600)
        print(json.dumps({'command_sha256': H(blob), 'command_bytes': len(blob), 'server_executed': False}))
    except BaseException as error:
        print(json.dumps({'stage': 'GBP_COMPLETION_PACKAGING_REJECTED', 'code': str(error) if isinstance(error, frozen.PackagingError) else 'PACKAGING_REJECTED'}))
        raise SystemExit(1)
