#!/usr/bin/env python3
"""Read-only server checks and protected evidence around the owner UI review.

Prepared locally; do not execute until the final successful upgrade is reviewed.
Supply independently observed SHA-256 pins for upgrade.py, acquired.json,
prepared-backend/candidate.json and upgrade-state.json. Run phase=before first;
retain its printed baseline_sha256, then supply that pin to phase=after using the
same verification_id. No valid login, credential, customer value or response body
is printed or written. Only new evidence files under the fixed release are made.

This is specific to the c1ae Stripe report release and frontend 913856b4d17b.
It never invokes upgrade.apply, stops/starts a service, restores a database,
changes the environment or Nginx, or calls a payment/provider operation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys


HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
VERSION = '913856b4d17b'
RELEASE = Path('/opt/t24-crm/releases/stripe-report-c1ae19b38fec-20261012')
PUBLIC = Path('/var/www/t24-crm-public/stripe-report-c1ae19b38fec-20261012')
HASH = re.compile('[a-f0-9]{64}')


class VerificationError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise VerificationError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def stamp(info):
    # atime can change on a read; mutation and identity fields remain pinned.
    return tuple(getattr(info, name) for name in (
        'st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink',
        'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def bootstrap_read(path, expected):
    """Check the helper itself before importing any release code."""
    need(HASH.fullmatch(expected or ''), 'FULL_HELPER_HASH_REQUIRED')
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_HELPER_REQUIRED')
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
             'PROTECTED_HELPER_ANCESTOR_REQUIRED')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
         and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= 1024**2,
         'ROOT_PROTECTED_HELPER_REQUIRED')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        need(stamp(os.fstat(stream.fileno())) == stamp(before), 'HELPER_IDENTITY_CHANGED')
        blob = stream.read(1024**2 + 1)
    need(len(blob) <= 1024**2 and stamp(path.lstat()) == stamp(before)
         and sha(blob) == expected, 'REVIEWED_HELPER_BYTES_REQUIRED')
    return blob


def load_upgrade(expected):
    path = RELEASE / 'upgrade.py'
    blob = bootstrap_read(path, expected)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_loader('_stripe_postdeploy_reviewed_upgrade', loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    # Execute only the already hash-checked bytes; no import-path race.
    exec(compile(blob, str(path), 'exec'), module.__dict__)
    need(module.HOST == HOST and module.SOURCE == SOURCE and module.RELEASE == RELEASE,
         'EXACT_RELEASE_HELPER_REQUIRED')
    return module


def read_json(upgrade, path):
    value = json.loads(upgrade.read_protected(path))
    need(isinstance(value, dict), 'OBJECT_EVIDENCE_REQUIRED')
    return value


def stable_digests(upgrade, switch, path):
    value = switch.stable_records(path)
    # Retained APIs return record digests keyed by IDs. Hash those keys as well.
    for key in ('items', 'preferences', 'connections', 'other_connections'):
        value[key] = {upgrade.digest(identity): fingerprint
                      for identity, fingerprint in value[key].items()}
    return value


def save_new(upgrade, path, value):
    upgrade.protected(path.parent, True)
    blob = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    upgrade.protected(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha(blob)


AUTH_PROBE = r'''import json,urllib.request,urllib.error
from services.emp_auth import create_access_token
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
cases=[('anonymous',None),
 ('owner_without_persistent_session',create_access_token({'emp_id':4,'role':'super_admin','sid':'stripe-release-invalid-session'})),
 ('non_owner_role_claim',create_access_token({'emp_id':1,'role':'super_admin','sid':'stripe-release-invalid-session'}))]
result=[]
for label,token in cases:
 headers={'Content-Type':'application/json'}
 if token: headers['Authorization']='Bearer '+token
 request=urllib.request.Request('http://127.0.0.1:8001/api/v1/private-workspace/stripe/report',data=b'{"period":"month"}',headers=headers,method='POST')
 try: response=opener.open(request,timeout=5)
 except urllib.error.HTTPError as error: response=error
 with response:
  body=response.read(65537)
  assert len(body)<=65536 and response.code in (401,403)
  assert 'no-store' in {part.strip().lower() for part in response.headers.get('Cache-Control','').split(',')}
  result.append({'case':label,'status':response.code,'no_store':True})
print(json.dumps({'stage':'STRIPE_REPORT_RUNTIME_AUTH_REJECTION_VERIFIED','checks':result,'writes':False},sort_keys=True))
'''


def auth_probe(upgrade, base, switch, receipt, profiles):
    row = receipt['roles']['api']
    upgrade.own_role(base, switch, row['id'], 'api', row['image'], row['attempt'],
                     row['source'], profiles['api'], True)
    # Tokens are created only in this exact verified container. Its captured
    # output is strictly validated and never forwarded as raw stdout/stderr.
    blob = switch.docker(['exec', '--workdir', '/app/backend', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                          row['id'], 'python', '-B', '-c', AUTH_PROBE], timeout=25)
    need(len(blob) <= 4096, 'BOUNDED_AUTH_PROBE_EVIDENCE_REQUIRED')
    value = json.loads(blob)
    need(set(value) == {'stage', 'checks', 'writes'}
         and value['stage'] == 'STRIPE_REPORT_RUNTIME_AUTH_REJECTION_VERIFIED'
         and value['writes'] is False and isinstance(value['checks'], list)
         and [item.get('case') for item in value['checks']] == [
             'anonymous', 'owner_without_persistent_session', 'non_owner_role_claim']
         and all(set(item) == {'case', 'status', 'no_store'} and item['status'] in (401, 403)
                 and item['no_store'] is True for item in value['checks']),
         'AUTH_REJECTION_PROOF_REQUIRED')
    return value


def current_roles(upgrade, base, switch, receipt):
    need(set(receipt.get('roles', {})) == {'api', 'worker'}, 'EXACT_FINAL_ROLES_REQUIRED')
    profiles, proofs = {}, {}
    for role in ('api', 'worker'):
        row = receipt['roles'][role]
        need(HASH.fullmatch(row.get('id', '')) and row.get('image') == receipt['candidate_image']
             and row.get('source') == SOURCE and row.get('attempt') == receipt['attempt'],
             'FINAL_ROLE_RECEIPT_BINDING_REQUIRED')
        info = base.inspect('t24-private-' + role)
        need(info['Id'] == row['id'] and info['Name'] == '/t24-private-' + role,
             'CANONICAL_FINAL_ROLE_ID_REQUIRED')
        values = switch.environment(info)
        need(upgrade.read_protected(RELEASE / 'live-upgrade' / (role + '-runtime.env'))
             == switch.profile_bytes(values), 'FINAL_ROLE_PROFILE_BYTES_DRIFT')
        proof = upgrade.own_role(base, switch, row['id'], role, row['image'], row['attempt'],
                                 row['source'], values, True)
        need(proof == row.get('runtime'), 'FINAL_ROLE_RUNTIME_RECEIPT_DRIFT')
        need(not base.inspect(receipt['old_ids'][role])['State']['Running'],
             'RETAINED_OLD_PRIVATE_ROLE_RUNNING')
        if role == 'api':
            need(info['State'].get('Health', {}).get('Status') == 'healthy', 'FINAL_API_HEALTH_REQUIRED')
        profiles[role], proofs[role] = values, proof
    upgrade.no_writers(base, switch, [receipt['roles'][role]['id'] for role in ('api', 'worker')])
    return profiles, proofs


def runtime_bytes(upgrade, switch, preparation, candidate, receipt):
    expected = candidate['byte_identity']
    for role in ('api', 'worker'):
        identity = receipt['roles'][role]['id']
        for code, field in ((preparation.SCAN_BACKEND, 'candidate_backend_sha256'),
                            (preparation.SCAN_STATIC, 'bundled_static_sha256')):
            value = json.loads(switch.docker(['exec', identity, 'python', '-B', '-c', code], timeout=45))
            need(isinstance(value, dict) and upgrade.digest(value) == expected[field],
                 'RUNNING_BACKEND_OR_BUNDLED_STATIC_BYTES_DRIFT')
        packages = json.loads(switch.docker(
            ['exec', identity, 'python', '-B', '-c', preparation.SCAN_PACKAGES], timeout=45))
        need(packages == expected['runtime_packages'], 'RUNNING_RUNTIME_PACKAGE_BYTES_DRIFT')
        runtime = json.loads(switch.docker(
            ['exec', identity, 'python', '-B', '-c', preparation.SCAN_RUNTIME], timeout=15))
        preparation.checked_base_runtime(runtime)


def expected_public(upgrade, base, static):
    # Match the retained install_public recipe: only old assets are retained.
    desired = dict(base.file_map(static))
    for name, fingerprint in base.file_map(upgrade.OLD_PUBLIC).items():
        if name.startswith('assets/'):
            need(name not in desired or desired[name] == fingerprint, 'HASHED_ASSET_COLLISION')
            desired.setdefault(name, fingerprint)
    need(read_json(upgrade, RELEASE / 'public-manifest.json') == desired
         and base.file_map(PUBLIC) == desired, 'PUBLISHED_COMPATIBLE_PUBLIC_BYTES_DRIFT')
    return desired


def checked_release(upgrade, base, nav, preparation, switch, args):
    acquired = upgrade.fixed_json(RELEASE / 'acquired.json', args.acquired_sha256)
    candidate = upgrade.fixed_json(RELEASE / 'prepared-backend/candidate.json', args.candidate_sha256)
    receipt = upgrade.fixed_json(RELEASE / 'upgrade-state.json', args.receipt_sha256)
    manifest = upgrade.fixed_json(RELEASE / 'stripe-report-manifest.json', candidate['payload_manifest_sha256'])
    frozen = upgrade.fixed_json(RELEASE / 'frozen-source.json', candidate['frozen_source_sha256'])
    need(acquired['files'].get('upgrade.py') == args.upgrade_helper_sha256
         and acquired['files'].get('stripe-report-manifest.json') == candidate['payload_manifest_sha256']
         and acquired['files'].get('frozen-source.json') == candidate['frozen_source_sha256']
         and acquired['files'].get('stripe-report-payload.tar.gz') == candidate['payload_sha256'],
         'ACQUIRED_CANDIDATE_BINDINGS_REQUIRED')
    need(manifest.get('frozen_manifest_sha256') == candidate['frozen_source_sha256']
         and manifest.get('frontend_version') == VERSION
         and sha(upgrade.read_protected(RELEASE / 'stripe-report-payload.tar.gz', 64 * 1024**2))
         == candidate['payload_sha256'], 'EXACT_FROZEN_PAYLOAD_REQUIRED')
    preparation.checked_payload(manifest, frozen, candidate['payload_sha256'])
    upgrade.checked_candidate(candidate, manifest)
    upgrade.checked_images(switch, candidate)
    need(receipt.get('format_version') == 1 and receipt.get('phase') == 'STRIPE_REPORT_PUBLIC_RELEASE_VERIFIED'
         and receipt.get('deployed') is True and receipt.get('public_assets_published') is True
         and receipt.get('source_sha') == SOURCE and receipt.get('frontend_version') == VERSION
         and receipt.get('candidate_image') == candidate['image_id']
         and receipt.get('rollback_image') == candidate['rollback_image_id']
         and receipt.get('candidate_content_sha256') == upgrade.digest(candidate)
         and receipt.get('payload_manifest_sha256') == candidate['payload_manifest_sha256']
         and receipt.get('frozen_source_sha256') == candidate['frozen_source_sha256']
         and receipt.get('public_root') == str(PUBLIC)
         and receipt.get('business_tables_verified') == 83 and receipt.get('private_tables_verified') == 11
         and all(receipt.get(key) is True for key in ('same_private_inode',
                 'credentials_and_generation_preserved', 'private_reports_require_owner'))
         and all(receipt.get(key) is False for key in ('bank_enabled', 'ai_enabled',
                 'credential_seed_attempted', 'databases_restored'))
         and 'failure_code' not in receipt and 'rollback_attempt' not in receipt,
         'SUCCESSFUL_FINAL_RELEASE_REQUIRED')
    before = read_json(upgrade, RELEASE / 'live-upgrade/schema-before.json')
    after = read_json(upgrade, RELEASE / 'live-upgrade/schema-after.json')
    proof = read_json(upgrade, RELEASE / 'live-upgrade/schema-validation.json')
    need(upgrade.digest(proof) == receipt.get('schema_validation_sha256')
         and upgrade.digest(before) == proof.get('before_sha256')
         and upgrade.digest(after) == proof.get('after_sha256')
         and before['private']['identity'] == after['private']['identity'] == receipt['private_identity']
         and before['private']['schema_objects'] == receipt['old_schema_objects']
         and before['business']['schema_sha256'] == receipt['business_schema_sha256'],
         'PINNED_LIVE_SCHEMA_PROOF_CHAIN_REQUIRED')
    need(preparation.compare_schema_snapshots(before, after, receipt['target_schema_objects'],
         source_sha=SOURCE, mode='in_place') == proof, 'EXACT_LIVE_SCHEMA_VALIDATION_REQUIRED')
    static = upgrade.checked_payload(RELEASE / 'prepared-backend/payload', manifest, base)
    base.RELEASE, base.PUBLIC, base.OLD_PUBLIC = RELEASE, PUBLIC, upgrade.OLD_PUBLIC
    public = expected_public(upgrade, base, static)
    need(sha(base.read_nginx()) == receipt['new_nginx_sha256'], 'CURRENT_PUBLIC_NGINX_DRIFT')
    upgrade.assert_runtime_boundary(base, receipt['baseline_runtime'])
    snapshot = upgrade.assert_schema(base, preparation, receipt['target_schema_objects'], after, exact_rows=False)
    need(set(snapshot['private']['tables']) == upgrade.TEN_TABLES | {'private_stripe_reports'},
         'EXACT_ELEVEN_PRIVATE_TABLES_REQUIRED')
    nav.disabled_live_features(base)
    profiles, roles = current_roles(upgrade, base, switch, receipt)
    return candidate, receipt, manifest, after, profiles, roles, public


def main(args):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == HOST,
         'EXPLICIT_VERIFIED_RELEASE_HOST_REQUIRED')
    need(re.fullmatch('[a-z0-9][a-z0-9-]{0,31}', args.verification_id), 'SAFE_VERIFICATION_ID_REQUIRED')
    pins = {name: getattr(args, name) for name in ('upgrade_helper_sha256', 'acquired_sha256',
                                                 'candidate_sha256', 'receipt_sha256')}
    need(all(HASH.fullmatch(value or '') for value in pins.values()), 'INDEPENDENT_FINAL_HASH_PINS_REQUIRED')
    need((args.phase == 'before' and args.baseline_sha256 is None)
         or (args.phase == 'after' and HASH.fullmatch(args.baseline_sha256 or '')),
         'PHASE_BASELINE_PIN_REQUIRED')
    upgrade = load_upgrade(args.upgrade_helper_sha256)
    upgrade.protected(RELEASE, True)
    # Independently pin acquisition before retained_tools follows its bindings.
    upgrade.fixed_json(RELEASE / 'acquired.json', args.acquired_sha256)
    base, nav, preparation, switch = upgrade.retained_tools(RELEASE)
    folder = RELEASE / ('postdeploy-verification-' + args.verification_id)
    baseline_path = folder / 'owner-ui-baseline.json'
    # A successful upgrade has already made this lock. Do not create a new one.
    upgrade.protected(base.CONFIG / 'private-finance-release.lock')
    with upgrade.release_lock(base):
        candidate, receipt, manifest, schema_after, profiles, roles, public = checked_release(
            upgrade, base, nav, preparation, switch, args)
        if args.phase == 'before':
            need(not folder.exists() and not folder.is_symlink(), 'NEW_VERIFICATION_DIRECTORY_REQUIRED')
            baseline = None
        else:
            upgrade.protected(folder, True)
            baseline = upgrade.fixed_json(baseline_path, args.baseline_sha256)
            need(baseline.get('stage') == 'STRIPE_REPORT_OWNER_UI_BASELINE'
                 and baseline.get('source_sha') == SOURCE and baseline.get('frontend_version') == VERSION
                 and baseline.get('pins') == pins and baseline.get('roles') == roles
                 and baseline.get('schema_after_sha256') == upgrade.digest(schema_after),
                 'SAME_PRE_UI_RELEASE_BASELINE_REQUIRED')
        authorization = upgrade.stable_authorization(base)
        stable = stable_digests(upgrade, switch, base.PRIVATE_DB)
        runtime_bytes(upgrade, switch, preparation, candidate, receipt)
        base.public_check(public, VERSION, PUBLIC)
        upgrade.report_auth_check(True)
        authentication = auth_probe(upgrade, base, switch, receipt, profiles)
        # Repeat decisive boundaries after all probes; private cache/provider rows
        # may change, but local notes/actions, preferences and auth may not.
        upgrade.assert_schema(base, preparation, receipt['target_schema_objects'], schema_after, exact_rows=False)
        upgrade.assert_runtime_boundary(base, receipt['baseline_runtime'])
        nav.disabled_live_features(base)
        _, final_roles = current_roles(upgrade, base, switch, receipt)
        need(final_roles == roles and upgrade.stable_authorization(base) == authorization,
             'AUTHORIZATION_OR_RUNTIME_CHANGED_DURING_VERIFICATION')
        final_stable = stable_digests(upgrade, switch, base.PRIVATE_DB)
        switch.preserved(stable, final_stable)
        need(sha(base.read_nginx()) == receipt['new_nginx_sha256']
             and expected_public(upgrade, base, RELEASE / 'prepared-backend/payload/frontend/dist') == public,
             'FINAL_PUBLIC_BOUNDARY_DRIFT')
        upgrade.fixed_json(RELEASE / 'upgrade-state.json', args.receipt_sha256)
        upgrade.fixed_json(RELEASE / 'acquired.json', args.acquired_sha256)
        if baseline is not None:
            switch.preserved(baseline['stable_records'], final_stable)
            need(baseline['stable_authorization'] == authorization, 'OWNER_UI_AUTHORIZATION_CHANGED')
        else:
            folder.mkdir(mode=0o700)
            upgrade.protected(folder, True)
        auth_path = folder / (args.phase + '-auth-rejections.json')
        auth_sha = save_new(upgrade, auth_path, authentication)
        evidence = {'format_version': 1, 'stage': 'STRIPE_REPORT_OWNER_UI_' + args.phase.upper() + '_VERIFIED',
                    'source_sha': SOURCE, 'frontend_version': VERSION, 'pins': pins, 'roles': roles,
                    'schema_after_sha256': upgrade.digest(schema_after), 'business_tables_verified': 83,
                    'private_tables_verified': 11, 'same_private_inode': True,
                    'stable_authorization': authorization, 'stable_records': final_stable,
                    'auth_probe_path': str(auth_path), 'auth_probe_sha256': auth_sha,
                    'database_mutation_performed': False, 'services_modified': False,
                    'bank_enabled': False, 'ai_enabled': False}
        if args.phase == 'before':
            evidence['stage'] = 'STRIPE_REPORT_OWNER_UI_BASELINE'
            baseline_sha = save_new(upgrade, baseline_path, evidence)
            result_path, result_sha = baseline_path, baseline_sha
        else:
            evidence['baseline_sha256'] = args.baseline_sha256
            evidence['stable_records_and_authorization_preserved'] = True
            result_path = folder / 'owner-ui-after.json'
            result_sha = save_new(upgrade, result_path, evidence)
        print(json.dumps({'stage': evidence['stage'], 'phase': args.phase, 'source_sha': SOURCE,
              'frontend_version': VERSION, 'evidence_path': str(result_path), 'evidence_sha256': result_sha,
              'baseline_sha256': result_sha if args.phase == 'before' else args.baseline_sha256,
              'auth_probe_path': str(auth_path), 'auth_probe_sha256': auth_sha,
              'business_tables_verified': 83, 'private_tables_verified': 11,
              'database_mutation_performed': False, 'services_modified': False}, sort_keys=True))


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise VerificationError('ARGUMENTS_REJECTED')


if __name__ == '__main__':
    parser = SafeParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--phase', required=True, choices=('before', 'after'))
    parser.add_argument('--verification-id', required=True)
    parser.add_argument('--upgrade-helper-sha256', required=True)
    parser.add_argument('--acquired-sha256', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--baseline-sha256')
    try:
        main(parser.parse_args())
    except BaseException as error:
        # Never emit tracebacks, command output, raw exception text or credentials.
        code = str(error) if isinstance(error, VerificationError) and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'POSTDEPLOY_VERIFICATION_REJECTED'
        print(json.dumps({'stage': 'STRIPE_REPORT_POSTDEPLOY_VERIFICATION_REJECTED', 'error': code,
                          'database_mutation_performed': False, 'services_modified': False}, sort_keys=True))
        sys.exit(1)
