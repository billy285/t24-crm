"""Reviewed exact callback logging change and six-key runtime switch; no SQL writes."""
import base64
import copy
import fcntl
import json
import os
import pwd
import re
import resource
import secrets
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import core as c
import preflight

CANDIDATE_NAME = 't24-crm-gbp-activation-20261030'
DISABLED_NAME = 't24-crm-gbp-disabled-20261030'
SCOPE = 'https://www.googleapis.com/auth/business.manage'
ATTEMPT_NAMESPACE = 'attempt-v2'
SECURITY_HEADERS = frozenset(('cache-control', 'strict-transport-security', 'content-security-policy',
    'x-frame-options', 'x-content-type-options', 'permissions-policy'))
LOG_METADATA_EVIDENCE_SHA = '2bda1b6ce27c9b4dec54198e83be5abf5d6d89144da7b5b3330b407a6760e27a'
EXPECTED_LOG_METADATA = {
    '/var/log/nginx/access.log': (33, 4, 0o640),
    '/var/log/nginx/error.log': (33, 4, 0o640),
    '/var/log/nginx/t24-private-error.log': (33, 0, 0o600),
}
REVIEW_FLAGS = {'independent_security_review_passed', 'approved_dedicated_client_project',
    'existing_consent_screen_and_clients_preserved', 'external_callback_logs_checked',
    'allow_exact_callback_logging_change', 'allow_exact_six_environment_additions'}


def attempt_root():
    # Credential receipt/env stay at their original fixed paths. Only this
    # attempt's immutable plan/review/logging/switch artifacts use the new folder.
    return c.ROOT / ATTEMPT_NAMESPACE


def module_hash(name):
    module = sys.modules[name]
    return getattr(module, '__tool_sha256__', None) or c.H(Path(module.__file__).read_bytes())


def tool_hashes():
    return {name + '.py': module_hash(name) for name in ('core', 'preflight', 'activation')}


def _tokens(blob):
    """Small strict Nginx scanner, retaining byte offsets and ignoring comments."""
    text = blob.decode('utf-8')
    token = re.compile(r'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};#"']+''')
    position, tokens = 0, []
    for item in token.finditer(text):
        c.need(item.start() == position, 'NGINX_SYNTAX_NOT_SUPPORTED')
        position = item.end()
        value = item.group()
        if not value.isspace() and not value.startswith('#'):
            tokens.append((value, item.start(), item.end()))
    c.need(position == len(text), 'NGINX_SYNTAX_NOT_SUPPORTED')
    return text, tokens


def nginx_blocks(blob):
    text, tokens = _tokens(blob)
    root = {'header': [], 'directives': [], 'parent': None}
    stack, result, directive = [], [root], []
    for value, start, end in tokens:
        if value == '{':
            c.need(bool(directive), 'NGINX_BLOCK_HEADER_REQUIRED')
            row = {'header': [item[0] for item in directive], 'start': directive[0][1], 'open': end,
                'parent': stack[-1] if stack else None, 'directives': []}
            result.append(row)
            stack.append(row)
            directive = []
        elif value == '}':
            c.need(bool(stack) and not directive, 'NGINX_BLOCK_STRUCTURE_REJECTED')
            row = stack.pop()
            row['close'], row['end'] = start, end
        elif value == ';':
            c.need(bool(directive), 'NGINX_EMPTY_DIRECTIVE_REJECTED')
            (stack[-1] if stack else root)['directives'].append([item[0] for item in directive])
            directive = []
        else:
            directive.append((value, start, end))
    c.need(not stack and not directive, 'NGINX_UNTERMINATED_STRUCTURE')
    return text, result


def next_nginx(blob):
    text, blocks = nginx_blocks(blob)
    servers = [row for row in blocks if row['header'] == ['server'] and
        any(item[0] == 'server_name' and 't24-crm.com' in item[1:] for item in row['directives']) and
        any(item[0] == 'listen' and any('443' == value or value.endswith(':443') for value in item[1:]) for item in row['directives'])]
    c.need(len(servers) == 1, 'EXACT_CRM_SERVER_REQUIRED')
    server = servers[0]
    c.need(not any(c.CALLBACK in row['header'] for row in blocks), 'EXISTING_CALLBACK_LOCATION_REQUIRES_REVIEW')
    def literal_prefix(row):
        header = row['header']
        if len(header) == 2 and header[0] == 'location' and header[1].startswith('/'):
            return header[1]
        if len(header) == 3 and header[:2] == ['location', '^~'] and header[2].startswith('/'):
            return header[2]
        return None
    candidates = [row for row in blocks if row['parent'] is server and literal_prefix(row) and
        c.CALLBACK.startswith(literal_prefix(row)) and any(item[0] == 'proxy_pass' for item in row['directives'])]
    c.need(bool(candidates), 'DIRECT_API_PROXY_LOCATION_REQUIRED')
    candidates.sort(key=lambda row: len(literal_prefix(row)), reverse=True)
    location = candidates[0]
    c.need(not any(row['parent'] is location for row in blocks), 'NESTED_PROXY_LOCATION_REQUIRES_REVIEW')
    copied = []
    allowed = {'proxy_pass', 'proxy_http_version', 'proxy_set_header', 'proxy_read_timeout',
        'proxy_send_timeout', 'proxy_connect_timeout', 'proxy_buffering', 'proxy_request_buffering'}
    for item in location['directives']:
        c.need(item[0] in allowed, 'NONSTANDARD_API_PROXY_REQUIRES_MANUAL_REVIEW')
        if item[0] == 'proxy_pass':
            c.need(len(item) == 2 and re.fullmatch(r'http://127\.0\.0\.1:[0-9]{2,5}', item[1]), 'EXACT_LOCAL_API_UPSTREAM_REQUIRED')
        elif item[0] == 'proxy_set_header':
            c.need(len(item) == 3 and item[1] in {'Host', 'X-Real-IP', 'X-Forwarded-For', 'X-Forwarded-Proto', 'Upgrade', 'Connection'} and
                bool(re.fullmatch(r'\$[a-z_]+|"upgrade"|upgrade|""', item[2])), 'PROXY_HEADER_REQUIRES_MANUAL_REVIEW')
        elif item[0] == 'proxy_http_version':
            c.need(item == ['proxy_http_version', '1.1'], 'PROXY_VERSION_REQUIRES_MANUAL_REVIEW')
        elif item[0] in {'proxy_buffering', 'proxy_request_buffering'}:
            c.need(len(item) == 2 and item[1] in {'on', 'off'}, 'PROXY_BUFFER_SETTING_REJECTED')
        else:
            c.need(len(item) == 2 and bool(re.fullmatch('[0-9]{1,5}[sm]?', item[1])), 'PROXY_TIMEOUT_REQUIRES_MANUAL_REVIEW')
        copied.append('        ' + ' '.join(item) + ';\n')
    c.need(sum(item[0] == 'proxy_pass' for item in location['directives']) == 1, 'EXACT_ONE_API_UPSTREAM_REQUIRED')
    added = ('    # T24 CRM dedicated Google callback: never log code/state query strings.\n'
        '    location = ' + c.CALLBACK + ' {\n' + ''.join(copied) +
        '        proxy_hide_header Referrer-Policy;\n        add_header Referrer-Policy no-referrer always;\n' +
        '        access_log off;\n        error_log /dev/null crit;\n    }\n\n')
    # Insert before the original proxy, preserving every existing byte verbatim.
    position = text.rfind('\n', 0, location['start']) + 1
    c.need(not text[position:location['start']].strip(), 'INLINE_API_LOCATION_REQUIRES_MANUAL_REVIEW')
    updated = text[:position] + added + text[position:]
    c.need(updated.replace(added, '', 1) == text, 'NGINX_NONCALLBACK_BYTES_DRIFT')
    return updated.encode(), added.encode()


def verify_no_debug_logging(active):
    _, blocks = nginx_blocks(active)
    for row in blocks:
        for item in row['directives']:
            c.need(item[0] != 'debug_connection' and not (item[0] == 'error_log' and 'debug' in item[1:]), 'DEBUG_LOGGING_BLOCKS_OAUTH_ACTIVATION')


def log_paths(active):
    _, blocks = nginx_blocks(active)
    paths = set()
    for row in blocks:
        for item in row['directives']:
            if item[0] not in {'access_log', 'error_log'}:
                continue
            c.need(len(item) >= 2, 'LOG_DESTINATION_REJECTED')
            value = item[1]
            if value in {'off', '/dev/null'}:
                continue
            c.need(value.startswith('/var/log/nginx/') and not any(char in value for char in '$\0\r\n'), 'EXTERNAL_LOG_DESTINATION_REQUIRES_REVIEW')
            paths.add(value)
    c.need(bool(paths), 'EXPLICIT_NGINX_LOG_PATHS_REQUIRED')
    return sorted(paths)


def active_logging_boundary(plan, expected_hash=None):
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    verify_no_debug_logging(active)
    c.need(log_paths(active) == plan['nginx_log_paths'], 'NGINX_LOG_DESTINATIONS_DRIFT')
    digest = c.H(active)
    c.need(expected_hash is None or digest == expected_hash, 'FULL_ACTIVE_NGINX_CONFIGURATION_DRIFT')
    verify_header_inheritance(active, callback_present=True)
    verify_worker_identity(active)
    verify_log_identities(plan)
    return digest


def verify_header_inheritance(active, *, callback_present=False):
    """Never cancel inherited Nginx header rules when adding the callback rule.

    Current observed config has header rules only in sibling static locations.
    Unknown include-level/http/server rules fail closed instead of guessing their
    effective inheritance or copying arbitrary configuration into this location.
    """
    _, blocks = nginx_blocks(active)
    callbacks = []
    for row in blocks:
        if row['header'] == ['location', '=', c.CALLBACK]: callbacks.append(row)
        for item in row['directives']:
            if item[0] == 'add_header_inherit':
                raise c.GuardError('CUSTOM_HEADER_INHERITANCE_REQUIRES_REVIEW')
            if item[0] not in {'add_header', 'proxy_hide_header', 'proxy_pass_header'}: continue
            current, in_location = row, False
            while current is not None:
                if current['header'] and current['header'][0] == 'location': in_location = True
                current = current['parent']
            c.need(in_location, 'INHERITED_NGINX_HEADER_RULES_REQUIRE_REVIEW')
    c.need(len(callbacks) == (1 if callback_present else 0), 'EXACT_CALLBACK_HEADER_CONTEXT_REQUIRED')
    if callbacks:
        actual = [item for item in callbacks[0]['directives'] if item[0] in {'add_header', 'proxy_hide_header', 'proxy_pass_header'}]
        c.need(actual == [['proxy_hide_header', 'Referrer-Policy'], ['add_header', 'Referrer-Policy', 'no-referrer', 'always']],
            'EXACT_CALLBACK_REFERRER_OVERRIDE_REQUIRED')


def response_headers(blob):
    c.need(isinstance(blob, bytes) and len(blob) <= 65536, 'CALLBACK_HEADERS_SIZE_REJECTED')
    blocks = [item for item in re.split(rb'\r?\n\r?\n', blob) if item.lower().startswith(b'http/')]
    c.need(bool(blocks), 'CALLBACK_HTTP_HEADERS_REQUIRED')
    rows = blocks[-1].splitlines()
    c.need(bool(re.match(rb'HTTP/[^\s]+\s+303(?:\s|$)', rows[0], re.I)), 'CALLBACK_303_REQUIRED')
    headers = {}
    for row in rows[1:]:
        if b':' not in row: continue
        name, value = row.split(b':', 1)
        headers.setdefault(name.lower().strip(), []).append(value.strip())
    c.need(headers.get(b'location') == [b'/media-ops?google=failed'] and
        any(b'no-store' in value.lower() for value in headers.get(b'cache-control', [])), 'CALLBACK_FIXED_PRIVATE_REDIRECT_REQUIRED')
    return headers


def security_fingerprints(blob):
    headers = response_headers(blob)
    c.need(all(name.encode() in headers for name in SECURITY_HEADERS), 'BASELINE_SECURITY_HEADERS_REQUIRED')
    return {name: c.H(b'\0'.join(headers[name.encode()])) for name in sorted(SECURITY_HEADERS)}


def baseline_security_headers():
    # No code/state/cookie/auth, no curlrc/proxy defaults and no Google request.
    blob = c.run(['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--max-time', '20', '--max-redirs', '0',
        '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', c.ORIGIN + c.CALLBACK], 'BASELINE_CALLBACK_HEADERS_FAILED')
    return security_fingerprints(blob)


def verify_worker_identity(active):
    rows = re.findall(rb'(?m)^\s*user\s+([A-Za-z_][A-Za-z0-9_.-]*)(?:\s+([A-Za-z_][A-Za-z0-9_.-]*))?\s*;', active)
    c.need(rows == [(b'www-data', b'')], 'OBSERVED_NGINX_WORKER_CONFIGURATION_DRIFT')
    user = pwd.getpwnam('www-data')
    c.need(user.pw_uid == 33 and user.pw_gid == 33, 'OBSERVED_NGINX_WORKER_IDENTITY_DRIFT')
    return {'configured_user': 'www-data', 'uid': 33, 'primary_gid': 33}


def capture_log_identities(paths):
    c.need(set(paths) == set(EXPECTED_LOG_METADATA), 'EXACT_OBSERVED_LOG_PATH_SET_REQUIRED')
    identities = {}
    for path in paths:
        fd, info = _log_open(path)
        try:
            identities[path] = [info.st_dev, info.st_ino]
        finally:
            os.close(fd)
    return identities


def verify_log_identities(plan):
    c.need(plan.get('log_metadata_evidence_sha256') == LOG_METADATA_EVIDENCE_SHA and
        set(plan.get('log_file_identities', {})) == set(EXPECTED_LOG_METADATA), 'REVIEWED_LOG_METADATA_EVIDENCE_REQUIRED')
    c.need(capture_log_identities(plan['nginx_log_paths']) == plan['log_file_identities'], 'OBSERVED_LOG_FILE_IDENTITY_DRIFT')


def plan_nginx():
    before = preflight.proof()
    m = c.legacy()
    original = m.NGINX.read_bytes()
    updated, added = next_nginx(original)
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    verify_no_debug_logging(active)
    verify_header_inheritance(active)
    logs = log_paths(active)
    worker = verify_worker_identity(active)
    identities = capture_log_identities(logs)
    baseline_headers = baseline_security_headers()
    c.mkdir(c.ROOT)
    c.mkdir(attempt_root())
    c.write(attempt_root() / 'nginx-before.conf', original)
    c.write(attempt_root() / 'nginx-next.conf', updated)
    c.write(attempt_root() / 'original-container.json', m.inspect('t24-crm'))
    preflight_sha = c.write(attempt_root() / 'preflight.json', before)
    plan = {'stage': 'GBP_ACTIVATION_NGINX_PLAN_ONLY', 'preflight_sha256': preflight_sha,
        'prior_deployed_sha256': c.PRIOR_SHA, 'source_sha': c.SOURCE, 'frontend_version': c.FRONTEND,
        'schema_revision': c.REVISION, 'image': c.IMAGE, 'nginx_before_sha256': c.H(original),
        'nginx_next_sha256': c.H(updated), 'active_config_before_sha256': c.H(active),
        'callback': c.ORIGIN + c.CALLBACK, 'scope': SCOPE, 'project_id': c.PROJECT_ID,
        'nginx_noncallback_bytes_unchanged': True, 'callback_only_log_suppression': True,
        'callback_block_safe_view': preflight.safe_nginx_view(added), 'nginx_log_paths': logs,
        'log_file_identities': identities, 'log_metadata_evidence_sha256': LOG_METADATA_EVIDENCE_SHA,
        'nginx_worker_identity': worker,
        'attempt_namespace': ATTEMPT_NAMESPACE, 'baseline_security_header_sha256': baseline_headers,
        'callback_referrer_override': {'hide_upstream': 'Referrer-Policy', 'add_always': 'no-referrer'},
        'inherited_nginx_header_rules_absent_verified': True,
        'tool_sha256': tool_hashes(), 'runtime_changed': False, 'business_writes': False,
        'provider_requests': False}
    digest = c.write(attempt_root() / 'nginx-plan.json', plan)
    return {**plan, 'plan_sha256': digest, 'manual_review_required': True}


def reviewed_plan(arguments):
    c.need(set(arguments) == {'plan_sha256', 'review', 'review_sha256'}, 'EXACT_REVIEW_ARGUMENTS_REQUIRED')
    c.need(all(isinstance(arguments[name], str) and re.fullmatch('[a-f0-9]{64}', arguments[name]) for name in ('plan_sha256', 'review_sha256')), 'REVIEW_HASH_REQUIRED')
    plan = c.strict_json(c.read(attempt_root() / 'nginx-plan.json', arguments['plan_sha256']))
    review = arguments['review']
    c.need(isinstance(review, dict) and c.H(c.encoded(review)) == arguments['review_sha256'], 'EXACT_MANUAL_REVIEW_HASH_REQUIRED')
    c.need(set(review) == REVIEW_FLAGS | {'stage', 'plan_sha256', 'project_id', 'callback', 'scope', 'tool_sha256', 'business_writes', 'provider_writes'}, 'EXACT_REVIEW_FIELDS_REQUIRED')
    c.need(review.get('stage') == 'GBP_ACTIVATION_MANUAL_REVIEW_APPROVED' and review.get('plan_sha256') == arguments['plan_sha256'] and
        review.get('project_id') == c.PROJECT_ID and review.get('callback') == c.ORIGIN + c.CALLBACK and review.get('scope') == SCOPE and
        review.get('tool_sha256') == tool_hashes() == plan['tool_sha256'], 'MANUAL_REVIEW_IDENTITIES_DRIFT')
    c.need(all(review.get(name) is True for name in REVIEW_FLAGS) and review.get('business_writes') is False and review.get('provider_writes') is False, 'EXPLICIT_MANUAL_REVIEW_REQUIRED')
    c.need(plan['stage'] == 'GBP_ACTIVATION_NGINX_PLAN_ONLY' and plan['source_sha'] == c.SOURCE and plan['image'] == c.IMAGE and
        plan['schema_revision'] == c.REVISION and plan['frontend_version'] == c.FRONTEND and plan['prior_deployed_sha256'] == c.PRIOR_SHA and
        plan.get('log_metadata_evidence_sha256') == LOG_METADATA_EVIDENCE_SHA and plan.get('attempt_namespace') == ATTEMPT_NAMESPACE,
        'NGINX_PLAN_SCOPE_DRIFT')
    c.need(set(plan.get('baseline_security_header_sha256', {})) == SECURITY_HEADERS and
        all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) for value in plan['baseline_security_header_sha256'].values()), 'REVIEWED_SECURITY_HEADER_BASELINE_REQUIRED')
    before = c.read(attempt_root() / 'nginx-before.conf', plan['nginx_before_sha256'])
    after = c.read(attempt_root() / 'nginx-next.conf', plan['nginx_next_sha256'])
    expected, added = next_nginx(before)
    c.need(after == expected and plan['callback_block_safe_view'] == preflight.safe_nginx_view(added), 'NGINX_PLAN_BODY_DRIFT')
    return plan, before, after, review


def save_review(review):
    path = attempt_root() / 'approved.json'
    if path.exists() or path.is_symlink():
        c.need(c.read(path) == c.encoded(review), 'EXISTING_MANUAL_REVIEW_DRIFT')
    else:
        c.write(path, review)


def replace_nginx(m, original, updated):
    c.need(m.NGINX.read_bytes() == original, 'NGINX_CONCURRENT_CHANGE')
    temp = m.NGINX.parent / '.t24-google-callback-next'
    c.need(not temp.exists() and not temp.is_symlink(), 'NGINX_TEMP_REQUIRES_MANUAL_RECOVERY')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    temp.chmod(0o644)
    os.replace(temp, m.NGINX)
    c.fsync_dir(m.NGINX.parent)


def reload_nginx():
    c.run(['nginx', '-t'], 'NGINX_TEST_FAILED')
    c.run(['systemctl', 'reload', 'nginx'], 'NGINX_RELOAD_FAILED')


def _log_open(path):
    p = Path(path)
    c.need(p.is_absolute() and p.resolve() == p and p.parent == Path('/var/log/nginx'), 'NGINX_LOG_PATH_REJECTED')
    c.need(str(p) in EXPECTED_LOG_METADATA, 'EXACT_OBSERVED_LOG_PATH_REQUIRED')
    directory_info = p.parent.lstat()
    c.need(stat.S_ISDIR(directory_info.st_mode) and directory_info.st_uid == 0 and directory_info.st_gid == 4 and
        stat.S_IMODE(directory_info.st_mode) == 0o755 and directory_info.st_nlink == 2, 'NGINX_LOG_DIRECTORY_REJECTED')
    before = p.lstat()
    uid, gid, mode = EXPECTED_LOG_METADATA[str(p)]
    c.need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == uid and before.st_gid == gid and
        stat.S_IMODE(before.st_mode) == mode, 'NGINX_LOG_FILE_REJECTED')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        c.need((before.st_dev, before.st_ino) == (info.st_dev, info.st_ino) and stat.S_ISREG(info.st_mode) and
            info.st_nlink == 1 and info.st_uid == uid and info.st_gid == gid and stat.S_IMODE(info.st_mode) == mode,
            'NGINX_LOG_FILE_REPLACED_OR_METADATA_DRIFT')
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def sentinel_probe(m, plan):
    sentinel = 't24_gbp_nonsecret_' + secrets.token_hex(16)
    since = datetime.now(timezone.utc).isoformat()
    logs = {}
    try:
        for path in plan['nginx_log_paths']:
            fd, info = _log_open(path)
            logs[path] = (fd, info)
            c.need([info.st_dev, info.st_ino] == plan['log_file_identities'][path], 'OBSERVED_LOG_FILE_IDENTITY_DRIFT')
            os.lseek(fd, info.st_size, os.SEEK_SET)
        target = c.ORIGIN + c.CALLBACK + '?code=' + sentinel + '&state=' + sentinel
        response = c.run(['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--max-time', '20', '--max-redirs', '0',
            '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', target], 'CALLBACK_SENTINEL_REQUEST_FAILED')
        headers = response_headers(response)
        c.need(headers.get(b'referrer-policy') == [b'no-referrer'], 'CALLBACK_SENTINEL_RESPONSE_REJECTED')
        c.need(security_fingerprints(response) == plan['baseline_security_header_sha256'], 'CALLBACK_OTHER_SECURITY_HEADERS_CHANGED')
        # Give application/container log pipes a short bounded opportunity to flush.
        time.sleep(0.25)
        for path, (fd, before) in logs.items():
            after = os.stat(path, follow_symlinks=False)
            c.need((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) and after.st_size >= before.st_size, 'LOG_ROTATED_DURING_SENTINEL')
            c.need((before.st_uid, before.st_gid, before.st_mode, before.st_nlink) ==
                (after.st_uid, after.st_gid, after.st_mode, after.st_nlink), 'LOG_METADATA_CHANGED_DURING_SENTINEL')
            blob = os.read(fd, 4 * 1024 * 1024 + 1)
            c.need(len(blob) <= 4 * 1024 * 1024 and sentinel.encode() not in blob, 'CALLBACK_QUERY_PRESENT_IN_NGINX_LOG')
        result = subprocess.run(['docker', 'logs', '--since', since, 't24-crm'], capture_output=True, timeout=15)
        c.need(result.returncode == 0 and sentinel.encode() not in result.stdout + result.stderr, 'CALLBACK_QUERY_PRESENT_IN_CONTAINER_LOG')
        return {'callback_sentinel_verified': True, 'nginx_access_and_error_logs_checked': True,
            'container_stdout_and_stderr_checked': True, 'loopback_https_request_only': True,
            'single_no_referrer_verified': True, 'other_security_header_fingerprints_unchanged': True,
            'actual_google_oauth_performed': False, 'provider_requests': False}
    finally:
        for fd, _ in logs.values():
            os.close(fd)


def protect_callback(arguments):
    plan, original, updated, review = reviewed_plan(arguments)
    preflight.proof()
    m = c.legacy()
    active_before = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    c.need(c.H(active_before) == plan['active_config_before_sha256'], 'ACTIVE_NGINX_CONFIGURATION_DRIFT')
    verify_header_inheritance(active_before)
    verify_worker_identity(active_before)
    verify_log_identities(plan)
    save_review(review)
    replace_nginx(m, original, updated)
    try:
        reload_nginx()
        active_after = active_logging_boundary(plan)
        proof = sentinel_probe(m, plan)
        current = preflight.proof(nginx_hash=plan['nginx_next_sha256'])
        c.need(current['active_nginx_config_sha256'] == active_after, 'ACTIVE_NGINX_CHANGED_DURING_LOGGING_PROBE')
        active_logging_boundary(plan, active_after)
    except BaseException:
        # Before any OAuth, safely restore only the exact known previous config.
        if m.NGINX.read_bytes() == updated:
            replace_nginx(m, updated, original)
            reload_nginx()
        raise
    receipt = {'stage': 'GBP_CALLBACK_LOGGING_PROTECTED', 'plan_sha256': arguments['plan_sha256'],
        'attempt_namespace': ATTEMPT_NAMESPACE,
        'review_sha256': arguments['review_sha256'], 'nginx_sha256': c.H(updated),
        'active_nginx_config_sha256': active_after, 'nginx_log_paths': plan['nginx_log_paths'],
        'full_active_config_and_no_debug_verified': True,
        'source_sha': c.SOURCE, 'crm': current['crm'], 'tool_sha256': tool_hashes(), **proof,
        'runtime_changed': False, 'business_writes': False}
    digest = c.write(attempt_root() / 'logging-protected.json', receipt)
    return {**receipt, 'receipt_sha256': digest}


def clone_config(original, values, networks):
    c.no_gbp(original)
    c.validate_gbp_env([name + '=' + value for name, value in values.items()])
    config = copy.deepcopy(original['Config'])
    config['Image'], config['Hostname'] = c.IMAGE, ''
    config['Env'] = list(original['Config']['Env']) + [name + '=' + values[name] for name in sorted(values)]
    config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    c.need(config['HostConfig'].get('AutoRemove') is False, 'ORIGINAL_AUTOREMOVE_MUST_BE_FALSE')
    c.need(bool(networks) or config['HostConfig']['NetworkMode'] in {'host', 'none'}, 'ORIGINAL_NETWORKS_REQUIRED')
    config['NetworkingConfig'] = {'EndpointsConfig': copy.deepcopy(networks)}
    return config


def verify_clone(candidate, original, values, runtime):
    c.need(candidate['Image'] == original['Image'] == c.IMAGE, 'SAME_REVIEWED_IMAGE_REQUIRED')
    actual = c.env_dict(candidate['Config']['Env'])
    previous = c.env_dict(original['Config']['Env'])
    c.need(actual == {**previous, **values} and set(actual) - set(previous) == c.GBP_NAMES, 'EXACT_SIX_ENVIRONMENT_ADDITIONS_REQUIRED')
    normalized = copy.deepcopy(candidate)
    normalized['Config']['Env'] = copy.deepcopy(original['Config']['Env'])
    for name in ('Image', 'Hostname'):
        normalized['Config'][name] = copy.deepcopy(original['Config'].get(name))
    c.need(runtime(normalized)['config'] == runtime(original)['config'], 'UNCHANGED_RUNTIME_CONFIGURATION_REQUIRED')


def _state(value):
    """Atomic state updates never contain environment values or credentials."""
    path = attempt_root() / 'switch-state.json'
    body = c.encoded(value)
    if not path.exists() and not path.is_symlink():
        c.write(path, body)
        return
    c.read(path)
    temp = attempt_root() / 'switch-state.next'
    c.write(temp, body)
    os.replace(temp, path)
    c.fsync_dir(attempt_root())


def _switch_requirements(arguments):
    c.need(set(arguments) == {'plan_sha256', 'review', 'review_sha256', 'logging_receipt_sha256'}, 'EXACT_ENABLE_ARGUMENTS_REQUIRED')
    base = {key: arguments[key] for key in ('plan_sha256', 'review', 'review_sha256')}
    plan, before, after, review = reviewed_plan(base)
    c.need(re.fullmatch('[a-f0-9]{64}', arguments['logging_receipt_sha256']), 'EXACT_LOGGING_RECEIPT_REQUIRED')
    receipt = c.strict_json(c.read(attempt_root() / 'logging-protected.json', arguments['logging_receipt_sha256']))
    c.need(receipt['stage'] == 'GBP_CALLBACK_LOGGING_PROTECTED' and receipt['plan_sha256'] == arguments['plan_sha256'] and
        receipt['review_sha256'] == arguments['review_sha256'] and receipt['nginx_sha256'] == plan['nginx_next_sha256'] and
        receipt['callback_sentinel_verified'] is True and receipt['tool_sha256'] == tool_hashes() and
        receipt.get('attempt_namespace') == ATTEMPT_NAMESPACE and receipt.get('single_no_referrer_verified') is True and
        receipt.get('other_security_header_fingerprints_unchanged') is True and
        receipt['full_active_config_and_no_debug_verified'] is True and receipt['nginx_log_paths'] == plan['nginx_log_paths'] and
        bool(re.fullmatch('[a-f0-9]{64}', receipt['active_nginx_config_sha256'])), 'REVIEWED_CALLBACK_PROTECTION_REQUIRED')
    c.need(c.read(attempt_root() / 'approved.json') == c.encoded(review), 'STORED_MANUAL_REVIEW_DRIFT')
    return plan, receipt


def config_probe(enabled):
    return ("import socket\ndef blocked(*a,**k):raise AssertionError('PROVIDER_NETWORK_FORBIDDEN')\n"
        "socket.socket.connect=blocked\nfrom services.google_business_provider import enabled,settings\n"
        + "assert enabled() is " + repr(enabled) + "\nvalues,missing=settings()\n"
        + ("assert not missing\n" if enabled else "assert set(missing)==" + repr(c.GBP_NAMES) + "\nassert all(not value for value in values.values())\n")
        + "print('GBP_CONFIG_NO_NETWORK_VERIFIED')\n")


def verify_active(m, candidate, original, values, plan, rows=None, active_hash=None):
    c.need(candidate['State']['Running'], 'ACTIVE_CONTAINER_REQUIRED')
    verify_clone(candidate, original, values, m.runtime)
    c.need(m.inventory(candidate['Id']) == json.loads(m.read(c.PRIOR / 'backend-candidate-inventory.json',
        json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))['candidate_inventory_sha256'])), 'ACTIVE_SOURCE_DRIFT')
    c.need(c.H(m.NGINX.read_bytes()) == plan['nginx_next_sha256'], 'CALLBACK_PROTECTION_DRIFT')
    c.need(isinstance(active_hash, str) and bool(re.fullmatch('[a-f0-9]{64}', active_hash)), 'REVIEWED_ACTIVE_NGINX_HASH_REQUIRED')
    active_logging_boundary(plan, active_hash)
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    c.need(m.schema_signature(m.BUSINESS, c.REVISION) == prior['schema_sha256'] and m.digest(m.tree(Path(prior['public_root']))) == prior['public_inventory_sha256'], 'SCHEMA_OR_STATIC_DRIFT')
    m.verify_secret_mount(candidate)
    m.verify_production_worker_enabled(candidate)
    m.private_boundary(json.loads(m.read(c.PINS, c.PINS_SHA)))
    m.ready(candidate['Id'])
    result = c.run(['docker', 'exec', candidate['Id'], 'python', '-B', '-c', config_probe(True)], 'ACTIVE_GBP_CONFIGURATION_FAILED')
    c.need(result.strip() == b'GBP_CONFIG_NO_NETWORK_VERIFIED', 'CONFIGURATION_PROBE_PROOF_REQUIRED')
    if rows is not None:
        c.need(m.sql_snapshot(m.BUSINESS) == rows, 'BUSINESS_ROWS_CHANGED_DURING_CONFIGURATION_SWITCH')


def enable(arguments):
    plan, logging = _switch_requirements(arguments)
    active_hash = logging['active_nginx_config_sha256']
    active_logging_boundary(plan, active_hash)
    current = preflight.proof(nginx_hash=plan['nginx_next_sha256'])
    c.need(current['active_nginx_config_sha256'] == active_hash, 'ACTIVE_NGINX_CHANGED_DURING_ENABLE_PREFLIGHT')
    c.need(current['crm'] == logging['crm'], 'REVIEWED_DISABLED_RUNTIME_DRIFT')
    m = c.legacy()
    original = c.strict_json(c.read(attempt_root() / 'original-container.json'))
    c.need(m.runtime(original) == current['crm'], 'SAVED_ORIGINAL_RUNTIME_DRIFT')
    values = c.read_gbp_env()
    stored = c.strict_json(c.read(c.ROOT / 'credential-receipt.json'))
    c.need(stored['stage'] == 'GBP_ACTIVATION_CREDENTIALS_STORED_NOT_ENABLED' and stored['project_id'] == c.PROJECT_ID and
        stored['project_number'] == c.PROJECT_NUMBER and stored['runtime_changed'] is False, 'DEDICATED_CREDENTIAL_RECEIPT_REQUIRED')
    # Recheck benign callback/log behavior immediately before any enabled runtime.
    sentinel_probe(m, plan)
    active_logging_boundary(plan, active_hash)
    c.need(not m.inspect_optional(CANDIDATE_NAME) and not m.inspect_optional(DISABLED_NAME), 'EXISTING_SWITCH_CONTAINER_REQUIRES_RECOVERY')
    c.need(not (attempt_root() / 'switch-state.json').exists(), 'EXISTING_SWITCH_REQUIRES_RECOVERY')
    rows = m.sql_snapshot(m.BUSINESS)
    state = {'stage': 'GBP_CONFIG_SWITCH_INTENT', 'original_id': original['Id'], 'candidate_name': CANDIDATE_NAME,
        'image': c.IMAGE, 'plan_sha256': arguments['plan_sha256'], 'review_sha256': arguments['review_sha256']}
    _state(state)
    config = clone_config(original, values, m.retained().clone_networks(original))
    status, body = m.retained().docker_request('POST', '/containers/create?name=' + CANDIDATE_NAME, config)
    c.need(status == 201, 'ENABLED_CONTAINER_CREATE_FAILED')
    candidate_id = json.loads(body)['Id']
    state.update(candidate_id=candidate_id, stage='GBP_CONFIG_CANDIDATE_CREATED')
    _state(state)
    verify_clone(m.inspect(candidate_id), original, values, m.runtime)
    try:
        c.need(m.runtime(m.inspect('t24-crm')) == current['crm'], 'ORIGINAL_CHANGED_BEFORE_SWITCH')
        active_logging_boundary(plan, active_hash)
        c.run(['docker', 'stop', '--time', '30', original['Id']], 'ORIGINAL_STOP_FAILED')
        c.run(['docker', 'rename', original['Id'], DISABLED_NAME], 'ORIGINAL_RENAME_FAILED')
        c.run(['docker', 'rename', candidate_id, 't24-crm'], 'CANDIDATE_RENAME_FAILED')
        c.run(['docker', 'start', candidate_id], 'CANDIDATE_START_FAILED')
        state['stage'] = 'GBP_CONFIG_CANDIDATE_STARTED'
        _state(state)
        candidate = m.inspect('t24-crm')
        c.need(candidate['Id'] == candidate_id, 'ACTIVE_CONTAINER_IDENTITY_DRIFT')
        verify_active(m, candidate, original, values, plan, rows, active_hash)
        sentinel_probe(m, plan)
        active_logging_boundary(plan, active_hash)
        state['stage'] = 'GBP_CONFIG_ENABLED_VERIFIED'
        _state(state)
        receipt = {'stage': state['stage'], 'source_sha': c.SOURCE, 'frontend_version': c.FRONTEND, 'schema_revision': c.REVISION,
            'image': c.IMAGE, 'crm': m.runtime(candidate), 'original_id': original['Id'],
            'plan_sha256': arguments['plan_sha256'], 'review_sha256': arguments['review_sha256'],
            'logging_receipt_sha256': arguments['logging_receipt_sha256'], 'tool_sha256': tool_hashes(),
            'active_nginx_config_sha256': active_hash, 'nginx_log_paths': plan['nginx_log_paths'],
            'exact_six_environment_additions': sorted(c.GBP_NAMES), 'existing_environment_values_unchanged': True,
            'network_mounts_command_labels_unchanged': True, 'same_reviewed_image': True,
            'business_rows_unchanged_during_switch': True, 'private_boundary_verified': True,
            'schema_static_source_unchanged': True, 'callback_sentinel_verified': True,
            'google_oauth_performed': False, 'provider_requests': False, 'provider_writes': False,
            'business_writes': False, 'credentials_exported': False, 'enabled': True}
        digest = c.write(attempt_root() / 'enabled.json', receipt)
        return {**receipt, 'receipt_sha256': digest}
    except BaseException:
        # Same-image, configuration-only recovery; never roll back the database.
        rollback({key: arguments[key] for key in ('plan_sha256', 'review', 'review_sha256', 'logging_receipt_sha256')})
        raise


def rollback(arguments):
    plan, _ = _switch_requirements(arguments)
    m = c.legacy()
    original = c.strict_json(c.read(attempt_root() / 'original-container.json'))
    state = c.strict_json(c.read(attempt_root() / 'switch-state.json'))
    c.need(state['original_id'] == original['Id'] and state['image'] == c.IMAGE and state['plan_sha256'] == arguments['plan_sha256'] and state['review_sha256'] == arguments['review_sha256'], 'SWITCH_RECOVERY_SCOPE_DRIFT')
    c.need(m.schema_signature(m.BUSINESS, c.REVISION) == json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))['schema_sha256'], 'RECOVERY_SCHEMA_DRIFT')
    c.need(c.H(m.NGINX.read_bytes()) == plan['nginx_next_sha256'], 'KEEP_CALLBACK_REDACTION_REQUIRED')
    values = c.read_gbp_env()
    candidate_id = state.get('candidate_id')
    candidate = m.inspect_optional(candidate_id) if candidate_id else m.inspect_optional(CANDIDATE_NAME)
    if candidate:
        verify_clone(candidate, original, values, m.runtime)
        c.need(candidate['Id'] != original['Id'], 'ORIGINAL_MUST_NOT_BE_REMOVED')
    retained = m.inspect(original['Id'])
    c.need(retained['Image'] == c.IMAGE and m.runtime(retained)['config'] == m.runtime(original)['config'], 'RETAINED_DISABLED_CONTAINER_DRIFT')
    c.no_gbp(retained)
    active = m.inspect_optional('t24-crm')
    c.need(not active or active['Id'] in {original['Id'], candidate['Id'] if candidate else ''}, 'UNKNOWN_ACTIVE_CONTAINER_REQUIRES_MANUAL_REVIEW')
    if candidate:
        if candidate['State']['Running']:
            c.run(['docker', 'stop', '--time', '30', candidate['Id']], 'RECOVERY_ENABLED_STOP_FAILED')
        c.run(['docker', 'rm', candidate['Id']], 'RECOVERY_ENABLED_REMOVE_FAILED')
    if retained.get('Name') != '/t24-crm':
        c.run(['docker', 'rename', original['Id'], 't24-crm'], 'RECOVERY_DISABLED_RENAME_FAILED')
    if not retained['State']['Running']:
        c.run(['docker', 'start', original['Id']], 'RECOVERY_DISABLED_START_FAILED')
    m.ready(original['Id'])
    recovered = m.inspect('t24-crm')
    c.need(recovered['Id'] == original['Id'] and m.runtime(recovered)['config'] == m.runtime(original)['config'], 'RECOVERY_CONFIGURATION_DRIFT')
    c.no_gbp(recovered)
    m.private_boundary(json.loads(m.read(c.PINS, c.PINS_SHA)))
    output = c.run(['docker', 'exec', original['Id'], 'python', '-B', '-c', config_probe(False)], 'RECOVERY_DISABLED_CONFIG_FAILED')
    c.need(output.strip() == b'GBP_CONFIG_NO_NETWORK_VERIFIED', 'RECOVERY_DISABLED_PROOF_REQUIRED')
    state['stage'] = 'GBP_CONFIG_ROLLED_BACK_DISABLED'
    _state(state)
    return {'stage': state['stage'], 'image': c.IMAGE, 'crm': m.runtime(recovered), 'enabled': False,
        'callback_logging_protection_retained': True, 'credentials_and_encryption_key_retained': True,
        'database_restored': False, 'google_rows_or_audits_deleted': False, 'provider_requests': False,
        'business_writes': False, 'schema_static_source_unchanged': True}


def dispatch(phase, arguments):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    c.server_guard()
    c.mkdir(c.ROOT)
    c.mkdir(attempt_root())
    lock_path = c.ROOT / 'activation.lock'
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        c.read(lock_path, maximum=0)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handlers = {'plan-nginx': lambda: plan_nginx(), 'protect-callback': lambda: protect_callback(arguments),
            'enable': lambda: enable(arguments), 'rollback': lambda: rollback(arguments)}
        c.need(phase in handlers and isinstance(arguments, dict), 'ACTIVATION_PHASE_REJECTED')
        c.need(phase != 'plan-nginx' or not arguments, 'NO_PLAN_ARGUMENTS_ALLOWED')
        return handlers[phase]()
    finally:
        os.close(fd)
