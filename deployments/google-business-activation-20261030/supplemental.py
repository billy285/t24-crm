"""Read-only logging facts: metadata and names only, never values or file content."""
import json
import os
import pwd
import grp
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
import core as c
import diagnostics as d

FORWARDER_MARKERS = ('filebeat', 'fluent', 'promtail', 'vector', 'rsyslog', 'syslog-ng', 'syslogng',
    'logtail', 'ilogtail', 'datadog', 'dd-agent', 'otel', 'opentelemetry', 'logstash', 'td-agent',
    'splunk', 'newrelic', 'new-relic', 'cloudwatch', 'stackdriver', 'google-cloud-ops', 'google_cloud_op',
    'grafana-agent', 'alloy', 'journal-upload', 'journal-remote', 'systemd-journal',
    'elastic-agent', 'apm-server', 'aliyun', 'aegis', 'cloudmonitor', 'cms-agent', 'argusagent',
    'cloud-assist', 'assist_daemon', 'alimonitor', 'telescope')
PACKAGE_MARKERS = ('opentelemetry', 'sentry', 'ddtrace', 'datadog', 'elastic-apm', 'elasticapm',
    'newrelic', 'logfire', 'honeycomb', 'bugsnag', 'rollbar', 'skywalking', 'instana', 'scout-apm',
    'google-cloud-logging', 'structlog', 'python-json-logger', 'loguru', 'fluent', 'splunk')
SAFE_NAME = re.compile(r'[A-Za-z0-9_.:+-]{1,100}\Z')


def matched_names(names, markers, *, unit=False):
    result = set()
    for value in names:
        if not isinstance(value, str):
            continue
        # Unit instances can contain tenant/credential-like arbitrary text. Keep
        # the actual unit stem while hiding any instantiated identifier.
        cleaned = (value.partition('@')[0] + '@INSTANCE_REDACTED.' + value.rsplit('.', 1)[-1]) if unit and '@' in value else value
        if not any(marker in cleaned.lower() for marker in markers):
            continue
        if unit:
            if not re.fullmatch(r'[A-Za-z0-9_.:+@-]{1,200}', cleaned):
                continue
        elif not SAFE_NAME.fullmatch(cleaned):
            continue
        result.add(cleaned)
    return sorted(result)


def worker_identity(active):
    rows = re.findall(rb'(?m)^\s*user\s+([A-Za-z_][A-Za-z0-9_.-]*)(?:\s+([A-Za-z_][A-Za-z0-9_.-]*))?\s*;', active)
    c.need(len(rows) == 1, 'EXACT_CONFIGURED_NGINX_WORKER_USER_REQUIRED')
    username = rows[0][0].decode('ascii')
    row = pwd.getpwnam(username)
    group = rows[0][1].decode('ascii') if rows[0][1] else None
    return {'configured_user': username, 'uid': row.pw_uid, 'primary_gid': row.pw_gid,
        'configured_group': group, 'effective_gid': grp.getgrnam(group).gr_gid if group else row.pw_gid,
        'explicit_group_configured': bool(group)}


def safe_resolved(path):
    resolved = str(path.resolve(strict=True))
    if re.fullmatch(r'/(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]*', resolved) and len(resolved) <= 512:
        return resolved
    return '[NONSTANDARD_PATH_REDACTED]'


def stat_logs(logging_rows):
    paths = sorted({row['destination'] for row in logging_rows if row.get('destination_type') == 'local-nginx-log'})
    result = []
    for name in paths:
        path = Path(name)
        c.need(path.is_absolute() and path.parent == Path('/var/log/nginx'), 'EXACT_NGINX_LOG_PATH_REQUIRED')
        parent = path.parent.lstat()
        item = {'path': name, 'parent': {'uid': parent.st_uid, 'gid': parent.st_gid,
            'mode': format(stat.S_IMODE(parent.st_mode), '04o'), 'nlink': parent.st_nlink,
            'is_directory': stat.S_ISDIR(parent.st_mode), 'resolved_path': safe_resolved(path.parent)}}
        try:
            row = path.lstat()
        except FileNotFoundError:
            item['exists'] = False
        else:
            item.update(exists=True, uid=row.st_uid, gid=row.st_gid, mode=format(stat.S_IMODE(row.st_mode), '04o'),
                nlink=row.st_nlink, is_regular_file=stat.S_ISREG(row.st_mode), is_symlink=stat.S_ISLNK(row.st_mode))
            try:
                item['resolved_path'] = safe_resolved(path)
            except FileNotFoundError:
                item['resolved_path'] = '[MISSING_SYMLINK_TARGET]'
        result.append(item)
    return result


def process_names(root=Path('/proc')):
    names = set()
    for path in root.iterdir():
        if not path.name.isdecimal():
            continue
        try:
            with (path / 'comm').open('rb') as stream:
                blob = stream.read(257)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue  # Process snapshots are inherently racy; no absence claim.
        if len(blob) <= 256:
            value = blob.decode('ascii', errors='replace').strip()
            if SAFE_NAME.fullmatch(value):
                names.add(value)
    return sorted(names)


def crm_probe_source():
    # Standard-library metadata inspection only. Never import/invoke telemetry
    # packages, read argv/environment/config values or inspect private services.
    return '''import json,re,sys,sysconfig
from pathlib import Path
from importlib import metadata
sys.dont_write_bytecode=True
safe=re.compile(r'[A-Za-z0-9_.:+-]{1,100}\\Z')
markers=''' + repr(PACKAGE_MARKERS) + '''
processes=set()
for p in Path('/proc').iterdir():
 if not p.name.isdecimal():continue
 try:
  with (p/'comm').open('rb') as f:b=f.read(257)
 except (FileNotFoundError,PermissionError,ProcessLookupError):continue
 if len(b)<=256:
  name=b.decode('ascii',errors='replace').strip()
  if safe.fullmatch(name):processes.add(name)
packages=set()
distribution_paths=sorted({sysconfig.get_path(name) for name in ('purelib','platlib') if sysconfig.get_path(name)})
for distribution in metadata.distributions(path=distribution_paths):
 name=distribution.metadata.get('Name','')
 if safe.fullmatch(name) and any(marker in name.lower() for marker in markers):packages.add(name)
print(json.dumps({'process_comm_names':sorted(processes),'matching_installed_package_names':sorted(packages)},sort_keys=True))
'''


def validate_crm_probe(blob):
    c.need(isinstance(blob, bytes) and len(blob) <= 16384, 'CRM_NAME_PROBE_SIZE_REJECTED')
    value = c.strict_json(blob)
    c.need(isinstance(value, dict) and set(value) == {'process_comm_names', 'matching_installed_package_names'}, 'CRM_NAME_PROBE_FIELDS_REJECTED')
    for key, rows in value.items():
        c.need(isinstance(rows, list) and len(rows) <= 200 and rows == sorted(set(rows)) and
            all(isinstance(name, str) and SAFE_NAME.fullmatch(name) for name in rows), 'CRM_NAME_PROBE_VALUES_REJECTED')
        if key == 'matching_installed_package_names':
            c.need(all(any(marker in name.lower() for marker in PACKAGE_MARKERS) for name in rows), 'CRM_PACKAGE_FILTER_REJECTED')
    return value


def proof():
    c.server_guard()
    prior_facts = d.proof()
    m = c.legacy()
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    info = m.inspect('t24-crm')
    c.need(m.runtime(info) == prior['crm'] and info['State']['Running'] and info['Image'] == c.IMAGE, 'EXACT_CRM_RUNTIME_REQUIRED')
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    c.need(c.H(active) == d.ACTIVE_NGINX_SHA, 'ACTUAL_PREFLIGHT_NGINX_DRIFT')
    identity = worker_identity(active)
    logs = stat_logs(prior_facts['nginx_logging_directives'])
    units_blob = c.run(['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend', '--no-pager', '--plain'], 'ACTIVE_SERVICE_NAMES_FAILED')
    c.need(len(units_blob) <= 2 * 1024 * 1024, 'SERVICE_LIST_SIZE_REJECTED')
    unit_names = [line.split(None, 1)[0].decode('ascii', errors='replace') for line in units_blob.splitlines() if line.strip()]
    host_units = matched_names(unit_names, FORWARDER_MARKERS, unit=True)
    host_processes = matched_names(process_names(), FORWARDER_MARKERS)
    # Exact immutable CRM identity, never t24-private-* or arbitrary containers.
    c.need(info['Id'] == prior['crm']['id'] and bool(re.fullmatch('[a-f0-9]{64}', info['Id'])), 'EXACT_CRM_ID_REQUIRED')
    crm = validate_crm_probe(c.run(['docker', 'exec', info['Id'], 'python', '-I', '-S', '-B', '-c', crm_probe_source()], 'CRM_READONLY_NAMES_PROBE_FAILED'))
    c.need(m.runtime(info) == m.runtime(m.inspect('t24-crm')) and c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) == d.ACTIVE_NGINX_SHA, 'RUNTIME_CHANGED_DURING_SUPPLEMENTAL_EVIDENCE')
    return {'stage': 'GBP_ACTIVATION_SUPPLEMENTAL_READONLY_LOGGING_FACTS', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'prior_safe_diagnostics': prior_facts, 'nginx_worker_identity': identity, 'nginx_log_path_metadata': logs,
        'host_matching_active_service_names': host_units, 'host_matching_process_comm_names': host_processes,
        'crm_readonly_name_probe': crm, 'process_snapshot_is_racy': True, 'package_presence_is_not_enablement_proof': True,
        'manual_external_logging_review_still_required': True, 'argv_or_configuration_or_environment_values_exported': False,
        'private_containers_accessed': False, 'log_contents_read': False, 'configuration_changed': False,
        'business_writes': False, 'provider_requests': False}


def main():
    print(json.dumps(proof(), sort_keys=True))
