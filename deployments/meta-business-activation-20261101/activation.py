"""Same-image Meta-only environment switch. No SQL, provider, Nginx or DB restore."""
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
    values = c.validate_meta_env(rows)
    receipt = c.strict_json(c.read(c.ROOT/'credential-receipt.json', maximum=8192))
    expected = {'stage': 'META_CREDENTIALS_STORED_RUNTIME_UNCHANGED', 'app_id': c.APP_ID, 'business_id': c.BUSINESS_ID,
                'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION, 'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA,
                'env_path': str(c.ENV_FILE), 'env_sha256': c.H(body), 'independent_fernet_key_generated': True,
                'credential_values_exported': False, 'runtime_changed': False, 'business_writes': False, 'provider_requests': False}
    c.need(all(receipt.get(key) == value for key, value in expected.items()), 'EXACT_TRANSFERRED_META_CREDENTIAL_RECEIPT_REQUIRED')
    return rows, values, c.H(body)


def clone_config(original, meta, m):
    c.need(original['Image'] == c.IMAGE and original['HostConfig'].get('AutoRemove') is False, 'SAME_RETAINED_IMAGE_CONFIGURATION_REQUIRED')
    old = original['Config']['Env']
    c.need(not any(row.split('=', 1)[0].startswith('T24_META_') for row in old), 'ORIGINAL_META_ENV_MUST_BE_ABSENT')
    values = c.validate_meta_env(meta)
    existing = dict(row.split('=', 1) for row in old)
    c.need(all(values['T24_META_TOKEN_KEY'] != existing.get(name) for name in ('T24_GBP_TOKEN_KEY', 'MASK_KEY', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY')),
           'DEDICATED_META_KEY_REQUIRED')
    config = copy.deepcopy(original['Config'])
    config.update(Image=c.IMAGE, Hostname='', Env=list(old) + list(meta))
    config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    networks = m.retained().clone_networks(original)
    c.need(networks or original['HostConfig']['NetworkMode'] in {'host', 'none'}, 'ORIGINAL_NETWORKS_REQUIRED')
    config['NetworkingConfig'] = {'EndpointsConfig': networks}
    return config


def compare(candidate, original, meta, m):
    c.need(candidate['Image'] == original['Image'] == c.IMAGE, 'SAME_IMAGE_ONLY_REQUIRED')
    c.need(candidate['Config']['Env'] == original['Config']['Env'] + list(meta), 'EXACT_NINE_META_ENV_ADDITION_REQUIRED')
    c.validate_meta_env(meta)
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
    c.need(m.runtime(normalized)['config'] == m.runtime(original)['config'], 'NON_META_RUNTIME_OPTION_CHANGED')


def _names():
    return ('t24-crm-before-meta-user-activation-' + c.SOURCE_SHA[:12], 't24-crm-meta-user-activation-' + c.SOURCE_SHA[:12])


def _intent(meta, env_sha, original):
    return {'source_sha': c.SOURCE_SHA, 'baseline_sha256': b.BASELINE_SHA, 'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA,
            'app_id': c.APP_ID, 'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION, 'image': c.IMAGE,
            'original_id': original['Id'], 'original_config_sha256': b.proof()['crm']['config'],
            'env_sha256': env_sha, 'expected_full_environment_sha256': digest(original['Config']['Env'] + list(meta))}


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
    ctx.pf.meta_environment(original); compare(candidate, original, meta, m)
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
            "from services.meta_business_provider import enabled,settings\nfrom services.google_business_provider import enabled as google,settings as gs\n"
            "from services.google_business_scheduler import enabled as worker,activation_from\nv,missing=settings()\nassert enabled() is True and not missing\n"
            "assert {k for k in os.environ if k.startswith('T24_META_')}==" + repr(set(c.META_KEYS)) + "\n"
            "assert all(v[k]==expected for k,expected in " + repr(public) + ".items())\nassert google() is True and not gs()[1] and worker() is True\n"
            "assert activation_from().isoformat()==" + repr(c.ACTIVATION_FROM.replace('Z', '+00:00')) + "\nprint('EXACT_META_CONFIGURED_GOOGLE_ON_NO_NETWORK')\n")


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
        return {'stage': 'META_ACTIVATION_ORIGINAL_UNCHANGED', 'manual_orphan_review_required': True, 'database_restored': False}
    state, intent = _state(); candidate = m.inspect(state['candidate_id'])
    c.need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == c.IMAGE, 'KNOWN_DURABLE_CANDIDATE_REQUIRED')
    # Contain only the durably identified candidate before any recovery check
    # that may fail. Never locate or terminate an unrecorded container by name.
    if candidate['State']['Running']: m.run(['docker', 'stop', '--time', '30', candidate['Id']], 'CANDIDATE_CONTAINMENT_FAILED', 60)
    original, candidate = _identities(ctx, state)
    c.need(candidate['State']['Running'] is False, 'CANDIDATE_MUST_REMAIN_CONTAINED')
    c.need(m.runtime(original)['config'] == intent['original_config_sha256'], 'ORIGINAL_CONFIG_CHANGED')
    ctx.pf.meta_environment(original)
    meta = [row for row in candidate['Config']['Env'] if row.split('=', 1)[0].startswith('T24_META_')]
    compare(candidate, original, meta, m)
    c.need(digest(candidate['Config']['Env']) == intent['expected_full_environment_sha256'], 'RECOVERY_CANDIDATE_ENV_CHANGED')
    b.verify('recovery-preserve-independent-rows', current=original, recovery=True); b.source(ctx, candidate)
    old_name, candidate_name = _names()
    if candidate['Name'] == '/t24-crm': m.run(['docker', 'rename', candidate['Id'], candidate_name], 'RETAIN_CANDIDATE_NAME_FAILED')
    if original['Name'] != '/t24-crm': m.run(['docker', 'rename', original['Id'], 't24-crm'], 'RESTORE_ORIGINAL_NAME_FAILED')
    if not original['State']['Running']: m.run(['docker', 'start', original['Id']], 'ORIGINAL_RESUME_FAILED')
    m.ready(original['Id']); original = m.inspect('t24-crm')
    c.need(original['Id'] == c.ORIGINAL_ID and original['State']['Running'] is True and m.runtime(original)['config'] == intent['original_config_sha256'], 'EXACT_ORIGINAL_NOT_RESUMED')
    b.verify('recovery-final', current=original, recovery=True)
    result = {'stage': 'META_ACTIVATION_ORIGINAL_RESUMED', 'original_id': original['Id'], 'candidate_retained_stopped': True,
              'independent_business_rows_preserved': True, 'meta_runtime_enabled': False, 'google_on_cutoff_preserved': True,
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
    # Reuse the already reviewed no-capability image and invalid-callback
    # sentinels. Only their Meta-disabled premise changes: the exact nine-key
    # candidate is now configured. No real cookie/state/code or lease is used.
    original, candidate = _fresh(ctx, state, intent, meta, live=True)
    proof = b.proof()
    def nginx(*, updated):
        active = ctx.m.run(['nginx', '-T'], 'ACTIVE_NGINX_REQUIRED')
        c.need(c.H(active) == proof['active_nginx_sha256'], 'EXACT_UNCHANGED_NGINX_REQUIRED')
        return c.H(active)
    probe = SimpleNamespace(m=ctx.m, proof=proof, nginx=nginx,
        pf=SimpleNamespace(meta_environment=lambda info: compare(info, original, meta, ctx.m), security_headers=ctx.pf.security_headers),
        rows=lambda: ctx.m.sql_snapshot(ctx.m.BUSINESS))
    probe.delivery_sentinel = lambda identity: ctx.release.Release.delivery_sentinel(probe, identity)
    probe.meta_callback_sentinel = lambda identity: ctx.release.Release.meta_callback_sentinel(probe, identity)
    result = ctx.release.Release.public_check(probe, candidate['Id'])
    _fresh(ctx, state, intent, meta, live=True)
    return result


def activate():
    fd = _lock()
    try:
        c.need(not (c.ROOT/'activation-started.json').exists() and not (c.ROOT/'candidate-created.json').exists() and not (c.ROOT/'activated.json').exists(), 'FRESH_REVIEWED_ACTIVATION_REQUIRED')
        initial = b.verify('activation-before-create'); ctx, original = initial['context'], initial['current']; m = ctx.m
        meta, values, env_sha = env_rows(); old_name, candidate_name = _names()
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
            c.need(m.run(['docker', 'exec', identity, 'python', '-B', '-c', _configured_probe()], 'CONFIGURATION_PROBE_FAILED').strip() == b'EXACT_META_CONFIGURED_GOOGLE_ON_NO_NETWORK', 'CONFIGURED_PROBE_MARKER_REQUIRED')
            _, candidate = _fresh(ctx, state, saved, meta, live=True)
            privacy = _privacy_probe(ctx, state, saved, meta)
            result = {'stage': 'META_USER_CONNECTION_RUNTIME_ACTIVATED', 'source_sha': c.SOURCE_SHA, 'frontend_version': c.FRONTEND,
                'baseline_sha256': b.BASELINE_SHA, 'app_id': c.APP_ID, 'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION,
                'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA, 'original_id': original['Id'], 'crm': m.runtime(candidate),
                'same_application_image': True, 'exact_nine_meta_environment_keys_added': True, 'old_environment_options_mounts_network_labels_preserved': True,
                'all_141_business_rows_schema_and_private_boundaries_unchanged': True, 'google_on_cutoff_preserved': True,
                'meta_configured': True, 'meta_publishing_implemented': False, 'meta_comments_implemented': False,
                'real_meta_oauth_verified': False, 'database_restored': False, 'business_writes': False, 'provider_requests': False,
                'nginx_changed': False, 'credential_values_exported': False, 'production_containers_deleted': False,
                'loopback_public_and_callback_privacy_verification': privacy}
            sha = c.write(c.ROOT/'activated.json', result)
            return {**result, 'receipt_sha256': sha}
        except BaseException:
            _recover_locked(); raise
    finally: os.close(fd)
