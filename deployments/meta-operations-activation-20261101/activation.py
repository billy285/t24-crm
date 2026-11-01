"""Same-image independent Publisher environment addition. No SQL, provider, Nginx or DB restore."""
import copy
import fcntl
import json
import os
import re
import time
from types import SimpleNamespace

c = None
b = None


def configure(core, baseline):
    global c, b
    c, b = core, baseline
    c.need(b.c is c, 'SAME_REVIEWED_BASELINE_CORE_REQUIRED')


def digest(value): return b.digest(value)


def env_rows():
    c.pins_ready()
    c.directory(c.ENV_FILE.parent)
    body = c.read(c.ENV_FILE, maximum=8192)
    try: rows = body.decode('ascii').splitlines()
    except UnicodeError: raise c.GuardError('STRICT_META_ENV_FILE_REQUIRED') from None
    values = c.validate_ops_env(rows)
    receipt = c.strict_json(c.read(c.ROOT/'credential-receipt.json', maximum=8192))
    expected = {'stage': 'META_OPERATIONS_CREDENTIALS_STORED_RUNTIME_UNCHANGED', 'app_id': c.APP_ID, 'business_id': c.BUSINESS_ID,
                'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION, 'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA,
                'env_path': str(c.ENV_FILE), 'env_sha256': c.H(body), 'independent_fernet_key_generated': True,
                'credential_values_exported': False, 'runtime_changed': False, 'business_writes': False, 'provider_requests': False, 'execution_enabled':False, 'scheduler_enabled':False, 'existing_read_credentials_preserved':True}
    c.need(all(receipt.get(key) == value for key, value in expected.items()), 'EXACT_TRANSFERRED_META_CREDENTIAL_RECEIPT_REQUIRED')
    return rows, values, c.H(body)


def replaced_environment(original, meta):
    c.old_environment(original['Config']['Env']); c.validate_ops_env(meta)
    return [*original['Config']['Env'], *meta]


def clone_config(original, meta, m):
    c.need(original['Image'] == c.IMAGE and original['HostConfig'].get('AutoRemove') is False, 'SAME_RETAINED_IMAGE_CONFIGURATION_REQUIRED')
    b.legacy_environment(b.dependencies(), original)
    values = c.validate_ops_env(meta); existing = c.old_environment(original['Config']['Env'])
    c.need(values['T24_META_OPS_APP_SECRET'] != existing['T24_META_APP_SECRET'], 'PUBLISHER_SECRET_MUST_DIFFER_FROM_READ_APP')
    c.need(all(values['T24_META_OPS_TOKEN_KEY'] != existing.get(key) for key in ('T24_META_TOKEN_KEY', 'T24_GBP_TOKEN_KEY', 'MASK_KEY', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY')), 'DEDICATED_NEW_OPS_KEY_REQUIRED')
    config = copy.deepcopy(original['Config']); config.update(Image=c.IMAGE, Hostname='', Env=replaced_environment(original, meta)); config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    networks = m.retained().clone_networks(original)
    c.need(networks or original['HostConfig']['NetworkMode'] in {'host', 'none'}, 'ORIGINAL_NETWORKS_REQUIRED')
    config['NetworkingConfig'] = {'EndpointsConfig': networks}; return config


def compare(candidate, original, meta, m):
    c.need(candidate['Image'] == original['Image'] == c.IMAGE, 'SAME_IMAGE_ONLY_REQUIRED')
    c.need(candidate['Config']['Env'] == replaced_environment(original,meta), 'EXACT_ELEVEN_OPS_ENV_ADDITION_REQUIRED')
    c.validate_ops_env(meta)
    c.need(candidate['Config'].get('Labels') == original['Config'].get('Labels'), 'EXISTING_LABELS_MUST_REMAIN_EXACT')
    for info in (original, candidate):
        c.need(info['HostConfig'].get('AutoRemove') is False, 'PRODUCTION_AUTOREMOVE_FORBIDDEN')
        value = info['HostConfig'].get('OomKillDisable', 'missing')
        c.need(value is None or value is False, 'EXACT_OOM_DEFAULT_REQUIRED')
        for endpoint in info.get('NetworkSettings', {}).get('Networks', {}).values():
            c.need(endpoint.get('IPAMConfig') is None or endpoint.get('IPAMConfig') == {}, 'EXPLICIT_IPAM_UNSUPPORTED')
    left, right = original['HostConfig']['OomKillDisable'], candidate['HostConfig']['OomKillDisable']
    c.need(left is right or left is None and right is False, 'UNPROVEN_OOM_DEFAULT_DIRECTION')
    normalized = copy.deepcopy(candidate)
    for key in ('Env', 'Hostname', 'Image'): normalized['Config'][key] = copy.deepcopy(original['Config'].get(key))
    normalized['HostConfig']['OomKillDisable'] = left
    c.need(m.runtime(normalized)['config'] == m.runtime(original)['config'], 'ORIGINAL_RUNTIME_OPTION_CHANGED')


def _names():
    return ('t24-crm-before-meta-operations-activation-' + c.SOURCE_SHA[:12], 't24-crm-meta-operations-activation-' + c.SOURCE_SHA[:12])


def _intent(meta, env_sha, original):
    return {'source_sha': c.SOURCE_SHA, 'baseline_sha256': b.BASELINE_SHA, 'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA,
            'app_id': c.APP_ID, 'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION, 'image': c.IMAGE,
            'original_id': original['Id'], 'original_config_sha256': b.proof()['crm']['config'],
            'env_sha256': env_sha, 'expected_full_environment_sha256': digest(replaced_environment(original,meta))}


def _state():
    value = c.strict_json(c.read(c.ROOT/'candidate-created.json', maximum=8192))
    c.need(set(value) == {'intent_sha256', 'candidate_id', 'original_id', 'image'} and value['original_id'] == c.ORIGINAL_ID and
           value['image'] == c.IMAGE and re.fullmatch('[a-f0-9]{64}', value['candidate_id']) and value['candidate_id'] != c.ORIGINAL_ID,
           'EXACT_DURABLE_CANDIDATE_ID_REQUIRED')
    intent = c.strict_json(c.read(c.ROOT/'activation-started.json', maximum=8192, sha=value['intent_sha256']))
    c.need(intent['source_sha'] == c.SOURCE_SHA and intent['baseline_sha256'] == b.BASELINE_SHA and intent['configuration_freeze_sha256'] == c.CONFIG_FREEZE_SHA and
           intent['original_id'] == c.ORIGINAL_ID and intent['image'] == c.IMAGE and intent['app_id'] == c.APP_ID and intent['config_id'] == c.CONFIG_ID and
           intent['graph_version'] == c.GRAPH_VERSION, 'EXACT_ACTIVATION_INTENT_REQUIRED')
    return value, intent


def _identities(ctx, state):
    m = ctx.m; old_name, candidate_name = _names()
    original = m.inspect(state['original_id']); candidate = m.inspect(state['candidate_id'])
    c.need(original['Id'] == c.ORIGINAL_ID and original['Image'] == c.IMAGE and original['Name'] in {'/t24-crm', '/' + old_name}, 'KNOWN_ORIGINAL_CONTAINER_REQUIRED')
    c.need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == c.IMAGE and candidate['Name'] in {'/t24-crm', '/' + candidate_name}, 'KNOWN_CANDIDATE_CONTAINER_REQUIRED')
    for name, identity in (('t24-crm', None), (old_name, original['Id']), (candidate_name, candidate['Id'])):
        found = m.inspect_optional(name)
        c.need(not found or found['Id'] in ({original['Id'], candidate['Id']} if identity is None else {identity}), 'UNKNOWN_RESERVED_CONTAINER')
    return original, candidate


def _fresh(ctx, state, intent, meta, *, live=False):
    original, candidate = _identities(ctx, state); m = ctx.m
    c.need(m.runtime(original) == b.proof()['crm'], 'ORIGINAL_RUNTIME_PROVENANCE_DRIFT')
    b.legacy_environment(ctx,original); compare(candidate, original, meta, m)
    c.need(c.H(c.read(c.ENV_FILE, maximum=8192)) == intent['env_sha256'], 'TRANSFERRED_ENV_FILE_CHANGED')
    c.need(digest(candidate['Config']['Env']) == intent['expected_full_environment_sha256'], 'EXACT_CAPTURED_ENVIRONMENT_REQUIRED')
    b.verify('activation-candidate-boundary', current=candidate)
    b.source(ctx, original)
    c.need(candidate['RestartCount'] == 0 and type(candidate['RestartCount']) is int, 'CANDIDATE_RESTARTED')
    if live:
        c.need(candidate['State']['Running'] is True and original['State']['Running'] is False and m.inspect('t24-crm')['Id'] == candidate['Id'], 'SINGLE_LIVE_KNOWN_CANDIDATE_REQUIRED')
        ctx.helper.validation_window(candidate)
    else: c.need(candidate['State']['Running'] is False, 'PRESTART_CANDIDATE_MUST_BE_STOPPED')
    return original, candidate


def _configured_probe():
    public = {'APP_ID': c.APP_ID, 'CONFIG_ID': c.CONFIG_ID, 'GRAPH_VERSION': c.GRAPH_VERSION, 'PUBLIC_URL': c.ORIGIN}
    return ("import socket,os\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\n"
            "from services.meta_operations_provider import enabled,execution_enabled,settings\nfrom services.meta_operations_scheduler import enabled as opsworker\n"
            "from services.meta_business_provider import enabled as read,settings as reads\nfrom services.google_business_provider import enabled as google,settings as gs\n"
            "from services.google_business_scheduler import enabled as worker,activation_from\nv,missing=settings()\nassert enabled() is True and not missing\n"
            "assert execution_enabled() is False and opsworker() is False\nassert {k for k in os.environ if k.startswith('T24_META_OPS_')}==" + repr(set(c.OPS_KEYS)) + "\n"
            "assert all(v[k]==expected for k,expected in " + repr(public) + ".items())\nassert read() is True and not reads()[1]\nassert google() is True and not gs()[1] and worker() is True\n"
            "assert activation_from().isoformat()==" + repr(c.ACTIVATION_FROM.replace('Z', '+00:00')) + "\nprint('EXACT_OPS_CONFIGURED_WRITES_OFF_READ_GOOGLE_ON_NO_NETWORK')\n")


def _lock():
    c.server_guard(); c.pins_ready(); c.directory(c.ROOT)
    fd = os.open(c.ROOT/'activation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        c.read(c.ROOT/'activation.lock', maximum=0)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd); raise


def _recover_locked():
    ctx = b.dependencies(); m = ctx.m
    if not (c.ROOT/'candidate-created.json').exists():
        b.verify('recovery-without-durable-candidate')
        return {'stage': 'META_OPERATIONS_ACTIVATION_ORIGINAL_UNCHANGED', 'manual_orphan_review_required': True, 'database_restored': False}
    state, intent = _state(); candidate = m.inspect(state['candidate_id'])
    c.need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == c.IMAGE, 'KNOWN_DURABLE_CANDIDATE_REQUIRED')
    # Contain only the durably identified candidate before any recovery check
    # that may fail. Never locate or terminate an unrecorded container by name.
    if candidate['State']['Running']: m.run(['docker', 'stop', '--time', '30', candidate['Id']], 'CANDIDATE_CONTAINMENT_FAILED', 60)
    original, candidate = _identities(ctx, state)
    c.need(candidate['State']['Running'] is False, 'CANDIDATE_MUST_REMAIN_CONTAINED')
    c.need(m.runtime(original)['config'] == intent['original_config_sha256'], 'ORIGINAL_CONFIG_CHANGED')
    b.legacy_environment(ctx,original)
    meta = [row for row in candidate['Config']['Env'] if row.split('=', 1)[0].startswith('T24_META_OPS_')]
    compare(candidate, original, meta, m)
    c.need(digest(candidate['Config']['Env']) == intent['expected_full_environment_sha256'], 'RECOVERY_CANDIDATE_ENV_CHANGED')
    # Only the separate Ops environment is removed on recovery. The original
    # read key is unchanged; independent Ops records and the new private key
    # file remain intact while operations become disabled.
    b.verify('recovery-preserve-independent-rows', current=original, recovery=True); b.source(ctx, candidate)
    old_name, candidate_name = _names()
    if candidate['Name'] == '/t24-crm': m.run(['docker', 'rename', candidate['Id'], candidate_name], 'RETAIN_CANDIDATE_NAME_FAILED')
    if original['Name'] != '/t24-crm': m.run(['docker', 'rename', original['Id'], 't24-crm'], 'RESTORE_ORIGINAL_NAME_FAILED')
    if not original['State']['Running']: m.run(['docker', 'start', original['Id']], 'ORIGINAL_RESUME_FAILED')
    m.ready(original['Id']); original = m.inspect('t24-crm')
    c.need(original['Id'] == c.ORIGINAL_ID and original['State']['Running'] is True and m.runtime(original)['config'] == intent['original_config_sha256'], 'EXACT_ORIGINAL_NOT_RESUMED')
    b.verify('recovery-final', current=original, recovery=True)
    result = {'stage': 'META_OPERATIONS_ACTIVATION_ORIGINAL_RESUMED', 'original_id': original['Id'], 'candidate_retained_stopped': True,
              'independent_business_rows_preserved': True, 'original_read_and_google_runtime_restored': True, 'operations_disabled': True, 'google_on_cutoff_preserved': True,
              'database_restored': False, 'business_writes': False, 'provider_requests': False, 'nginx_changed': False}
    c.write(c.ROOT/('recovery-' + str(time.time_ns()) + '.json'), result)
    return result


def recover():
    fd = _lock()
    try:
        c.need(not (c.ROOT/'activated.json').exists(), 'SUCCESSFUL_ACTIVATION_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        return _recover_locked()
    finally: os.close(fd)


def _privacy_probe(ctx, state, intent, meta):
    original, candidate = _fresh(ctx, state, intent, meta, live=True); proof = b.proof()
    def nginx(*, updated):
        active = ctx.m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
        c.need(c.H(active) == proof['active_nginx_sha256'], 'EXACT_UNCHANGED_NGINX_REQUIRED'); return c.H(active)
    probe = SimpleNamespace(m=ctx.m, retained=ctx.workflow.retained, proof=proof, nginx=nginx,
        pf=SimpleNamespace(meta_environment=lambda info: compare(info, original, meta, ctx.m), security_headers=ctx.workflow.pf.security_headers),
        rows=lambda:ctx.m.sql_snapshot(ctx.m.BUSINESS))
    probe.delivery_sentinel = lambda identity:ctx.module.OperationsMethods.delivery_sentinel(probe, identity)
    probe.meta_callback_sentinel = lambda identity:ctx.workflow.retained.Release.meta_callback_sentinel(probe, identity)
    result = ctx.workflow.retained.Release.public_check(probe, candidate['Id'])
    _fresh(ctx, state, intent, meta, live=True); return result


def prepare():
    fd = _lock()
    try:
        checked = b.verify('activation-prepare'); ctx, original = checked['context'], checked['current']
        meta, values, env_sha = env_rows(); clone_config(original, meta, ctx.m)
        result = {'stage':'META_OPERATIONS_ACTIVATION_PREPARED', **_intent(meta, env_sha, original),
            'table_count':150, 'all_existing_meta_and_ops_rows_preserved':True, 'same_image':True,
            'existing_full_environment_preserved':True, 'operations_execution_enabled':False, 'operations_scheduler_enabled':False,
            'runtime_changed':False, 'provider_requests':False, 'business_writes':False, 'credential_values_exported':False}
        sha = c.write(c.ROOT/'prepared.json', result)
        return {**result, 'receipt_sha256':sha}
    finally:os.close(fd)


def _reviewed(review_sha, meta, env_sha, original):
    c.need(isinstance(review_sha,str) and re.fullmatch('[a-f0-9]{64}',review_sha), 'ACTUAL_PREPARED_ACTIVATION_REVIEW_REQUIRED')
    value = c.strict_json(c.read(c.ROOT/'prepared.json', sha=review_sha))
    expected = {'stage':'META_OPERATIONS_ACTIVATION_PREPARED', **_intent(meta, env_sha, original),
        'table_count':150, 'all_existing_meta_and_ops_rows_preserved':True, 'same_image':True,
        'existing_full_environment_preserved':True, 'operations_execution_enabled':False, 'operations_scheduler_enabled':False,
        'runtime_changed':False, 'provider_requests':False, 'business_writes':False, 'credential_values_exported':False}
    c.need(value == expected and all(value.get(key) is wanted for key, wanted in expected.items() if type(wanted) is bool), 'EXACT_PREPARED_ACTIVATION_REVIEW_REQUIRED')


def activate(review_sha):
    fd = _lock()
    try:
        c.need(not (c.ROOT/'activation-started.json').exists() and not (c.ROOT/'candidate-created.json').exists() and not (c.ROOT/'activated.json').exists(), 'FRESH_REVIEWED_ACTIVATION_REQUIRED')
        initial = b.verify('activation-before-create'); ctx, original = initial['context'], initial['current']; m = ctx.m
        meta, values, env_sha = env_rows(); _reviewed(review_sha, meta, env_sha, original); old_name, candidate_name = _names()
        c.need(not m.inspect_optional(old_name) and not m.inspect_optional(candidate_name), 'FRESH_ACTIVATION_NAMES_REQUIRED')
        config = clone_config(original, meta, m); intent = _intent(meta, env_sha, original)
        intent_sha = c.write(c.ROOT/'activation-started.json', intent)
        status, body = m.retained().docker_request('POST', '/containers/create?name=' + candidate_name, config)
        c.need(status == 201, 'SAME_IMAGE_CANDIDATE_CREATE_FAILED'); identity = c.strict_json(body).get('Id')
        c.need(isinstance(identity, str) and re.fullmatch('[a-f0-9]{64}', identity), 'EXACT_CREATED_CANDIDATE_ID_REQUIRED')
        # The file and its directory are fsynced by core.write before stop.
        c.write(c.ROOT/'candidate-created.json', {'intent_sha256': intent_sha, 'candidate_id': identity, 'original_id': original['Id'], 'image': c.IMAGE})
        state, saved = _state()
        try:
            _fresh(ctx, state, saved, meta)
            created = m.inspect(identity)
            c.need(created['State']['Status'] == 'created' and created['State'].get('StartedAt') in {'', '0001-01-01T00:00:00Z', '0001-01-01T00:00:00.000000000Z'}, 'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker', 'stop', '--time', '30', original['Id']], 'ORIGINAL_STOP_FAILED', 60)
            retained, _ = _fresh(ctx, state, saved, meta); c.need(retained['State']['Running'] is False, 'ORIGINAL_STOPPED_REQUIRED')
            m.run(['docker', 'rename', original['Id'], old_name], 'RETAIN_ORIGINAL_NAME_FAILED')
            m.run(['docker', 'rename', identity, 't24-crm'], 'CANDIDATE_ROLE_FAILED')
            _fresh(ctx, state, saved, meta)
            m.run(['docker', 'start', identity], 'CANDIDATE_START_FAILED'); m.ready(identity)
            _, candidate = _fresh(ctx, state, saved, meta, live=True)
            c.need(m.run(['docker', 'exec', identity, 'python', '-B', '-c', _configured_probe()], 'CONFIGURATION_PROBE_FAILED').strip() == b'EXACT_OPS_CONFIGURED_WRITES_OFF_READ_GOOGLE_ON_NO_NETWORK', 'CONFIGURED_PROBE_MARKER_REQUIRED')
            _, candidate = _fresh(ctx, state, saved, meta, live=True)
            privacy = _privacy_probe(ctx, state, saved, meta)
            result = {'stage': 'META_OPERATIONS_PUBLISHER_RUNTIME_ACTIVATED', 'source_sha': c.SOURCE_SHA, 'frontend_version': c.FRONTEND,
                'baseline_sha256': b.BASELINE_SHA, 'app_id': c.APP_ID, 'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION,
                'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA, 'original_id': original['Id'], 'crm': m.runtime(candidate),
                'same_application_image': True, 'exact_eleven_ops_environment_keys_added': True, 'all_original_env_order_options_mounts_network_labels_preserved': True, 'existing_read_credential_files_preserved': True, 'fresh_independent_ops_key': True,
                'all_150_business_rows_schema_and_private_boundaries_unchanged': True, 'google_on_cutoff_preserved': True,
                'operations_configured': True, 'operations_execution_enabled':False, 'operations_scheduler_enabled':False,
                'real_publisher_oauth_verified': False, 'prepared_sha256':review_sha, 'database_restored': False, 'business_writes': False, 'provider_requests': False,
                'nginx_changed': False, 'credential_values_exported': False, 'production_containers_deleted': False,
                'loopback_public_and_callback_privacy_verification': privacy}
            sha = c.write(c.ROOT/'activated.json', result)
            return {**result, 'receipt_sha256': sha}
        except BaseException:
            _recover_locked(); raise
    finally: os.close(fd)
