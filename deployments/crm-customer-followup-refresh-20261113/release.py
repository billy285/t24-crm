"""Guarded unique-router runtime replacement plus static release. No DB restore or migration."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import tarfile
import time
import types

SCOPE = 'crm-customer-followup-refresh'
DATE = '20261113'
STAGE = 'CRM_CUSTOMER_FOLLOWUP_REFRESH'
PREFLIGHT_CODE_SHA = 'a40622549366fad22ff2e1b2644bb61b1f35f59a10117982c006756311d54978'
RUNTIME_CODE_SHA = 'edc6f5c4df2ecab1af8a823c1cd04ddae5bf3b2d55fee1c4decf766fa135f512'
REVIEWED_SOURCE_FILES = frozenset(('app/backend/routers/app_config.py', 'app/backend/tests/test_customer_followup_status_config.py', 'app/frontend/src/components/CustomerFollowUpStatusManager.tsx', 'app/frontend/src/components/customer-detail-navigation.css', 'app/frontend/src/lib/customer-detail-refresh.ts', 'app/frontend/src/lib/customer-followup-statuses.ts', 'app/frontend/src/lib/dict-config.ts', 'app/frontend/src/pages/Customers.tsx', 'app/frontend/src/pages/Settings.tsx', 'app/frontend/tests/customer-detail-refresh.test.mjs', 'app/frontend/tests/customer-followup-integration.test.mjs', 'app/frontend/tests/customer-followup-statuses.test.mjs'))
TRUE_FLAGS = ('backend_changes', 'runtime_replacement', 'existing_hashed_assets_preserved')
FALSE_FLAGS = ('database_writes', 'database_migration', 'environment_changes', 'permissions_changes', 'provider_or_publication_actions', 'credentials_included')


def need(value, code):
    if not value:
        raise RuntimeError(code)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def changed_nginx(body, old, new, expected):
    need(sha(body) == expected, 'EXACT_NGINX_BYTES_REQUIRED')
    matches = list(re.finditer(rb'(?m)^(\s*root\s+)(' + re.escape(os.fsencode(old)) + rb')(;)', body))
    need(len(matches) == 1 and body.count(os.fsencode(new)) == 0, 'EXACT_ONE_STATIC_ROOT_SUBSTITUTION_REQUIRED')
    start, end = matches[0].span(2)
    return body[:start] + os.fsencode(new) + body[end:]

def write_private(path, body):
    if not isinstance(body, bytes):
        body = (json.dumps(body, sort_keys=True, separators=(',', ':')) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return sha(body)


def load_preflight(root):
    path = root / 'preflight.py'
    need(path.is_file() and not path.is_symlink(), 'REGULAR_PREFLIGHT_REQUIRED')
    body = path.read_bytes()
    need(sha(body) == PREFLIGHT_CODE_SHA, 'FROZEN_PREFLIGHT_CODE_REQUIRED')
    module = types.ModuleType('_frozen_customer_followup_preflight')
    module.__file__ = str(path)
    exec(compile(body, str(path), 'exec'), module.__dict__)
    module.protected(path, PREFLIGHT_CODE_SHA, private=True)
    return module


def load_runtime(root, pf):
    path = root / 'runtime_patch.py'
    body = pf.protected(path, RUNTIME_CODE_SHA, private=True)
    module = types.ModuleType('_frozen_customer_followup_runtime')
    module.__file__ = str(path)
    exec(compile(body, str(path), 'exec'), module.__dict__)
    return module


def validate_manifest(pf, value):
    need(value.get('stage') == STAGE + '_RUNTIME_STATIC_PAYLOAD' and value.get('template_only') is False, 'FINAL_RUNTIME_STATIC_MANIFEST_REQUIRED')
    source, version = value.get('source_sha', ''), value.get('frontend_version', '')
    need(re.fullmatch('[a-f0-9]{40}', source) and source not in ('0' * 40, pf.BASE_SOURCE) and re.fullmatch('[a-f0-9]{12}', version) and version not in ('0' * 12, pf.BASE_VERSION), 'NEW_SOURCE_AND_VERSION_REQUIRED')
    need(value.get('baseline_source_sha') == pf.BASE_SOURCE and value.get('baseline_frontend_version') == pf.BASE_VERSION and value.get('schema_revision') == pf.SCHEMA, 'EXACT_BASELINE_REQUIRED')
    need(value.get('static_only') is False and all(value.get(key) is True for key in TRUE_FLAGS) and all(value.get(key) is False for key in FALSE_FLAGS), 'EXACT_RUNTIME_STATIC_BOUNDARY_REQUIRED')
    for key in ('payload_sha256', 'preflight_sha256', 'source_freeze_sha256', 'target_probe_sha256', 'source_allowlist_sha256'):
        need(re.fullmatch('[a-f0-9]{64}', value.get(key, '')) and value[key] != '0' * 64, 'FINAL_NONZERO_PROOF_PINS_REQUIRED')
    sources = value.get('changed_source_files', {})
    need(isinstance(sources, dict) and set(sources) == REVIEWED_SOURCE_FILES and all(re.fullmatch('[a-f0-9]{64}', digest) for digest in sources.values()), 'EXACT_REVIEWED_SOURCE_FILES_REQUIRED')
    members = value.get('files', {})
    need(isinstance(members, dict) and {'static/index.html', 'static/app-version.json', 'backend/routers/app_config.py'} <= set(members) and len(members) <= 2000, 'EXACT_RUNTIME_STATIC_MEMBERS_REQUIRED')
    need({name for name in members if not name.startswith('static/')} == {'backend/routers/app_config.py'}, 'UNIQUE_RUNTIME_ROUTER_REQUIRED')
    need(all(pf.static_path(name) and re.fullmatch('[a-f0-9]{64}', digest) and (name == 'backend/routers/app_config.py' or name.startswith('static/') and not name.endswith(('.py', '.db', '.env', '.key', '.pem'))) for name, digest in members.items()), 'SAFE_STATIC_AND_UNIQUE_ROUTER_REQUIRED')
    need(value.get('backend_before') == {'routers/app_config.py': pf.EXPECTED_BACKEND['routers/app_config.py']}, 'EXACT_OLD_ROUTER_REQUIRED')
    need(members['backend/routers/app_config.py'] == sources['app/backend/routers/app_config.py'] and members['backend/routers/app_config.py'] != value['backend_before']['routers/app_config.py'], 'EXACT_NEW_ROUTER_REQUIRED')


def payload_members(pf, body, files):
    selected, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as archive:
        for item in archive:
            need(item.isfile() and item.name in files and item.name not in selected and 0 < item.size <= 16777216, 'EXACT_UNIQUE_PAYLOAD_MEMBER_REQUIRED')
            total += item.size
            need(total <= 67108864, 'BOUNDED_PAYLOAD_REQUIRED')
            value = archive.extractfile(item).read(item.size + 1)
            need(len(value) == item.size and sha(value) == files[item.name], 'PAYLOAD_MEMBER_HASH_CHANGED')
            selected[item.name] = value
    need(set(selected) == set(files), 'COMPLETE_PAYLOAD_REQUIRED')
    need(len(selected['backend/routers/app_config.py']) <= 262144, 'BOUNDED_ROUTER_REQUIRED')
    compile(selected['backend/routers/app_config.py'], 'reviewed-app-config.py', 'exec')
    return selected


class Release:
    def __init__(self, args):
        self.args, self.root = args, args.release
        need(self.root.is_absolute() and self.root.resolve() == self.root, 'CANONICAL_RELEASE_ROOT_REQUIRED')
        row = self.root.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o077, 'ROOT_PRIVATE_RELEASE_REQUIRED')
        self.pf = pf = load_preflight(self.root)
        self.rt = load_runtime(self.root, pf)
        need(os.geteuid() == 0 and socket.gethostname() == pf.HOST, 'EXACT_ROOT_SERVER_REQUIRED')
        self.manifest = m = pf.strict_json(pf.protected(self.root / 'manifest.json', args.manifest_sha256, private=True))
        validate_manifest(pf, m)
        need(self.root == Path('/opt/t24-crm/releases/' + SCOPE + '-' + m['source_sha'][:12] + '-' + DATE), 'EXACT_RELEASE_NAMESPACE_REQUIRED')
        self.public = Path('/var/www/t24-crm-public/' + SCOPE + '-' + m['source_sha'][:12] + '-' + DATE)
        scope = pf.strict_json(pf.protected(self.root / 'source-allowlist.json', m['source_allowlist_sha256'], private=True))
        need(isinstance(scope, list) and len(scope) == len(REVIEWED_SOURCE_FILES) and set(scope) == REVIEWED_SOURCE_FILES, 'EXACT_REVIEWED_SOURCE_ALLOWLIST_REQUIRED')
        proof = pf.strict_json(pf.protected(self.root / 'preflight.json', m['preflight_sha256'], private=True))
        metadata = {'stage', 'captured_at_unix', 'baseline_source_sha', 'read_only', 'static_only', 'backend_patch_planned', 'business_rows_read', 'database_writes', 'runtime_restarts', 'old_helpers_executed'}
        need(proof.get('stage') == STAGE + '_READONLY_BASELINE' and proof.get('baseline_source_sha') == pf.BASE_SOURCE and proof.get('read_only') is True and proof.get('static_only') is False and proof.get('backend_patch_planned') == ['routers/app_config.py'], 'EXACT_REVIEWED_PREFLIGHT_REQUIRED')
        need(all(proof.get(key) is False for key in ('business_rows_read', 'database_writes', 'runtime_restarts', 'old_helpers_executed')), 'STRICT_READONLY_PREFLIGHT_REQUIRED')
        need({key: value for key, value in proof.items() if key not in metadata} == pf.EXPECTED_BOUNDARY, 'EXACT_SIXTEEN_BOUNDARY_PINS_REQUIRED')
        need(type(proof.get('captured_at_unix')) is int and proof['captured_at_unix'] <= time.time() + 60, 'VALID_PREFLIGHT_TIME_REQUIRED')
        if args.phase in ('prepare', 'activate'):
            need(time.time() - proof['captured_at_unix'] <= 21600, 'FRESH_SIX_HOUR_PREFLIGHT_REQUIRED')
        self.proof, self.baseline = proof, dict(pf.EXPECTED_BOUNDARY)
        target = pf.strict_json(pf.protected(self.root / 'target-probe.json', m['target_probe_sha256'], private=True))
        need(target.get('stage') == STAGE + '_TARGET_PROBE' and target.get('eligible_for_image_only_backend_patch') is True and target.get('code_overlay_destinations') == [] and target.get('runtime_id') == proof['runtime']['id'] and target.get('base_image_id') == proof['runtime']['image'] and target.get('router', {}).get('sha256') == m['backend_before']['routers/app_config.py'], 'EXACT_REVIEWED_TARGET_ARCHITECTURE_REQUIRED')
        freeze = pf.strict_json(pf.protected(self.root / 'source-freeze.json', m['source_freeze_sha256'], private=True))
        need(freeze.get('stage') == STAGE + '_SOURCE_FREEZE' and freeze.get('source_sha') == m['source_sha'] and freeze.get('frontend_version') == m['frontend_version'] and freeze.get('changed_source_files') == m['changed_source_files'] and freeze.get('baseline_source_sha') == pf.BASE_SOURCE and all(freeze.get(key) is True for key in ('fresh_build_passed', 'source_commit_bytes_verified', 'backend_focused_tests_passed', 'no_migration')), 'EXACT_SOURCE_AND_BUILD_FREEZE_REQUIRED')
        self.payload = pf.protected(self.root / 'payload.tar.gz', m['payload_sha256'], maximum=67108864, private=True)

    def expected_backend(self):
        prepared = self.reviewed()
        before = self.pf.strict_json(self.pf.protected(self.root / 'backend-before.json', prepared['backend_before_sha256'], private=True))
        expected = self.rt.expected_inventory(before, self.manifest['files']['backend/routers/app_config.py'])
        need(self.pf.digest(expected) == prepared['backend_after_inventory_sha256'], 'EXACT_PREPARED_BACKEND_MAP_REQUIRED')
        return expected

    def original(self):
        return self.pf.strict_json(self.pf.protected(self.root / 'original-inspect.json', self.reviewed()['original_inspect_sha256'], private=True))

    def reviewed(self):
        need(self.args.prepared_sha256 and re.fullmatch('[a-f0-9]{64}', self.args.prepared_sha256), 'REVIEWED_PREPARED_HASH_REQUIRED')
        p = self.pf.strict_json(self.pf.protected(self.root / 'prepared.json', self.args.prepared_sha256, private=True))
        need(p.get('stage') == STAGE + '_RUNTIME_STATIC_PREPARED' and p.get('source_sha') == self.manifest['source_sha'] and p.get('manifest_sha256') == self.args.manifest_sha256 and p.get('preflight_sha256') == self.manifest['preflight_sha256'] and p.get('payload_sha256') == self.manifest['payload_sha256'] and p.get('public_root') == str(self.public), 'EXACT_REVIEWED_PREPARED_RECEIPT_REQUIRED')
        need(re.fullmatch(r'sha256:[a-f0-9]{64}', p.get('candidate_image', '')) and p['candidate_image'] != self.rt.BASE_IMAGE, 'PREPARED_NEW_IMAGE_REQUIRED')
        for key in ('original_inspect_sha256', 'backend_before_sha256', 'backend_after_inventory_sha256', 'public_inventory_sha256', 'nginx_next_sha256', 'active_nginx_next_sha256', 'clone_database_sha256'):
            need(re.fullmatch('[a-f0-9]{64}', p.get(key, '')), 'PREPARED_COMPLETE_PROOF_HASHES_REQUIRED')
        need(p.get('cold_base_matches_live') is True and p.get('unique_router_diff') is True and p.get('offline_readonly_validation') is True and p.get('database_writes') is False and p.get('database_migration') is False, 'PREPARED_SAFETY_PROOFS_REQUIRED')
        need(self.pf.digest(self.pf.tree(self.public)) == p['public_inventory_sha256'], 'PREPARED_STATIC_DRIFT')
        return p

    def describe(self, info):
        original = self.baseline['runtime']
        if info['Id'] == original['id']:
            expected = {'id': original['id'], 'image': original['image'], 'started': info['State']['StartedAt'], 'config': original['config']}
        else:
            mounts = sorted(info['Mounts'], key=self.pf.canonical)
            expected = {'id': info['Id'], 'image': info['Image'], 'started': info['State']['StartedAt'], 'config': self.pf.runtime_hash(info, mounts)}
        return self.pf.runtime(info, expected)

    def capture_expected(self, runtime, backend_sha, root, version):
        pf = self.pf
        old_runtime, old_inventory, old_files = pf.RUNTIME, pf.BASE_INVENTORY_SHA, pf.EXPECTED_BACKEND
        try:
            pf.RUNTIME = {key: runtime[key] for key in ('id', 'image', 'started', 'config')}
            pf.BASE_INVENTORY_SHA = backend_sha
            pf.EXPECTED_BACKEND = {**old_files, 'routers/app_config.py': self.manifest['files']['backend/routers/app_config.py'] if backend_sha != self.baseline['backend_inventory_sha256'] else self.rt.BASE_ROUTER_SHA}
            return pf.capture(str(root), version)
        finally:
            pf.RUNTIME, pf.BASE_INVENTORY_SHA, pf.EXPECTED_BACKEND = old_runtime, old_inventory, old_files

    def boundary(self, *, updated=False, runtime=None, recovered=False):
        expected = dict(self.baseline)
        if runtime:
            expected['runtime'] = runtime
        if updated:
            p = self.reviewed()
            expected.update(backend_inventory_sha256=p['backend_after_inventory_sha256'], public_root=str(self.public), frontend_version=self.manifest['frontend_version'], public_inventory_sha256=p['public_inventory_sha256'], nginx_sha256=p['nginx_next_sha256'], active_nginx_sha256=p['active_nginx_next_sha256'])
        actual = self.capture_expected(expected['runtime'], expected['backend_inventory_sha256'], expected['public_root'], expected['frontend_version'])
        need(actual == expected, 'RUNTIME_STATIC_BOUNDARY_DRIFT')
        need(self.pf.digest(self.pf.tree(Path(self.pf.BASE_PUBLIC))) == self.baseline['public_inventory_sha256'], 'OLD_STATIC_BYTES_CHANGED')
        return actual

    def stage_static(self, selected):
        pf = self.pf
        previous = pf.tree(Path(pf.BASE_PUBLIC))
        static = {name[7:]: body for name, body in selected.items() if name.startswith('static/')}
        need(pf.strict_json(static['app-version.json']) == {'version': self.manifest['frontend_version']}, 'EXACT_STATIC_VERSION_REQUIRED')
        for name, body in static.items():
            if name.startswith('assets/') and name in previous:
                need(sha(body) == previous[name], 'EXISTING_HASHED_ASSET_CONFLICT')
        need(not self.public.exists(), 'FRESH_STATIC_ROOT_REQUIRED')
        self.public.mkdir(mode=0o755)
        self.public.chmod(0o755)
        for name in sorted(set(previous) | set(static)):
            target, parent = self.public / name, self.public
            for part in Path(name).parts[:-1]:
                parent /= part
                if not parent.exists():
                    parent.mkdir(mode=0o755)
                    parent.chmod(0o755)
                need(parent.resolve() == parent and parent.is_dir() and not parent.stat().st_mode & 0o022, 'PROTECTED_STATIC_PARENT_REQUIRED')
            body = static[name] if name in static else pf.protected(Path(pf.BASE_PUBLIC) / name)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o644)
        actual = pf.tree(self.public)
        need(actual == {**previous, **{name: sha(body) for name, body in static.items()}}, 'EXACT_PREPARED_STATIC_MAP_REQUIRED')
        return pf.digest(actual)

    def build_image(self, router):
        rt, source = self.rt, self.manifest['source_sha']
        base_tag = 't24-crm:customer-followup-base-' + source[:12]

        def exact_base(reference):
            rows = self.pf.strict_json(rt.run(['docker', 'image', 'inspect', reference], 'LOCAL_BASE_IMAGE_INSPECT_FAILED'))
            need(len(rows) == 1 and rows[0]['Id'] == rt.BASE_IMAGE, 'EXACT_LOCAL_BASE_ALIAS_REQUIRED')

        exact_base(rt.BASE_IMAGE)
        alias = __import__('subprocess').run(['docker', 'image', 'inspect', base_tag], capture_output=True, timeout=30)
        if alias.returncode == 0:
            rows = self.pf.strict_json(alias.stdout)
            need(len(rows) == 1 and rows[0]['Id'] == rt.BASE_IMAGE, 'LOCAL_BASE_ALIAS_COLLISION')
        else:
            need(b'No such' in alias.stderr or b'not found' in alias.stderr, 'LOCAL_BASE_ALIAS_LOOKUP_FAILED')
            rt.run(['docker', 'image', 'tag', rt.BASE_IMAGE, base_tag], 'LOCAL_BASE_ALIAS_CREATE_FAILED')
        exact_base(base_tag)
        context = self.root / 'image-context'
        context.mkdir(mode=0o700)
        write_private(context / 'app_config.py', router)
        dockerfile = ('FROM ' + base_tag + '\nCOPY app_config.py /app/backend/routers/app_config.py\n').encode()
        write_private(context / 'Dockerfile', dockerfile)
        tag = 't24-crm:customer-followup-' + source[:12]
        result = __import__('subprocess').run(['docker', 'image', 'inspect', tag], capture_output=True, timeout=30)
        need(result.returncode != 0 and (b'No such' in result.stderr or b'not found' in result.stderr), 'FRESH_CANDIDATE_IMAGE_TAG_REQUIRED')
        rt.run(['docker', 'build', '--network=none', '--pull=false', '-f', str(context / 'Dockerfile'), '-t', tag, str(context)], 'UNIQUE_ROUTER_IMAGE_BUILD_FAILED', timeout=300)
        exact_base(base_tag)
        images = self.pf.strict_json(rt.run(['docker', 'image', 'inspect', tag], 'CANDIDATE_IMAGE_INSPECT_FAILED'))
        need(len(images) == 1 and re.fullmatch(r'sha256:[a-f0-9]{64}', images[0]['Id']) and images[0]['Id'] != rt.BASE_IMAGE, 'EXACT_NEW_CANDIDATE_IMAGE_REQUIRED')
        return images[0]['Id']

    def prepare(self):
        pf, rt, m = self.pf, self.rt, self.manifest
        self.boundary()
        need(not (self.root / 'prepared.json').exists() and not (self.root / 'original-inspect.json').exists(), 'FRESH_PREPARE_REQUIRED')
        old = rt.inspect('t24-crm')
        need(self.describe(old) == self.baseline['runtime'], 'EXACT_ORIGINAL_RUNTIME_REQUIRED')
        rt.validate_layout(old, pf.DB)
        layer = rt.run(['docker', 'diff', old['Id']], 'WRITABLE_LAYER_READ_FAILED').decode().splitlines()
        rt.validate_writable_layer(old, layer)
        before = rt.inventory(old['Id'])
        need(len(before) == 443 and pf.digest(before) == self.baseline['backend_inventory_sha256'], 'EXACT_LIVE_BASE_BACKEND_REQUIRED')
        need(rt.cold_inventory(rt.BASE_IMAGE) == before, 'COLD_BASE_MUST_EQUAL_LIVE_BACKEND')
        selected = payload_members(pf, self.payload, m['files'])
        expected = rt.expected_inventory(before, m['files']['backend/routers/app_config.py'])
        available = os.statvfs(self.root)
        need(available.f_bavail * available.f_frsize > len(self.payload) * 3 + pf.DB.stat().st_size * 3 + 536870912, 'BOUNDED_PREPARE_DISK_CAPACITY_REQUIRED')
        original_sha = write_private(self.root / 'original-inspect.json', old)
        before_sha = write_private(self.root / 'backend-before.json', before)
        write_private(self.root / 'writable-layer-paths-private.json', layer)
        _, raw, active, _ = pf.nginx()
        write_private(self.root / 'nginx-before.conf', raw)
        candidate = self.build_image(selected['backend/routers/app_config.py'])
        need(rt.cold_inventory(candidate) == expected, 'CANDIDATE_DIFF_MUST_BE_UNIQUE_ROUTER')
        clone = self.root / 'clone-database.db'
        rt.backup_clone(pf.DB, clone)
        clone_hash = sha(pf.protected(clone, maximum=1073741824, private=True))
        metadata = rt.schema_metadata(clone)
        need(metadata == {'revision': [(pf.SCHEMA,)], 'sha256': pf.SCHEMA_SHA, 'table_count': 169}, 'CLONE_SCHEMA_MUST_MATCH_BASELINE')
        offline = rt.offline_validation(candidate, clone, pf.SCHEMA, pf.SCHEMA_SHA)
        need(offline == {'offline_import_and_service_dictionary_valid': True, 'schema_unchanged': True, 'database_writes': False, 'provider_network': False}, 'EXACT_OFFLINE_READONLY_PROOF_REQUIRED')
        need(sha(pf.protected(clone, maximum=1073741824, private=True)) == clone_hash, 'OFFLINE_CLONE_DATABASE_CHANGED')
        public_sha = self.stage_static(selected)
        changed = changed_nginx(raw, pf.BASE_PUBLIC, self.public, self.baseline['nginx_sha256'])
        changed_active = active.replace(os.fsencode(pf.BASE_PUBLIC), os.fsencode(self.public), 1)
        self.boundary()
        value = {'stage': STAGE + '_RUNTIME_STATIC_PREPARED', 'source_sha': m['source_sha'], 'frontend_version': m['frontend_version'], 'manifest_sha256': self.args.manifest_sha256, 'payload_sha256': m['payload_sha256'], 'preflight_sha256': m['preflight_sha256'], 'candidate_image': candidate, 'base_image': rt.BASE_IMAGE, 'original_inspect_sha256': original_sha, 'backend_before_sha256': before_sha, 'backend_after_inventory_sha256': pf.digest(expected), 'public_root': str(self.public), 'public_inventory_sha256': public_sha, 'nginx_next_sha256': sha(changed), 'active_nginx_next_sha256': sha(changed_active), 'clone_database_sha256': clone_hash, 'cold_base_matches_live': True, 'unique_router_diff': True, 'offline_readonly_validation': True, 'database_writes': False, 'database_migration': False, 'runtime_stopped': False, 'existing_hashed_assets_preserved': True}
        return {**value, 'prepared_sha256': write_private(self.root / 'prepared.json', value)}

    def replace_nginx(self, before, after):
        pf, path = self.pf, Path(self.proof['nginx_path'])
        need(pf.protected(path) == before and pf.NGINX.resolve() == path, 'EXACT_CURRENT_NGINX_REQUIRED')
        row = path.stat()
        temp = path.with_name(path.name + '.customer-followup-' + self.manifest['source_sha'][:12] + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, stat.S_IMODE(row.st_mode))
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, stat.S_IMODE(row.st_mode))
        need(pf.protected(path) == before, 'NGINX_CHANGED_DURING_SWAP')
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        pf.run(['nginx', '-t'], 'NGINX_CONFIG_TEST_FAILED')
        pf.run(['nginx', '-s', 'reload'], 'NGINX_RELOAD_FAILED')

    def immutable_recovery_boundary(self):
        pf = self.pf
        need([pf.DB.stat().st_dev, pf.DB.stat().st_ino] == pf.DATABASE_IDENTITY, 'PRODUCTION_DB_IDENTITY_CHANGED')
        need(self.rt.schema_metadata(pf.DB) == {'revision': [(pf.SCHEMA,)], 'sha256': pf.SCHEMA_SHA, 'table_count': 169}, 'PRODUCTION_SCHEMA_CHANGED')
        need({name: pf.runtime(pf.inspect(name), expected) for name, expected in pf.PRIVATE.items()} == self.baseline['private_runtimes'], 'PRIVATE_RUNTIME_DRIFT')
        need({name: sha(pf.protected(name, expected)) for name, expected in pf.HELPERS.items()} == self.baseline['helper_hashes'], 'HISTORICAL_HELPER_DRIFT')
        need(pf.digest(pf.tree(Path(pf.BASE_PUBLIC))) == self.baseline['public_inventory_sha256'], 'OLD_PUBLIC_TREE_DRIFT')

    def retry_boundary(self, *, updated=False, runtime=None, recovered=False):
        for attempt in range(8):
            try:
                return self.boundary(updated=updated, runtime=runtime, recovered=recovered)
            except RuntimeError as error:
                if str(error) not in ('EXACT_PUBLIC_VERSION_REQUIRED', 'PUBLIC_VERSION_READ_FAILED') or attempt == 7:
                    raise
                time.sleep(0.4)

    def recover(self):
        pf, rt, p = self.pf, self.rt, self.reviewed()
        need((self.root / 'activation-started.json').exists(), 'OWN_ACTIVATION_REQUIRED_FOR_RECOVERY')
        marker = pf.strict_json(pf.protected(self.root / 'activation-started.json', private=True))
        need(marker.get('prepared_sha256') == self.args.prepared_sha256 and marker.get('manifest_sha256') == self.args.manifest_sha256, 'EXACT_OWN_ACTIVATION_MARKER_REQUIRED')
        original = self.original()
        need(marker.get('old_id') == original['Id'], 'EXACT_OLD_RUNTIME_MARKER_REQUIRED')
        self.immutable_recovery_boundary()
        old_raw = pf.protected(self.root / 'nginx-before.conf', self.baseline['nginx_sha256'], private=True)
        new_raw = changed_nginx(old_raw, pf.BASE_PUBLIC, self.public, self.baseline['nginx_sha256'])
        need(sha(new_raw) == p['nginx_next_sha256'], 'EXACT_PREPARED_NGINX_REQUIRED')
        path = Path(self.proof['nginx_path'])
        current_raw = pf.protected(path)
        need(current_raw in (old_raw, new_raw), 'UNKNOWN_NGINX_NOT_RECOVERED')
        for version in (pf.BASE_VERSION, self.manifest['frontend_version']):
            try:
                need(pf.public(version) == self.baseline['content_security_policy_sha256'], 'CSP_DRIFT_NOT_RECOVERED')
                break
            except RuntimeError as error:
                if str(error) != 'EXACT_PUBLIC_VERSION_REQUIRED':
                    raise
        else:
            raise RuntimeError('UNKNOWN_PUBLIC_VERSION_NOT_RECOVERED')
        retained = 't24-crm-before-customer-followup-' + self.manifest['source_sha'][:12]
        old = rt.inspect(original['Id'])
        need(old['Name'] in ('/t24-crm', '/' + retained), 'EXACT_RETAINED_OLD_NAME_REQUIRED')
        rt.configuration_equal(old, original, rt.BASE_IMAGE, self.manifest['source_sha'], original_runtime=True, retained_name=retained)
        rt.validate_writable_layer(old, rt.run(['docker', 'diff', old['Id']], 'OLD_WRITABLE_LAYER_READ_FAILED').decode().splitlines())
        current = rt.optional('t24-crm')
        if current and current['Id'] != original['Id']:
            try:
                rt.configuration_equal(current, original, p['candidate_image'], self.manifest['source_sha'])
            except RuntimeError:
                # A clone rejected immediately after create must never start,
                # but its exact recorded, still-stopped ID can be quarantined
                # so the original runtime can resume. Later drift fails closed.
                state = pf.strict_json(pf.protected(self.root / 'candidate.json', private=True))
                need(not (self.root / 'candidate-config-verified.json').exists() and current['State']['Running'] is False and current['Image'] == p['candidate_image'] and state.get('id') == current['Id'] and state.get('manifest_sha256') == self.args.manifest_sha256 and state.get('prepared_sha256') == self.args.prepared_sha256, 'UNKNOWN_OR_CHANGED_CANDIDATE_NOT_RECOVERED')
        if current_raw == new_raw:
            self.replace_nginx(new_raw, old_raw)
        else:
            pf.run(['nginx', '-t'], 'NGINX_CONFIG_TEST_FAILED')
            pf.run(['nginx', '-s', 'reload'], 'NGINX_RELOAD_FAILED')
        if current and current['Id'] != original['Id']:
            if current['State']['Running']:
                rt.run(['docker', 'stop', '--time', '30', current['Id']], 'FAILED_CANDIDATE_STOP_FAILED', timeout=60)
            rt.run(['docker', 'rename', current['Id'], 't24-customer-followup-failed-' + current['Id'][:12]], 'FAILED_CANDIDATE_RETAIN_FAILED')
        if old['Name'] != '/t24-crm':
            rt.run(['docker', 'rename', original['Id'], 't24-crm'], 'OLD_RUNTIME_NAME_RESTORE_FAILED')
        if not old['State']['Running']:
            rt.run(['docker', 'start', original['Id']], 'OLD_RUNTIME_START_FAILED')
        rt.ready(original['Id'])
        restored = rt.inspect(original['Id'])
        rt.configuration_equal(restored, original, rt.BASE_IMAGE, self.manifest['source_sha'], original_runtime=True)
        need(rt.inventory(restored['Id']) == pf.strict_json(pf.protected(self.root / 'backend-before.json', p['backend_before_sha256'], private=True)), 'RESTORED_OLD_SOURCE_DRIFT')
        runtime = self.describe(restored)
        after = self.retry_boundary(runtime=runtime, recovered=True)
        value = {'stage': STAGE + '_RUNTIME_STATIC_RECOVERED', 'database_restored': False, 'database_writes': False, 'database_migration': False, 'private_services_changed': False, 'runtime': runtime, 'boundary': after, 'prepared_sha256': self.args.prepared_sha256}
        return {**value, 'receipt_sha256': write_private(self.root / ('recovered-' + str(time.time_ns()) + '.json'), value)}

    def activate(self):
        pf, rt, m, p = self.pf, self.rt, self.manifest, self.reviewed()
        self.boundary()
        need(not (self.root / 'activation-started.json').exists(), 'FRESH_ACTIVATION_REQUIRED')
        original = self.original()
        live = rt.inspect('t24-crm')
        need(self.describe(live) == self.baseline['runtime'], 'EXACT_PREPARED_OLD_RUNTIME_REQUIRED')
        rt.validate_layout(live, pf.DB)
        need(rt.cold_inventory(p['candidate_image']) == self.expected_backend(), 'PREPARED_IMAGE_SOURCE_DRIFT')
        old_raw = pf.protected(self.root / 'nginx-before.conf', self.baseline['nginx_sha256'], private=True)
        new_raw = changed_nginx(old_raw, pf.BASE_PUBLIC, self.public, self.baseline['nginx_sha256'])
        need(sha(new_raw) == p['nginx_next_sha256'], 'PREPARED_NGINX_BYTES_CHANGED')
        retained = 't24-crm-before-customer-followup-' + m['source_sha'][:12]
        need(rt.optional(retained) is None, 'FRESH_ROLLBACK_CONTAINER_NAME_REQUIRED')
        write_private(self.root / 'activation-started.json', {'old_id': original['Id'], 'manifest_sha256': self.args.manifest_sha256, 'prepared_sha256': self.args.prepared_sha256})
        try:
            rt.run(['docker', 'stop', '--time', '30', original['Id']], 'OLD_RUNTIME_STOP_FAILED', timeout=60)
            need(not rt.inspect(original['Id'])['State']['Running'], 'OLD_RUNTIME_STILL_RUNNING')
            rt.run(['docker', 'rename', original['Id'], retained], 'OLD_RUNTIME_RETAIN_FAILED')
            ident = rt.create_candidate(original, p['candidate_image'], m['source_sha'])
            write_private(self.root / 'candidate.json', {'id': ident, 'manifest_sha256': self.args.manifest_sha256, 'prepared_sha256': self.args.prepared_sha256})
            rt.configuration_equal(rt.inspect(ident), original, p['candidate_image'], m['source_sha'])
            write_private(self.root / 'candidate-config-verified.json', {'id': ident, 'manifest_sha256': self.args.manifest_sha256, 'prepared_sha256': self.args.prepared_sha256})
            rt.run(['docker', 'start', ident], 'CANDIDATE_START_FAILED')
            rt.ready(ident)
            current = rt.inspect(ident)
            rt.configuration_equal(current, original, p['candidate_image'], m['source_sha'])
            need(rt.inventory(ident) == self.expected_backend(), 'LIVE_UNIQUE_ROUTER_SOURCE_DRIFT')
            need(current['RestartCount'] == 0, 'FRESH_CANDIDATE_NO_RESTARTS_REQUIRED')
            runtime = self.describe(current)
            self.immutable_recovery_boundary()
            self.replace_nginx(old_raw, new_raw)
            after = self.retry_boundary(updated=True, runtime=runtime)
            value = {'stage': STAGE + '_RUNTIME_STATIC_DEPLOYED', 'source_sha': m['source_sha'], 'frontend_version': m['frontend_version'], 'public_root': str(self.public), 'runtime': runtime, 'retained_original': retained, 'schema_revision': pf.SCHEMA, 'prepared_sha256': self.args.prepared_sha256, 'preflight_sha256': m['preflight_sha256'], 'boundary': after, 'static_only': False, 'runtime_replacement': True, 'runtime_restarts': True, 'database_writes': False, 'database_migration': False, 'environment_changes': False, 'permissions_changes': False, 'provider_or_publication_actions': False}
            return {**value, 'receipt_sha256': write_private(self.root / 'deployed.json', value)}
        except BaseException:
            self.recover()
            raise

    def status(self):
        path = self.root / 'deployed.json'
        if path.exists():
            value = self.pf.strict_json(self.pf.protected(path, private=True))
            original = self.original()
            current = self.rt.inspect('t24-crm')
            self.rt.configuration_equal(current, original, self.reviewed()['candidate_image'], self.manifest['source_sha'])
            need(self.describe(current) == value['runtime'], 'DEPLOYED_RUNTIME_IDENTITY_DRIFT')
            self.boundary(updated=True, runtime=value['runtime'])
            return value
        if (self.root / 'activation-started.json').exists():
            return {'stage': STAGE + '_ACTIVATION_REQUIRES_REVIEW', 'recovery_command_required': True, 'database_restored': False}
        self.boundary()
        return {'stage': STAGE + '_NOT_ACTIVE', 'prepared_exists': (self.root / 'prepared.json').exists()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepare', 'activate', 'status', 'recover'), required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--prepared-sha256')
    args = parser.parse_args()
    need(re.fullmatch('[a-f0-9]{64}', args.manifest_sha256), 'EXACT_MANIFEST_SHA_REQUIRED')
    need(os.geteuid() == 0 and socket.gethostname() == 'iZj6c4cj7edgnhdimts4l7Z', 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    lock = Path('/opt/t24-crm/releases/.customer-followup-refresh.lock')
    for parent in lock.parents:
        row = parent.lstat()
        need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_LOCK_PARENT_REQUIRED')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        row = os.fstat(fd)
        need(stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PRIVATE_RELEASE_LOCK_REQUIRED')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = Release(args)
        print(json.dumps(getattr(release, args.phase)(), sort_keys=True))
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
