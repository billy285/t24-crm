"""Local, read-only checklist for this exact reviewed package and prepared receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCE = '2f3a5b7b086d996e5fc04eca265d3cdb103a89ba'
VERSION = '2908954fe44e'
BEFORE = '22a72649f369f57bdc44a8c33b1e837396dc1e79'
BASELINE = '2e31d362a00c46fe05495d39008deb8c4ab5742da8c68adf2b5720ec8e615cb0'
MANIFEST = '877965eb9836e58c4aab28769c225c5b9525fdb4440ec5370534dea8761ab00c'
PAYLOAD = 'dece1eeec332b796e9a61c922261a4b5428372efac8dcc435471457563294913'
ALLOWLIST = '0a27ea1436d6259c040b37b1daf4266d6e5caedf99be40f595e29b3f08798bf9'


def need(value, reason):
    if not value:
        raise RuntimeError(reason)


def checked(path, sha=None):
    need(path.is_file() and not path.is_symlink(), 'LOCAL_FILE_REQUIRED:' + path.name)
    body = path.read_bytes()
    need(sha is None or hashlib.sha256(body).hexdigest() == sha, 'HASH_MISMATCH:' + path.name)
    return body


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def main(args):
    need(bool(re.fullmatch('[a-f0-9]{40}', args.carrier)), 'EXACT_CARRIER_REQUIRED')
    need(bool(re.fullmatch('[a-f0-9]{64}', args.receipt_sha256)), 'EXACT_RECEIPT_SHA_REQUIRED')
    manifest = json.loads(checked(ROOT / 'artifacts/manifest.json', MANIFEST))
    baseline = json.loads(checked(ROOT / 'artifacts/baseline.json', BASELINE))
    allowed = json.loads(checked(ROOT / 'artifacts/source-allowlist.json', ALLOWLIST))
    checked(ROOT / 'artifacts/payload.tar.gz', PAYLOAD)
    need(manifest['source_sha'] == SOURCE and manifest['frontend_version'] == VERSION, 'SOURCE_OR_FE_DRIFT')
    need(manifest['baseline_source_sha'] == BEFORE and manifest['previous_frontend_version'] == baseline['frontend_version'] == '2f1166b5ff64', 'BEFORE_BINDING_DRIFT')
    need(set(allowed) == set(manifest['changed_source_files']), 'EXACT_ALLOWLIST_DRIFT')
    for key in ('private_source_changes', 'authorization_logic_changes', 'backend_changes', 'database_changes', 'service_changes', 'credentials_included'):
        need(manifest[key] is False, 'FORBIDDEN_SCOPE:' + key)
    for key in ('unchanged', 'mutation_calls_unchanged', 'original_api_requests_unchanged', 'authorization_gates_unchanged', 'private_and_ordinary_dialog_unchanged'):
        need(manifest['protected_behavior'][key] is True, 'BEHAVIOR_GUARD:' + key)
    pins = json.loads(checked(args.pins))
    need(pins['carrier'] == args.carrier and pins['source_sha'] == SOURCE and pins['frontend_version'] == VERSION, 'COMMAND_PINS_DRIFT')
    need(git('rev-parse', args.carrier + ':app') == git('rev-parse', SOURCE + ':app'), 'CARRIER_APP_DIFFERS')
    members = {'baseline.py': 'baseline.py', 'static_release.py': 'static_release.py', 'baseline.json': 'artifacts/baseline.json',
               'source-allowlist.json': 'artifacts/source-allowlist.json', 'manifest.json': 'artifacts/manifest.json', 'payload.tar.gz': 'artifacts/payload.tar.gz'}
    need(set(pins['files']) == set(members), 'EXACT_SIX_DOWNLOAD_MEMBERS_REQUIRED')
    for target, relative in members.items():
        body = checked(ROOT / relative)
        pin = pins['files'][target]
        repo_relative = (ROOT / relative).relative_to(REPO).as_posix()
        expected_url = 'https://raw.githubusercontent.com/billy285/t24-crm/' + args.carrier + '/' + repo_relative
        need(pin['url'] == expected_url and pin['bytes'] == len(body) and pin['sha256'] == hashlib.sha256(body).hexdigest(), 'DOWNLOAD_PIN_DRIFT:' + target)
        need(git('show', args.carrier + ':' + repo_relative) == body, 'CARRIER_MEMBER_DRIFT:' + target)
    receipt = json.loads(checked(args.prepared, args.receipt_sha256))
    expected = {'stage': 'CRM_UI_FOCUS_STATIC_PREPARED', 'source_sha': SOURCE, 'frontend_version': VERSION,
                'baseline_sha256': BASELINE, 'source_allowlist_sha256': ALLOWLIST, 'manifest_sha256': MANIFEST, 'payload_sha256': PAYLOAD,
                'public_root': '/var/www/t24-crm-public/crm-ui-focus-' + SOURCE[:12] + '-20261026',
                'runtime_and_schema_identity_unchanged': True, 'old_assets_preserved': True,
                'database_mutations': False, 'services_modified': False, 'provider_requests': False}
    need(all(receipt[key] == value for key, value in expected.items()), 'PREPARED_SCOPE_OR_PIN_DRIFT')
    need(all(bool(re.fullmatch('[a-f0-9]{64}', receipt.get(key, ''))) for key in ('nginx_next_sha256', 'public_inventory_sha256')), 'PREPARED_STATIC_HASHES_INVALID')
    print(json.dumps({'independent_local_prepared_review': 'passed', 'source_sha': SOURCE, 'frontend_version': VERSION,
                      'carrier': args.carrier, 'prepared_sha256': args.receipt_sha256, 'six_carrier_members_verified': True,
                      'production_contacted': False, 'files_modified': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--carrier', required=True)
    parser.add_argument('--pins', type=Path, default=ROOT / 'commands/pins.json')
    main(parser.parse_args())
