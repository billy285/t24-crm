"""Fresh disabled-release proof, and a deliberately redacted Nginx planning view."""
import base64
import json
import os
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
import core as c


def safe_nginx_view(blob):
    """No arbitrary config values, header secrets, URLs or comments are returned."""
    safe_names = {'listen', 'server_name', 'root', 'location', 'proxy_http_version',
        'proxy_read_timeout', 'proxy_send_timeout', 'proxy_connect_timeout',
        'try_files', 'access_log', 'error_log', 'include', 'server', 'http', 'events'}
    result = []
    for index, raw in enumerate(blob.decode('utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name = line.split(None, 1)[0].rstrip(';{}')
        if line in {'}', '};', '{'}:
            display = line
        elif name in safe_names and re.fullmatch(r'[A-Za-z0-9_$ /.:;{}=~^*?+@()\[\]-]+', line):
            display = line
        elif name == 'proxy_pass' and re.fullmatch(r'proxy_pass http://(?:127\.0\.0\.1|localhost):[0-9]{2,5}/?;', line):
            display = line
        elif name == 'proxy_set_header' and re.fullmatch(r'proxy_set_header (?:Host|X-Real-IP|X-Forwarded-For|X-Forwarded-Proto|Upgrade|Connection) (?:\$[a-z_]+|"?upgrade"?);', line):
            display = line
        else:
            display = (name if re.fullmatch('[a-z_]+', name) else 'directive') + ' [REDACTED]' + (' {' if line.endswith('{') else '')
        result.append({'line': index, 'config': display})
    return result


def rows_evidence(rows):
    return {name: {'count': row['count'], 'rows_sha256': row['rows_sha256'],
        'shape_sha256': c.H(json.dumps({key: row[key] for key in ('columns', 'schema', 'indexes')}, sort_keys=True, separators=(',', ':')).encode())}
        for name, row in rows.items()}


def proof(*, nginx_hash=None, require_empty=True):
    c.server_guard()
    m = c.legacy()
    pins = json.loads(m.read(c.PINS, c.PINS_SHA))
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    c.need(prior['stage'] == 'GOOGLE_BUSINESS_DEPLOYED_VERIFIED' and prior['deployed'] is True and prior['source_sha'] == c.SOURCE and prior['frontend_version'] == c.FRONTEND and prior['schema_revision'] == c.REVISION, 'EXACT_DISABLED_RELEASE_REQUIRED')
    crm = m.inspect('t24-crm')
    c.need(crm['State']['Running'] and crm['Image'] == c.IMAGE and m.runtime(crm) == prior['crm'], 'DISABLED_RUNTIME_DRIFT')
    c.no_gbp(crm)
    m.retained().require_safe_original_restart(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.private_boundary(pins)
    credential = m.credential_boundary()
    inventory = m.inventory(crm['Id'])
    expected_inventory = json.loads(m.read(c.PRIOR / 'backend-candidate-inventory.json', prior['candidate_inventory_sha256']))
    c.need(inventory == expected_inventory, 'BACKEND_INVENTORY_DRIFT')
    schema = m.schema_signature(m.BUSINESS, c.REVISION)
    c.need(schema == prior['schema_sha256'], 'SCHEMA_DRIFT')
    rows = m.sql_snapshot(m.BUSINESS)
    c.need(len(rows) == 124 and c.TABLES <= rows.keys(), 'EXACT_EXISTING_TABLE_SET_REQUIRED')
    if require_empty:
        c.need(all(rows[name]['count'] == 0 for name in c.TABLES), 'GOOGLE_ROWS_MUST_STILL_BE_EMPTY')
    nginx = m.NGINX.read_bytes()
    c.need(c.H(nginx) == (nginx_hash or prior['nginx_sha256']), 'NGINX_BASELINE_DRIFT')
    public = Path(prior['public_root'])
    static = m.tree(public)
    c.need(m.digest(static) == prior['public_inventory_sha256'] and json.loads((public / 'app-version.json').read_bytes())['version'] == c.FRONTEND, 'STATIC_INVENTORY_DRIFT')
    # Parse/check the active configuration without printing its raw values.
    active = c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')
    c.need(nginx.rstrip() in active and active.count(b'# configuration file /etc/nginx/sites-enabled/t24-crm:') == 1, 'ACTIVE_SITE_NOT_CONFIRMED')
    m.ready(crm['Id'])
    c.need(rows == m.sql_snapshot(m.BUSINESS), 'ROWS_CHANGED_DURING_PREFLIGHT')
    c.need(m.runtime(crm) == m.runtime(m.inspect('t24-crm')) and inventory == m.inventory(crm['Id']), 'RUNTIME_CHANGED_DURING_PREFLIGHT')
    c.need(nginx == m.NGINX.read_bytes() and static == m.tree(public), 'PUBLIC_CONFIGURATION_CHANGED_DURING_PREFLIGHT')
    m.private_boundary(pins)
    identity = m.BUSINESS.stat()
    return {'stage': 'GBP_ACTIVATION_READONLY_PREFLIGHT', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'host': c.HOST, 'source_sha': c.SOURCE, 'frontend_version': c.FRONTEND, 'schema_revision': c.REVISION,
        'schema_sha256': schema, 'prior_deployed_sha256': c.PRIOR_SHA, 'crm': m.runtime(crm),
        'backend_inventory_sha256': m.digest(inventory), 'public_root': str(public),
        'public_inventory_sha256': m.digest(static), 'nginx_sha256': c.H(nginx),
        'active_nginx_config_sha256': c.H(active), 'nginx_safe_view': safe_nginx_view(nginx),
        'database_identity': [identity.st_dev, identity.st_ino], 'rows': rows_evidence(rows),
        'private_boundary_verified': True, 'credential_boundary': credential,
        'gbp_environment_absent': True, 'google_tables_empty': require_empty,
        'provider_requests': False, 'business_writes': False, 'configuration_changed': False,
        'environment_values_exported': False, 'customer_records_exported': False}


def main():
    value = proof()
    blob = c.encoded(value)
    print(json.dumps({'stage': value['stage'], 'proof_bytes': len(blob), 'proof_sha256': c.H(blob),
        'proof_zlib_base64': base64.b64encode(zlib.compress(blob, 9)).decode()}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'stage': 'GBP_ACTIVATION_PREFLIGHT_REJECTED', 'code': c.safe_code(error)}))
        raise SystemExit(1)
