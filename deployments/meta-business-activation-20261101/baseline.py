"""Fresh 141-table read-only baseline, with no credentials or row contents exported."""
import hashlib
import json
from pathlib import Path
import re
from types import ModuleType, SimpleNamespace
from datetime import datetime, timezone

c = None
BASELINE_SHA = '20be9f4367c65b7a00882dbcd789a5867d00a4bfa8a57bf611bc2b3c3ad0c823'
RELEASE = Path('/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031')
RELEASE_SHA = 'a14f6d41eb6089e1a124c8326a27031280af4dbc9f58c5a73e797565d0135c98'
PREFLIGHT_SHA = 'b4f672ed78d5743027ad99dce0a95b222c3059bd8868866a8314bff7734a1483'
_CACHE = None


def configure(core):
    global c
    c = core


def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _load(path, sha, name):
    module = ModuleType(name); module.__file__ = str(path)
    exec(compile(c.read(path, sha=sha), str(path), 'exec'), module.__dict__)
    return module


def dependencies():
    global _CACHE
    c.need(c is not None, 'REVIEWED_CORE_REQUIRED')
    # Always verify entry bytes; never cache a live business/runtime boundary.
    c.read(RELEASE / 'release.py', sha=RELEASE_SHA)
    c.read(RELEASE / 'preflight.py', sha=PREFLIGHT_SHA)
    if _CACHE is None:
        release = _load(RELEASE / 'release.py', RELEASE_SHA, '_meta_activation_retained_release')
        pf = _load(RELEASE / 'preflight.py', PREFLIGHT_SHA, '_meta_activation_retained_preflight')
        helper, m, base, safe, workflow, static, previous = pf.dependencies()
        receipt = c.strict_json(c.read(RELEASE / 'deployed.json', sha=c.DEPLOYED_SHA))
        c.need(receipt['stage'] == 'META_BUSINESS_DEPLOYED_VERIFIED' and receipt['deployed'] is True and
            receipt['source_sha'] == c.SOURCE_SHA and receipt['frontend_version'] == c.FRONTEND and
            receipt['schema_revision'] == c.SCHEMA_REVISION and receipt['crm']['id'] == c.ORIGINAL_ID and receipt['crm']['image'] == c.IMAGE,
            'EXACT_DEPLOYED_META_BASELINE_REQUIRED')
        c.need(receipt['meta_environment_keys_absent'] is True and receipt['meta_feature_enabled'] is False and
            receipt['scheduler_enabled'] is True and receipt['scheduler_activation_from'] == c.ACTIVATION_FROM,
            'EXACT_META_DISABLED_GOOGLE_ON_BASELINE_REQUIRED')
        inventory = c.strict_json(c.read(RELEASE / 'backend-candidate-inventory.json', sha=receipt['candidate_inventory_sha256']))
        pins = c.strict_json(m.read(base.PRIVATE_PINS, base.PRIVATE_PINS_SHA))
        _CACHE = SimpleNamespace(release=release, pf=pf, helper=helper, m=m, base=base, safe=safe, receipt=receipt,
                                 inventory=inventory, pins=pins)
    return _CACHE


def protected_sample(ctx, *, require_meta_empty=False):
    m, r = ctx.m, ctx.receipt
    identity = m.BUSINESS.stat()
    rows = ctx.release.evidence(m.sql_snapshot(m.BUSINESS))
    c.need(len(rows) == 141, 'EXACT_141_TABLES_REQUIRED')
    if require_meta_empty:
        c.need(set(ctx.release.NEW_TABLES) <= set(rows) and all(rows[name]['count'] == 0 for name in ctx.release.NEW_TABLES),
               'EXISTING_META_DATA_REQUIRES_KEY_REUSE_REVIEW')
    c.need(m.schema_signature(m.BUSINESS, c.SCHEMA_REVISION) == r['schema_sha256'], 'EXACT_CURRENT_SCHEMA_REQUIRED')
    nginx = m.NGINX.read_bytes(); active = m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
    c.need(c.H(nginx) == r['nginx_sha256'] and c.H(active) == r['sentinel_active_nginx_sha256'], 'EXACT_UNCHANGED_NGINX_REQUIRED')
    ctx.pf.privacy_blocks(ctx.release, active)
    _, blocks = ctx.release.nginx_blocks(active)
    callbacks = [row for row in blocks if row['header'] == ['location', '=', c.CALLBACK_PATH]]
    c.need(len(callbacks) == 1 and ['access_log', 'off'] in callbacks[0]['directives'] and
           ['error_log', '/dev/null', 'crit'] in callbacks[0]['directives'], 'EXACT_META_CALLBACK_PRIVACY_REQUIRED')
    static = Path(r['public_root'])
    c.need(digest(m.tree(static)) == r['public_inventory_sha256'] and json.loads((static/'app-version.json').read_bytes())['version'] == c.FRONTEND,
           'EXACT_STATIC_SOURCE_REQUIRED')
    headers = ctx.pf.security_headers(m)
    c.need(headers['content_security_policy_sha256'] == r['content_security_policy_sha256'], 'EXACT_CSP_REQUIRED')
    return {'database_identity': [identity.st_dev, identity.st_ino], 'rows': rows,
            'schema_sha256': r['schema_sha256'], 'database_metadata': ctx.helper.db_metadata(m.BUSINESS),
            'nginx_sha256': c.H(nginx), 'active_nginx_sha256': c.H(active), 'public_root': str(static),
            'public_inventory_sha256': r['public_inventory_sha256'], 'content_security_policy_sha256': headers['content_security_policy_sha256'],
            'private_boundary': ctx.safe.safe_private_boundary(m, ctx.pins), 'credential_boundary': m.credential_boundary(),
            'google_credential_metadata': ctx.safe.protected_metadata(ctx.safe.GBP_ENV)}


def collect():
    ctx = dependencies(); m = ctx.m; original = m.inspect('t24-crm')
    c.need(original['State']['Running'] is True and m.runtime(original) == ctx.receipt['crm'], 'EXACT_RUNNING_ORIGINAL_REQUIRED')
    ctx.pf.google_environment(original); ctx.pf.meta_environment(original)
    m.verify_secret_mount(original); m.verify_production_worker_enabled(original); m.retained().require_safe_original_restart(original)
    c.need(m.inventory(original['Id']) == ctx.inventory, 'EXACT_BACKEND_SOURCE_REQUIRED')
    sample = protected_sample(ctx, require_meta_empty=True)
    return {**sample, 'stage': 'META_ACTIVATION_READONLY_BASELINE', 'host': c.HOST, 'source_sha': c.SOURCE_SHA,
            'frontend_version': c.FRONTEND, 'schema_revision': c.SCHEMA_REVISION, 'deployed_sha256': c.DEPLOYED_SHA,
            'crm': m.runtime(original), 'environment_sha256': digest(original['Config']['Env']),
            'backend_inventory_sha256': digest(ctx.inventory), 'meta_environment_keys_absent': True,
            'google_scheduler_enabled': True, 'google_scheduler_activation_from': c.ACTIVATION_FROM}


def capture():
    # This read-only capture does not require a newly created Meta config or
    # consent to access a secret; it creates only a protected fingerprint proof.
    c.server_guard(); first = collect(); latest = collect()
    dependencies().release.live_sequence_boundary(first['database_metadata'], latest['database_metadata'])
    c.need({**latest, 'database_metadata': first['database_metadata']} == first, 'BASELINE_CHANGED_DURING_CAPTURE')
    c.mkdir(c.ROOT); path = c.ROOT/'baseline.json'; sha = c.write(path, latest)
    return {'stage': 'META_ACTIVATION_BASELINE_CAPTURED', 'sha256': sha, 'path': str(path), 'table_count': 141,
            'source_sha': c.SOURCE_SHA, 'frontend_version': c.FRONTEND, 'schema_revision': c.SCHEMA_REVISION,
            'rows_sha256': digest(latest['rows']), 'runtime': latest['crm'], 'meta_environment_keys_absent': True,
            'google_scheduler_enabled': True, 'google_scheduler_activation_from': c.ACTIVATION_FROM,
            'business_writes': False, 'credential_content_read': False, 'provider_requests': False, 'runtime_changed': False}


def proof():
    c.need(isinstance(BASELINE_SHA, str) and re.fullmatch('[a-f0-9]{64}', BASELINE_SHA) and BASELINE_SHA != '0'*64,
           'ACTUAL_REVIEWED_BASELINE_SHA_REQUIRED')
    value = c.strict_json(c.read(c.ROOT/'baseline.json', sha=BASELINE_SHA))
    c.need(value['stage'] == 'META_ACTIVATION_READONLY_BASELINE' and value['deployed_sha256'] == c.DEPLOYED_SHA and
        value['source_sha'] == c.SOURCE_SHA and value['schema_revision'] == c.SCHEMA_REVISION and len(value['rows']) == 141,
        'EXACT_CAPTURED_BASELINE_REQUIRED')
    return value


def source(ctx, info):
    ctx.base.Release.source_overlay_boundary(SimpleNamespace(m=ctx.m), info, ctx.inventory)


def verify(stage, *, current=None, recovery=False):
    c.server_guard(); p = proof(); ctx = dependencies(); m = ctx.m
    sample = protected_sample(ctx)
    ctx.release.sequence_boundary(p['database_metadata'], sample['database_metadata'], recovery=True) if recovery else ctx.release.live_sequence_boundary(p['database_metadata'], sample['database_metadata'])
    for key in sample:
        if key == 'database_metadata' or recovery and key == 'rows': continue
        c.need(sample[key] == p[key], 'PROTECTED_141_TABLE_OR_PRIVATE_BOUNDARY_DRIFT')
    if current is None:
        current = m.inspect('t24-crm')
        c.need(current['State']['Running'] is True and m.runtime(current) == p['crm'], 'EXACT_BASELINE_RUNTIME_REQUIRED')
        ctx.pf.meta_environment(current)
    c.need(current['Image'] == c.IMAGE, 'SAME_APPLICATION_IMAGE_REQUIRED')
    ctx.pf.google_environment(current); m.verify_secret_mount(current); m.verify_production_worker_enabled(current)
    source(ctx, current)
    return {'proof': p, 'context': ctx, 'current': current, 'stage': stage}
