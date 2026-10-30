"""Read-only rollback/header facts, with no OAuth parameters or header secrets."""
import json
import re
from datetime import datetime, timezone
import core as c

OBSERVED_ACTIVE_SHA = 'bc02ad30e8499729f040a6e87c7cf039597085e8e15a3d30755ca78bb290d76c'
HEADER_NAMES = {'referrer-policy', 'cache-control', 'strict-transport-security', 'content-security-policy',
    'x-frame-options', 'x-content-type-options', 'permissions-policy'}


def header_scopes(blob):
    token = re.compile(rb'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};#"']+''')
    position, pending, stack, result = 0, [], [], []
    for match in token.finditer(blob):
        c.need(match.start() == position, 'HEADER_CONTEXT_SYNTAX_REJECTED'); position = match.end()
        value = match[0]
        if value.isspace() or value.startswith(b'#'): continue
        if value == b'{':
            c.need(bool(pending), 'HEADER_CONTEXT_BLOCK_REJECTED')
            stack.append(list(pending)); pending = []
        elif value == b'}':
            c.need(bool(stack) and not pending, 'HEADER_CONTEXT_STRUCTURE_REJECTED')
            stack.pop()
        elif value == b';':
            if pending and pending[0] in {b'add_header', b'add_header_inherit', b'proxy_hide_header', b'proxy_pass_header'}:
                kinds = [item[0].decode('ascii', errors='replace') for item in stack]
                name = pending[1].decode('ascii', errors='replace').lower() if len(pending) > 1 else ''
                result.append({'directive': pending[0].decode('ascii'), 'context_kinds': kinds,
                    'is_location_scope': any(item[0] == b'location' for item in stack),
                    'is_api_location': any(item in ([b'location', b'/api/'], [b'location', b'^~', b'/api/']) for item in stack),
                    'public_security_header_name': name if name in HEADER_NAMES else '[OTHER_HEADER_OR_SETTING_REDACTED]'})
            pending = []
        else:
            pending.append(value)
    c.need(position == len(blob) and not stack and not pending, 'HEADER_CONTEXT_UNTERMINATED')
    return result


def response_facts(blob):
    c.need(len(blob) <= 65536, 'CALLBACK_HEADER_RESPONSE_TOO_LARGE')
    blocks = [item for item in re.split(rb'\r?\n\r?\n', blob) if item.lower().startswith(b'http/')]
    c.need(bool(blocks), 'HTTP_STATUS_HEADER_REQUIRED')
    rows = blocks[-1].splitlines()
    status = re.match(rb'HTTP/[^\s]+\s+([0-9]{3})(?:\s|$)', rows[0], flags=re.I)
    c.need(bool(status), 'HTTP_STATUS_HEADER_REJECTED')
    values = {}
    for row in rows[1:]:
        if b':' not in row: continue
        name, value = row.split(b':', 1)
        values.setdefault(name.lower().strip(), []).append(value.strip().lower())
    referrers = values.get(b'referrer-policy', [])
    known = {b'no-referrer', b'strict-origin-when-cross-origin', b'same-origin', b'strict-origin', b'origin', b'no-referrer-when-downgrade', b'unsafe-url'}
    return {'status': int(status[1]), 'location_is_fixed_failed_redirect': values.get(b'location') == [b'/media-ops?google=failed'],
        'referrer_policy_header_count': len(referrers), 'referrer_policy': [value.decode('ascii') if value in known else '[UNEXPECTED_VALUE_REDACTED]' for value in referrers],
        'cache_control_has_no_store': any(b'no-store' in value for value in values.get(b'cache-control', [])),
        'public_security_header_names_present': sorted(name for name in HEADER_NAMES if name.encode() in values)}


def proof():
    c.server_guard()
    m = c.legacy()
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    original = m.inspect('t24-crm')
    c.need(original['State']['Running'] and original['Image'] == c.IMAGE and m.runtime(original) == prior['crm'], 'EXACT_DISABLED_RUNTIME_REQUIRED')
    c.no_gbp(original)
    site = m.NGINX.read_bytes()
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    scopes = header_scopes(active)
    response = c.run(['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--max-time', '20', '--max-redirs', '0',
        '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', c.ORIGIN + c.CALLBACK], 'CALLBACK_NOQUERY_READ_FAILED')
    c.need(site == m.NGINX.read_bytes() and c.H(active) == c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) and
        m.runtime(original) == m.runtime(m.inspect('t24-crm')), 'RUNTIME_CHANGED_DURING_HEADER_PROBE')
    return {'stage': 'GBP_CALLBACK_NOQUERY_READONLY_HEADERS', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'site_nginx_sha256': c.H(site), 'active_nginx_config_sha256': c.H(active),
        'original_site_restored': c.H(site) == prior['nginx_sha256'], 'observed_active_config_restored': c.H(active) == OBSERVED_ACTIVE_SHA,
        'nginx_header_directive_scopes': scopes,
        'potential_inherited_header_directive_count': sum(not row['is_location_scope'] for row in scopes),
        'api_header_directive_count': sum(row['is_api_location'] for row in scopes),
        'callback_response_facts': response_facts(response), 'query_or_cookie_or_authentication_sent': False,
        'header_values_other_than_public_policy_exported': False, 'configuration_changed': False,
        'business_writes': False, 'provider_requests': False}


def main():
    print(json.dumps(proof(), sort_keys=True))
