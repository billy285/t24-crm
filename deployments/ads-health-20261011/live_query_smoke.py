#!/usr/bin/env python3
"""Query the pinned candidate's Ads adapter without saving any provider data.

The only mutable object is a separately labelled temporary container, removed
by its recorded ID. Both production database directories are physical read-only
binds. Tokens stay in memory; refreshed credentials are intentionally discarded.
No application, worker, migration, sync orchestration or storage initializer runs.
"""
import argparse
from datetime import datetime, timedelta, timezone
import inspect as source_inspect
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
from types import ModuleType
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

SOURCE = 'dd8061ca30b91554f3f431446616dffc12c81b7a'
VERSION = 'dc6e92e22ef7'
RELEASE = Path('/opt/t24-crm/releases/ads-health-dd8061c-20261011')
TARGET = '7539806760'
BUCKETS = ('problem', 'attention', 'healthy', 'paused', 'unknown')
PROVIDER_CODES = {'not_configured', 'invalid_credentials', 'authorization_expired', 'access_denied',
                  'rate_limited', 'upstream_unavailable', 'upstream_timeout', 'invalid_response',
                  'request_not_allowed', 'sync_limit', 'ads_project_not_approved', 'ads_account_changed',
                  'ads_manager_account'}


def validate_batch(batch, now=None):
    """Return only safe shape/count evidence; never campaign identities or money."""
    def require(condition):
        if not condition:
            raise ValueError('ADS_HEALTH_BATCH_SHAPE_INVALID')
    require(isinstance(batch, dict) and batch.get('balances') == [])
    items, metadata = batch.get('items'), batch.get('metadata')
    require(isinstance(items, list) and 0 < len(items) <= 100 and isinstance(metadata, dict))
    require(metadata.get('ads_customer_id') == TARGET and metadata.get('api_version') == 'v25' and
            metadata.get('record_limit') == 100 and metadata.get('aggregated_totals') is False)
    snapshot = metadata.get('ads_snapshot')
    require(isinstance(snapshot, dict) and snapshot.get('inventory_count') == len(items) and
            snapshot.get('record_limit') == 100)
    UUID(snapshot.get('id', ''))
    observed = datetime.fromisoformat(snapshot.get('observed_at', '').replace('Z', '+00:00'))
    now = now or datetime.now(timezone.utc)
    require(observed.tzinfo is not None and -60 <= (now-observed).total_seconds() <= 300)
    zone = ZoneInfo(snapshot.get('account_timezone', ''))
    today = observed.astimezone(zone).date()
    require(type(snapshot.get('inventory_complete')) is bool and type(snapshot.get('metrics_complete')) is bool)
    counts = {bucket: 0 for bucket in BUCKETS}
    ids = set()
    for item in items:
        require(isinstance(item, dict) and item.get('kind') == 'campaign' and item.get('amount_minor') is None)
        evidence = item.get('evidence')
        require(isinstance(evidence, dict) and evidence.get('customer_id') == TARGET and
                evidence.get('accounting_effect') == 'none' and evidence.get('period') == 'LAST_30_DAYS' and
                evidence.get('ads_snapshot_id') == snapshot['id'])
        campaign = evidence.get('campaign_id')
        require(isinstance(campaign, str) and campaign.isdigit() and campaign not in ids and
                item.get('external_id') == TARGET+':'+campaign+':last_30_days')
        ids.add(campaign)
        health = evidence.get('ads_health')
        require(isinstance(health, dict) and health.get('version') == 1 and health.get('snapshot_id') == snapshot['id'] and
                health.get('observed_at') == snapshot['observed_at'] and health.get('account_timezone') == snapshot['account_timezone'] and
                health.get('local_date') == today.isoformat() and health.get('bucket') in BUCKETS)
        require(health.get('currency') == str(item.get('currency', '')).upper() and
                re.fullmatch('[A-Z]{3}', health['currency']) is not None)
        coverage = health.get('coverage')
        require(coverage == {key: snapshot[key] for key in ('inventory_complete', 'metrics_complete')})
        metrics, periods = health.get('metrics'), health.get('periods')
        require(isinstance(metrics, dict) and isinstance(periods, dict))
        for key, start, end in (('yesterday', 1, 1), ('last_7_days', 7, 1), ('previous_7_days', 14, 8), ('last_30_days', 30, 1)):
            require(periods.get(key) == {'start': (today-timedelta(days=start)).isoformat(),
                                         'end': (today-timedelta(days=end)).isoformat()} and key in metrics)
            metric = metrics[key]
            if snapshot['metrics_complete']:
                require(isinstance(metric, dict) and set(metric) == {'impressions', 'clicks', 'cost_micros', 'conversions'})
                require(all(type(value) in (int, float) and 0 <= value <= 9_000_000_000_000_000 for value in metric.values()))
            else:
                require(metric is None)
        counts[health['bucket']] += 1
    return {'stage': 'ADS_HEALTH_LIVE_QUERY_VERIFIED', 'api_version': 'v25', 'health_version': 1,
            'campaign_count': len(items), 'bucket_counts': counts,
            'inventory_complete': snapshot['inventory_complete'], 'metrics_complete': snapshot['metrics_complete'],
            'fixed_periods_verified': True, 'target_verified': True, 'accounting_effect_none': True,
            'provider_data_saved': False, 'refreshed_credentials_saved': False}


def query_code():
    # Only the read adapter is imported. In particular the core module is not
    # imported because its dependency graph includes the storage layer.
    return ("import asyncio,base64,hashlib,io,json,os,re,sqlite3\n"
            "from contextlib import redirect_stdout,redirect_stderr\n"
            "from datetime import datetime,timedelta,timezone\n"
            "from uuid import UUID\nfrom zoneinfo import ZoneInfo\n"
            "from cryptography.fernet import Fernet\n"
            "TARGET="+repr(TARGET)+"\nBUCKETS="+repr(BUCKETS)+"\nPROVIDER_CODES="+repr(PROVIDER_CODES)+"\n"+
            source_inspect.getsource(validate_batch)+"\n"+
            """report=None
try:
 with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
  from services import private_workspace_providers as provider
  assert provider.ADS_VERSION=='v25'
  assert os.environ.get('PRIVATE_WORKSPACE_OWNER_IDS')=='4'
  assert os.environ.get('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID')==TARGET
  assert not os.environ.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID','').strip()
  with sqlite3.connect('file:/private-data/workspace.db?mode=ro',uri=True,timeout=15) as db:
   db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
   rows=db.execute("SELECT status,metadata_json,encrypted_credentials FROM private_connections WHERE owner_id='4' AND source_id='google_ads'").fetchall()
  assert len(rows)==1 and rows[0][0]=='connected' and rows[0][2]
  metadata=json.loads(rows[0][1]);assert metadata.get('ads_customer_id')==TARGET and metadata.get('connection_mode')=='oauth' and metadata.get('read_only_adapter') is True
  assert 'https://www.googleapis.com/auth/adwords' in (metadata.get('scope') or '').split()
  key=os.environ['PRIVATE_WORKSPACE_ENCRYPTION_KEY'].strip();assert len(key)>=32
  cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
  credentials=json.loads(cipher.decrypt(rows[0][2].encode()));assert isinstance(credentials,dict) and credentials
  batch=asyncio.run(provider.fetch_source('google_ads',credentials,metadata))
  report=validate_batch(batch)
except BaseException as error:
 code=getattr(error,'code',None)
 report={'stage':'ADS_HEALTH_LIVE_QUERY_FAILED','provider_error_code':code if isinstance(code,str) and code in PROVIDER_CODES else 'safe_validation_failure'}
print(json.dumps(report,sort_keys=True))
raise SystemExit(0 if report['stage']=='ADS_HEALTH_LIVE_QUERY_VERIFIED' else 1)
""")


def create_command(name, attempt, image):
    return ['docker', 'create', '--name', name, '--label', 't24.ads_health.live_query='+attempt,
            '--restart', 'no', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--network', 'bridge', '--no-healthcheck', '--log-driver', 'none',
            '--env-file', '/opt/t24-crm/private-workspace/config/runtime.env',
            '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--mount', 'type=bind,src=/opt/t24-crm/app/data,dst=/app/backend/data,readonly',
            '--mount', 'type=bind,src=/opt/t24-crm/private-workspace/data,dst=/private-data,readonly',
            '--entrypoint', 'python', image, '-c', query_code()]


def container_check(module, identity, image, attempt):
    info = module.inspect(identity)
    module.need(info['Id'] == identity and info['Image'] == image and identity not in {*module.OLD_IDS.values(), module.CRM_ID} and
                info['Config'].get('Labels', {}).get('t24.ads_health.live_query') == attempt, 'QUERY_CONTAINER_IDENTITY_DRIFT')
    host = info['HostConfig']
    module.need(host['ReadonlyRootfs'] and host.get('CapDrop') == ['ALL'] and
                host.get('SecurityOpt') in (['no-new-privileges'], ['no-new-privileges:true']) and
                host.get('NetworkMode') == 'bridge' and host.get('RestartPolicy', {}).get('Name') == 'no' and
                host.get('LogConfig', {}).get('Type') == 'none' and not host.get('PortBindings') and
                not host.get('Privileged') and not host.get('CapAdd') and not host.get('Devices') and
                not host.get('DeviceRequests') and not host.get('Binds') and not host.get('Tmpfs') and
                host.get('PidMode', '') == '' and host.get('IpcMode') == 'private' and host.get('UTSMode', '') == '',
                'QUERY_CONTAINER_ISOLATION_DRIFT')
    module.need(len(info['Mounts']) == 2 and {(m['Type'], m['Source'], m['Destination'], m['RW']) for m in info['Mounts']} ==
                {('bind', '/opt/t24-crm/app/data', '/app/backend/data', False),
                 ('bind', '/opt/t24-crm/private-workspace/data', '/private-data', False)}, 'QUERY_DATABASE_MOUNTS_MUST_BE_READONLY')
    module.need(info['Config']['Entrypoint'] == ['python'] and info['Config']['Cmd'] == ['-c', query_code()], 'QUERY_COMMAND_DRIFT')
    return info


def safe_report(raw, success):
    value = json.loads(raw)
    if not success:
        if set(value) != {'stage', 'provider_error_code'} or value['stage'] != 'ADS_HEALTH_LIVE_QUERY_FAILED' or value['provider_error_code'] not in PROVIDER_CODES | {'safe_validation_failure'}:
            raise ValueError('UNSAFE_QUERY_FAILURE_OUTPUT')
        return value
    keys = {'stage','api_version','health_version','campaign_count','bucket_counts','inventory_complete','metrics_complete',
            'fixed_periods_verified','target_verified','accounting_effect_none','provider_data_saved','refreshed_credentials_saved'}
    if set(value) != keys or value['stage'] != 'ADS_HEALTH_LIVE_QUERY_VERIFIED' or value['api_version'] != 'v25' or value['health_version'] != 1:
        raise ValueError('UNSAFE_QUERY_SUCCESS_OUTPUT')
    count = value['campaign_count']; buckets = value['bucket_counts']
    if type(count) is not int or not 0 < count <= 100 or not isinstance(buckets, dict) or set(buckets) != set(BUCKETS) or any(type(n) is not int or n < 0 for n in buckets.values()) or sum(buckets.values()) != count:
        raise ValueError('UNSAFE_QUERY_COUNT_OUTPUT')
    if any(type(value[key]) is not bool for key in keys-{'stage','api_version','health_version','campaign_count','bucket_counts'}) or not all(value[key] for key in ('fixed_periods_verified','target_verified','accounting_effect_none')) or value['provider_data_saved'] or value['refreshed_credentials_saved']:
        raise ValueError('UNSAFE_QUERY_PROTECTION_OUTPUT')
    return value


def main(args):
    # Import only a separately hash-reviewed deployment helper, never its main.
    import hashlib
    path = RELEASE/'switch_ads_health_upgrade.py'
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 131072:
        raise RuntimeError('PROTECTED_SWITCH_HELPER_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        seen=os.fstat(stream.fileno())
        if (seen.st_dev,seen.st_ino)!=(info.st_dev,info.st_ino):
            raise RuntimeError('SWITCH_HELPER_CHANGED_DURING_READ')
        blob=stream.read(131073)
    if not re.fullmatch('[a-f0-9]{40}', SOURCE) or not re.fullmatch('[a-f0-9]{12}', VERSION) or '__' in str(RELEASE):
        raise RuntimeError('REVIEWED_CONSTANTS_MUST_BE_STAMPED')
    if not re.fullmatch('[a-f0-9]{64}', args.switch_script_sha256) or hashlib.sha256(blob).hexdigest() != args.switch_script_sha256:
        raise RuntimeError('REVIEWED_SWITCH_HELPER_HASH_REQUIRED')
    module=ModuleType('verified_ads_health_switch');module.__file__=str(path)
    exec(compile(blob,str(path),'exec'),module.__dict__)
    module.secure(path, mode=0o600);module.secure(RELEASE, True, 0o700)
    module.need(os.geteuid() == 0 and socket.gethostname() == module.HOST and module.SOURCE == SOURCE and
                module.VERSION == VERSION and module.RELEASE == RELEASE, 'QUERY_SERVER_OR_SOURCE_DRIFT')
    module.need(re.fullmatch('[a-f0-9]{64}', args.candidate_sha256), 'PINNED_CANDIDATE_HASH_REQUIRED')
    candidate, _ = module.candidate_check(args)
    baseline_blob=module.read_protected(RELEASE/'readonly-baseline.json',2*1024**2)
    module.need(module.sha(baseline_blob) == module.BASELINE_SHA, 'READONLY_BASELINE_HASH_DRIFT')
    baseline=json.loads(baseline_blob)
    env = module.read_protected(module.ENV);values = module.parse_env(env)
    module.env_check(env, env, values['PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT'])
    def runtime():
        module.crm_check()
        for role in ('api', 'worker'):
            module.old_check(role, candidate['running_baseline'], values, True)
        module.need(module.sha(module.read_nginx()) == module.NGINX_SHA and module.read_protected(module.ENV) == env, 'QUERY_RUNTIME_OR_ENVIRONMENT_DRIFT')
        module.need(module.business_fingerprints() == baseline['business_fingerprints'], 'QUERY_BUSINESS_FINGERPRINT_DRIFT')
        snapshot = module.private_snapshot();module.connected_ads_check(snapshot)
        module.connected_gmail_check(snapshot, values['PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT'])
        return snapshot
    before = runtime();identity = None;attempt = uuid4().hex
    try:
        identity = module.run(create_command('t24-ads-health-query-'+attempt[:12], attempt, candidate['image_id']), 'QUERY_CREATE_FAILED').decode().strip()
        module.need(re.fullmatch('[a-f0-9]{64}', identity), 'QUERY_CREATED_ID_REQUIRED')
        container_check(module, identity, candidate['image_id'], attempt)
        result = subprocess.run(['docker','start','--attach',identity],capture_output=True,timeout=90,check=False)
        info = container_check(module, identity, candidate['image_id'], attempt)
        module.need(info['State']['Status'] == 'exited' and len(result.stdout) <= 4096, 'QUERY_RESPONSE_OR_STATE_INVALID')
        report = safe_report(result.stdout, result.returncode == 0 and info['State']['ExitCode'] == 0)
        module.check_private_preserved(before, runtime())
        if report['stage'] != 'ADS_HEALTH_LIVE_QUERY_VERIFIED':
            raise RuntimeError('LIVE_QUERY_'+report['provider_error_code'].upper())
        report.update({'source_sha':SOURCE,'candidate_sha256':args.candidate_sha256,'business_tables_verified':83,
                       'production_services_modified':False,'databases_readonly':True,'existing_connections_preserved':True})
        print(json.dumps(report,sort_keys=True))
    finally:
        if identity:
            # Never use a guessed container name or remove a running service.
            container_check(module, identity, candidate['image_id'], attempt)
            module.run(['docker','rm','--force',identity],'QUERY_OWN_CONTAINER_CLEANUP_FAILED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--switch-script-sha256', required=True)
    try:
        main(parser.parse_args())
    except BaseException as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'ADS_HEALTH_LIVE_QUERY_FAILED'
        print('ADS_HEALTH_LIVE_QUERY_ERROR '+code, flush=True)
        raise SystemExit(1) from None
