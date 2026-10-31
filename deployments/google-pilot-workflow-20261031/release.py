"""Exact-source no-migration patch release for the owner-only Google pilot UI."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
import sys
import time
import types

H = lambda body: hashlib.sha256(body).hexdigest()
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE_SHA = '5931e430e629fb633f846ebc068a8fc12d4b9a0a'
FRONTEND = '8cc54170ca26'
APPLICATION_FREEZE_SHA = '3c96413522b2f36e930093bd586fe85ad746bf68497b7aed66a16fd4cd4c8843'
PREFLIGHT_SHA = '23c630bd73abfe6a5f4862e9285856e4bd4bfcb74b7adec79d124ae2424fe22e'
BASE_SOURCE = 'c114242205af98c33a7c2ad435409e0c84ebd085'
BASE_FRONTEND = '33047aa593a2'
BASE_DEPLOYED_SHA = '5639019ef95f88523eea7dc0548a74c0d7705871d7af834bb0b3b33d24ebd3bc'
REVISION = 'acd7c9d0e136'
SCOPE = 'google-pilot-workflow'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
BACKEND_FILES = frozenset({'routers/google_business.py', 'services/google_business_readiness.py'})
EXISTING_BACKEND_FILES = frozenset({'routers/google_business.py'})
FRONTEND_FILES = frozenset('app/frontend/src/' + name for name in ('pages/MediaOperations.tsx', 'components/GoogleBusinessManagement.tsx', 'components/GoogleBusinessWorkspace.tsx', 'components/GoogleReadinessChecklist.tsx', 'components/google-readiness.css', 'lib/google-readiness.ts', 'components/MediaPlanningWorkspace.tsx'))
TEST_FILES = frozenset({'app/backend/tests/test_google_business_readiness.py', 'app/frontend/tests/google-pilot-workflow.test.mjs'})
SOURCE_FILES = frozenset('app/backend/' + name for name in BACKEND_FILES) | FRONTEND_FILES | TEST_FILES
DELIVERY_PREFIX = '/api/v1/media-publication-images/delivery/'
CALLBACK = '/api/v1/google-business/oauth/callback'


def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def pins_ready():
    need(all(isinstance(v, str) and re.fullmatch(pattern, v) and set(v) != {'0'} for v, pattern in ((SOURCE_SHA, '[a-f0-9]{40}'), (FRONTEND, '[a-f0-9]{12}'), (APPLICATION_FREEZE_SHA, '[a-f0-9]{64}'), (PREFLIGHT_SHA, '[a-f0-9]{64}'))) and bool(FRONTEND_FILES), 'ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED')


def local_bytes(path, maximum=16 * 1024 ** 2):
    path = Path(path); row = path.lstat()
    need(path.resolve() == path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink == 1, 'REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); body = stream.read(maximum + 1)
    after = path.lstat(); fields = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    need(fields(row) == fields(opened) == fields(after) and len(body) <= maximum, 'LOCAL_INPUT_READ_DRIFT'); return body


def protected_read(path, sha):
    row = path.lstat(); need(row.st_uid == 0 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_TOOL_REQUIRED')
    body = local_bytes(path, 1048576); need(H(body) == sha, 'EXACT_REVIEWED_TOOL_BYTES_REQUIRED'); return body


def validate_summary(summary):
    need(summary['stage'] == 'GOOGLE_PILOT_WORKFLOW_PREFLIGHT_CAPTURED' and summary['source_sha'] == BASE_SOURCE and summary['frontend_version'] == BASE_FRONTEND and summary['schema_revision'] == REVISION and summary['table_count'] == 136 and summary['deployed_sha256'] == BASE_DEPLOYED_SHA, 'EXACT_ACTUAL_PREFLIGHT_SUMMARY_REQUIRED')
    need(summary['scheduler_enabled'] is True and summary['scheduler_activation_from'] == ACTIVATION_FROM and all(summary[k] is True for k in ('gbp_feature_enabled', 'callback_logging_protection_retained', 'image_delivery_logging_protection_retained', 'existing_image_policies_and_data_preserved', 'private_boundary_verified', 'host_docker_timestamp_parser_verified')), 'EXACT_EXISTING_ON_SUMMARY_REQUIRED')
    need(all(summary[k] is False for k in ('credential_content_read', 'private_content_read', 'executed_business_writes')), 'READONLY_SUMMARY_REQUIRED')
    sha = summary['sha256']; need(re.fullmatch('[a-f0-9]{64}', sha) and summary['path'] == '/opt/t24-crm/releases/google-pilot-workflow-preflight-' + sha[:12] + '.json', 'EXACT_SERVER_PROOF_PATH_REQUIRED')


def next_nginx(original, old, new):
    old, new = os.fsencode(str(old)), os.fsencode(str(new))
    need(original.count(old) == 1 and new not in original, 'EXACT_SINGLE_OLD_PUBLIC_ROOT_REQUIRED')
    updated = original.replace(old, new, 1)
    need(updated.replace(new, old, 1) == original, 'NONROOT_NGINX_CHANGE_REJECTED'); return updated


class Release:
    def __init__(self, args):
        pins_ready(); self.args = args
        module = types.ModuleType('_google_pilot_preflight'); module.__file__ = str(args.release / 'preflight.py')
        exec(compile(protected_read(Path(module.__file__), PREFLIGHT_SHA), module.__file__, 'exec'), module.__dict__); self.pf = module
        self.helper, self.m, self.base, self.safe, self.w, _ = module.dependencies(); m = self.m
        self.manifest = json.loads(m.read(args.release / 'manifest.json', args.manifest_sha256)); m.read(args.release / 'payload.tar.gz', args.payload_sha256)
        self.proof = json.loads(m.read(args.preflight, args.preflight_sha256)); self.validate()
        self.pins = json.loads(m.read(self.base.PRIVATE_PINS, self.base.PRIVATE_PINS_SHA)); self.source, self.version = SOURCE_SHA, FRONTEND
        self.public = Path('/var/www/t24-crm-public/' + SCOPE + '-' + SOURCE_SHA[:12] + '-20261031')
        need(args.release == Path('/opt/t24-crm/releases/' + SCOPE + '-' + SOURCE_SHA[:12] + '-20261031'), 'EXACT_RELEASE_PATH_REQUIRED')
        m.SOURCE, m.SCOPE, m.BACKEND = SOURCE_SHA, SCOPE, set(BACKEND_FILES)
        m.BASELINE_FRONTEND, m.FRONTEND_VERSION = BASE_FRONTEND, FRONTEND
        m.PUBLIC, m.NGINX_SHA, m.STATIC_SHA = Path(self.proof['public_root']), self.proof['nginx_sha256'], self.proof['public_inventory_sha256']
        m.OLD_ID, m.BASE_IMAGE, m.OLD_CONFIG = (self.proof['crm'][k] for k in ('id', 'image', 'config'))
        m.public_root = lambda: self.public
        m.next_nginx = lambda original: next_nginx(original, self.proof['public_root'], self.public)
        # Hash-loaded helper source stays unchanged. Only these local, public
        # release identity parameters are rebound for explicitly reused methods.
        self.w.SOURCE_SHA, self.w.FRONTEND, self.w.SCOPE, self.w.BACKEND_FILES = SOURCE_SHA, FRONTEND, SCOPE, BACKEND_FILES
        self.old_name = 't24-crm-before-' + SCOPE + '-' + SOURCE_SHA[:12]; self.candidate_name = 't24-crm-candidate-' + SCOPE + '-' + SOURCE_SHA[:12]; self.offline_name = 't24-' + SCOPE + '-probe-' + SOURCE_SHA[:12]

    def validate(self):
        p, v, a = self.proof, self.manifest, self.args
        need(p['stage'] == 'GOOGLE_PILOT_WORKFLOW_READONLY_PREFLIGHT' and p['host'] == HOST and p['source_sha'] == BASE_SOURCE and p['frontend_version'] == BASE_FRONTEND and p['schema_revision'] == REVISION and p['deployed_sha256'] == BASE_DEPLOYED_SHA, 'EXACT_ENABLED_BASELINE_REQUIRED')
        need(p['crm']['id'] == self.pf.ORIGINAL_ID and p['crm']['image'] == self.pf.IMAGE and p['scheduler_enabled'] is True and p['scheduler_activation_from'] == ACTIVATION_FROM and len(p['rows']) == 136 and all(p[k] is True for k in ('callback_logging_protection_retained', 'image_delivery_logging_protection_retained', 'existing_image_policies_and_data_preserved', 'host_docker_timestamp_parser_verified')), 'EXACT_EXISTING_136_TABLE_BOUNDARIES_REQUIRED')
        need(all(p[k] is False for k in ('provider_requests', 'business_writes', 'private_content_read', 'credential_content_read', 'container_or_configuration_changed')), 'READONLY_PREFLIGHT_REQUIRED')
        need(v['source_sha'] == SOURCE_SHA and v['frontend_version'] == FRONTEND and v['baseline_source_sha'] == BASE_SOURCE and v['baseline_frontend_version'] == BASE_FRONTEND and v['schema_revision'] == REVISION and v['database_migration'] is False and v['production_seed_rows'] is False and v['credentials_included'] is False and v['runtime_environment_changed'] is False and v['existing_image_policies_and_data_preserved'] is True, 'EXACT_NO_MIGRATION_SOURCE_SCOPE_REQUIRED')
        need(set(v['changed_source_files']) == SOURCE_FILES and len(v['changed_source_files']) == len(SOURCE_FILES) and v['application_freeze_sha256'] == APPLICATION_FREEZE_SHA, 'EXACT_APPLICATION_DELTA_REQUIRED')
        need(v['preflight_sha256'] == a.preflight_sha256 and v['payload_sha256'] == a.payload_sha256 and set(v['backend_before']) == set(v['backend_after']) == BACKEND_FILES and v['backend_before'] == p['backend_changed_before'], 'EXACT_PAYLOAD_PROOF_REQUIRED')
        need(all(bool(re.fullmatch('[a-f0-9]{64}', value or '')) if name in EXISTING_BACKEND_FILES else value is None for name, value in v['backend_before'].items()), 'EXACT_EXISTING_BACKEND_HASHES_REQUIRED')
        need({n[8:] for n in v['files'] if n.startswith('backend/')} == BACKEND_FILES and all(v['files']['backend/' + n] == v['backend_after'][n] for n in BACKEND_FILES), 'EXACT_RUNTIME_PATCHES_REQUIRED')
        need(all(re.fullmatch('[a-f0-9]{64}', value) for value in [*v['files'].values(), *v['backend_after'].values()]), 'EXACT_MEMBER_HASHES_REQUIRED')
        need({'static/index.html', 'static/app-version.json'} <= set(v['files']) and all(n in {'backend/' + name for name in BACKEND_FILES} or n.startswith('static/') and self.m.static_path(n[7:]) for n in v['files']), 'EXACT_STATIC_PAYLOAD_REQUIRED')

    def record(self, name, value): return self.w.Release.record(self, name, value)
    def private_boundary(self): return self.w.Release.private_boundary(self)
    def metadata(self, path): return self.helper.db_metadata(path)
    def rows(self, path=None): return self.w.snapshot(self.m, path or self.m.BUSINESS)
    def source_boundary(self, info, inventory): return self.base.Release.source_overlay_boundary(self, info, inventory)
    def image(self): return self.w.Release.image(self)
    def offline_args(self, data, image): return self.w.Release.offline_args(self, data, image)
    def state(self, r, old): return self.w.Release.state(self, r, old)
    def identities(self, state, old): return self.w.Release.identities(self, state, old)
    def delivery_sentinel(self, candidate_id): return self.w.Release.delivery_sentinel(self, candidate_id)
    def public_check(self, candidate_id): return self.w.Release.public_check(self, candidate_id)
    def active_probe(self): return self.w.Release.active_probe(self)

    def nginx(self, updated=False):
        body = self.m.NGINX.read_bytes(); active = self.m.run(['nginx', '-T'], 'ACTIVE_NGINX_PARSE_FAILED'); observed = H(active)
        old, new = os.fsencode(self.proof['public_root']), os.fsencode(str(self.public))
        if updated:
            need(body.count(new) == active.count(new) == 1, 'EXACT_NEW_PUBLIC_ROOT_REQUIRED'); body, active = body.replace(new, old, 1), active.replace(new, old, 1)
        need(H(body) == self.proof['nginx_sha256'] and H(active) == self.proof['active_nginx_config_sha256'], 'CALLBACK_DELIVERY_OR_NONROOT_NGINX_DRIFT'); return observed

    def protections(self, *, updated=False, recovery=False):
        m, p = self.m, self.proof; self.private_boundary()
        need(m.credential_boundary() == p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV) == p['google_credential_metadata'], 'CREDENTIAL_METADATA_DRIFT')
        row = m.BUSINESS.stat(); need([row.st_dev, row.st_ino] == p['database_identity'], 'DATABASE_INODE_DRIFT')
        self.w.sequence_boundary(p['database_metadata'], self.metadata(m.BUSINESS), forward=not recovery, recovery=recovery)
        need(m.schema_signature(m.BUSINESS, REVISION) == p['schema_sha256'], 'EXACT_UNCHANGED_136_TABLE_SCHEMA_REQUIRED')
        need(digest(m.tree(m.PUBLIC)) == p['public_inventory_sha256'], 'ORIGINAL_STATIC_DRIFT'); self.nginx(updated)

    def current(self):
        m, p = self.m, self.proof; self.protections(); old = m.inspect('t24-crm')
        need(old['State']['Running'] is True and m.runtime(old) == p['crm'], 'CURRENT_RUNTIME_DRIFT')
        self.pf.google_environment(old); m.verify_secret_mount(old); m.verify_production_worker_enabled(old); m.retained().require_safe_original_restart(old)
        inventory = m.inventory(old['Id']); need(digest(inventory) == p['backend_inventory_sha256'] and len(inventory) == p['backend_file_count'], 'CURRENT_SOURCE_DRIFT')
        need(digest(sorted(old['Config']['Env'])) == p['environment_sha256'] and self.w.evidence(self.rows()) == p['rows'], 'CURRENT_ENVIRONMENT_OR_ROWS_DRIFT')
        m.ready(old['Id']); return old, inventory

    def route_probe(self):
        expected = {'/api/v1/google-business': ('routers.google_business', self.base.GBP_ROUTES | {('/api/v1/google-business/bindings/{binding_id}/review', 'GET'), ('/api/v1/google-business/bindings/{binding_id}/readiness', 'GET')}), '/api/v1/media-operations': ('routers.media_operations', self.base.MEDIA_ROUTES), '/api/v1/media-publication-images': ('routers.media_publication_images', self.w.IMAGE_ROUTES), '/api/v1/media-planning': ('routers.media_planning', self.w.PLANNING_ROUTES)}
        return ("import socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nfrom main import app\nimport fastapi.routing\nexpected=" + repr(expected) + "\nschema=app.openapi()\ncontexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\nfor prefix,(module,methods) in expected.items():\n hidden={(prefix+'/delivery/{token}.png',m) for m in ('GET','HEAD')} if prefix=='/api/v1/media-publication-images' else set()\n actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}\n assert actual==methods-hidden\n registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__',''),getattr(x,'include_in_schema',True)) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]\n assert len(registered)==len(methods) and {(p,m) for p,m,_,_ in registered}==methods and all(mod==module for _,_,mod,_ in registered)\n assert all(visible is False for p,m,_,visible in registered if (p,m) in hidden)\nprint('EXACT_GOOGLE_PILOT_AND_EXISTING_MEDIA_ROUTES')\n")

    def prepare(self):
        self.helper.docker_timestamp_probe(); m, a = self.m, self.args; old, before = self.current()
        need({p.name for p in a.release.iterdir()} == {'release.py', 'preflight.py', 'manifest.json', 'payload.tar.gz'}, 'FRESH_STAGING_REQUIRED')
        m.extract(a.release, self.manifest); expected = {**before, **self.manifest['backend_after']}
        original_sha = self.record('original-container.json', old); before_sha = self.record('backend-original-inventory.json', before); after_sha = self.record('backend-candidate-inventory.json', expected)
        image = self.image(); data = a.release / 'probe-data'; data.mkdir(mode=0o700); (a.release / 'probe-logs').mkdir(mode=0o700)
        m.backup(m.BUSINESS, data / 'crm_prod.db'); rows = self.rows(data / 'crm_prod.db'); metadata = self.metadata(data / 'crm_prod.db'); objects = self.w.objects(data / 'crm_prod.db')
        need(self.w.evidence(rows) == self.proof['rows'] and m.schema_signature(data / 'crm_prod.db', REVISION) == self.proof['schema_sha256'], 'ISOLATED_COPY_DRIFT'); self.w.sequence_boundary(self.proof['database_metadata'], metadata, forward=True)
        need(not m.inspect_optional(self.offline_name), 'FRESH_OFFLINE_PROBE_NAME_REQUIRED'); command = self.offline_args(data, image); command[2:2] = ['--name', self.offline_name, '-d']; m.run(command, 'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name); self.base.verify_disabled_environment(m.inspect(self.offline_name)); need(m.inventory(self.offline_name) == expected, 'OFFLINE_SOURCE_DRIFT')
            checks = [("import sys;assert sys.version_info[:2]==(3,10);print('EXACT_PYTHON310')", b'EXACT_PYTHON310'), (self.route_probe(), b'EXACT_GOOGLE_PILOT_AND_EXISTING_MEDIA_ROUTES'), (self.base.gbp_disabled_probe(), b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK')]
            for code, marker in checks: need(marker in m.run(['docker', 'exec', self.offline_name, 'python', '-B', '-c', code], 'OFFLINE_PROBE_FAILED'), 'EXACT_OFFLINE_PROBE_MARKER_REQUIRED')
        finally: m.run(['docker', 'stop', '--time', '20', self.offline_name], 'OFFLINE_STOP_FAILED', 45)
        need(self.rows(data / 'crm_prod.db') == rows and self.w.objects(data / 'crm_prod.db') == objects and m.schema_signature(data / 'crm_prod.db', REVISION) == self.proof['schema_sha256'] and self.metadata(data / 'crm_prod.db') == metadata, 'OFFLINE_STARTUP_CHANGED_DATABASE')
        root, static = m.stage_public(a.release, self.manifest); next_sha = H(m.next_nginx(m.NGINX.read_bytes())); self.current()
        result = {'stage': 'GOOGLE_PILOT_WORKFLOW_PREPARED_OFFLINE_VERIFIED', 'source_sha': SOURCE_SHA, 'frontend_version': FRONTEND, 'schema_revision': REVISION, 'schema_sha256': self.proof['schema_sha256'], 'old_crm': m.runtime(old), 'candidate_image': image, 'preflight_sha256': a.preflight_sha256, 'manifest_sha256': a.manifest_sha256, 'payload_sha256': a.payload_sha256, 'original_container_sha256': original_sha, 'original_inventory_sha256': before_sha, 'candidate_inventory_sha256': after_sha, 'public_root': str(root), 'public_inventory_sha256': static, 'nginx_next_sha256': next_sha, 'table_count': 136, 'database_migration': False, 'offline_all_rows_schema_metadata_unchanged': True, 'existing_image_policies_and_data_preserved': True, 'callback_and_image_logging_protection_retained': True, 'actual_python310_verified': True, 'exact_media_google_routes': True, 'offline_network_none': True, 'offline_credentials_absent': True, 'offline_workers_off': True, 'scheduler_on_and_cutoff_preserved': True, 'host_docker_timestamp_parser_verified': True, 'provider_requests': False, 'production_database_written_by_tool': False, 'sequence_written_by_tool': False}
        sha = self.record('prepared.json', result); return {**result, 'receipt_sha256': sha}

    def reviewed(self):
        m, a = self.m, self.args; need(re.fullmatch('[a-f0-9]{64}', a.review_sha256 or ''), 'PREPARED_INDEPENDENT_REVIEW_REQUIRED'); r = json.loads(m.read(a.release / 'prepared.json', a.review_sha256))
        need(r['stage'] == 'GOOGLE_PILOT_WORKFLOW_PREPARED_OFFLINE_VERIFIED' and r['source_sha'] == SOURCE_SHA and r['frontend_version'] == FRONTEND and r['schema_revision'] == REVISION and r['schema_sha256'] == self.proof['schema_sha256'] and r['table_count'] == 136 and r['database_migration'] is False, 'EXACT_PREPARED_SCOPE_REQUIRED')
        need(r['manifest_sha256'] == a.manifest_sha256 and r['payload_sha256'] == a.payload_sha256 and r['preflight_sha256'] == a.preflight_sha256, 'EXACT_PREPARED_IDENTITIES_REQUIRED')
        need(all(r[k] is True for k in ('offline_all_rows_schema_metadata_unchanged', 'existing_image_policies_and_data_preserved', 'callback_and_image_logging_protection_retained', 'actual_python310_verified', 'exact_media_google_routes', 'offline_network_none', 'offline_credentials_absent', 'offline_workers_off', 'scheduler_on_and_cutoff_preserved', 'host_docker_timestamp_parser_verified')) and all(r[k] is False for k in ('provider_requests', 'production_database_written_by_tool', 'sequence_written_by_tool')), 'EXACT_OFFLINE_ACCEPTANCE_REQUIRED')
        old = json.loads(m.read(a.release / 'original-container.json', r['original_container_sha256'])); before = json.loads(m.read(a.release / 'backend-original-inventory.json', r['original_inventory_sha256'])); expected = json.loads(m.read(a.release / 'backend-candidate-inventory.json', r['candidate_inventory_sha256']))
        need(m.runtime(old) == r['old_crm'] == self.proof['crm'] and digest(before) == self.proof['backend_inventory_sha256'] and expected == {**before, **self.manifest['backend_after']}, 'PREPARED_BASELINE_DRIFT')
        need(m.image_id(r['candidate_image']) == r['candidate_image'] and m.verify_public(self.public, self.manifest) == r['public_inventory_sha256'], 'PREPARED_IMAGE_STATIC_DRIFT'); return r, old, before, expected

    def fresh(self, r, old, before, expected, state, *, updated=False, live=False, baseline=None, recovery=False):
        self.protections(updated=updated, recovery=recovery); retained, candidate = self.identities(state, old); self.w.compare(candidate, old, self.m); self.pf.google_environment(candidate)
        if not recovery: need(self.m.runtime(retained) == self.m.runtime(old), 'ORIGINAL_RESTART_PROVENANCE_DRIFT')
        self.m.verify_secret_mount(candidate); self.m.verify_production_worker_enabled(candidate); self.source_boundary(retained, before); self.source_boundary(candidate, expected)
        if live:
            need(candidate['State']['Running'] is True and retained['State']['Running'] is False and self.m.inspect('t24-crm')['Id'] == candidate['Id'], 'EXACT_SINGLE_LIVE_CANDIDATE_REQUIRED'); self.helper.validation_window(candidate)
        else: need(candidate['State']['Running'] is False, 'PRESTART_CANDIDATE_STOPPED_REQUIRED')
        need(type(candidate['RestartCount']) is int and candidate['RestartCount'] == 0, 'CANDIDATE_RESTARTED')
        if not recovery: need(self.w.evidence(self.rows()) == self.proof['rows'] and (baseline is None or self.rows() == baseline), 'BUSINESS_ROWS_CHANGED_DURING_SWITCH')
        return retained, candidate

    def accept(self, r, old, before, expected, state, baseline, *, updated):
        _, candidate = self.fresh(r, old, before, expected, state, updated=updated, live=True, baseline=baseline)
        output = self.m.run(['docker', 'exec', candidate['Id'], 'python', '-B', '-c', self.active_probe()], 'ACTIVE_GOOGLE_ENVIRONMENT_FAILED'); need(output.strip() == b'EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK', 'EXACT_ON_CUTOFF_MARKER_REQUIRED')
        need(self.m.verify_public(self.public, self.manifest) == r['public_inventory_sha256'], 'FINAL_PUBLIC_INVENTORY_DRIFT'); _, candidate = self.fresh(r, old, before, expected, state, updated=updated, live=True, baseline=baseline); return candidate

    def activate(self):
        m, a = self.m, self.args; r, old, before, expected = self.reviewed(); self.current()
        need(not (a.release / 'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name), 'FRESH_SWITCH_REQUIRED')
        original_nginx = m.NGINX.read_bytes(); need(H(m.next_nginx(original_nginx)) == r['nginx_next_sha256'], 'REVIEWED_NGINX_REQUIRED')
        self.record('nginx-before.conf', original_nginx); self.record('activation-started.json', {'source_sha': SOURCE_SHA, 'review_sha256': a.review_sha256, 'original_id': old['Id'], 'candidate_image': r['candidate_image']})
        status, body = m.retained().docker_request('POST', '/containers/create?name=' + self.candidate_name, m.clone_config(r['candidate_image'], old)); need(status == 201, 'CANDIDATE_CREATE_FAILED'); identity = json.loads(body)['Id']; need(re.fullmatch('[a-f0-9]{64}', identity), 'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json', {'source_sha': SOURCE_SHA, 'candidate_id': identity, 'candidate_image': r['candidate_image'], 'original_id': old['Id'], 'review_sha256': a.review_sha256}); state = self.state(r, old)
        try:
            _, candidate = self.fresh(r, old, before, expected, state); need(candidate['State']['Status'] == 'created' and candidate['State'].get('StartedAt') in {'', '0001-01-01T00:00:00Z', '0001-01-01T00:00:00.000000000Z'}, 'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker', 'stop', '--time', '30', old['Id']], 'ORIGINAL_STOP_FAILED', 60); retained, _ = self.fresh(r, old, before, expected, state); need(retained['State']['Running'] is False, 'ORIGINAL_STOPPED_REQUIRED')
            baseline = self.rows(); need(self.w.evidence(baseline) == self.proof['rows'], 'STOPPED_ORIGINAL_ROWS_DRIFT'); baseline_sha = self.record('production-before-rows.json', baseline); self.record('production-baseline-identity.json', {'source_sha': SOURCE_SHA, 'original_id': old['Id'], 'candidate_id': identity, 'review_sha256': a.review_sha256, 'rows_sha256': baseline_sha})
            m.run(['docker', 'rename', old['Id'], self.old_name], 'ORIGINAL_RENAME_FAILED'); m.run(['docker', 'rename', identity, 't24-crm'], 'CANDIDATE_RENAME_FAILED'); self.fresh(r, old, before, expected, state, baseline=baseline)
            m.run(['docker', 'start', identity], 'CANDIDATE_START_FAILED'); m.ready(identity); self.accept(r, old, before, expected, state, baseline, updated=False)
            m.replace_nginx(original_nginx, m.next_nginx(original_nginx)); m.retained().reload_nginx(); candidate = self.accept(r, old, before, expected, state, baseline, updated=True); sentinel = self.public_check(identity); candidate = self.accept(r, old, before, expected, state, baseline, updated=True)
            result = {'stage': 'GOOGLE_PILOT_WORKFLOW_DEPLOYED_VERIFIED', 'deployed': True, 'source_sha': SOURCE_SHA, 'frontend_version': FRONTEND, 'schema_revision': REVISION, 'schema_sha256': self.proof['schema_sha256'], 'crm': m.runtime(candidate), 'original_id': old['Id'], 'preflight_sha256': a.preflight_sha256, 'prepared_sha256': a.review_sha256, 'candidate_inventory_sha256': r['candidate_inventory_sha256'], 'public_root': str(self.public), 'public_inventory_sha256': r['public_inventory_sha256'], 'nginx_sha256': H(m.NGINX.read_bytes()), 'all_136_table_rows_and_schema_unchanged': True, 'existing_image_policies_and_data_preserved': True, 'scheduler_enabled': True, 'scheduler_activation_from': ACTIVATION_FROM, 'existing_google_environment_preserved': True, 'original_env_mounts_network_unchanged': True, 'private_runtime_unchanged': True, 'database_migration': False, 'database_restored': False, 'production_containers_deleted': False, 'no_policy_task_schedule_lease_or_post_created_by_tool': True, 'provider_requests_by_deployment': False, 'sequence_written_by_tool': False, **sentinel}
            sha = self.record('deployed.json', result); return {**result, 'receipt_sha256': sha}
        except BaseException:
            self.recover_internal(r, old, before, expected); raise

    def recover_internal(self, r, old, before, expected):
        m, a = self.m, self.args; state = self.state(r, old); retained, candidate = self.identities(state, old)
        # Known stopped candidate only; no guesses, delete, DB restore or
        # provider requests. New legitimate rows remain in the shared database.
        if candidate['State']['Running']: m.run(['docker', 'stop', '--time', '30', candidate['Id']], 'RECOVERY_CONTAINMENT_FAILED', 60)
        need(m.inspect(candidate['Id'])['State']['Running'] is False, 'RECOVERY_CANDIDATE_STOPPED_REQUIRED'); self.w.compare(candidate, old, m); self.pf.google_environment(candidate); m.verify_secret_mount(candidate)
        body = m.NGINX.read_bytes(); updated = H(body) == r['nginx_next_sha256']; self.protections(updated=updated, recovery=True); self.source_boundary(retained, before); self.source_boundary(candidate, expected)
        if updated: m.replace_nginx(body, m.read(a.release / 'nginx-before.conf', self.proof['nginx_sha256']))
        m.retained().reload_nginx()
        if candidate['Name'] == '/t24-crm': m.run(['docker', 'rename', candidate['Id'], self.candidate_name], 'RETAIN_CANDIDATE_FAILED')
        if retained['Name'] != '/t24-crm': m.run(['docker', 'rename', retained['Id'], 't24-crm'], 'RESTORE_OLD_NAME_FAILED')
        if not retained['State']['Running']: m.run(['docker', 'start', retained['Id']], 'ORIGINAL_RESUME_FAILED')
        m.ready(retained['Id']); restored = m.inspect('t24-crm'); self.pf.google_environment(restored); m.verify_secret_mount(restored); self.helper.validation_window(restored)
        need(restored['Id'] == old['Id'] and restored['State']['Running'] is True and m.runtime(restored)['config'] == m.runtime(old)['config'], 'ORIGINAL_NOT_RESTORED')
        self.source_boundary(restored, before); self.protections(recovery=True); kept = m.inspect(state['candidate_id']); need(kept['State']['Running'] is False and kept['Name'] == '/' + self.candidate_name, 'CANDIDATE_NOT_RETAINED_STOPPED')
        result = {'stage': 'GOOGLE_PILOT_WORKFLOW_ORIGINAL_RESUMED', 'source_sha': BASE_SOURCE, 'schema_revision': REVISION, 'candidate_retained_stopped': True, 'database_migration': False, 'database_restored': False, 'independent_rows_preserved': True, 'sequence_written_by_tool': False, 'provider_requests_by_tool': False}; self.record('recovery-' + str(time.time_ns()) + '.json', result); return result

    def recover(self):
        r, old, before, expected = self.reviewed(); a = self.args; need(not (a.release / 'deployed.json').exists(), 'SUCCESSFUL_DEPLOYMENT_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        started = json.loads(self.m.read(a.release / 'activation-started.json')); need(started == {'source_sha': SOURCE_SHA, 'review_sha256': a.review_sha256, 'original_id': old['Id'], 'candidate_image': r['candidate_image']}, 'EXACT_RECOVERY_INTENT_REQUIRED')
        if not (a.release / 'candidate-created.json').exists(): self.current(); return {'stage': 'GOOGLE_PILOT_WORKFLOW_ABORTED_BEFORE_SWITCH', 'original_unchanged': True, 'candidate_not_touched': True, 'manual_orphan_review_required': True, 'database_restored': False}
        return self.recover_internal(r, old, before, expected)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--phase', choices=['prepare', 'activate', 'recover'], required=True); parser.add_argument('--release', type=Path, required=True); parser.add_argument('--manifest-sha256', required=True); parser.add_argument('--payload-sha256', required=True); parser.add_argument('--preflight', type=Path, required=True); parser.add_argument('--preflight-sha256', required=True); parser.add_argument('--review-sha256'); args = parser.parse_args()
    pins_ready(); need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED'); resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077); sys.dont_write_bytecode = True
    need(args.release.resolve() == args.release and args.release.parent == Path('/opt/t24-crm/releases'), 'EXACT_RELEASE_PARENT_REQUIRED')
    for parent in args.release.parents:
        row = parent.lstat(); need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_RELEASE_PARENT_REQUIRED')
    row = args.release.lstat(); need(stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and stat.S_IMODE(row.st_mode) == 0o700, 'PROTECTED_RELEASE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}', s) for s in (args.manifest_sha256, args.payload_sha256, args.preflight_sha256)), 'EXACT_PUBLIC_PINS_REQUIRED'); need(args.preflight == Path('/opt/t24-crm/releases/google-pilot-workflow-preflight-' + args.preflight_sha256[:12] + '.json'), 'EXACT_SERVER_PREFLIGHT_PATH_REQUIRED'); need(args.phase != 'prepare' or args.review_sha256 is None, 'PREPARE_HAS_NO_SWITCH_REVIEW_ARGUMENT')
    lock = os.open('/opt/t24-crm/releases/.google-pilot-workflow-release.lock', os.O_RDWR | os.O_NONBLOCK | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        row = os.fstat(lock); need(stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_LOCK_REQUIRED'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); print(json.dumps(getattr(Release(args), args.phase)(), sort_keys=True))
    finally: os.close(lock)


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        value = str(error); code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PILOT_RELEASE_REJECTED'; print(json.dumps({'stage': 'GOOGLE_PILOT_WORKFLOW_RELEASE_REJECTED', 'code': code, 'database_restored': False})); sys.exit(1)
