#!/usr/bin/env python3
"""Explicit runtime repair after an accepted Stripe seed. Never initializes or seeds.

Original seed, claims and migration receipts remain immutable. A new candidate
must pass a complete GET-only fetch with both production databases mounted
readonly before replacing the accepted API. The worker remains stopped until a
real persisted sync succeeds. Rollback restores only the ancestor API runtime;
it never restores a database or retries a credential connection.
"""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

import credential_transfer as transfer
import diagnose_private_stripe as diagnosis
import live_preflight as live
import private_schema_guard as guard
import seed_private_stripe as seed
import switch_completed as switch

STAGE = 'PRIVATE_SEEDED_REPAIR_READONLY_BASELINE'
MINIMUM_TESTS = 845
RELEASES = Path('/opt/t24-crm/releases')
LABEL = 't24.private_finance.seeded_fetch'
RESOURCES = ('account', 'balance', 'charges', 'refunds', 'disputes', 'payouts')
FIELDS = ('ancestor_api_state', 'ancestor_api_state_sha256', 'ancestor_candidate',
    'ancestor_candidate_sha256', 'ancestor_source_sha', 'ancestor_image',
    'ancestor_schema_state', 'ancestor_schema_state_sha256', 'ancestor_stripe_seed',
    'ancestor_stripe_seed_sha256', 'original_claim', 'original_claim_sha256',
    'reviewed_retry_claim', 'reviewed_retry_claim_sha256', 'bootstrap_sha256')


class RepairError(RuntimeError): pass
class SafeParser(argparse.ArgumentParser):
    def error(self, message): raise RepairError('ARGUMENTS_REJECTED')

def need(condition, code):
    if not condition: raise RepairError(code)

def fixed(path, expected): return seed.fixed_json(path, expected)

def ancestor(api_state, api_state_sha256):
    state = fixed(api_state, api_state_sha256)
    need(api_state.name == 'api-state.json' and api_state.parent.name == 'completed-release' and
         api_state.parent.parent.parent == RELEASES, 'EXACT_ANCESTOR_API_STATE_PATH_REQUIRED')
    args = SimpleNamespace(source_sha=state.get('source_sha'), candidate=Path(state['candidate']),
        candidate_sha256=state['candidate_sha256'], api_state=api_state, api_state_sha256=api_state_sha256)
    receipt = switch.checked_candidate(args)
    need(api_state.parent.parent == args.candidate.parent, 'ANCESTOR_RELEASE_PATH_DRIFT')
    state, after, baseline = switch.checked_api_state(args, receipt)
    schema_args = SimpleNamespace(**vars(args), schema_state=Path(state['schema_state']),
        schema_state_sha256=state['schema_state_sha256'])
    schema, _, _, _ = switch.checked_schema_state(schema_args, receipt)
    stripe = fixed(Path(state['stripe_seed']), state['stripe_seed_sha256'])
    switch.checked_seed_scope(stripe, args, schema)
    need(state.get('worker_started') is False and state.get('public_assets_published') is False and
         state.get('deployed') is False, 'ANCESTOR_MUST_BE_ACCEPTED_API_ONLY')
    return state, after, baseline, receipt, stripe

def lineage_fields(api_state, api_state_sha256, state, stripe):
    need(stripe.get('original_claim_preserved') is True and
         re.fullmatch('[a-f0-9]{64}', stripe.get('original_claim_sha256', '')) and
         re.fullmatch('[a-f0-9]{64}', stripe.get('retry_claim_sha256', '')),
         'ACCEPTED_EXCLUSIVE_SEED_CLAIMS_REQUIRED')
    bootstrap = stripe['bootstrap_sha256']
    root = transfer.CONFIG/'stripe-seed-claims'
    return {'ancestor_api_state': str(api_state), 'ancestor_api_state_sha256': api_state_sha256,
        'ancestor_candidate': state['candidate'], 'ancestor_candidate_sha256': state['candidate_sha256'],
        'ancestor_source_sha': state['source_sha'], 'ancestor_image': state['candidate_image'],
        'ancestor_schema_state': state['schema_state'], 'ancestor_schema_state_sha256': state['schema_state_sha256'],
        'ancestor_stripe_seed': state['stripe_seed'], 'ancestor_stripe_seed_sha256': state['stripe_seed_sha256'],
        'original_claim': str(root/(bootstrap+'.json')), 'original_claim_sha256': stripe['original_claim_sha256'],
        'reviewed_retry_claim': stripe['retry_claim'], 'reviewed_retry_claim_sha256': stripe['retry_claim_sha256'],
        'bootstrap_sha256': bootstrap}

def claims_unchanged(value):
    bootstrap = value['bootstrap_sha256']; root = transfer.CONFIG/'stripe-seed-claims'
    need(re.fullmatch('[a-f0-9]{64}', bootstrap) and
         Path(value['original_claim']) == root/(bootstrap+'.json') and
         Path(value['reviewed_retry_claim']) == root/(bootstrap+'.reviewed-retry.json'),
         'EXACT_ORIGINAL_CLAIM_PATHS_REQUIRED')
    need(switch.sha(transfer.read_protected(transfer.BOOTSTRAP, 32768)) == bootstrap,
         'ORIGINAL_BOOTSTRAP_CHANGED')
    for name in ('original_claim', 'reviewed_retry_claim'):
        need(switch.sha(transfer.read_protected(Path(value[name]))) == value[name+'_sha256'],
             'ACCEPTED_SEED_CLAIM_CHANGED')

def stripe_fingerprint(generation, *, verify_bootstrap=False):
    row = seed.connection_state(live.PRIVATE_DB)['row']
    need(row and row.get('owner_id') == '4' and row.get('source_id') == 'stripe' and
         row.get('status') == 'connected' and row.get('generation') == generation and
         isinstance(row.get('encrypted_credentials'), str) and row['encrypted_credentials'] and
         not row.get('sync_lease_until'), 'EXACT_EXISTING_STRIPE_AUTHORIZATION_REQUIRED')
    metadata = json.loads(row.get('metadata_json') or '{}')
    need(metadata.get('stripe_account_id') == transfer.ACCOUNT and metadata.get('mode') == 'live' and
         metadata.get('read_only_adapter') is True, 'EXISTING_STRIPE_ACCOUNT_OR_MODE_CHANGED')
    if verify_bootstrap:
        try:
            secret = transfer.environment_guard()
            payload = json.loads(transfer.Crypto('docker').fernet('open', secret, row['encrypted_credentials'].encode()))
            original = transfer.get_bootstrap(sealed_crypto='docker')['credentials']
            need(payload == original, 'EXISTING_STRIPE_CREDENTIAL_MUST_MATCH_ACCEPTED_BOOTSTRAP')
            del payload, original, secret
        except RepairError: raise
        except Exception: raise RepairError('EXISTING_STRIPE_CREDENTIAL_VERIFICATION_REJECTED') from None
    return {'identity_sha256': guard.digest([row.get(name) for name in
        ('id', 'owner_id', 'source_id', 'generation', 'created_at')]),
        'generation': generation, 'encrypted_credentials_sha256': guard.digest(row['encrypted_credentials']),
        'account_id': transfer.ACCOUNT, 'mode': 'live'}

def ancestor_runtime(state, baseline, *, api_running=True, stable=True):
    switch.runtime_guard(baseline)
    values = {role: switch.role_configuration(transfer.read_protected(transfer.ENV), role) for role in ('api', 'worker')}
    api = switch.staged_check(state['new_ids']['api'], 'api', state['candidate_image'], state['attempt'],
        state['source_sha'], values['api'], running=api_running, require_stable=stable)
    if api_running and stable:
        need(api == state['new_private']['api'] and switch.inspect(state['new_ids']['api'])['Name']=='/t24-private-api',
             'ACCEPTED_ANCESTOR_API_RUNTIME_CHANGED')
    switch.staged_check(state['new_ids']['worker'], 'worker', state['candidate_image'], state['attempt'],
        state['source_sha'], values['worker'], running=False, require_stable=False)
    for role in ('api', 'worker'): switch.old_check(role, baseline, running=False)
    switch.no_writers([state['new_ids']['api']] if api_running else [])
    return api

def existing_data(current, state, after, stripe):
    switch.schema_and_business_unchanged(current, after); switch.disabled_data(current)
    switch.preserved(state['stable_before'], switch.stable_records(live.PRIVATE_DB), allow_provider_changes=False)
    return stripe_fingerprint(stripe['generation'])

def preflight(*, api_state, api_state_sha256):
    switch.root_guard()
    state, after, baseline, _, stripe = ancestor(api_state, api_state_sha256)
    fields = lineage_fields(api_state, api_state_sha256, state, stripe)
    claims_unchanged(fields); api = ancestor_runtime(state, baseline)
    current = guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS)
    fingerprint = existing_data(current, state, after, stripe)
    stable = switch.stable_records(live.PRIVATE_DB)
    need(stripe_fingerprint(stripe['generation'], verify_bootstrap=True) == fingerprint,
         'STRIPE_AUTHORIZATION_CHANGED_DURING_READ')
    need(guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS) == current and
         ancestor_runtime(state, baseline) == api, 'SEEDED_REPAIR_BASELINE_CHANGED_DURING_READ')
    claims_unchanged(fields)
    return {**baseline, 'format_version': 1, 'stage': STAGE, **fields,
        'snapshot': current, 'stripe_authorization': fingerprint, 'ancestor_api_runtime': api,
        'stable_records': stable, 'bank_enabled': False, 'ai_enabled': False,
        'mutation_performed': False, 'initializer_rerun': False, 'credential_seed_attempted': False,
        'original_claims_preserved': True}

def compare_baseline(current, baseline):
    need(baseline.get('stage') == STAGE and baseline.get('format_version') == 1 and
         baseline.get('mutation_performed') is False and current == baseline,
         'FROZEN_SEEDED_REPAIR_BASELINE_DRIFT')

def candidate_lineage(args, baseline):
    return {'format_version': 1, **{name: baseline[name] for name in FIELDS},
        'new_baseline': str(args.release/'repair-baseline.json'), 'new_baseline_sha256': args.baseline_sha256}

def checked_lineage(receipt):
    value = receipt.get('seeded_repair_lineage')
    need('resume_lineage' not in receipt and isinstance(value, dict) and
         set(value) == set(FIELDS) | {'format_version', 'new_baseline', 'new_baseline_sha256'} and
         value.get('format_version') == 1, 'EXPLICIT_COMPLETE_SEEDED_REPAIR_LINEAGE_REQUIRED')
    state, after, original, _, stripe = ancestor(Path(value['ancestor_api_state']), value['ancestor_api_state_sha256'])
    expected = lineage_fields(Path(value['ancestor_api_state']), value['ancestor_api_state_sha256'], state, stripe)
    need(all(value[name] == expected[name] for name in FIELDS), 'ANCESTOR_SEED_OR_MIGRATION_LINEAGE_CHANGED')
    path = Path(value['new_baseline'])
    need(path.name == 'repair-baseline.json' and path.parent.parent == RELEASES and
         re.fullmatch('private-finance-'+receipt['source_sha'][:12]+'-20261011-candidate(?:-[a-z0-9]{1,16})?', path.parent.name)
         and receipt.get('baseline_sha256') == value['new_baseline_sha256'], 'EXACT_NEW_REPAIR_BASELINE_PATH_REQUIRED')
    baseline = fixed(path, value['new_baseline_sha256'])
    need(baseline.get('stage') == STAGE and baseline.get('mutation_performed') is False and
         all(baseline.get(name) == expected[name] for name in FIELDS) and
         baseline.get('snapshot', {}).get('business') == after['business'] and
         baseline['snapshot']['private']['identity'] == after['private']['identity'] and
         baseline['snapshot']['private']['schema_objects'] == receipt['synthetic_schema']['schema_objects'] == after['private']['schema_objects'] and
         baseline['stripe_authorization']['generation'] == stripe['generation'] and
         baseline.get('initializer_rerun') is False and baseline.get('credential_seed_attempted') is False,
         'ACCEPTED_SEEDED_REPAIR_BASELINE_BINDING_REQUIRED')
    claims_unchanged(value)
    return state, after, original, stripe, baseline

def checked_candidate(args):
    receipt = switch.checked_candidate(args)
    need(receipt['candidate_regressions']['minimum'] >= MINIMUM_TESTS and
         receipt['candidate_regressions']['tests'] >= MINIMUM_TESTS, 'ALL_845_SEEDED_REPAIR_REGRESSIONS_REQUIRED')
    checked_lineage(receipt)
    return receipt

def helper_code():
    return '''import asyncio,io,json,os,sqlite3,sys
from contextlib import redirect_stdout,redirect_stderr
packet=json.load(sys.stdin);calls=[];stage='configuration'
class SafeFailure(RuntimeError):
 def __init__(self,code):self.code=code
async def operation():
 global stage
 os.environ.update(packet['configuration'])
 from sqlalchemy.ext.asyncio import async_sessionmaker
 from dependencies.private_workspace import valid_private_owner
 from services.private_workspace_worker import create_business_reader
 from services import private_workspace as core,private_workspace_providers as provider
 engine=create_business_reader();sessions=async_sessionmaker(engine,expire_on_commit=False)
 original=provider._Client.request
 async def owner():
  async with sessions() as db:return await valid_private_owner('4',db)
 async def request(client,method,url,**arguments):
  global stage
  allowed=RESOURCE_MAP
  if method!='GET' or url not in allowed:raise SafeFailure('request_not_allowed')
  stage=allowed[url];calls.append(stage)
  if len(calls)>10 or calls.count(stage)>(1 if stage in ('account','balance') else 2):raise SafeFailure('request_not_allowed')
  return await original(client,method,url,**arguments)
 try:
  stage='owner'
  if not await owner():raise SafeFailure('owner_changed')
  stage='existing_credentials'
  with sqlite3.connect('file:/private-data/workspace.db?mode=ro',uri=True,timeout=15) as db:
   db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
   rows=db.execute("SELECT owner_id,status,encrypted_credentials,metadata_json,generation,sync_lease_until FROM private_connections WHERE source_id='stripe'").fetchall()
  if len(rows)!=1:raise SafeFailure('invalid_credentials')
  row=rows[0]
  if row[0]!='4' or row[1]!='connected' or row[4]!=packet['generation'] or row[5]:raise SafeFailure('invalid_credentials')
  credentials=core.decrypt_credentials(row[2]);metadata=json.loads(row[3] or '{}')
  provider._Client.request=request
  result=await provider.fetch_source('stripe',credentials,metadata)
  for item in result.get('items') or []:core._provider_item('4','stripe',item)
  stage='complete';meta=result.get('metadata') or {};snapshot=meta.get('stripe_snapshot') or {}
  if (meta.get('stripe_account_id')!=EXPECTED_ACCOUNT or meta.get('mode')!='live' or
      meta.get('read_only_adapter') is not True or meta.get('aggregated_totals') is not False or
      meta.get('payouts_are_income') is not False or meta.get('coverage')!='bounded_recent_records' or
      snapshot.get('account_id')!=EXPECTED_ACCOUNT or snapshot.get('mode')!='live' or not snapshot.get('id') or
      not isinstance(result.get('items'),list) or len(result['items'])>400 or result.get('credentials')):raise SafeFailure('invalid_response')
  counts={name:meta.get('resources',{}).get(name,{}).get('fetched') for name in ('charges','refunds','disputes','payouts')}
  if any(type(n) is not int or not 0<=n<=100 for n in counts.values()) or not await owner():raise SafeFailure('invalid_response')
  return {'stage':'PRIVATE_SEEDED_FULL_FETCH_VALIDATED','success':True,'calls':calls,'resource_counts':counts,
    'database_writes':False,'connected':False,'seed_attempted':False}
 finally:
  provider._Client.request=original;await engine.dispose()
try:
 with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):report=asyncio.run(asyncio.wait_for(operation(),timeout=125))
except BaseException as error:
 code=getattr(error,'code','');codes=ERROR_CODES
 report={'stage':'PRIVATE_SEEDED_FULL_FETCH_REJECTED','success':False,'last_stage':stage if stage in SAFE_STAGES else 'configuration',
  'error_code':code if code in codes else 'unclassified','database_writes':False,'connected':False,'seed_attempted':False}
print(json.dumps(report,sort_keys=True))
'''.replace('RESOURCE_MAP', repr({'https://api.stripe.com/v1/'+name: name for name in RESOURCES})).replace(
        'EXPECTED_ACCOUNT', repr(transfer.ACCOUNT)).replace('ERROR_CODES', repr(diagnosis.ERRORS)).replace(
        'SAFE_STAGES', repr(diagnosis.STAGES))

def fetch_command(name, image, attempt):
    need(name == 't24-private-seeded-fetch-'+attempt and re.fullmatch('[a-f0-9]{32}', attempt) and
         re.fullmatch('sha256:[a-f0-9]{64}', image), 'EXACT_READONLY_FULL_FETCH_HELPER_REQUIRED')
    command = diagnosis.create_command('t24-private-stripe-diagnosis-'+attempt, image, attempt)
    command[command.index('--name')+1] = name
    command[command.index('--label')+1] = LABEL+'='+attempt
    command[-1] = helper_code()
    return command

def fetch_helper(info, identity, image, attempt):
    # Reuse the audited physical isolation checker after independently checking
    # this helper's exact fixed program/name/label. No Docker field is changed.
    need(info['Name'] == '/t24-private-seeded-fetch-'+attempt and
         info['Config'].get('Labels', {}).get(LABEL) == attempt and
         info['Config'].get('Cmd') == ['-c', helper_code()], 'EXACT_FULL_FETCH_PROGRAM_REQUIRED')
    from copy import deepcopy
    checked = deepcopy(info)
    checked['Config']['Labels'][diagnosis.LABEL] = attempt
    checked['Config']['Cmd'] = ['-c', diagnosis.helper_code()]
    diagnosis.checked_helper(checked, identity, image, attempt)
    return info

def fetch_report(raw):
    need(len(raw) <= 4096, 'BOUNDED_FULL_FETCH_REPORT_REQUIRED')
    value = json.loads(raw)
    need(isinstance(value, dict) and all(value.get(key) is False for key in
        ('database_writes', 'connected', 'seed_attempted')), 'READONLY_FULL_FETCH_PROOF_REQUIRED')
    if value.get('success') is not True:
        need(set(value) == {'stage','success','last_stage','error_code','database_writes','connected','seed_attempted'} and
             value.get('success') is False and value.get('stage') == 'PRIVATE_SEEDED_FULL_FETCH_REJECTED' and
             value.get('last_stage') in diagnosis.STAGES and value.get('error_code') in diagnosis.ERRORS | {'unclassified'},
             'SAFE_FULL_FETCH_FAILURE_REQUIRED')
        return value
    need(set(value) == {'stage','success','calls','resource_counts','database_writes','connected','seed_attempted'} and
         value['stage'] == 'PRIVATE_SEEDED_FULL_FETCH_VALIDATED' and isinstance(value['calls'], list) and
         6 <= len(value['calls']) <= 10 and value['calls'][:2] == ['account','balance'] and
         [name for index,name in enumerate(value['calls']) if index == 0 or name != value['calls'][index-1]] == list(RESOURCES) and
         all(value['calls'].count(name) <= (1 if name in RESOURCES[:2] else 2) for name in RESOURCES) and
         isinstance(value['resource_counts'], dict) and set(value['resource_counts']) == set(RESOURCES[2:]) and
         all(type(n) is int and 0 <= n <= 100 for n in value['resource_counts'].values()),
         'COMPLETE_BOUNDED_GET_ONLY_FETCH_REQUIRED')
    return value

def repair_root(args, *, create=False):
    root = args.candidate.parent/'seeded-repair'
    if create and not root.exists(): root.mkdir(mode=0o700)
    transfer.protected_directory(root)
    return root

def validate(args):
    receipt = checked_candidate(args); state, _, _, _, baseline = checked_lineage(receipt)
    compare_baseline(preflight(api_state=Path(baseline['ancestor_api_state']),
        api_state_sha256=baseline['ancestor_api_state_sha256']), baseline)
    need(args.baseline == Path(receipt['seeded_repair_lineage']['new_baseline']) and
         args.baseline_sha256 == receipt['baseline_sha256'], 'EXACT_FROZEN_REPAIR_BASELINE_REQUIRED')
    root = repair_root(args, create=True)
    attempt = uuid4().hex; path = root/('validation-'+attempt+'.json'); identity = None
    report = None
    try:
        command = fetch_command('t24-private-seeded-fetch-'+attempt, receipt['image_id'], attempt)
        identity = diagnosis.docker(command).decode().strip()
        need(re.fullmatch('[a-f0-9]{64}', identity), 'READONLY_FETCH_ID_REQUIRED')
        fetch_helper(diagnosis.inspect(identity), identity, receipt['image_id'], attempt)
        compare_baseline(preflight(api_state=Path(baseline['ancestor_api_state']),
            api_state_sha256=baseline['ancestor_api_state_sha256']), baseline)
        packet = transfer.encoded({'configuration': switch.role_configuration(transfer.read_protected(transfer.ENV), 'api'),
            'generation': baseline['stripe_authorization']['generation']})
        raw = diagnosis.docker(['start','--attach','--interactive',identity], input=packet, timeout=145)
        report = fetch_report(raw)
        compare_baseline(preflight(api_state=Path(baseline['ancestor_api_state']),
            api_state_sha256=baseline['ancestor_api_state_sha256']), baseline)
        value = {**report, 'format_version': 1, 'source_sha': args.source_sha,
            'candidate_sha256': args.candidate_sha256, 'image_id': receipt['image_id'],
            'baseline_sha256': args.baseline_sha256, 'seeded_repair_lineage_sha256': guard.digest(receipt['seeded_repair_lineage']),
            'snapshot_sha256': guard.digest(baseline['snapshot']), 'stripe_authorization': baseline['stripe_authorization'],
            'original_claims_preserved': True, 'production_services_changed': False, 'deployed': False}
        saved = switch.save(path, value)
        print(json.dumps({'stage': value['stage'], 'validation': str(path), 'validation_sha256': saved,
            'success': value['success'], 'deployed': False}, sort_keys=True))
        need(value['success'], 'READONLY_COMPLETE_FETCH_REJECTED_NO_RUNTIME_SWITCH')
    finally:
        if identity:
            info = fetch_helper(diagnosis.inspect(identity), identity, receipt['image_id'], attempt)
            need(not info['State']['Running'], 'READONLY_FETCH_OUTCOME_REQUIRES_OPERATOR_REVIEW')
            diagnosis.docker(['rm',identity])

def checked_validation(value, args, receipt, baseline):
    need(args.validation.parent == args.candidate.parent/'seeded-repair' and
         re.fullmatch('validation-[a-f0-9]{32}\\.json', args.validation.name), 'EXACT_FULL_FETCH_VALIDATION_PATH_REQUIRED')
    need(value.get('format_version') == 1 and value.get('stage') == 'PRIVATE_SEEDED_FULL_FETCH_VALIDATED' and
         value.get('success') is True and value.get('source_sha') == args.source_sha and
         value.get('candidate_sha256') == args.candidate_sha256 and value.get('image_id') == receipt['image_id'] and
         value.get('baseline_sha256') == receipt['baseline_sha256'] and
         value.get('seeded_repair_lineage_sha256') == guard.digest(receipt['seeded_repair_lineage']) and
         value.get('snapshot_sha256') == guard.digest(baseline['snapshot']) and
         value.get('stripe_authorization') == baseline['stripe_authorization'] and
         value.get('original_claims_preserved') is True and all(value.get(name) is False for name in
         ('database_writes','connected','seed_attempted','production_services_changed','deployed')),
         'ACTUAL_COMPLETE_FETCH_BEFORE_RUNTIME_REPAIR_REQUIRED')
    fields = {name: value[name] for name in ('stage','success','calls','resource_counts','database_writes','connected','seed_attempted')}
    fetch_report(transfer.encoded(fields))

def activate(args):
    receipt = checked_candidate(args); state, _, original, _, baseline = checked_lineage(receipt)
    checked_validation(fixed(args.validation, args.validation_sha256), args, receipt, baseline)
    compare_baseline(preflight(api_state=Path(baseline['ancestor_api_state']),
        api_state_sha256=baseline['ancestor_api_state_sha256']), baseline)
    root = repair_root(args)
    need(not (root/'activate-progress.json').exists(), 'EXCLUSIVE_SEEDED_REPAIR_ACTIVATION_REQUIRED')
    progress = {'format_version': 1, 'phase': 'PRIVATE_SEEDED_REPAIR_ACTIVATION_PREPARED',
        'source_sha': args.source_sha, 'candidate': str(args.candidate), 'candidate_sha256': args.candidate_sha256,
        'candidate_image': receipt['image_id'], 'attempt': uuid4().hex, 'old_ids': live.PRIVATE_IDS,
        'seeded_repair_lineage': receipt['seeded_repair_lineage'], 'baseline': receipt['seeded_repair_lineage']['new_baseline'],
        'baseline_sha256': receipt['baseline_sha256'], 'validation': str(args.validation),
        'validation_sha256': args.validation_sha256, 'ancestor_ids': state['new_ids'],
        'ancestor_attempt': state['attempt'], 'new_ids': {}, 'stage_names': {}, 'new_private': {},
        'role_environment_sha256': {}, 'stable_before': baseline['stable_records'],
        'frozen_snapshot': baseline['snapshot'], 'stripe_authorization': baseline['stripe_authorization'],
        'api_started': False, 'worker_started': False, 'bank_enabled': False, 'ai_enabled': False,
        'initializer_rerun': False, 'credential_seed_attempted': False, 'databases_restored': False,
        'public_assets_published': False, 'deployed': False}
    journal = root/'activate-progress.json'; switch.save(journal, progress)
    ancestor_runtime(state, original)
    progress['ancestor_stop_intent'] = True; switch.save(journal, progress, replace=True)
    switch.docker(['stop','--time','30',state['new_ids']['api']], timeout=45)
    ancestor_runtime(state, original, api_running=False, stable=False)
    need(guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS) == baseline['snapshot'], 'STOPPING_API_CHANGED_DATABASE')
    claims_unchanged(baseline)
    values = {}
    for role in ('api', 'worker'):
        values[role] = switch.role_configuration(transfer.read_protected(transfer.ENV), role)
        profile = root/(role+'-runtime.env'); transfer.write_exclusive(profile, switch.profile_bytes(values[role]))
        progress['role_environment_sha256'][role] = switch.sha(switch.profile_bytes(values[role]))
        switch.save(journal, progress, replace=True)
        switch.create_role(role, progress, values[role], profile, journal)
    retained = 't24-private-api-seeded-ancestor-'+progress['attempt']
    need(switch.inspect(retained, optional=True) is None and
         switch.inspect(state['new_ids']['api'])['Name'] == '/t24-private-api', 'EXACT_ANCESTOR_API_NAME_REQUIRED')
    progress['ancestor_retained_name'] = retained; switch.save(journal, progress, replace=True)
    switch.docker(['rename',state['new_ids']['api'],retained])
    switch.docker(['rename',progress['new_ids']['api'],'t24-private-api'])
    switch.docker(['start',progress['new_ids']['api']])
    progress['api_started'] = True; switch.save(journal, progress, replace=True)
    switch.wait_api(progress['new_ids']['api'])
    progress['new_private']['api'] = switch.staged_check(progress['new_ids']['api'], 'api', receipt['image_id'],
        progress['attempt'], args.source_sha, values['api'], running=True)
    switch.no_writers([progress['new_ids']['api']]); switch.runtime_guard(original); claims_unchanged(baseline)
    need(guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS) == baseline['snapshot'] and
         stripe_fingerprint(baseline['stripe_authorization']['generation']) == baseline['stripe_authorization'],
         'API_REPAIR_START_CHANGED_DATABASE_OR_AUTHORIZATION')
    value = {**progress, 'phase': 'PRIVATE_SEEDED_REPAIR_API_READY', 'services_switched': True,
        'customer_tables_verified': 83, 'local_auth_cache_verified': True}
    saved = switch.save(root/'api-state.json', value)
    print(json.dumps({'phase': value['phase'], 'api_state_sha256': saved,
        'api_id': progress['new_ids']['api'], 'worker_started': False, 'deployed': False}, sort_keys=True))

def checked_repair_state(args, receipt):
    need(args.state.parent == args.candidate.parent/'seeded-repair' and args.state.name in
         {'activate-progress.json','api-state.json','sync-progress.json','sync-state.json','finish-progress.json','switch-state.json'}, 'EXACT_SEEDED_REPAIR_STATE_PATH_REQUIRED')
    value = fixed(args.state, args.state_sha256)
    ancestor_state,_,_,_,baseline=checked_lineage(receipt)
    need(value.get('format_version') == 1 and value.get('source_sha') == args.source_sha and
         value.get('candidate_sha256') == args.candidate_sha256 and value.get('candidate_image') == receipt['image_id'] and
         value.get('seeded_repair_lineage') == receipt['seeded_repair_lineage'] and
         value.get('baseline') == receipt['seeded_repair_lineage']['new_baseline'] and
         value.get('baseline_sha256') == receipt['baseline_sha256'] and
         value.get('frozen_snapshot') == baseline['snapshot'] and
         value.get('stripe_authorization') == baseline['stripe_authorization'] and
         value.get('stable_before') == baseline['stable_records'] and
         value.get('ancestor_ids') == ancestor_state['new_ids'] and
         value.get('old_ids') == live.PRIVATE_IDS and
         value.get('bank_enabled') is False and value.get('ai_enabled') is False and
         value.get('initializer_rerun') is False and value.get('credential_seed_attempted') is False and
         re.fullmatch('[a-f0-9]{32}', value.get('attempt','')), 'EXACT_ACCEPTED_REPAIR_ATTEMPT_REQUIRED')
    return value

def sync_code():
    return '''import asyncio,io,json,os,sys
from contextlib import redirect_stdout,redirect_stderr
packet=json.load(sys.stdin)
async def operation():
 os.environ.update(packet['configuration'])
 from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
 from dependencies.private_workspace import valid_private_owner
 from services.private_workspace_worker import create_business_reader
 from services import private_workspace as core
 business=create_business_reader();readers=async_sessionmaker(business,expire_on_commit=False)
 private=create_async_engine('sqlite+aiosqlite:////private-data/workspace.db',connect_args={'timeout':15})
 sessions=async_sessionmaker(private,expire_on_commit=False)
 async def owner():
  async with readers() as db:return await valid_private_owner('4',db)
 try:
  if not await owner():raise RuntimeError('owner_changed')
  async with sessions() as db:
   result=await core.sync_source(db,'4','stripe',timeout_seconds=90,owner_validator=owner)
  counts=result.get('counts') or {}
  if set(counts)!={'created','updated'} or any(type(n) is not int or not 0<=n<=400 for n in counts.values()) or not await owner():raise RuntimeError('sync_not_verified')
  return {'stage':'PRIVATE_SEEDED_NORMAL_SYNC_SUCCEEDED','success':True,'counts':counts,'seed_attempted':False,'connected':False}
 finally:await private.dispose();await business.dispose()
try:
 with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):report=asyncio.run(asyncio.wait_for(operation(),timeout=125))
except BaseException:
 report={'stage':'PRIVATE_SEEDED_NORMAL_SYNC_REJECTED','success':False,'seed_attempted':False,'connected':False}
print(json.dumps(report,sort_keys=True))
'''

def sync_command(name,image,attempt):
    command = fetch_command('t24-private-seeded-fetch-'+attempt,image,attempt)
    need(name == 't24-private-seeded-sync-'+attempt,'EXACT_NORMAL_SYNC_HELPER_REQUIRED')
    command[command.index('--name')+1] = name
    command[command.index('--label')+1] = LABEL+'.sync='+attempt
    private_mount = 'type=bind,src='+str(live.PRIVATE_DB.parent)+',dst=/private-data,readonly'
    command[command.index(private_mount)] = private_mount.removesuffix(',readonly')
    command[-1] = sync_code()
    return command

def sync_helper(info,identity,image,attempt):
    need(info['Name'] == '/t24-private-seeded-sync-'+attempt and
         info['Config'].get('Labels',{}).get(LABEL+'.sync') == attempt and
         info['Config'].get('Cmd') == ['-c',sync_code()], 'EXACT_NORMAL_SYNC_PROGRAM_REQUIRED')
    binds = [m for m in info['Mounts'] if m.get('Type') == 'bind']
    need(len(binds)==2 and {(m['Source'],m['Destination'],m['RW']) for m in binds}=={
        (str(live.BUSINESS.parent),'/app/backend/data',False),(str(live.PRIVATE_DB.parent),'/private-data',True)},
        'NORMAL_SYNC_ONLY_PRIVATE_WRITE_MOUNT_REQUIRED')
    from copy import deepcopy
    checked = deepcopy(info)
    checked['Config']['Labels'][LABEL] = attempt
    checked['Config']['Cmd'] = ['-c',helper_code()]
    checked['Name'] = '/t24-private-seeded-fetch-'+attempt
    for mount in checked['Mounts']:
        if mount.get('Destination') == '/private-data': mount['RW'] = False
    fetch_helper(checked,identity,image,attempt)
    return info

def sync_audits():
    with sqlite3.connect(live.PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        columns=[row[1] for row in db.execute('PRAGMA table_info(private_sync_runs)')]
        values={}
        for row in db.execute('SELECT * FROM private_sync_runs ORDER BY id'):
            item=dict(zip(columns,row))
            need(item.get('owner_id')=='4','SYNC_AUDIT_OWNER_CHANGED')
            values[guard.digest(item['id'])]={'sha256':guard.digest(item),'source':item['source_id'],'status':item['status']}
    return values

def normal_sync(args):
    receipt=checked_candidate(args);_,after,original,_,baseline=checked_lineage(receipt)
    state=checked_repair_state(args,receipt)
    need(args.state.name=='api-state.json' and state.get('phase')=='PRIVATE_SEEDED_REPAIR_API_READY' and
         state.get('api_started') is True and state.get('worker_started') is False,'API_ONLY_STATE_BEFORE_NORMAL_SYNC_REQUIRED')
    root=repair_root(args);claims_unchanged(baseline);switch.runtime_guard(original)
    profiles={role:switch.role_configuration(transfer.read_protected(transfer.ENV),role) for role in ('api','worker')}
    api=switch.staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=True)
    need(api==state['new_private']['api'],'NORMAL_SYNC_API_RUNTIME_DRIFT')
    switch.staged_check(state['new_ids']['worker'],'worker',receipt['image_id'],state['attempt'],args.source_sha,profiles['worker'],running=False)
    switch.no_writers([state['new_ids']['api']])
    before=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    switch.schema_and_business_unchanged(before,after);switch.disabled_data(before)
    stable=switch.stable_records(live.PRIVATE_DB);audits=sync_audits()
    need(stripe_fingerprint(baseline['stripe_authorization']['generation'])==baseline['stripe_authorization'],
         'NORMAL_SYNC_AUTHORIZATION_CHANGED')
    progress={**state,'phase':'PRIVATE_SEEDED_NORMAL_SYNC_PREPARED','sync_helper_attempt':uuid4().hex,
        'sync_before_snapshot_sha256':guard.digest(before),'sync_before_audits':audits,'sync_before_stable':stable}
    journal=root/'sync-progress.json';switch.save(journal,progress)
    switch.docker(['stop','--time','30',state['new_ids']['api']],timeout=45)
    switch.staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=False)
    switch.no_writers()
    need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)==before,'STOPPING_SYNC_API_CHANGED_DATABASE')
    helper_attempt=progress['sync_helper_attempt'];identity=None
    try:
        identity=diagnosis.docker(sync_command('t24-private-seeded-sync-'+helper_attempt,receipt['image_id'],helper_attempt)).decode().strip()
        need(re.fullmatch('[a-f0-9]{64}',identity),'NORMAL_SYNC_HELPER_ID_REQUIRED')
        sync_helper(diagnosis.inspect(identity),identity,receipt['image_id'],helper_attempt)
        progress['sync_helper_id']=identity;switch.save(journal,progress,replace=True)
        switch.no_writers()
        raw=diagnosis.docker(['start','--attach','--interactive',identity],input=transfer.encoded({'configuration':profiles['api']}),timeout=145)
        need(len(raw)<=4096,'BOUNDED_NORMAL_SYNC_REPORT_REQUIRED');report=json.loads(raw)
        need(set(report)=={'stage','success','counts','seed_attempted','connected'} and
             report.get('stage')=='PRIVATE_SEEDED_NORMAL_SYNC_SUCCEEDED' and report.get('success') is True and
             report.get('seed_attempted') is False and report.get('connected') is False and
             set(report['counts'])=={'created','updated'} and all(type(n) is int and 0<=n<=400 for n in report['counts'].values()),
             'NORMAL_SYNC_FAILED_REQUIRES_EXPLICIT_REVIEW')
        info=sync_helper(diagnosis.inspect(identity),identity,receipt['image_id'],helper_attempt)
        need(not info['State']['Running'],'NORMAL_SYNC_OUTCOME_REQUIRES_OPERATOR_REVIEW')
        switch.no_writers()
        current=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
        switch.schema_and_business_unchanged(current,after);switch.disabled_data(current)
        switch.preserved(stable,switch.stable_records(live.PRIVATE_DB),allow_provider_changes=False)
        observed=sync_audits();added=observed.keys()-audits.keys()
        need(all(observed.get(k)==v for k,v in audits.items()) and len(added)==1 and
             all(observed[k]['source']=='stripe' and observed[k]['status']=='succeeded' for k in added),
             'EXACT_ONE_NEW_STRIPE_SYNC_AUDIT_REQUIRED')
        need(stripe_fingerprint(baseline['stripe_authorization']['generation'])==baseline['stripe_authorization'],
             'NORMAL_SYNC_CHANGED_ORIGINAL_STRIPE_CREDENTIAL')
        switch.checked_first_sync(current);claims_unchanged(baseline);switch.runtime_guard(original)
        progress['normal_sync_report']=report;switch.save(journal,progress,replace=True)
        switch.docker(['start',state['new_ids']['api']]);switch.wait_api(state['new_ids']['api'])
        progress['new_private']['api']=switch.staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=True)
        switch.no_writers([state['new_ids']['api']])
        need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)==current,'SYNC_API_RESTART_CHANGED_DATABASE')
        progress['phase']='PRIVATE_SEEDED_REPAIR_API_READY';progress['normal_sync_verified']=True
        saved=switch.save(root/'sync-state.json',progress)
        print(json.dumps({'phase':progress['phase'],'sync_state_sha256':saved,'normal_sync_verified':True,'worker_started':False,'deployed':False},sort_keys=True))
    finally:
        if identity:
            info=sync_helper(diagnosis.inspect(identity),identity,receipt['image_id'],helper_attempt)
            need(not info['State']['Running'],'NORMAL_SYNC_OUTCOME_REQUIRES_OPERATOR_REVIEW')
            diagnosis.docker(['rm',identity])

def finish(args):
    receipt = checked_candidate(args); ancestor_state, after, original, _, baseline = checked_lineage(receipt)
    state = checked_repair_state(args, receipt)
    need(args.state.name in {'api-state.json','sync-state.json'} and state.get('phase') == 'PRIVATE_SEEDED_REPAIR_API_READY' and
         state.get('api_started') is True and state.get('worker_started') is False and
         set(state.get('new_ids', {})) == {'api','worker'}, 'REPAIR_API_READY_WITH_WORKER_STOPPED_REQUIRED')
    root = repair_root(args); switch.runtime_guard(original); claims_unchanged(baseline)
    profiles = {role: switch.role_configuration(transfer.read_protected(transfer.ENV), role) for role in ('api','worker')}
    for role in profiles:
        need(switch.sha(transfer.read_protected(root/(role+'-runtime.env'))) == state['role_environment_sha256'][role] ==
             switch.sha(switch.profile_bytes(profiles[role])), 'ORIGINAL_REPAIR_ROLE_PROFILE_CHANGED')
    api = switch.staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=True)
    need(api == state['new_private']['api'], 'REPAIR_API_RUNTIME_CHANGED')
    switch.wait_api(state['new_ids']['api'])
    switch.staged_check(state['new_ids']['worker'],'worker',receipt['image_id'],state['attempt'],args.source_sha,profiles['worker'],running=False)
    switch.no_writers([state['new_ids']['api']])
    current = guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS)
    switch.schema_and_business_unchanged(current, after); switch.disabled_data(current)
    switch.preserved(state['stable_before'],switch.stable_records(live.PRIVATE_DB),allow_provider_changes=False)
    need(stripe_fingerprint(baseline['stripe_authorization']['generation']) == baseline['stripe_authorization'],
         'REPAIR_MUST_PRESERVE_ORIGINAL_STRIPE_CREDENTIAL')
    sync = switch.checked_first_sync(current)
    progress = {**state,'phase':'PRIVATE_SEEDED_REPAIR_WORKER_PREPARED','first_stripe_sync':sync}
    journal = root/'finish-progress.json'; switch.save(journal, progress)
    old_worker = switch.old_check('worker', original, running=False)
    need(old_worker['Name'] == '/t24-private-worker' and
         switch.inspect('t24-private-worker-repair-retained-'+state['attempt'],optional=True) is None,
         'EXACT_RETAINED_OLD_WORKER_NAME_REQUIRED')
    switch.docker(['rename',live.PRIVATE_IDS['worker'],'t24-private-worker-repair-retained-'+state['attempt']])
    switch.docker(['rename',state['new_ids']['worker'],'t24-private-worker'])
    switch.docker(['start',state['new_ids']['worker']]); progress['worker_started'] = True
    switch.save(journal,progress,replace=True); time.sleep(3)
    for role in profiles:
        progress['new_private'][role] = switch.staged_check(state['new_ids'][role],role,receipt['image_id'],state['attempt'],args.source_sha,profiles[role],running=True)
    switch.no_writers(progress['new_ids'].values()); switch.runtime_guard(original); claims_unchanged(baseline)
    final = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    switch.schema_and_business_unchanged(final,after); switch.disabled_data(final)
    switch.preserved(state['stable_before'],switch.stable_records(live.PRIVATE_DB))
    need(stripe_fingerprint(baseline['stripe_authorization']['generation']) == baseline['stripe_authorization'],
         'WORKER_CHANGED_ORIGINAL_STRIPE_CREDENTIAL')
    switch.checked_first_sync(final)
    value = {**progress,'phase':'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED','business':final['business'],
        'private_database':final['private'],'crm':original['crm'],'business_tables_verified':83,
        'customer_tables_verified':83,'customer_finance_unchanged':True,'original_runtime_env_unchanged':True,
        'services_switched':True,'deployed':True,'public_assets_published':False,'env_sha256':live.ENV_SHA,
        'original_claims_preserved':True,'rollback_restores_ancestor_api_only':True}
    saved = switch.save(root/'switch-state.json',value)
    print(json.dumps({'phase':value['phase'],'switch_state_sha256':saved,'new_ids':value['new_ids'],
        'bank_enabled':False,'ai_enabled':False,'deployed':True,'public_assets_published':False},sort_keys=True))

def checked_final(state,receipt):
    """Static publisher's explicit seeded-repair gate; never changes runtime."""
    ancestor_state,after,_,_,baseline=checked_lineage(receipt)
    need(state.get('format_version')==1 and state.get('phase')=='PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED' and
         state.get('source_sha')==receipt['source_sha'] and state.get('candidate_image')==receipt['image_id'] and
         state.get('seeded_repair_lineage')==receipt['seeded_repair_lineage'] and
         state.get('baseline_sha256')==receipt['baseline_sha256'] and
         state.get('frozen_snapshot')==baseline['snapshot'] and
         state.get('stripe_authorization')==baseline['stripe_authorization'] and
         state.get('api_started') is True and state.get('worker_started') is True and
         state.get('deployed') is True and state.get('public_assets_published') is False and
         state.get('business_tables_verified')==83 and
         all(state.get(name) is False for name in ('bank_enabled','ai_enabled','initializer_rerun',
             'credential_seed_attempted','databases_restored')) and state.get('original_claims_preserved') is True and
         set(state.get('new_ids',{}))=={'api','worker'} and set(state.get('new_private',{}))=={'api','worker'} and
         len(set(state['new_ids'].values()))==2 and
         not set(state['new_ids'].values()) & {live.CRM_ID,*live.PRIVATE_IDS.values(),*ancestor_state['new_ids'].values()},
         'ACCEPTED_FINISHED_SEEDED_REPAIR_REQUIRED')
    args=SimpleNamespace(source_sha=state['source_sha'],candidate=Path(state['candidate']),
        candidate_sha256=state['candidate_sha256'],validation=Path(state['validation']),validation_sha256=state['validation_sha256'])
    need(args.candidate==Path(receipt['seeded_repair_lineage']['new_baseline']).parent/'candidate.json' and
         fixed(args.candidate,args.candidate_sha256)==receipt,'STATIC_EXACT_REPAIR_CANDIDATE_REQUIRED')
    checked_validation(fixed(args.validation,args.validation_sha256),args,receipt,baseline)
    current=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    switch.schema_and_business_unchanged(current,after);switch.disabled_data(current)
    switch.preserved(baseline['stable_records'],switch.stable_records(live.PRIVATE_DB))
    need(stripe_fingerprint(baseline['stripe_authorization']['generation'])==baseline['stripe_authorization'],
         'STATIC_REPAIR_ORIGINAL_STRIPE_AUTHORIZATION_CHANGED')
    switch.checked_first_sync(current)
    return state

def rollback(args):
    receipt = checked_candidate(args); ancestor_state, after, original, _, baseline = checked_lineage(receipt)
    state = checked_repair_state(args, receipt); root = repair_root(args)
    switch.runtime_guard(original); claims_unchanged(baseline)
    profiles = {role: switch.role_configuration(transfer.read_protected(transfer.ENV),role) for role in ('api','worker')}
    owned = dict(state.get('new_ids',{}))
    for role, name in state.get('stage_names',{}).items():
        if role not in owned:
            found = switch.inspect(name,optional=True)
            if found:
                switch.staged_check(found['Id'],role,receipt['image_id'],state['attempt'],args.source_sha,profiles[role],require_stable=False)
                owned[role] = found['Id']
    for role in ('worker','api'):
        if role in owned:
            switch.staged_check(owned[role],role,receipt['image_id'],state['attempt'],args.source_sha,profiles[role],require_stable=False)
            if switch.inspect(owned[role])['State']['Running']: switch.docker(['stop','--time','30',owned[role]],timeout=45)
            info = switch.inspect(owned[role])
            if info['Name'] == '/t24-private-'+role:
                name = 't24-private-'+role+'-repair-failed-'+state['attempt']
                need(switch.inspect(name,optional=True) is None,'EXCLUSIVE_REPAIR_ROLLBACK_NAME_REQUIRED')
                switch.docker(['rename',owned[role],name])
    if state.get('sync_helper_attempt'):
        helper_attempt=state['sync_helper_attempt']
        need(re.fullmatch('[a-f0-9]{32}',helper_attempt),'EXACT_INTERRUPTED_SYNC_ATTEMPT_REQUIRED')
        helper=switch.inspect('t24-private-seeded-sync-'+helper_attempt,optional=True)
        if helper:
            sync_helper(helper,helper['Id'],receipt['image_id'],helper_attempt)
            need(not state.get('sync_helper_id') or state['sync_helper_id']==helper['Id'],
                 'INTERRUPTED_SYNC_HELPER_ID_CHANGED')
            if helper['State']['Running']:switch.docker(['stop','--time','30',helper['Id']],timeout=45)
    ancestor_info=switch.inspect(ancestor_state['new_ids']['api'])
    if ancestor_info['State']['Running']:
        ancestor_runtime(ancestor_state,original)
        switch.docker(['stop','--time','30',ancestor_state['new_ids']['api']],timeout=45)
    ancestor_runtime(ancestor_state,original,api_running=False,stable=False)
    current = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    switch.schema_and_business_unchanged(current,after); switch.disabled_data(current)
    switch.preserved(baseline['stable_records'],switch.stable_records(live.PRIVATE_DB))
    need(stripe_fingerprint(baseline['stripe_authorization']['generation']) == baseline['stripe_authorization'],
         'ROLLBACK_ORIGINAL_STRIPE_AUTHORIZATION_CHANGED')
    if not state.get('api_started'):
        need(current == baseline['snapshot'],'PRE_API_REPAIR_FAILURE_CHANGED_DATABASE')
    for role, identity in (('api',ancestor_state['new_ids']['api']),('worker',live.PRIVATE_IDS['worker'])):
        info = switch.inspect(identity)
        if info['Name'] != '/t24-private-'+role:
            need(switch.inspect('t24-private-'+role,optional=True) is None,'RESTORED_ANCESTOR_ROLE_NAME_COLLISION')
            switch.docker(['rename',identity,'t24-private-'+role])
    switch.docker(['start',ancestor_state['new_ids']['api']]); switch.wait_api(ancestor_state['new_ids']['api'])
    api = switch.staged_check(ancestor_state['new_ids']['api'],'api',ancestor_state['candidate_image'],ancestor_state['attempt'],
        ancestor_state['source_sha'],profiles['api'],running=True)
    switch.no_writers([ancestor_state['new_ids']['api']]); claims_unchanged(baseline); switch.runtime_guard(original)
    need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS) == current,'ROLLBACK_API_START_CHANGED_DATABASE')
    value = {'format_version':1,'phase':'PRIVATE_SEEDED_REPAIR_ROLLED_BACK_ANCESTOR_API','source_sha':args.source_sha,
        'candidate_sha256':args.candidate_sha256,'attempt':state['attempt'],'ancestor_api_runtime':api,
        'seeded_repair_lineage':receipt['seeded_repair_lineage'],'worker_started':False,'databases_restored':False,
        'original_claims_preserved':True,'stripe_credentials_preserved':True,'customer_tables_verified':83,'deployed':False}
    saved = switch.save(root/('rollback-'+state['attempt']+'.json'),value)
    print(json.dumps({'phase':value['phase'],'receipt_sha256':saved,'worker_started':False,'deployed':False},sort_keys=True))

def cli(argv=None):
    parser = SafeParser(description=__doc__); sub = parser.add_subparsers(dest='phase',required=True)
    read = sub.add_parser('preflight')
    read.add_argument('--ancestor-api-state',type=Path,required=True); read.add_argument('--ancestor-api-state-sha256',required=True)
    for phase in ('validate','activate','sync','finish','rollback'):
        p = sub.add_parser(phase); p.add_argument('--execute',action='store_true'); p.add_argument('--source-sha',required=True)
        p.add_argument('--candidate',type=Path,required=True); p.add_argument('--candidate-sha256',required=True)
        if phase == 'validate':
            p.add_argument('--baseline',type=Path,required=True); p.add_argument('--baseline-sha256',required=True)
        elif phase == 'activate':
            p.add_argument('--validation',type=Path,required=True); p.add_argument('--validation-sha256',required=True)
        else:
            p.add_argument('--state',type=Path,required=True); p.add_argument('--state-sha256',required=True)
    try:
        args = parser.parse_args(argv); os.umask(0o077)
        if args.phase == 'preflight':
            print(json.dumps(preflight(api_state=args.ancestor_api_state,api_state_sha256=args.ancestor_api_state_sha256),sort_keys=True)); return 0
        need(args.execute and re.fullmatch('[a-f0-9]{40}',args.source_sha),'EXPLICIT_REVIEWED_REPAIR_EXECUTION_REQUIRED')
        with switch.release_lock(): (normal_sync if args.phase=='sync' else globals()[args.phase])(args)
        return 0
    except Exception as error:
        code = str(error) if isinstance(error,(RepairError,switch.SwitchError,transfer.TransferError,seed.SeedError,diagnosis.DiagnosisError)) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else 'SEEDED_REPAIR_REJECTED'
        print(json.dumps({'stage':'PRIVATE_SEEDED_REPAIR_REJECTED','error':code,'deployed':False},sort_keys=True)); return 1

if __name__ == '__main__': raise SystemExit(cli())
