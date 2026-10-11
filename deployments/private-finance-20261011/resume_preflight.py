#!/usr/bin/env python3
"""Readonly proof for an accepted ten-table schema with restored old services.

This explicit path preserves the original four-table migration and rollback
receipts. It never stops a service or writes either DB. Google authorization
is decrypted only in memory through the original offline crypto boundary;
receipts contain credential hashes, never decrypted values.
Only existing Gmail/Ads provider fields may have refreshed; local data, scopes,
connection identities and long-term authorization remain tied to the backup.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
from types import SimpleNamespace

import credential_transfer as transfer
import live_preflight as live
import private_schema_guard as guard

STAGE = 'PRIVATE_FINANCE_RESUME_READONLY_BASELINE'
RELEASES = Path('/opt/t24-crm/releases')
PROVIDER_SOURCES = frozenset({'gmail', 'google_ads'})
CONNECTION_VOLATILE = frozenset({'last_sync', 'last_attempt_at', 'sync_lease_until', 'error', 'updated_at'})
METADATA_VOLATILE = frozenset({'partial', 'sync_window', 'record_limit', 'importance_source',
    'balances', 'coverage', 'record_limit_per_resource', 'resources', 'ads_snapshot'})
ITEM_LOCAL_COLUMNS = ('id', 'owner_id', 'source_id', 'external_id', 'local_title',
    'local_summary', 'action_status', 'snoozed_until', 'created_at')
LINEAGE_FIELDS = ('resume_schema_state', 'resume_schema_state_sha256', 'rollback_state',
    'rollback_state_sha256', 'new_baseline', 'new_baseline_sha256', 'original_source_sha',
    'original_candidate', 'original_candidate_sha256', 'original_candidate_image',
    'original_schema_after_sha256', 'original_schema_validation_sha256', 'original_backup_sha256',
    'original_claim_path', 'original_claim_sha256', 'bootstrap_sha256')


class ResumeError(RuntimeError): pass

class SafeParser(argparse.ArgumentParser):
    def error(self, message): raise ResumeError('ARGUMENTS_REJECTED')

def need(condition, code):
    if not condition: raise ResumeError(code)

def root_guard():
    need(os.geteuid() == 0 and socket.gethostname() == live.HOST, 'VERIFIED_ROOT_RESUME_SERVER_REQUIRED')

def fixed_json(path, expected):
    from seed_private_stripe import fixed_json as read
    return read(path, expected)

def original_proof(schema_state, schema_state_sha256, rollback_state, rollback_state_sha256):
    # Imports are lazy so candidate preparation can use this module without an
    # import cycle through the previously reviewed seed/switch programs.
    import seed_private_stripe as seed
    import switch_completed as switch
    state = fixed_json(schema_state, schema_state_sha256)
    need(state.get('phase') == 'PRIVATE_COMPLETED_SCHEMA_VERIFIED_WRITERS_STOPPED' and
         state.get('worker_started') is False and state.get('services_switched') is False and
         state.get('deployed') is False, 'EXACT_ORIGINAL_PRE_SEED_SCHEMA_STATE_REQUIRED')
    original_args = SimpleNamespace(candidate=Path(state['candidate']), candidate_sha256=state['candidate_sha256'],
        source_sha=state['source_sha'], schema_state=schema_state, schema_state_sha256=schema_state_sha256)
    need(original_args.candidate.parent.parent == RELEASES and original_args.candidate.name == 'candidate.json' and
         re.fullmatch('private-finance-' + state['source_sha'][:12] + '-20261011-candidate(?:-[a-z0-9]{1,16})?',
             original_args.candidate.parent.name), 'EXACT_ORIGINAL_CANDIDATE_RELEASE_PATH_REQUIRED')
    receipt = seed.checked_candidate(fixed_json(original_args.candidate, original_args.candidate_sha256),
        source_sha=original_args.source_sha, release=original_args.candidate.parent)
    state, before, after, baseline = switch.checked_schema_state(original_args, receipt)
    need(rollback_state.parent == schema_state.parent and re.fullmatch('rollback-[a-f0-9]{32}\\.json', rollback_state.name),
         'EXACT_ORIGINAL_ROLLBACK_PATH_REQUIRED')
    rollback = fixed_json(rollback_state, rollback_state_sha256)
    need(rollback.get('format_version') == 1 and rollback.get('phase') == 'PRIVATE_COMPLETED_RELEASE_ROLLED_BACK_OLD_SERVICES'
         and rollback.get('source_sha') == state['source_sha'] and rollback.get('attempt') == state['attempt']
         and rollback.get('old_ids') == live.PRIVATE_IDS and rollback.get('customer_tables_verified') == 83
         and all(rollback.get(name) is False for name in ('bank_enabled', 'ai_enabled', 'databases_restored',
         'private_database_replaced', 'public_assets_published', 'deployed')),
         'EXACT_OLD_SERVICES_RESTORED_WITHOUT_DATABASE_RESTORE_REQUIRED')
    return state, before, after, baseline

def _rows(db, table):
    columns = [row[1] for row in db.execute('PRAGMA table_info("' + table + '")')]
    need(columns, 'RESUME_STABLE_TABLE_COLUMNS_REQUIRED')
    return [dict(zip(columns, row)) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY id')]

def fingerprint_google_credentials(ciphertexts):
    """Only hashes leave this process; decrypt via the pinned offline adapter.

    This uses the original protected configuration and original private image.
    Its existing crypto adapter has no network or production mounts, logs are
    disabled and the encryption key/ciphertext travel only over captured stdin.
    Neither the refresh token nor the decrypted JSON enters a receipt or error.
    """
    if not ciphertexts: return {}
    secret = transfer.environment_guard()
    crypto = transfer.Crypto('docker')
    result = {}
    for identity, ciphertext in ciphertexts.items():
        try:
            need(isinstance(ciphertext, str) and 0 < len(ciphertext) <= 100000,
                 'RESUME_GOOGLE_CREDENTIAL_FORMAT_REJECTED')
            plaintext = crypto.fernet('open', secret, ciphertext.encode())
            need(len(plaintext) <= 65536, 'RESUME_GOOGLE_CREDENTIAL_FORMAT_REJECTED')
            payload = json.loads(plaintext)
            required = {'access_token', 'expires_at', 'refresh_token', 'scope', 'token_type'}
            need(isinstance(payload, dict) and required <= set(payload) and
                 all(isinstance(payload[name], str) and 0 < len(payload[name]) <= 8192 and
                     not any(ord(char) < 32 or ord(char) == 127 for char in payload[name])
                     for name in ('access_token', 'refresh_token', 'scope', 'token_type')) and
                 payload['token_type'] == 'Bearer' and type(payload['expires_at']) is int and
                 payload['expires_at'] > 0, 'RESUME_GOOGLE_CREDENTIAL_FORMAT_REJECTED')
            # Unknown fields remain frozen too. Exactly these two fields are
            # short-lived outputs of the existing Google refresh adapter.
            stable = {key: value for key, value in payload.items() if key not in {'access_token', 'expires_at'}}
            result[identity] = {'payload_sha256': guard.digest(payload), 'stable_sha256': guard.digest(stable)}
            del plaintext, payload, stable
        except Exception:
            raise ResumeError('RESUME_GOOGLE_CREDENTIAL_DECRYPT_OR_FORMAT_REJECTED') from None
    return result

def stable_records(path):
    """Hashes only; Google credentials are compared in memory, never emitted."""
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        connections = {}; immutable_items = {}; local_items = {}; new_item_defaults = {}; runs = {}
        google_credentials = {}; ciphertexts = {}
        for row in _rows(db, 'private_connections'):
            need(row.get('owner_id') == '4', 'RESUME_OWNER_SCOPE_DRIFT')
            metadata = json.loads(row.get('metadata_json') or '{}')
            need(isinstance(metadata, dict), 'RESUME_CONNECTION_METADATA_REJECTED')
            selected = dict(row)
            if row['source_id'] in PROVIDER_SOURCES:
                selected = {name: value for name, value in selected.items() if name not in CONNECTION_VOLATILE}
                selected['metadata_json'] = {name: value for name, value in metadata.items()
                    if name not in METADATA_VOLATILE and not (row['source_id'] == 'gmail' and name == 'fetched_messages')}
                # Only connected, encrypted Google authorizations can refresh.
                if row.get('status') == 'connected' and row.get('encrypted_credentials'):
                    identity = guard.digest(row['id']); ciphertexts[identity] = row['encrypted_credentials']
                    google_credentials[identity] = {'source_id': row['source_id'],
                        'ciphertext_sha256': guard.digest(row['encrypted_credentials']), 'last_sync': row.get('last_sync')}
                    selected['encrypted_credentials'] = None
            connections[guard.digest(row['id'])] = selected
        for row in _rows(db, 'private_items'):
            need(row.get('owner_id') == '4', 'RESUME_OWNER_SCOPE_DRIFT')
            identity = guard.digest(row['id'])
            local_items[identity] = guard.digest([row.get(name) for name in ITEM_LOCAL_COLUMNS])
            new_item_defaults[identity] = row.get('source_id') in PROVIDER_SOURCES and row.get('local_title') is None and \
                row.get('local_summary') is None and row.get('action_status') == 'open' and row.get('snoozed_until') is None
            if row.get('source_id') not in PROVIDER_SOURCES: immutable_items[identity] = guard.digest(row)
        prefs = {guard.digest(row[0]): guard.digest(list(row)) for row in db.execute(
            'SELECT owner_id,preferences_json FROM private_preferences ORDER BY owner_id')}
        for row in _rows(db, 'private_sync_runs'):
            need(row.get('owner_id') == '4', 'RESUME_OWNER_SCOPE_DRIFT')
            identity = guard.digest(row['id']); runs[identity] = {'hash': guard.digest(row),
                'provider_source': row.get('source_id') in PROVIDER_SOURCES,
                'source_id': row.get('source_id'), 'status': row.get('status'),
                'started_at': row.get('started_at'), 'completed_at': row.get('completed_at')}
    fingerprints = fingerprint_google_credentials(ciphertexts)
    need(set(fingerprints) == set(ciphertexts), 'RESUME_COMPLETE_GOOGLE_CREDENTIAL_FINGERPRINTS_REQUIRED')
    for identity, fingerprint in fingerprints.items():
        need(set(fingerprint) == {'payload_sha256', 'stable_sha256'} and
             all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) for value in fingerprint.values()),
             'RESUME_GOOGLE_CREDENTIAL_FINGERPRINTS_REJECTED')
        google_credentials[identity].update(fingerprint)
        connections[identity]['encrypted_credentials'] = {'google_long_term_authorization_sha256': fingerprint['stable_sha256']}
    connections = {identity: guard.digest(row) for identity, row in connections.items()}
    return {'connections': connections, 'local_items': local_items, 'immutable_items': immutable_items,
        'new_item_defaults': new_item_defaults, 'preferences': prefs, 'sync_runs': runs,
        'google_credentials': google_credentials}

def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError): return None

def checked_google_refresh(reference, current):
    before = reference['google_credentials']; after = current['google_credentials']
    need(set(before) == set(after), 'RESUME_GOOGLE_AUTHORIZATION_IDENTITY_CHANGED')
    new_runs = [run for identity, run in current['sync_runs'].items() if identity not in reference['sync_runs']]
    for identity, original in before.items():
        observed = after[identity]
        need(observed['source_id'] == original['source_id'] and observed['stable_sha256'] == original['stable_sha256'],
             'RESUME_ACCOUNT_SCOPE_OR_ENCRYPTED_CREDENTIAL_CHANGED')
        if observed['ciphertext_sha256'] == original['ciphertext_sha256']:
            need(observed['payload_sha256'] == original['payload_sha256'], 'RESUME_GOOGLE_CREDENTIAL_FINGERPRINT_DRIFT')
            continue
        # Both exact-plaintext re-encryption and access-token/expiry updates
        # require a newly persisted successful sync for this exact source.
        last_sync = _time(observed['last_sync']); previous = _time(original['last_sync'])
        matched = False
        for run in new_runs:
            started, completed = _time(run['started_at']), _time(run['completed_at'])
            if (run['source_id'] == original['source_id'] and run['status'] == 'succeeded' and started and completed and
                    last_sync and started <= last_sync <= completed and (completed - last_sync).total_seconds() <= 5 and
                    (previous is None or last_sync > previous)):
                matched = True; break
        need(matched, 'RESUME_GOOGLE_TOKEN_CHANGE_REQUIRES_SUCCESSFUL_SYNC_AUDIT')

def checked_stable(reference, current):
    need(reference['connections'] == current['connections'], 'RESUME_ACCOUNT_SCOPE_OR_ENCRYPTED_CREDENTIAL_CHANGED')
    checked_google_refresh(reference, current)
    need(reference['preferences'] == current['preferences'], 'RESUME_PERSONAL_PREFERENCES_CHANGED')
    need(all(current['local_items'].get(key) == value for key, value in reference['local_items'].items()),
         'RESUME_ORIGINAL_NOTES_ACTIONS_OR_ITEM_IDENTITY_CHANGED')
    need(reference['immutable_items'] == current['immutable_items'], 'RESUME_NON_GOOGLE_PROVIDER_ITEMS_CHANGED')
    need(all(current['new_item_defaults'].get(key) is True for key in current['local_items'].keys() - reference['local_items'].keys()),
         'RESUME_NEW_NON_PROVIDER_OR_EDITED_LOCAL_ITEM_REJECTED')
    need(all(current['sync_runs'].get(key) == value for key, value in reference['sync_runs'].items()) and
         all(value['provider_source'] is True for key, value in current['sync_runs'].items() if key not in reference['sync_runs']),
         'RESUME_UNRELATED_OR_ORIGINAL_SYNC_AUDIT_CHANGED')

def checked_claim(state):
    blob = transfer.read_protected(transfer.BOOTSTRAP, 32768); bootstrap_sha = live.sha(blob)
    path = transfer.CONFIG / 'stripe-seed-claims' / (bootstrap_sha + '.json')
    transfer.protected_directory(path.parent)
    raw = transfer.read_protected(path); value = json.loads(raw)
    need(set(value) == {'stage', 'attempt', 'candidate_sha256', 'bootstrap_sha256', 'source_sha'} and
         value['stage'] == 'STRIPE_SEED_ONE_USE_CLAIMED' and value['candidate_sha256'] == state['candidate_sha256']
         and value['bootstrap_sha256'] == bootstrap_sha and value['source_sha'] == state['source_sha']
         and re.fullmatch('[a-f0-9]{32}', value['attempt']), 'EXACT_ORIGINAL_FAILED_ONE_USE_CLAIM_REQUIRED')
    original_success = Path(state['candidate']).parent / 'stripe-seed-receipt.json'
    need(not original_success.exists() and not original_success.is_symlink(), 'ORIGINAL_SUCCESSFUL_STRIPE_SEED_MUST_NOT_EXIST')
    return {'original_claim_path': str(path), 'original_claim_sha256': live.sha(raw),
        'bootstrap_sha256': bootstrap_sha, 'original_seed_attempt': value['attempt']}

def checked_frozen_snapshot(new_baseline, current):
    import candidate_prepare as candidate
    import seed_private_stripe as seed
    original = new_baseline['accepted_snapshot']
    need(current['business'] == original['business'] and len(current['business']['tables']) == 83,
         'RESUME_ALL_CUSTOMER_TABLE_FINGERPRINTS_CHANGED')
    need(current['private']['identity'] == original['private']['identity'] and
         current['private']['schema_objects'] == original['private']['schema_objects'] and
         set(current['private']['tables']) == candidate.TARGET_TABLES and
         all(current['private']['tables'][name]['columns_sha256'] == value['columns_sha256']
             for name, value in original['private']['tables'].items()), 'RESUME_ACCEPTED_INODE_OR_TEN_TABLE_SCHEMA_CHANGED')
    need(all(current['private']['tables'][name]['rows'] == 0 for name in candidate.TARGET_TABLES - guard.BASE_TABLES),
         'RESUME_BANK_OR_AI_ROWS_MUST_REMAIN_EMPTY')
    need(seed.connection_state(live.PRIVATE_DB)['row'] is None, 'RESUME_MUST_HAVE_NO_COMMITTED_STRIPE_CONNECTION')
    checked_stable(new_baseline['original_stable_reference'], stable_records(live.PRIVATE_DB))
    return current

def _restored_runtime(environment):
    previous, static = live.prior_receipts(); previous = deepcopy(previous)
    for role in live.PRIVATE_IDS:
        info = live.inspect('t24-private-' + role)
        live.healthy(info, api=role == 'api')
        saved = previous['new_private'][role]
        need(isinstance(info['State'].get('StartedAt'), str) and info['State']['StartedAt'] > saved['started_at'] and
             info.get('RestartCount') == saved['restart_count'], 'RESUME_EXACT_RESTORED_OLD_START_REQUIRED')
        saved['started_at'] = info['State']['StartedAt']
    return live.private_runtime(previous, environment), static

def preflight(*, schema_state, schema_state_sha256, rollback_state, rollback_state_sha256):
    import switch_completed as switch
    root_guard()
    state, before, after, baseline = original_proof(schema_state, schema_state_sha256, rollback_state, rollback_state_sha256)
    environment = switch.runtime_guard(baseline)
    private, static = _restored_runtime(environment)
    current = guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS)
    with sqlite3.connect(live.BUSINESS.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        need(db.execute('SELECT version_num FROM alembic_version').fetchall() == [('ab6d8e2f0411',)] and
             db.execute('SELECT role,status FROM employees WHERE id=4').fetchall() == [('super_admin', 'active')],
             'RESUME_OWNER_OR_BUSINESS_SCHEMA_HEAD_CHANGED')
    reference = stable_records(Path(state['backup']))
    claim = checked_claim(state)
    value = {**baseline, 'format_version': 1, 'stage': STAGE, 'mutation_performed': False,
        'private': private, 'private_database': {'device': current['private']['identity']['device'],
            'inode': current['private']['identity']['inode'], 'schema_sha256': current['private']['schema_sha256'],
            'table_inventory': sorted(current['private']['tables']), 'owner_scope_verified': True},
        'resume_schema_state': str(schema_state), 'resume_schema_state_sha256': schema_state_sha256,
        'rollback_state': str(rollback_state), 'rollback_state_sha256': rollback_state_sha256,
        'original_source_sha': state['source_sha'], 'original_candidate': state['candidate'],
        'original_candidate_sha256': state['candidate_sha256'], 'original_candidate_image': state['candidate_image'],
        'original_schema_after_sha256': state['schema_after_sha256'],
        'original_schema_validation_sha256': state['schema_validation_sha256'], 'original_backup_sha256': state['backup_sha256'],
        'accepted_snapshot': after, 'original_stable_reference': reference, **claim,
        'observed_snapshot_sha256': guard.digest(current), 'exact_accepted_schema_after': current == after,
        'fresh_no_successful_seed_verified': True, 'stripe_connection_absent': True, 'bank_enabled': False, 'ai_enabled': False}
    checked_frozen_snapshot(value, current)
    switch.runtime_guard(baseline)
    need(_restored_runtime(environment)[0] == private, 'RESTORED_PRIVATE_RUNTIME_CHANGED_DURING_RESUME_READ')
    need(checked_claim(state) == claim, 'ORIGINAL_FAILED_CLAIM_CHANGED_DURING_RESUME_READ')
    return value

def compare_baseline(current, baseline):
    need(baseline.get('format_version') == 1 and baseline.get('stage') == STAGE and
         baseline.get('mutation_performed') is False, 'EXPLICIT_RESUME_BASELINE_REQUIRED')
    # Both values have independently passed all original-backup invariants.
    # Only a current provider snapshot hash/full-equality flag can change while
    # old read-only Google monitoring continues during isolated build/tests.
    dynamic = {'observed_snapshot_sha256', 'exact_accepted_schema_after'}
    need({k: v for k, v in current.items() if k not in dynamic} ==
         {k: v for k, v in baseline.items() if k not in dynamic}, 'FROZEN_RESUME_BASELINE_DRIFT')

def checked_lineage(receipt):
    lineage = receipt.get('resume_lineage')
    need(isinstance(lineage, dict) and set(lineage) == set(LINEAGE_FIELDS) | {'format_version', 'fresh_no_successful_seed_verified'}
         and lineage.get('format_version') == 1 and lineage.get('fresh_no_successful_seed_verified') is True,
         'EXPLICIT_COMPLETE_RESUME_LINEAGE_REQUIRED')
    state, before, after, old_baseline = original_proof(Path(lineage['resume_schema_state']),
        lineage['resume_schema_state_sha256'], Path(lineage['rollback_state']), lineage['rollback_state_sha256'])
    new_baseline = fixed_json(Path(lineage['new_baseline']), lineage['new_baseline_sha256'])
    baseline_path = Path(lineage['new_baseline'])
    need(baseline_path.name == 'resume-baseline.json' and baseline_path.parent.parent == RELEASES and
         re.fullmatch('private-finance-' + receipt['source_sha'][:12] + '-20261011-candidate(?:-[a-z0-9]{1,16})?',
             baseline_path.parent.name), 'EXACT_NEW_CANDIDATE_RESUME_BASELINE_PATH_REQUIRED')
    need(receipt.get('baseline_sha256') == lineage['new_baseline_sha256'] and new_baseline.get('stage') == STAGE and
         new_baseline.get('mutation_performed') is False and new_baseline.get('accepted_snapshot') == after and
         new_baseline.get('original_stable_reference') == stable_records(Path(state['backup'])) and
         all(new_baseline.get(key) == lineage[key] for key in LINEAGE_FIELDS if not key.startswith('new_baseline')),
         'ORIGINAL_ACCEPTED_SCHEMA_AND_RESUME_BASELINE_BINDING_REQUIRED')
    claim = checked_claim(state)
    need(all(new_baseline.get(key) == value for key, value in claim.items()), 'RESUME_ORIGINAL_CLAIM_OR_BOOTSTRAP_CHANGED')
    need(lineage['original_source_sha'] == state['source_sha'] and lineage['original_candidate'] == state['candidate'] and
         lineage['original_candidate_sha256'] == state['candidate_sha256'] and lineage['original_candidate_image'] == state['candidate_image'] and
         lineage['original_schema_after_sha256'] == state['schema_after_sha256'] and
         lineage['original_schema_validation_sha256'] == state['schema_validation_sha256'] and
         lineage['original_backup_sha256'] == state['backup_sha256'] and
         receipt['synthetic_schema']['schema_objects'] == after['private']['schema_objects'], 'RESUME_ORIGINAL_PROOF_LINEAGE_DRIFT')
    return state, before, after, old_baseline, new_baseline

def candidate_lineage(args, baseline):
    return {'format_version': 1, 'fresh_no_successful_seed_verified': True,
        **{name: baseline[name] for name in LINEAGE_FIELDS if not name.startswith('new_baseline')},
        'new_baseline': str(args.release / 'resume-baseline.json'), 'new_baseline_sha256': args.baseline_sha256}

def main(args):
    value = preflight(schema_state=args.resume_schema_state, schema_state_sha256=args.resume_schema_state_sha256,
        rollback_state=args.rollback_state, rollback_state_sha256=args.rollback_state_sha256)
    print(json.dumps(value, sort_keys=True))

def cli(argv=None):
    parser = SafeParser(description=__doc__)
    for name in ('resume-schema-state', 'rollback-state'):
        parser.add_argument('--' + name, type=Path, required=True); parser.add_argument('--' + name + '-sha256', required=True)
    try: main(parser.parse_args(argv))
    except Exception as error:
        code = str(error) if isinstance(error, ResumeError) and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'RESUME_PREFLIGHT_REJECTED'
        print(json.dumps({'stage': 'PRIVATE_FINANCE_RESUME_REJECTED', 'error': code, 'mutation_performed': False}, sort_keys=True)); return 1
    return 0

if __name__ == '__main__': raise SystemExit(cli())
