"""Root-only collector policy facts: types/pathnames only, no policy values."""
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
import core as c
import diagnostics as d

UNITS = ('rsyslog.service', 'cloudmonitor.service', 'aliyun.service')
POLICY_GLOBS = (
    ('rsyslog', '/etc', 'rsyslog.conf'), ('rsyslog', '/etc/rsyslog.d', '*.conf'),
    ('cloudmonitor', '/usr/local/cloudmonitor/conf', '*'), ('cloudmonitor', '/usr/local/cloudmonitor/conf', '*/*'),
    ('aegis', '/usr/local/aegis/conf', '*'), ('aegis', '/usr/local/aegis/etc', '*'),
    ('aegis', '/usr/local/aegis/aegis_client/conf', '*'), ('aegis', '/usr/local/aegis/aegis_client', '*.conf'),
    ('aegis', '/usr/local/aegis/aegis_client', 'aegis_*/conf/*'),
    ('ilogtail', '/etc/ilogtail', '*.json'), ('ilogtail', '/usr/local/ilogtail', '*config*.json'),
)
MODULES = ('imuxsock', 'imklog', 'imjournal', 'imfile', 'imtcp', 'imudp', 'imptcp', 'imrelp', 'impstats',
    'omfile', 'omfwd', 'omhttp', 'omrelp', 'omkafka', 'omelasticsearch', 'omjournal', 'omprog',
    'cpu', 'memory', 'disk', 'network', 'system', 'metrics', 'host', 'jvm', 'nginx', 'apache',
    'file', 'syslog', 'journal', 'pcap', 'ebpf', 'packet', 'http_request', 'request_body', 'response_body')
NETWORK_OUTPUTS = {'omfwd', 'omhttp', 'omrelp', 'omkafka', 'omelasticsearch'}
LOG_PREFIXES = ('/var/log/', '/run/log/', '/opt/t24-crm/app/logs/', '/opt/t24-crm/app/backend/logs/',
    '/usr/local/cloudmonitor/logs/', '/usr/local/aegis/logs/')
CAPTURE_MARKERS = ('pcap', 'ebpf', 'packet_capture', 'capture_request', 'request_body', 'response_body', 'http_request')


def safe_path(value):
    return isinstance(value, str) and value.startswith('/') and len(value) <= 512 and bool(re.fullmatch(r'/[A-Za-z0-9_./*?\[\]+-]+', value)) and '..' not in Path(value).parts


def log_path(value):
    return safe_path(value) and (value == '/dev/log' or value.startswith(LOG_PREFIXES))


def summary(blob):
    c.need(isinstance(blob, bytes) and len(blob) <= 262144, 'POLICY_FILE_TOO_LARGE')
    text = blob.decode('utf-8', errors='replace')
    # Comments do not contribute markers. This is bounded evidence extraction,
    # not an interpreter or a claim that a proprietary agent's semantics are known.
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith(('#', '//')))
    lowered = text.lower()
    modules = sorted(name for name in MODULES if re.search(r'(?<![a-z0-9_-])' + re.escape(name) + r'(?![a-z0-9_-])', lowered))
    paths = set()
    redacted_paths = False
    for match in re.finditer(r'(?im)(?:\$InputFileName\s+|(?:File|FileName|Path|LogPath|LogFile|InputFile)\s*[=:]\s*)["\']?([^\s"\'<>]+)', text):
        value = match[1].rstrip(',);')
        if value.startswith('/'):
            if log_path(value): paths.add(value)
            else: redacted_paths = True
    format_name = 'text-markers-only'
    try:
        value = c.strict_json(blob)
    except (ValueError, UnicodeError):
        pass
    else:
        format_name = 'json-key-and-marker-extraction'
        stack, count = [(value, 0)], 0
        while stack:
            item, depth = stack.pop(); count += 1
            c.need(count <= 20000 and depth <= 16, 'POLICY_JSON_COMPLEXITY_REJECTED')
            if isinstance(item, dict):
                for key, entry in item.items():
                    if isinstance(key, str) and isinstance(entry, str) and re.search(r'(?:path|file|filename)$', key, re.I) and entry.startswith('/'):
                        if log_path(entry): paths.add(entry)
                        else: redacted_paths = True
                    stack.append((entry, depth + 1))
            elif isinstance(item, list):
                stack.extend((entry, depth + 1) for entry in item)
    network = bool(NETWORK_OUTPUTS & set(modules)) or bool(re.search(r'(?m)^\s*[^#\n]+\s+@@?\S+', text))
    return {'extraction_type': format_name, 'module_or_input_type_markers': modules, 'local_log_input_pathnames': sorted(paths),
        'nonlog_path_values_redacted': redacted_paths, 'network_output_marker_present': network,
        'http_or_packet_capture_marker_present': any(marker in lowered for marker in CAPTURE_MARKERS),
        'semantics_not_fully_evaluated': True, 'configuration_values_exported': False}


def protected_policy(path):
    c.need(safe_path(str(path)), 'POLICY_PATH_REJECTED')
    resolved = path.resolve(strict=True)
    unit = str(path).startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/'))
    if unit:
        c.need(str(resolved).startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/')), 'POLICY_RESOLVED_PATH_REJECTED')
    else:
        c.need(resolved == path, 'POLICY_CONFIG_SYMLINK_REJECTED')
        c.need(any(str(path).startswith(root.rstrip('/') + '/') for _, root, _ in POLICY_GLOBS), 'FIXED_POLICY_ROOT_REQUIRED')
    for parent in (resolved.parent, *resolved.parent.parents):
        info = parent.lstat()
        c.need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'POLICY_PARENT_NOT_PROTECTED')
    before = resolved.lstat()
    c.need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and not before.st_mode & 0o022, 'POLICY_FILE_NOT_PROTECTED')
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        c.need((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'POLICY_FILE_REPLACED')
        blob = stream.read(262145)
    after = resolved.lstat()
    c.need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'POLICY_CHANGED_DURING_READ')
    c.need(len(blob) <= 262144, 'POLICY_FILE_TOO_LARGE')
    return blob


def candidates():
    rows = {}
    for family, root, pattern in POLICY_GLOBS:
        directory = Path(root)
        if not directory.exists(): continue
        for path in directory.glob(pattern):
            if not safe_path(str(path)): continue
            if path.suffix.lower() not in {'.conf', '.json', '.ini', '.yaml', '.yml', '.xml', '.properties'}: continue
            if re.search(r'password|passwd|credential|secret|token|cert|private|auth|\.key', path.name, re.I): continue
            if path.is_file(): rows[str(path)] = family
    c.need(len(rows) <= 120, 'BOUNDED_COLLECTOR_POLICY_SET_EXCEEDED')
    return sorted(rows.items())


def proof():
    c.server_guard()
    m = c.legacy()
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    original = m.inspect('t24-crm')
    c.need(original['State']['Running'] and original['Image'] == c.IMAGE and m.runtime(original) == prior['crm'], 'EXACT_DISABLED_RUNTIME_REQUIRED')
    c.no_gbp(original)
    c.need(c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) == d.ACTIVE_NGINX_SHA, 'ACTUAL_NGINX_BASELINE_DRIFT')
    units = []
    for unit in UNITS:
        body = c.run(['systemctl', 'show', '--property=FragmentPath', '--value', unit], 'COLLECTOR_UNIT_PATH_LOOKUP_FAILED')
        c.need(len(body) <= 1024, 'UNIT_PATH_SIZE_REJECTED')
        path = body.decode('ascii').strip()
        if not path:
            units.append({'unit_name': unit, 'fragment_path': None}); continue
        c.need(safe_path(path) and path.startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/')), 'COLLECTOR_UNIT_PATH_REJECTED')
        blob = protected_policy(Path(path))
        executables = []
        for match in re.finditer(rb'(?m)^\s*ExecStart\s*=\s*[-+!:@]*([^\s"\']+)', blob):
            candidate = match[1].decode('ascii', errors='replace')
            if safe_path(candidate) and candidate.startswith(('/usr/', '/bin/', '/sbin/')): executables.append(candidate)
        units.append({'unit_name': unit, 'fragment_path': path, 'executable_pathnames_only': sorted(set(executables))})
    policies = []
    for path, family in candidates():
        try:
            facts = summary(protected_policy(Path(path)))
        except (c.GuardError, OSError, ValueError):
            policies.append({'family': family, 'policy_pathname': path, 'status': 'not-readable-or-not-trusted-or-not-parsed'})
        else:
            policies.append({'family': family, 'policy_pathname': path, 'status': 'bounded-types-and-paths-extracted', **facts})
    c.need(m.runtime(original) == m.runtime(m.inspect('t24-crm')) and c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) == d.ACTIVE_NGINX_SHA, 'RUNTIME_CHANGED_DURING_COLLECTOR_POLICY_PROBE')
    return {'stage': 'GBP_COLLECTOR_POLICY_READONLY_AGGREGATE', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'prior_deployed_sha256': c.PRIOR_SHA, 'active_nginx_config_sha256': d.ACTIVE_NGINX_SHA,
        'unit_pathnames_only': units, 'policy_type_and_pathname_facts': policies,
        'policy_scope_is_fixed_and_bounded': True, 'proprietary_agent_semantics_or_dynamic_runtime_rules_may_remain_unknown': True,
        'manual_external_logging_review_still_required': True, 'raw_configuration_or_argv_or_environment_values_exported': False,
        'log_contents_read': False, 'private_containers_accessed': False, 'configuration_changed': False,
        'business_writes': False, 'provider_requests': False}


def main():
    print(json.dumps(proof(), sort_keys=True))
