"""Resume one already-created container; one verified Docker default equivalence only.

No container creation/removal, Nginx edits, database writes or provider requests.
The frozen V3 artifacts and actual runtime digests are never rewritten.
"""
import copy
import base64
import http.client
import socket
import time
import fcntl
import json
import io
import re
import tarfile
from urllib.parse import quote
import os
import resource
import sys
from pathlib import Path
import core as c
import preflight
import activation as a

PLAN_SHA = '70f950d405c7ceafc9fa43023edb68d4c6324bcedf9329f0ee31bb3019a542ea'
REVIEW_SHA = '708e285e42c748e80090c998c9da806ad5a87db0453b3957d831762afb27da0b'
LOGGING_SHA = '43e6f45db4fdcb6e907c622eb081e023659e7538ff97bf45cb6adbc0eefd6c50'
CREDENTIAL_SHA = '7bb8ba99f9e0c33ff05a083e16958592b8b1a523a19c671aa96a85fa9c6796f0'
CLONE_EVIDENCE_SHA = '9498c213783c677b29f1ceceffd8680133910f62a8ea1f411f4a6606143fc01b'
OOM_EVIDENCE_SHA = '8eb4cf8df1ec34d81cbc6484a89bca15ee40fb297b8a155431e62fa3c7b66ac7'
ORIGINAL_ID = '31938c60089feb7a1105f6124f630bc25490b69e9c32d2bcd3487d990e8ec8ab'
FROZEN_TOOLS = {
    'core.py': '903081856fbdb042b9af74295cbebd6745b57e019e7039a7fce26c23bddde107',
    'preflight.py': 'df6a02ab394c10ab81f4f6c2a6c153a370cfa91648961ccaf9392c8f9df02b8d',
    'activation.py': '4136a73ca9564f168d279d0ff344b7626c5747e20c533a98a930b67d519e0538'}
ZERO_START = {'', '0001-01-01T00:00:00Z', '0001-01-01T00:00:00.000000000Z'}


def root():
    return a.attempt_root() / 'completion-oom-default'


def tool_hash():
    return getattr(sys.modules[__name__], '__tool_sha256__', None) or c.H(Path(__file__).read_bytes())


def arguments():
    c.need(a.tool_hashes() == FROZEN_TOOLS and a.ATTEMPT_NAMESPACE == 'attempt-v3', 'FROZEN_V3_TOOLS_REQUIRED')
    review = c.strict_json(c.read(a.attempt_root() / 'approved.json', REVIEW_SHA))
    return {'plan_sha256': PLAN_SHA, 'review': review, 'review_sha256': REVIEW_SHA,
        'logging_receipt_sha256': LOGGING_SHA}


def scope():
    args = arguments()
    plan, logging = a._switch_requirements(args)
    m = c.legacy()
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    original = c.strict_json(c.read(a.attempt_root() / 'original-container.json'))
    state_blob = c.read(a.attempt_root() / 'switch-state.json')
    state = c.strict_json(state_blob)
    c.need(original['Id'] == ORIGINAL_ID and original['Image'] == c.IMAGE and
        m.runtime(original) == prior['crm'], 'EXACT_SAVED_ORIGINAL_REQUIRED')
    c.need(state['stage'] == 'GBP_CONFIG_CANDIDATE_CREATED' and state['original_id'] == ORIGINAL_ID and
        state['image'] == c.IMAGE and state['candidate_name'] == a.CANDIDATE_NAME and
        state['plan_sha256'] == PLAN_SHA and state['review_sha256'] == REVIEW_SHA and
        isinstance(state.get('candidate_id'), str) and len(state['candidate_id']) == 64 and
        all(char in '0123456789abcdef' for char in state['candidate_id']) and
        state['candidate_id'] != ORIGINAL_ID, 'EXACT_EXISTING_CANDIDATE_STATE_REQUIRED')
    return m, original, state, c.H(state_blob), plan, logging


class ExactDefaultRuntime:
    """Comparison-only view; never change global legacy code or receipt runtime."""
    def __init__(self, module, original, candidate_id, *, allow_running_null=False):
        c.need('OomKillDisable' in original['HostConfig'] and original['HostConfig']['OomKillDisable'] is None,
            'ORIGINAL_OOM_KEY_EXACT_NULL_REQUIRED')
        self.module, self.original, self.candidate_id = module, original, candidate_id
        self.allow_running_null = allow_running_null

    def runtime(self, info):
        c.need(info['Id'] in {ORIGINAL_ID, self.candidate_id}, 'COMPARISON_IDENTITY_REJECTED')
        if info['Id'] == self.candidate_id:
            if ('OomKillDisable' in info['HostConfig'] and info['HostConfig']['OomKillDisable'] is None and
                    self.allow_running_null and info['State']['Running'] is True):
                return self.module.runtime(info)  # Exact equality with saved null; no normalization.
            c.need('OomKillDisable' in info['HostConfig'] and info['HostConfig']['OomKillDisable'] is False,
                'CANDIDATE_OOM_KEY_EXACT_FALSE_REQUIRED')
            normalized = copy.deepcopy(info)
            normalized['HostConfig']['OomKillDisable'] = None
            return self.module.runtime(normalized)
        c.need('OomKillDisable' in info['HostConfig'] and info['HostConfig']['OomKillDisable'] is None,
            'ORIGINAL_OOM_KEY_EXACT_NULL_REQUIRED')
        return self.module.runtime(info)

    def __getattr__(self, name):
        return getattr(self.module, name)


def _identities(m, original, state):
    retained, candidate = m.inspect(ORIGINAL_ID), m.inspect(state['candidate_id'])
    c.need(retained['Id'] == ORIGINAL_ID and retained['Image'] == c.IMAGE and
        m.runtime(retained)['config'] == m.runtime(original)['config'], 'ORIGINAL_RUNTIME_CONFIGURATION_DRIFT')
    c.no_gbp(retained)
    c.need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == c.IMAGE,
        'EXACT_KNOWN_CANDIDATE_REQUIRED')
    active = m.inspect_optional('t24-crm')
    c.need(not active or active['Id'] in {ORIGINAL_ID, state['candidate_id']}, 'UNKNOWN_PRIMARY_CONTAINER_REQUIRES_REVIEW')
    for name, expected in ((a.CANDIDATE_NAME, state['candidate_id']), (a.DISABLED_NAME, ORIGINAL_ID)):
        found = m.inspect_optional(name)
        c.need(not found or found['Id'] == expected, 'RESERVED_CONTAINER_NAME_OCCUPIED')
    c.need(retained.get('Name') in {'/t24-crm', '/' + a.DISABLED_NAME} and
        candidate.get('Name') in {'/t24-crm', '/' + a.CANDIDATE_NAME}, 'KNOWN_CONTAINER_NAME_DRIFT')
    return retained, candidate


def _audit_context():
    m, original, state, state_sha, plan, logging = scope()
    active_hash = logging['active_nginx_config_sha256']
    a.active_logging_boundary(plan, active_hash)
    current = preflight.proof(nginx_hash=plan['nginx_next_sha256'])
    c.need(current['crm'] == logging['crm'] == m.runtime(original) and
        current['active_nginx_config_sha256'] == active_hash, 'FRESH_DISABLED_BASELINE_REQUIRED')
    retained, candidate = _identities(m, original, state)
    c.need(retained['State']['Running'] is True and retained['Name'] == '/t24-crm' and
        m.runtime(retained) == current['crm'], 'ORIGINAL_MUST_REMAIN_RUNNING_PRIMARY')
    c.need(candidate['Name'] == '/' + a.CANDIDATE_NAME and candidate['State']['Running'] is False and
        candidate['State'].get('Status') == 'created' and candidate['State'].get('StartedAt') in ZERO_START and
        type(candidate.get('RestartCount')) is int and candidate['RestartCount'] == 0,
        'EXISTING_CANDIDATE_MUST_BE_NEVER_STARTED')
    stored = c.strict_json(c.read(c.ROOT / 'credential-receipt.json', CREDENTIAL_SHA))
    c.need(stored['stage'] == 'GBP_ACTIVATION_CREDENTIALS_STORED_NOT_ENABLED' and stored['project_id'] == c.PROJECT_ID and
        stored['project_number'] == c.PROJECT_NUMBER and stored['runtime_changed'] is False, 'DEDICATED_STAGED_CREDENTIALS_REQUIRED')
    values = c.read_gbp_env()
    proxy = ExactDefaultRuntime(m, original, state['candidate_id'])
    a.verify_clone(candidate, original, values, proxy.runtime)
    verify_stopped_source(m, original, json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA)))
    c.need(m.runtime(retained) == m.runtime(m.inspect(ORIGINAL_ID)) and
        m.runtime(candidate) == m.runtime(m.inspect(state['candidate_id'])) and
        c.H(c.read(a.attempt_root() / 'switch-state.json')) == state_sha,
        'CONTAINERS_OR_SWITCH_STATE_CHANGED_DURING_AUDIT')
    facts = {'stage': 'GBP_EXISTING_CANDIDATE_COMPLETION_AUDIT', 'original_oom_key_present_exact_null': True,
        'candidate_oom_key_present_exact_false': True, 'all_other_runtime_configuration_equal': True,
        'original_running_primary_unchanged': True, 'candidate_created_never_started': True,
        'original_source_no_execution_read_verified': True,
        'exact_six_staged_env_additions_verified': True, 'protected_callback_and_fresh_disabled_baseline_verified': True,
        'original_id': ORIGINAL_ID, 'candidate_id': state['candidate_id'], 'candidate_actual_runtime': m.runtime(candidate),
        'original_actual_runtime': m.runtime(retained), 'v3_switch_state_sha256': state_sha,
        'plan_sha256': PLAN_SHA, 'review_sha256': REVIEW_SHA, 'logging_receipt_sha256': LOGGING_SHA,
        'frozen_tool_sha256': FROZEN_TOOLS, 'completion_tool_sha256': tool_hash(),
        'actual_clone_evidence_sha256': CLONE_EVIDENCE_SHA, 'actual_false_evidence_sha256': OOM_EVIDENCE_SHA,
        'default_equivalence_scope': 'comparison-only HostConfig.OomKillDisable null to exact false',
        'live_kernel_oom_behavior_verified': False, 'configuration_changed': False,
        'provider_requests': False, 'business_writes': False, 'credentials_exported': False}
    return (m, original, state, state_sha, plan, logging, values, proxy, facts)


def audit():
    return _audit_context()[-1]


def event(name, value):
    """Exclusive, append-only completion records; never update frozen V3 files."""
    path = root() / (name + '.json')
    if path.exists() or path.is_symlink():
        c.need(c.read(path) == c.encoded(value), 'COMPLETION_EVENT_DRIFT')
        return c.H(c.encoded(value))
    return c.write(path, value)


def _intent(original, state, state_sha, facts):
    return {'stage': 'GBP_EXISTING_CANDIDATE_COMPLETION_INTENT', 'original_id': original['Id'],
        'candidate_id': state['candidate_id'], 'image': c.IMAGE, 'plan_sha256': PLAN_SHA,
        'review_sha256': REVIEW_SHA, 'logging_receipt_sha256': LOGGING_SHA, 'v3_switch_state_sha256': state_sha,
        'candidate_actual_runtime_before_start': facts['candidate_actual_runtime'],
        'original_actual_runtime_before_switch': facts['original_actual_runtime'],
        'completion_tool_sha256': tool_hash(), 'frozen_tool_sha256': FROZEN_TOOLS,
        'default_equivalence': facts['default_equivalence_scope'],
        'no_container_create_or_delete': True, 'no_v3_artifact_updates': True}


def _load_intent(original, state, state_sha):
    value = c.strict_json(c.read(root() / 'intent.json'))
    c.need(value['stage'] == 'GBP_EXISTING_CANDIDATE_COMPLETION_INTENT' and value['original_id'] == original['Id'] and
        value['candidate_id'] == state['candidate_id'] and value['image'] == c.IMAGE and value['plan_sha256'] == PLAN_SHA and
        value['review_sha256'] == REVIEW_SHA and value['logging_receipt_sha256'] == LOGGING_SHA and
        value['v3_switch_state_sha256'] == state_sha and value['completion_tool_sha256'] == tool_hash() and
        value['frozen_tool_sha256'] == FROZEN_TOOLS and value['no_container_create_or_delete'] is True and
        value['no_v3_artifact_updates'] is True, 'EXACT_COMPLETION_INTENT_REQUIRED')
    return value


def complete():
    # Existing intent means interrupted work: only explicit no-delete rollback is allowed.
    c.need(not root().exists() and not root().is_symlink(), 'EXISTING_COMPLETION_REQUIRES_EXPLICIT_RECOVERY')
    m, original, state, state_sha, plan, logging, values, proxy, facts = _audit_context()
    a.sentinel_probe(m, plan)
    a.active_logging_boundary(plan, logging['active_nginx_config_sha256'])
    rows = m.sql_snapshot(m.BUSINESS)
    retained, candidate = _identities(m, original, state)
    c.need(m.runtime(retained) == facts['original_actual_runtime'] and m.runtime(candidate) == facts['candidate_actual_runtime'],
        'RUNTIME_CHANGED_BEFORE_COMPLETION_INTENT')
    a.verify_clone(candidate, original, values, proxy.runtime)
    c.mkdir(root())
    event('audit', facts)
    event('intent', _intent(original, state, state_sha, facts))
    try:
        # Journal exists before the first mutation; each action targets immutable IDs.
        c.need(m.runtime(m.inspect('t24-crm')) == facts['original_actual_runtime'], 'ORIGINAL_CHANGED_BEFORE_STOP')
        a.active_logging_boundary(plan, logging['active_nginx_config_sha256'])
        c.run(['docker', 'stop', '--time', '30', ORIGINAL_ID], 'COMPLETION_ORIGINAL_STOP_FAILED')
        event('original-stopped', {'stage': 'COMPLETION_ORIGINAL_STOPPED', 'original_id': ORIGINAL_ID})
        c.run(['docker', 'rename', ORIGINAL_ID, a.DISABLED_NAME], 'COMPLETION_ORIGINAL_RENAME_FAILED')
        c.run(['docker', 'rename', state['candidate_id'], 't24-crm'], 'COMPLETION_CANDIDATE_RENAME_FAILED')
        c.run(['docker', 'start', state['candidate_id']], 'COMPLETION_CANDIDATE_START_FAILED')
        event('candidate-started', {'stage': 'COMPLETION_CANDIDATE_STARTED', 'candidate_id': state['candidate_id']})
        proxy = ExactDefaultRuntime(m, original, state['candidate_id'], allow_running_null=True)
        active = m.inspect('t24-crm')
        c.need(active['Id'] == state['candidate_id'], 'COMPLETION_PRIMARY_IDENTITY_DRIFT')
        a.verify_active(proxy, active, original, values, plan, rows, logging['active_nginx_config_sha256'])
        a.sentinel_probe(m, plan)
        a.active_logging_boundary(plan, logging['active_nginx_config_sha256'])
        active = m.inspect('t24-crm')
        c.need(active['Id'] == state['candidate_id'] and active['State']['Running'] is True, 'COMPLETION_FINAL_PRIMARY_DRIFT')
        a.verify_clone(active, original, values, proxy.runtime)
        retained, _ = _identities(m, original, state)
        c.need(retained['State']['Running'] is False, 'RETAINED_ORIGINAL_MUST_REMAIN_STOPPED')
        c.need(m.sql_snapshot(m.BUSINESS) == rows and c.H(c.read(a.attempt_root() / 'switch-state.json')) == state_sha,
            'ROWS_OR_V3_ARTIFACT_CHANGED_DURING_COMPLETION')
        receipt = {'stage': 'GBP_CONFIG_ENABLED_EXISTING_CANDIDATE_VERIFIED', 'enabled': True,
            'source_sha': c.SOURCE, 'frontend_version': c.FRONTEND, 'schema_revision': c.REVISION, 'image': c.IMAGE,
            'crm': m.runtime(active), 'original_id': ORIGINAL_ID, 'candidate_id': state['candidate_id'],
            'plan_sha256': PLAN_SHA, 'review_sha256': REVIEW_SHA, 'logging_receipt_sha256': LOGGING_SHA,
            'v3_switch_state_sha256': state_sha, 'frozen_tool_sha256': FROZEN_TOOLS, 'completion_tool_sha256': tool_hash(),
            'comparison_only_default_equivalence': facts['default_equivalence_scope'],
            'actual_runtime_hashes_preserved': True, 'live_kernel_oom_behavior_verified': False,
            'exact_six_environment_additions': sorted(c.GBP_NAMES), 'existing_environment_values_unchanged': True,
            'all_other_runtime_configuration_unchanged': True, 'business_rows_unchanged_during_switch': True,
            'private_boundary_verified': True, 'schema_static_source_unchanged': True,
            'original_source_no_execution_read_verified_before_stop': True,
            'callback_sentinel_verified': True, 'active_nginx_config_sha256': logging['active_nginx_config_sha256'],
            'same_existing_candidate_reused': True, 'containers_created': False, 'containers_deleted': False,
            'v3_artifacts_rewritten': False, 'database_restored': False, 'credentials_exported': False,
            'google_oauth_performed': False, 'provider_requests': False, 'provider_writes': False, 'business_writes': False}
        digest = event('enabled', receipt)
        return {**receipt, 'receipt_sha256': digest}
    except BaseException as error:
        try:
            event('failure', {'stage': 'GBP_COMPLETION_FAILED', 'code': c.safe_code(error)})
        except (OSError, c.GuardError):
            pass  # A full journal filesystem must not prevent safe service recovery.
        rollback()
        raise


def _source_request(method, container_id, path, timeout):
    """Fixed local Unix-socket, read-only HEAD/GET; cap response allocation."""
    c.need(method in {'HEAD', 'GET'} and container_id == ORIGINAL_ID and isinstance(path, str) and
        (path == '/app' or path.startswith('/app/')) and
        all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) and part not in {'.', '..'} for part in path.split('/')[1:]),
        'EXACT_SOURCE_REQUEST_REQUIRED')
    connection = http.client.HTTPConnection('localhost', timeout=timeout)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect('/var/run/docker.sock')
        connection.sock = sock
        connection.request(method, '/containers/' + container_id + '/archive?path=' + quote(path, safe=''))
        response = connection.getresponse()
        c.need(response.status == 200, 'RECOVERY_SOURCE_RESPONSE_REJECTED')
        headers = [value for name, value in response.getheaders() if name.lower() == 'x-docker-container-path-stat']
        c.need(len(headers) == 1 and len(headers[0]) <= 8192, 'RECOVERY_SOURCE_STAT_HEADER_REQUIRED')
        info = c.strict_json(base64.b64decode(headers[0], validate=True))
        body = response.read(4 * 1024 * 1024 + 65537) if method == 'GET' else b''
        c.need(len(body) <= 4 * 1024 * 1024 + 65536, 'RECOVERY_SOURCE_ARCHIVE_TOO_LARGE')
        return info, body
    finally:
        connection.close()
        sock.close()


def verify_stopped_source(m, original, prior):
    """Hash only pinned source files, without executing stopped-container code."""
    expected = json.loads(m.read(c.PRIOR / 'backend-candidate-inventory.json', prior['candidate_inventory_sha256']))
    excluded = {'data', 'logs', '__pycache__', '.git', '.pytest_cache', '.venv', 'node_modules'}
    c.need(isinstance(expected, dict) and 0 < len(expected) <= 2048, 'BOUNDED_SOURCE_INVENTORY_REQUIRED')
    parents = {'/app', '/app/backend'}
    for name, digest in expected.items():
        parts = name.split('/') if isinstance(name, str) else []
        c.need(parts and all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) and part not in {'.', '..'} for part in parts) and
            not (set(parts) & excluded) and re.fullmatch('[a-f0-9]{64}', digest), 'EXACT_SOURCE_INVENTORY_PATH_REQUIRED')
        parents.update('/app/backend/' + '/'.join(parts[:index]) for index in range(1, len(parts)))
    # Diff metadata detects extra code that the expected file list cannot cover.
    # No data/log/credential paths are fetched; directories receive HEAD only.
    diff = c.run(['docker', 'diff', original['Id']], 'RECOVERY_SOURCE_METADATA_FAILED')
    c.need(len(diff) <= 512 * 1024, 'RECOVERY_SOURCE_METADATA_TOO_LARGE')
    for line in diff.decode('utf-8').splitlines():
        c.need(len(line) >= 3 and line[0] in 'ACD' and line[1] == ' ', 'RECOVERY_SOURCE_METADATA_REJECTED')
        path = line[2:]
        if path in {'/app', '/app/backend'}:
            c.need(line[0] == 'C', 'RECOVERY_SOURCE_ROOT_DRIFT')
            continue
        if not path.startswith('/app/backend/'):
            continue
        name = path[len('/app/backend/'):]
        if set(name.split('/')) & excluded or name.endswith(('.pyc', '.pyo')):
            continue
        c.need(name in expected or (line[0] == 'C' and path in parents), 'RECOVERY_UNEXPECTED_SOURCE_PATH')
    deadline = time.monotonic() + 30
    def request(method, path):
        remaining = deadline - time.monotonic()
        c.need(remaining > 0, 'RECOVERY_SOURCE_PROOF_DEADLINE')
        info, body = _source_request(method, original['Id'], path, min(2, remaining))
        c.need(time.monotonic() <= deadline and isinstance(info, dict) and
            info.get('name') == path.rsplit('/', 1)[-1] and info.get('linkTarget') == '' and
            type(info.get('mode')) is int, 'RECOVERY_SOURCE_PATH_STAT_REJECTED')
        return info, body
    for path in sorted(parents):
        info, body = request('HEAD', path)
        # Docker PathStat.mode uses Go os.FileMode; bit31 is ModeDir.
        c.need(info['mode'] & ~0o777 == 1 << 31 and body == b'', 'RECOVERY_SOURCE_PARENT_MUST_BE_DIRECTORY')
    for name, digest in expected.items():
        info, blob = request('GET', '/app/backend/' + name)
        c.need(info['mode'] & ~0o777 == 0 and type(info.get('size')) is int and
            0 <= info['size'] <= 4 * 1024 * 1024, 'RECOVERY_SOURCE_MUST_BE_REGULAR_FILE')
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            members = archive.getmembers()
            c.need(len(members) == 1, 'RECOVERY_SOURCE_ARCHIVE_MEMBER_COUNT')
            item = members[0]
            c.need(item.name == name.rsplit('/', 1)[-1] and item.isfile() and not item.linkname and
                item.size == info['size'], 'RECOVERY_SOURCE_ARCHIVE_FILE_REQUIRED')
            stream = archive.extractfile(item)
            c.need(stream is not None and c.H(stream.read(item.size + 1)) == digest, 'RECOVERY_SOURCE_CONTENT_DRIFT')




def rollback():
    m, original, state, state_sha, plan, logging = scope()
    _load_intent(original, state, state_sha)
    retained, candidate = _identities(m, original, state)
    prior = json.loads(m.read(c.PRIOR / 'deployed.json', c.PRIOR_SHA))
    c.need(m.schema_signature(m.BUSINESS, c.REVISION) == prior['schema_sha256'], 'COMPLETION_RECOVERY_SCHEMA_DRIFT')
    c.need(c.H(m.NGINX.read_bytes()) == plan['nginx_next_sha256'] and
        c.H(c.run(['nginx', '-T'], 'NGINX_ACTIVE_PARSE_FAILED')) == logging['active_nginx_config_sha256'],
        'COMPLETION_RECOVERY_CALLBACK_PROTECTION_DRIFT')
    c.need(m.digest(m.tree(Path(prior['public_root']))) == prior['public_inventory_sha256'], 'COMPLETION_RECOVERY_STATIC_DRIFT')
    m.private_boundary(json.loads(m.read(c.PINS, c.PINS_SHA)))
    verify_stopped_source(m, original, prior)
    # Do not allow a failed candidate metadata check to block restoring the known
    # original. This recovery may only stop/retain that exact recorded candidate.
    try:
        event('recovery-intent', {'stage': 'GBP_COMPLETION_RECOVERY_INTENT', 'candidate_id': state['candidate_id'], 'original_id': ORIGINAL_ID})
    except (OSError, c.GuardError):
        pass  # The immutable forward intent already fences the exact recoverable IDs.
    if candidate['State']['Running']:
        c.run(['docker', 'stop', '--time', '30', candidate['Id']], 'COMPLETION_RECOVERY_CANDIDATE_STOP_FAILED')
    if candidate['Name'] == '/t24-crm':
        c.run(['docker', 'rename', candidate['Id'], a.CANDIDATE_NAME], 'COMPLETION_RECOVERY_CANDIDATE_RENAME_FAILED')
    retained = m.inspect(ORIGINAL_ID)
    if retained['Name'] != '/t24-crm':
        c.run(['docker', 'rename', ORIGINAL_ID, 't24-crm'], 'COMPLETION_RECOVERY_ORIGINAL_RENAME_FAILED')
    if not retained['State']['Running']:
        c.run(['docker', 'start', ORIGINAL_ID], 'COMPLETION_RECOVERY_ORIGINAL_START_FAILED')
    recovered, kept = m.inspect('t24-crm'), m.inspect(state['candidate_id'])
    c.need(recovered['Id'] == ORIGINAL_ID and recovered['State']['Running'] is True and
        m.runtime(recovered)['config'] == m.runtime(original)['config'] and kept['State']['Running'] is False and
        kept['Name'] == '/' + a.CANDIDATE_NAME, 'COMPLETION_DISABLED_RECOVERY_NOT_VERIFIED')
    c.no_gbp(recovered)
    m.ready(ORIGINAL_ID)
    c.need(m.inventory(ORIGINAL_ID) == json.loads(m.read(c.PRIOR / 'backend-candidate-inventory.json',
        prior['candidate_inventory_sha256'])), 'COMPLETION_RECOVERY_SOURCE_DRIFT')
    m.verify_secret_mount(recovered)
    m.verify_production_worker_enabled(recovered)
    m.private_boundary(json.loads(m.read(c.PINS, c.PINS_SHA)))
    output = c.run(['docker', 'exec', ORIGINAL_ID, 'python', '-B', '-c', a.config_probe(False)], 'COMPLETION_RECOVERY_DISABLED_CONFIG_FAILED')
    c.need(output.strip() == b'GBP_CONFIG_NO_NETWORK_VERIFIED', 'COMPLETION_RECOVERY_DISABLED_CONFIG_PROOF_REQUIRED')
    a.active_logging_boundary(plan, logging['active_nginx_config_sha256'])
    c.need(c.H(c.read(a.attempt_root() / 'switch-state.json')) == state_sha, 'V3_SWITCH_ARTIFACT_DRIFT')
    receipt = {'stage': 'GBP_COMPLETION_ROLLED_BACK_DISABLED', 'enabled': False, 'image': c.IMAGE,
        'crm': m.runtime(recovered), 'candidate_id': kept['Id'], 'candidate_retained_stopped': True,
        'containers_created': False, 'containers_deleted': False, 'database_restored': False,
        'v3_artifacts_rewritten': False, 'callback_logging_protection_retained': True,
        'credentials_and_encryption_key_retained': True, 'private_boundary_verified': True,
        'frozen_tool_sha256': FROZEN_TOOLS, 'completion_tool_sha256': tool_hash(),
        'provider_requests': False, 'business_writes': False}
    digest = event('rolled-back', receipt)
    return {**receipt, 'receipt_sha256': digest}


def dispatch(phase):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    c.server_guard()
    c.need(phase in {'audit', 'complete', 'rollback'}, 'EXACT_COMPLETION_PHASE_REQUIRED')
    c.directory(c.ROOT, exact_mode=0o700)
    lock = c.ROOT / 'activation.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        c.read(lock, maximum=0)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return {'audit': audit, 'complete': complete, 'rollback': rollback}[phase]()
    finally:
        os.close(fd)
