"""Generate hash-bound commands locally; never executes a server operation."""
import argparse
import base64
import hashlib
import json
import re
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()
PHASES = {'preflight', 'diagnostics', 'transport-init', 'transport-install', 'plan-nginx', 'protect-callback', 'enable', 'rollback'}
REVIEW_FLAGS = {'independent_security_review_passed', 'approved_dedicated_client_project',
    'existing_consent_screen_and_clients_preserved', 'external_callback_logs_checked',
    'allow_exact_callback_logging_change', 'allow_exact_six_environment_additions'}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('ARGUMENTS_REJECTED')


def validate_review_arguments(phase, value):
    expected = {'plan_sha256', 'review', 'review_sha256'} | ({'logging_receipt_sha256'} if phase in {'enable', 'rollback'} else set())
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('EXACT_REVIEW_ARGUMENTS_REQUIRED')
    if any(not isinstance(value[name], str) or not re.fullmatch('[a-f0-9]{64}', value[name]) for name in expected - {'review'}):
        raise ValueError('PUBLIC_HASH_FIELDS_REQUIRED')
    review = value['review']
    fields = REVIEW_FLAGS | {'stage', 'plan_sha256', 'project_id', 'callback', 'scope', 'tool_sha256', 'business_writes', 'provider_writes'}
    if not isinstance(review, dict) or set(review) != fields or not all(review[name] is True for name in REVIEW_FLAGS):
        raise ValueError('EXACT_PUBLIC_REVIEW_FIELDS_REQUIRED')
    if review['stage'] != 'GBP_ACTIVATION_MANUAL_REVIEW_APPROVED' or review['plan_sha256'] != value['plan_sha256'] or review['project_id'] != 't24-beauty-os-20260823' or review['callback'] != 'https://t24-crm.com/api/v1/google-business/oauth/callback' or review['scope'] != 'https://www.googleapis.com/auth/business.manage' or review['business_writes'] is not False or review['provider_writes'] is not False:
        raise ValueError('REVIEW_PUBLIC_SCOPE_REJECTED')
    if not isinstance(review['tool_sha256'], dict) or set(review['tool_sha256']) != {'core.py', 'preflight.py', 'activation.py'} or any(not isinstance(row, str) or not re.fullmatch('[a-f0-9]{64}', row) for row in review['tool_sha256'].values()):
        raise ValueError('EXACT_TOOL_HASH_FIELDS_REQUIRED')
    if H((json.dumps(review, sort_keys=True, indent=2) + '\n').encode()) != value['review_sha256']:
        raise ValueError('REVIEW_HASH_DRIFT')


def command(phase, arguments):
    if phase not in PHASES:
        raise ValueError('PHASE_REJECTED')
    if not isinstance(arguments, dict):
        raise ValueError('PUBLIC_ARGUMENTS_OBJECT_REQUIRED')
    if phase in {'protect-callback', 'enable', 'rollback'}:
        validate_review_arguments(phase, arguments)
    if phase == 'plan-nginx' and arguments:
        raise ValueError('NO_PLAN_ARGUMENTS_ALLOWED')
    modules = ['core', 'diagnostics'] if phase == 'diagnostics' else ['core', 'preflight']
    if phase.startswith('transport-'):
        modules.append('transport')
    if phase in {'plan-nginx', 'protect-callback', 'enable', 'rollback'}:
        modules.append('activation')
    members = {}
    for name in modules:
        blob = (ROOT / (name + '.py')).read_bytes()
        members[name] = {'sha256': H(blob), 'body': base64.b64encode(zlib.compress(blob, 9)).decode()}
    if phase == 'diagnostics':
        target = "loaded['diagnostics'].main()"
    elif phase == 'preflight':
        target = "loaded['preflight'].main()"
    elif phase == 'transport-init':
        target = "print(json.dumps(loaded['transport'].prepare(),sort_keys=True))"
    elif phase == 'transport-install':
        if set(arguments) != {'transfer_id', 'ciphertext'} or not re.fullmatch('[a-f0-9]{32}', arguments['transfer_id']) or not re.fullmatch('[A-Za-z0-9+/]{512}', arguments['ciphertext']):
            raise ValueError('ONLY_TRANSPORT_ID_AND_RSA_CIPHERTEXT_ALLOWED')
        target = "print(json.dumps(loaded['transport'].receive(**arguments),sort_keys=True))"
    else:
        target = "print(json.dumps(loaded['activation'].dispatch(phase,arguments),sort_keys=True))"
    if phase in {'preflight', 'diagnostics', 'transport-init'} and arguments:
        raise ValueError('NO_ARGUMENTS_ALLOWED')
    return f'''#!/bin/bash
set -eu
sudo python3 -B - <<'GBP_ACTIVATION_HASH_PINNED'
import base64,hashlib,json,re,sys,types,zlib
sys.dont_write_bytecode=True
members={members!r}
arguments={arguments!r}
phase={phase!r}
loaded={{}}
try:
 for name,member in members.items():
  blob=zlib.decompress(base64.b64decode(member['body']))
  if hashlib.sha256(blob).hexdigest()!=member['sha256']:raise RuntimeError('TOOL_MEMBER_HASH_DRIFT')
  module=types.ModuleType(name);module.__file__='hash-pinned-gbp-activation/'+name+'.py';module.__tool_sha256__=member['sha256']
  sys.modules[name]=module;loaded[name]=module
  exec(compile(blob,module.__file__,'exec'),module.__dict__)
 loaded['core'].server_guard()
 {target}
except BaseException as error:
 code=loaded['core'].safe_code(error) if 'core' in loaded else 'PINNED_TOOL_REJECTED'
 print(json.dumps({{'stage':'GBP_ACTIVATION_REJECTED','phase':phase,'code':code}}));sys.exit(1)
GBP_ACTIVATION_HASH_PINNED
'''


def main():
    parser = SafeParser()
    parser.add_argument('--phase', choices=sorted(PHASES), required=True)
    parser.add_argument('--arguments', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.arguments.read_bytes()) if args.arguments else {}
    text = command(args.phase, value)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    args.out.chmod(0o600)
    print(json.dumps({'command_created': True, 'phase': args.phase, 'command_sha256': H(text.encode()), 'server_executed': False}))


if __name__ == '__main__':
    main()
