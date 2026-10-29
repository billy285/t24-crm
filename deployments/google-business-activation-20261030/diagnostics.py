"""Read-only public DNS/logging evidence; no environment or log-option values."""
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
import core as c

ACTIVE_NGINX_SHA = 'bc02ad30e8499729f040a6e87c7cf039597085e8e15a3d30755ca78bb290d76c'
KNOWN_DRIVERS = {'json-file', 'local', 'journald', 'syslog', 'fluentd', 'splunk', 'gelf', 'awslogs', 'gcplogs', 'logentries', 'etwlogs', 'none'}
APM_NAME = re.compile(r'OTEL|OPENTELEMETRY|SENTRY|DATADOG|NEW_RELIC|ELASTIC_APM|HONEYCOMB|APPINSIGHTS|APPLICATIONINSIGHTS|BUGSNAG|ROLLBAR|SKYWALKING|INSTANA|SCOUT|APM|TRACE|TRACING|TELEMETRY|MONITOR|LOG|^DD_|^NODE_OPTIONS$|^JAVA_TOOL_OPTIONS$|^PYTHONPATH$', re.I)
COMMAND_MARKERS = ('opentelemetry-instrument', 'ddtrace-run', 'newrelic-admin', 'elasticapm-run', 'sentry_sdk', 'py-spy', 'memray')
MODULE_MARKERS = ('opentelemetry', 'opentracing', 'otel', 'lua', 'modsecurity', 'app_protect', 'datadog')


def public_dns_ips(rows):
    public, nonpublic = set(), False
    for row in rows:
        try:
            address = ipaddress.ip_address(row[4][0])
        except (ValueError, TypeError, IndexError):
            raise c.GuardError('DNS_RESULT_FORMAT_REJECTED') from None
        if address.is_global:
            public.add(str(address))
        else:
            nonpublic = True
    return sorted(public), nonpublic


def logging_view(blob):
    # Match only known directive names. Never export directive bodies, format
    # strings, headers, credentials, syslog URLs or arbitrary option values.
    rows, module_markers = [], set()
    tokens = re.compile(rb'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};#"']+''')
    position, pending, directives = 0, [], []
    for match in tokens.finditer(blob):
        c.need(match.start() == position, 'NGINX_DIAGNOSTIC_SYNTAX_REJECTED')
        position = match.end()
        token = match[0]
        if token.isspace() or token.startswith(b'#'):
            continue
        if token in {b'{', b'}'}:
            pending = []
        elif token == b';':
            directives.append(pending)
            pending = []
        else:
            pending.append(token)
    c.need(position == len(blob) and not pending, 'NGINX_DIAGNOSTIC_SYNTAX_REJECTED')
    for parts in directives:
        if not parts or parts[0] not in {b'access_log', b'error_log', b'log_format', b'debug_connection', b'load_module'}:
            continue
        c.need(len(parts) >= 2, 'NGINX_LOG_DIRECTIVE_REJECTED')
        name = parts[0].decode('ascii')
        value = b' '.join(parts[1:])
        first = parts[1]
        if name == 'log_format':
            token = first.decode('ascii', errors='ignore')
            rows.append({'directive': name, 'format_name': token if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', token) else '[REDACTED]'})
        elif name == 'load_module':
            lowered = value.lower()
            module_markers.update(marker for marker in MODULE_MARKERS if marker.encode() in lowered)
        elif name == 'debug_connection':
            rows.append({'directive': name, 'destination': '[REDACTED]', 'debug_enabled': True})
        else:
            text = first.decode('ascii', errors='ignore')
            item = {'directive': name, 'debug_enabled': bool(re.search(rb'(?:^|\s)debug(?:\s|$)', value))}
            if text in {'off', 'stderr', '/dev/null'}:
                item.update(destination_type='builtin', destination=text)
            elif re.fullmatch(r'/var/log/nginx/[A-Za-z0-9_.-]{1,100}\.log(?:\.[0-9]+)?', text):
                item.update(destination_type='local-nginx-log', destination=text)
            elif text.startswith('syslog:'):
                item.update(destination_type='syslog', destination='[REDACTED]')
            else:
                item.update(destination_type='other-redacted', destination='[REDACTED]')
            rows.append(item)
    # De-duplicate repeated inherited destinations without exposing raw text.
    unique = {json.dumps(row, sort_keys=True): row for row in rows}
    return [unique[key] for key in sorted(unique)], sorted(module_markers)


def proof():
    c.server_guard()
    m = c.legacy()
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    c.need(prior['stage'] == 'GOOGLE_BUSINESS_DEPLOYED_VERIFIED' and prior['source_sha'] == c.SOURCE and
        prior['frontend_version'] == c.FRONTEND and prior['schema_revision'] == c.REVISION, 'EXACT_DISABLED_RELEASE_REQUIRED')
    info = m.inspect('t24-crm')
    c.need(info['State']['Running'] and info['Image'] == c.IMAGE and m.runtime(info) == prior['crm'], 'EXACT_DISABLED_RUNTIME_REQUIRED')
    c.no_gbp(info)
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    c.need(c.H(active) == ACTIVE_NGINX_SHA, 'ACTUAL_PREFLIGHT_NGINX_DRIFT')
    logs, modules = logging_view(active)
    values = c.env_dict(info['Config']['Env'])
    names = sorted(name for name in values if APM_NAME.search(name))
    driver = info['HostConfig'].get('LogConfig') or {}
    driver_type = driver.get('Type')
    c.need(isinstance(driver_type, str) and driver_type in KNOWN_DRIVERS, 'UNKNOWN_DOCKER_LOG_DRIVER_REQUIRES_REVIEW')
    options = driver.get('Config') or {}
    c.need(isinstance(options, dict) and all(isinstance(name, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,100}', name) for name in options), 'LOG_OPTION_NAMES_REJECTED')
    command = ' '.join(str(value) for value in (info['Config'].get('Entrypoint') or []) + (info['Config'].get('Cmd') or []))
    markers = [name for name in COMMAND_MARKERS if name in command.lower()]
    addresses, nonpublic = public_dns_ips(socket.getaddrinfo('t24-crm.com', 443, type=socket.SOCK_STREAM))
    c.need(m.runtime(info) == m.runtime(m.inspect('t24-crm')) and c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) == ACTIVE_NGINX_SHA, 'RUNTIME_CHANGED_DURING_DIAGNOSTICS')
    return {'stage': 'GBP_ACTIVATION_READONLY_LOGGING_DNS_EVIDENCE', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'source_sha': c.SOURCE, 'prior_deployed_sha256': c.PRIOR_SHA, 'active_nginx_config_sha256': ACTIVE_NGINX_SHA,
        'dns_host': 't24-crm.com', 'public_dns_ips': addresses, 'nonpublic_dns_answers_observed': nonpublic,
        'dns_addresses_are_not_origin_route_proof': True, 'docker_log_driver': driver_type,
        'docker_log_option_names': sorted(options), 'apm_or_logging_environment_names': names,
        'instrumentation_command_markers': markers, 'nginx_logging_directives': logs, 'nginx_module_markers': modules,
        'manual_external_logging_review_still_required': True, 'environment_values_exported': False,
        'log_option_values_exported': False, 'business_writes': False, 'configuration_changed': False,
        'provider_requests': False}


def main():
    print(json.dumps(proof(), sort_keys=True))
