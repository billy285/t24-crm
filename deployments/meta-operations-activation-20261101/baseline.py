"""Fresh all-150-table baseline. No rotation gate, cleanup, or SQL writes."""
import hashlib
import json
from pathlib import Path
import re
from types import ModuleType, SimpleNamespace

c = None
BASELINE_SHA = '1bb4774655a7fd87664c591ef7463979cccdc26e362fa2c562c8ff668cc09522'
_CACHE = None


def configure(core):
    global c
    c = core


def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def dependencies():
    global _CACHE
    c.need(c is not None, 'REVIEWED_CORE_REQUIRED'); c.runtime_pins_ready()
    root = Path('/opt/t24-crm/releases/meta-operations-'+c.SOURCE_SHA[:12]+'-20261101')
    body = c.read(root/'release.py', sha=c.RELEASE_TOOL_SHA)
    if _CACHE is None:
        module = ModuleType('_independent_publisher_deployed_operations_release'); module.__file__ = str(root/'release.py')
        exec(compile(body, module.__file__, 'exec'), module.__dict__)
        c.need(module.SOURCE_SHA == c.SOURCE_SHA and module.FRONTEND == c.FRONTEND and module.NEW_REVISION == c.SCHEMA_REVISION, 'EXACT_DEPLOYED_OPERATIONS_TOOL_REQUIRED')
        receipt = c.strict_json(c.read(root/'deployed.json', sha=c.DEPLOYED_SHA))
        c.need(receipt['stage'] == 'META_OPERATIONS_DEPLOYED_OFF_VERIFIED' and receipt['deployed'] is True and
               receipt['source_sha'] == c.SOURCE_SHA and receipt['frontend_version'] == c.FRONTEND and receipt['schema_revision'] == c.SCHEMA_REVISION and
               receipt['crm']['id'] == c.ORIGINAL_ID and receipt['crm']['image'] == c.IMAGE, 'EXACT_OPERATIONS_DEPLOYED_RECEIPT_REQUIRED')
        c.need(receipt['operations_environment_absent'] is True and receipt['operations_execution_enabled'] is False and
               receipt['operations_scheduler_enabled'] is False and receipt['old_meta_nine_env_and_owner_connections_bindings_preserved'] is True and
               receipt['google_on_cutoff_preserved'] is True and receipt['external_publish_or_reply_performed'] is False, 'EXACT_DISABLED_PRESERVING_DEPLOYMENT_REQUIRED')
        prepared = c.strict_json(c.read(root/'prepared.json', sha=receipt['prepared_sha256']))
        args = SimpleNamespace(release=root, manifest_sha256=prepared['manifest_sha256'], payload_sha256=prepared['payload_sha256'],
            preflight=Path('/opt/t24-crm/releases/meta-operations-preflight-'+prepared['preflight_sha256'][:12]+'.json'),
            preflight_sha256=prepared['preflight_sha256'], review_sha256=receipt['prepared_sha256'])
        workflow = module.Release(args)
        inventory = c.strict_json(c.read(root/'backend-candidate-inventory.json', sha=receipt['candidate_inventory_sha256']))
        _CACHE = SimpleNamespace(module=module, workflow=workflow, m=workflow.m, safe=workflow.safe, base=workflow.base,
            helper=workflow.helper, receipt=receipt, inventory=inventory)
    return _CACHE


def source(ctx, info): return ctx.workflow.source_boundary(info, ctx.inventory)


def legacy_environment(ctx, info):
    env = info['Config']['Env']; c.old_environment(env)
    selected = [row for row in env if row.split('=', 1)[0].startswith('T24_META_')]
    ctx.workflow.core.validate_meta_env(selected)
    c.need(digest(env) == ctx.workflow.proof['environment_sha256'] and
           digest(selected) == ctx.workflow.proof['meta_environment_sha256'], 'ALL_ORIGINAL_ENVIRONMENT_VALUES_AND_ORDER_DRIFT')
    return digest(env)


def _sample(ctx):
    w, m = ctx.workflow, ctx.m
    w.protections(updated=True, head=c.SCHEMA_REVISION, schema=ctx.receipt['schema_sha256'], recovery=True)
    rows = w.rows(); c.need(len(rows) == 150 and set(w.retained.NEW_TABLES) <= set(rows), 'EXACT_CURRENT_150_TABLES_REQUIRED')
    # No table-emptiness test: legitimate read grants, flows and all nine new
    # Ops tables are preserved whether they are empty or populated.
    c.need(w.new_schema(m.BUSINESS, empty=False) == ctx.receipt['schema_sha256'], 'EXACT_CURRENT_OPERATIONS_SCHEMA_REQUIRED')
    return {'rows': w.retained.evidence(rows), 'database_metadata': w.metadata(m.BUSINESS),
            'schema_sha256': ctx.receipt['schema_sha256'], 'database_identity': w.proof['database_identity'],
            'private_boundary': w.proof['private_boundary'], 'nginx_sha256': c.H(m.NGINX.read_bytes()),
            'active_nginx_sha256': c.H(m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')),
            'public_root': str(w.public), 'public_inventory_sha256': m.verify_public(w.public, w.manifest),
            'content_security_policy_sha256': w.proof['content_security_policy_sha256']}


def collect():
    ctx = dependencies(); m = ctx.m; old = m.inspect('t24-crm')
    c.need(old['State']['Running'] is True and m.runtime(old) == ctx.receipt['crm'], 'EXACT_CURRENT_DEPLOYED_RUNTIME_REQUIRED')
    env_sha = legacy_environment(ctx, old)
    ctx.workflow.pf.google_environment(old); m.verify_secret_mount(old); m.verify_production_worker_enabled(old)
    m.retained().require_safe_original_restart(old); source(ctx, old)
    sample = _sample(ctx)
    return {**sample, 'stage': 'META_OPERATIONS_ACTIVATION_READONLY_BASELINE', 'host': c.HOST, 'source_sha': c.SOURCE_SHA,
            'frontend_version': c.FRONTEND, 'schema_revision': c.SCHEMA_REVISION, 'deployed_sha256': c.DEPLOYED_SHA,
            'crm': m.runtime(old), 'environment_sha256': env_sha, 'backend_inventory_sha256': digest(ctx.inventory),
            'google_scheduler_enabled': True, 'google_scheduler_activation_from': c.ACTIVATION_FROM,
            'all_existing_meta_and_ops_rows_preserved': True, 'business_writes': False, 'provider_requests': False}


def capture():
    c.server_guard(); first = collect(); current = collect(); ctx = dependencies()
    ctx.workflow.retained.live_sequence_boundary(first['database_metadata'], current['database_metadata'])
    c.need({**current, 'database_metadata': first['database_metadata']} == first, 'ACTIVATION_BASELINE_CHANGED_DURING_CAPTURE')
    c.mkdir(c.ROOT); sha = c.write(c.ROOT/'baseline.json', current)
    return {'stage': 'META_OPERATIONS_ACTIVATION_BASELINE_CAPTURED', 'sha256': sha, 'path': str(c.ROOT/'baseline.json'),
            'source_sha': c.SOURCE_SHA, 'frontend_version': c.FRONTEND, 'schema_revision': c.SCHEMA_REVISION,
            'table_count': 150, 'runtime': current['crm'], 'rows_sha256': digest(current['rows']),
            'all_existing_meta_and_ops_rows_preserved': True, 'google_scheduler_enabled': True,
            'google_scheduler_activation_from': c.ACTIVATION_FROM, 'business_writes': False,
            'credential_file_content_read': False, 'provider_requests': False, 'runtime_changed': False}


def proof():
    c.need(isinstance(BASELINE_SHA, str) and re.fullmatch('[a-f0-9]{64}', BASELINE_SHA) and BASELINE_SHA != '0'*64, 'ACTUAL_FRESH_ALL150_BASELINE_REQUIRED')
    value = c.strict_json(c.read(c.ROOT/'baseline.json', sha=BASELINE_SHA))
    c.need(value['stage'] == 'META_OPERATIONS_ACTIVATION_READONLY_BASELINE' and value['source_sha'] == c.SOURCE_SHA and
           value['deployed_sha256'] == c.DEPLOYED_SHA and len(value['rows']) == 150 and
           value['crm']['id'] == c.ORIGINAL_ID and value['crm']['image'] == c.IMAGE, 'EXACT_ALL150_ACTIVATION_PROOF_REQUIRED')
    return value


def verify(stage, *, current=None, recovery=False):
    c.server_guard(); p = proof(); ctx = dependencies(); sample = _sample(ctx)
    boundary = ctx.workflow.retained
    (boundary.sequence_boundary(p['database_metadata'], sample['database_metadata'], recovery=True) if recovery else
     boundary.live_sequence_boundary(p['database_metadata'], sample['database_metadata']))
    for key, value in sample.items():
        if key == 'database_metadata' or recovery and key == 'rows': continue
        c.need(value == p[key], 'ALL150_SCHEMA_ROWS_OR_PROTECTED_BOUNDARY_DRIFT')
    if current is None:
        current = ctx.m.inspect('t24-crm')
        c.need(current['State']['Running'] is True and ctx.m.runtime(current) == p['crm'], 'EXACT_ACTIVATION_ORIGINAL_RUNTIME_REQUIRED')
        legacy_environment(ctx, current)
    c.need(current['Image'] == c.IMAGE, 'SAME_APPLICATION_IMAGE_REQUIRED')
    ctx.workflow.pf.google_environment(current); ctx.m.verify_secret_mount(current); ctx.m.verify_production_worker_enabled(current); source(ctx, current)
    return {'proof': p, 'context': ctx, 'current': current, 'stage': stage}
