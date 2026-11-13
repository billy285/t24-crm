"""Static-only CRM mobile information focus release: new public tree + exact Nginx root substitution.

No container lifecycle, backend writes, database writes, migrations, provider or
publication operations. The prepared receipt must be reviewed before activation.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import resource
import socket
import stat
import tarfile
import time
import types
from pathlib import Path

PREFLIGHT_CODE_SHA = 'fa270112d77de69891b2a6c843cbcf07e63e94346f95e1cc411fbcac65c538f9'
SCOPE = 'crm-customer-mobile-layout'
DATE = '20261113'
REVIEWED_SOURCE_FILES = frozenset(('app/frontend/src/components/customer-operations.css',))
TRUE_FLAGS = ('static_only', 'existing_hashed_assets_preserved')
FALSE_FLAGS = ('backend_changes', 'database_writes', 'database_migration', 'runtime_restarts', 'environment_changes', 'permissions_changes', 'provider_or_publication_actions', 'credentials_included')

def need(value, code):
    if not value:
        raise RuntimeError(code)

def sha(body):
    return hashlib.sha256(body).hexdigest()

def load_preflight(root):
    # The preflight code is verified before execution, independent of any old
    # server static helper. It contains all read-only boundary operations.
    path = root / 'preflight.py'
    need(path.is_file() and not path.is_symlink(), 'REGULAR_PREFLIGHT_CODE_REQUIRED')
    body = path.read_bytes()
    need(sha(body) == PREFLIGHT_CODE_SHA, 'FROZEN_READONLY_CODE_REQUIRED')
    module = types.ModuleType('_frozen_theme_boundary')
    module.__file__ = str(path)
    exec(compile(body, str(path), 'exec'), module.__dict__)
    module.protected(path, PREFLIGHT_CODE_SHA, private=True)
    return module

def validate_manifest(pf, value):
    need(value.get('stage') == 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_PAYLOAD' and value.get('template_only') is False, 'FINAL_STATIC_MANIFEST_REQUIRED')
    source, version = value.get('source_sha', ''), value.get('frontend_version', '')
    need(re.fullmatch('[a-f0-9]{40}', source) and source not in ('0' * 40, pf.BASE_SOURCE) and re.fullmatch('[a-f0-9]{12}', version) and version not in ('0' * 12, pf.BASE_VERSION), 'NEW_SOURCE_AND_VERSION_REQUIRED')
    need(value.get('baseline_source_sha') == pf.BASE_SOURCE and value.get('baseline_frontend_version') == pf.BASE_VERSION and value.get('schema_revision') == pf.SCHEMA, 'EXACT_STATIC_BASELINE_REQUIRED')
    need(all(value.get(key) is True for key in TRUE_FLAGS) and all(value.get(key) is False for key in FALSE_FLAGS), 'STATIC_ONLY_BOUNDARY_REQUIRED')
    for key in ('payload_sha256', 'preflight_sha256', 'source_freeze_sha256'):
        need(re.fullmatch('[a-f0-9]{64}', value.get(key, '')), 'FINAL_NONZERO_PROOF_PINS_REQUIRED')
        need(value[key] != '0' * 64, 'FINAL_NONZERO_PROOF_PINS_REQUIRED')
    members = value.get('files', {})
    need(isinstance(members, dict) and {'static/index.html', 'static/app-version.json'} <= set(members), 'SPA_STATIC_MEMBERS_REQUIRED')
    need(len(members) <= 2000 and all(name.startswith('static/') and pf.static_path(name[7:]) and not name.endswith(('.py', '.db', '.env', '.key', '.pem')) and re.fullmatch('[a-f0-9]{64}', digest) for name, digest in members.items()), 'STATIC_MEMBERS_ONLY_REQUIRED')
    source_files = value.get('changed_source_files', {})
    need(isinstance(source_files, dict) and bool(source_files) and all(name.startswith('app/frontend/') and pf.static_path(name) and re.fullmatch('[a-f0-9]{64}', digest) for name, digest in source_files.items()), 'FRONTEND_SOURCE_ONLY_REQUIRED')
    need(set(source_files) <= REVIEWED_SOURCE_FILES, 'EXACT_CUSTOMER_MOBILE_LAYOUT_SOURCE_SCOPE_REQUIRED')

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

def static_payload(pf, body, files):
    selected, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as archive:
        for item in archive:
            need(item.isfile() and item.name in files and item.name[7:] not in selected and 0 < item.size <= 16777216, 'EXACT_UNIQUE_STATIC_MEMBER_REQUIRED')
            total += item.size
            need(total <= 67108864, 'BOUNDED_STATIC_PAYLOAD_REQUIRED')
            value = archive.extractfile(item).read(item.size + 1)
            need(len(value) == item.size and sha(value) == files[item.name], 'STATIC_MEMBER_HASH_CHANGED')
            selected[item.name[7:]] = value
    need(set('static/' + name for name in selected) == set(files), 'COMPLETE_STATIC_PAYLOAD_REQUIRED')
    return selected

class Release:
    def __init__(self, args):
        self.args, self.root = args, args.release
        need(self.root.is_absolute() and self.root.resolve() == self.root, 'CANONICAL_RELEASE_ROOT_REQUIRED')
        row = self.root.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o077, 'ROOT_PRIVATE_RELEASE_DIRECTORY_REQUIRED')
        self.pf = pf = load_preflight(self.root)
        need(os.geteuid() == 0 and socket.gethostname() == pf.HOST, 'EXACT_ROOT_SERVER_REQUIRED')
        self.manifest = m = pf.strict_json(pf.protected(self.root / 'manifest.json', args.manifest_sha256, private=True))
        validate_manifest(pf, m)
        source = m['source_sha']
        need(self.root == Path('/opt/t24-crm/releases/' + SCOPE + '-' + source[:12] + '-' + DATE), 'EXACT_CUSTOMER_MOBILE_LAYOUT_RELEASE_NAMESPACE_REQUIRED')
        self.public = Path('/var/www/t24-crm-public/' + SCOPE + '-' + source[:12] + '-' + DATE)
        self.proof = p = pf.strict_json(pf.protected(self.root / 'preflight.json', m['preflight_sha256'], private=True))
        need(p.get('stage') == 'CRM_CUSTOMER_MOBILE_LAYOUT_READONLY_BASELINE' and p.get('baseline_source_sha') == pf.BASE_SOURCE and p.get('frontend_version') == pf.BASE_VERSION and p.get('public_root') == pf.BASE_PUBLIC and p.get('schema_sha256') == pf.SCHEMA_SHA and p.get('database_identity') == pf.DATABASE_IDENTITY, 'EXACT_REVIEWED_LIVE_BASELINE_REQUIRED')
        need(p.get('business_rows_read') is False and p.get('database_writes') is False and p.get('runtime_restarts') is False and p.get('old_helpers_executed') is False, 'READONLY_PREFLIGHT_REQUIRED')
        need(type(p.get('captured_at_unix')) is int and p['captured_at_unix'] <= time.time() + 60, 'VALID_CAPTURE_TIME_REQUIRED')
        if args.phase in ('prepare', 'activate'):
            need(time.time() - p['captured_at_unix'] <= 21600, 'FRESH_SIX_HOUR_PREFLIGHT_REQUIRED')
        freeze = pf.strict_json(pf.protected(self.root / 'source-freeze.json', m['source_freeze_sha256'], private=True))
        need(freeze.get('source_sha') == source and freeze.get('changed_source_files') == m['changed_source_files'] and freeze.get('baseline_source_sha') == pf.BASE_SOURCE and freeze.get('frontend_version') == m['frontend_version'] and freeze.get('fresh_build_passed') is True and freeze.get('source_commit_bytes_verified') is True and freeze.get('frontend_only') is True, 'EXACT_SOURCE_COMMIT_BUILD_FREEZE_REQUIRED')
        self.payload = pf.protected(self.root / 'payload.tar.gz', m['payload_sha256'], maximum=67108864, private=True)
        self.baseline = {key: value for key, value in p.items() if key not in ('stage', 'captured_at_unix', 'baseline_source_sha', 'static_only', 'business_rows_read', 'database_writes', 'runtime_restarts', 'old_helpers_executed')}
        need(self.baseline == pf.EXPECTED_BOUNDARY, 'EXACT_REVIEWED_FULL_BASELINE_REQUIRED')

    def boundary(self, updated=False, recovery=False):
        pf, p = self.pf, self.proof
        expected = dict(self.baseline)
        root = str(self.public) if updated else pf.BASE_PUBLIC
        version = self.manifest['frontend_version'] if updated else pf.BASE_VERSION
        if updated:
            prepared = self.reviewed()
            expected.update(public_root=root, frontend_version=version, public_inventory_sha256=prepared['public_inventory_sha256'], nginx_sha256=prepared['nginx_next_sha256'], active_nginx_sha256=prepared['active_nginx_next_sha256'])
        if recovery:
            # A failed nginx reload can leave disk=new/listener=old. Recovery
            # accepts only either of our two exact known listener versions.
            original = pf.public
            def known_public(_):
                for candidate in (pf.BASE_VERSION, self.manifest['frontend_version']):
                    try:
                        return original(candidate)
                    except RuntimeError as error:
                        if str(error) != 'EXACT_PUBLIC_VERSION_REQUIRED':
                            raise
                raise RuntimeError('UNKNOWN_PUBLIC_VERSION_NOT_RECOVERED')
            pf.public = known_public
            try:
                actual = pf.capture(root, version)
            finally:
                pf.public = original
        else:
            actual = pf.capture(root, version)
        need(actual == expected, 'STATIC_RELEASE_BOUNDARY_DRIFT')
        # Original static bytes remain present throughout, including all assets.
        need(pf.digest(pf.tree(Path(pf.BASE_PUBLIC))) == p['public_inventory_sha256'], 'OLD_STATIC_BYTES_CHANGED')
        return actual

    def reviewed(self):
        need(bool(self.args.prepared_sha256 and re.fullmatch('[a-f0-9]{64}', self.args.prepared_sha256)), 'REVIEWED_PREPARED_HASH_REQUIRED')
        value = self.pf.strict_json(self.pf.protected(self.root / 'prepared.json', self.args.prepared_sha256, private=True))
        need(value.get('stage') == 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_PREPARED' and value.get('source_sha') == self.manifest['source_sha'] and value.get('manifest_sha256') == self.args.manifest_sha256 and value.get('public_root') == str(self.public), 'EXACT_REVIEWED_PREPARE_REQUIRED')
        need(value.get('preflight_sha256') == self.manifest['preflight_sha256'] and value.get('payload_sha256') == self.manifest['payload_sha256'] and value.get('static_only') is True, 'REVIEWED_PREPARE_PINS_CHANGED')
        for key in ('public_inventory_sha256', 'nginx_next_sha256', 'active_nginx_next_sha256'):
            need(re.fullmatch('[a-f0-9]{64}', value.get(key, '')), 'REVIEWED_PREPARE_DIGEST_REQUIRED')
        need(self.pf.digest(self.pf.tree(self.public)) == value['public_inventory_sha256'], 'PREPARED_STATIC_BYTES_CHANGED')
        return value

    def prepare(self):
        pf, m = self.pf, self.manifest
        self.boundary()
        need(not self.public.exists() and not (self.root / 'prepared.json').exists(), 'FRESH_STATIC_PREPARE_REQUIRED')
        selected = static_payload(pf, self.payload, m['files'])
        need(pf.strict_json(selected['app-version.json']) == {'version': m['frontend_version']}, 'EXACT_PAYLOAD_VERSION_REQUIRED')
        previous = pf.tree(Path(pf.BASE_PUBLIC))
        for name, body in selected.items():
            if name.startswith('assets/') and name in previous:
                need(sha(body) == previous[name], 'EXISTING_HASHED_ASSET_CONFLICT')
        self.public.mkdir(mode=0o755)
        self.public.chmod(0o755)
        for name in sorted(set(previous) | set(selected)):
            target = self.public / name
            parent = self.public
            for part in Path(name).parts[:-1]:
                parent /= part
                if not parent.exists():
                    parent.mkdir(mode=0o755)
                    parent.chmod(0o755)
                need(parent.resolve() == parent and parent.is_dir() and not parent.stat().st_mode & 0o022, 'PROTECTED_PUBLIC_PARENT_REQUIRED')
            body = selected[name] if name in selected else pf.protected(Path(pf.BASE_PUBLIC) / name)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o644)
        actual = pf.tree(self.public)
        expected = {**previous, **{name: sha(body) for name, body in selected.items()}}
        need(actual == expected, 'EXACT_PREPARED_STATIC_INVENTORY_REQUIRED')
        for parent in [p for p in self.public.rglob('*') if p.is_dir()] + [self.public, self.public.parent]:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _, raw, active, _ = pf.nginx()
        changed = changed_nginx(raw, pf.BASE_PUBLIC, self.public, self.proof['nginx_sha256'])
        changed_active = active.replace(os.fsencode(pf.BASE_PUBLIC), os.fsencode(self.public), 1)
        self.boundary()
        receipt = {'stage': 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_PREPARED', 'source_sha': m['source_sha'], 'frontend_version': m['frontend_version'], 'manifest_sha256': self.args.manifest_sha256, 'payload_sha256': m['payload_sha256'], 'preflight_sha256': m['preflight_sha256'], 'public_root': str(self.public), 'public_inventory_sha256': pf.digest(actual), 'nginx_next_sha256': sha(changed), 'active_nginx_next_sha256': sha(changed_active), 'static_only': True, 'database_writes': False, 'runtime_restarts': False, 'existing_hashed_assets_preserved': True}
        return {**receipt, 'prepared_sha256': write_private(self.root / 'prepared.json', receipt)}

    def replace_nginx(self, before, after):
        pf = self.pf
        path = Path(self.proof['nginx_path'])
        need(pf.protected(path) == before and pf.NGINX.resolve() == path, 'EXACT_NGINX_CONFIG_NOT_REPLACED')
        row = path.stat()
        temp = path.with_name(path.name + '.crm-customer-mobile-layout-' + self.manifest['source_sha'][:12] + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, stat.S_IMODE(row.st_mode))
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, stat.S_IMODE(row.st_mode))
        need(pf.protected(path) == before, 'NGINX_CHANGED_DURING_REPLACEMENT')
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        pf.run(['nginx', '-t'], 'NGINX_CONFIG_TEST_FAILED')
        pf.run(['nginx', '-s', 'reload'], 'NGINX_RELOAD_FAILED')

    def recover(self):
        pf = self.pf
        prepared = self.reviewed()
        old = pf.protected(self.root / 'nginx-before.conf', self.proof['nginx_sha256'], private=True)
        new = changed_nginx(old, pf.BASE_PUBLIC, self.public, self.proof['nginx_sha256'])
        need(sha(new) == prepared['nginx_next_sha256'], 'EXACT_RECOVERY_ROOT_REQUIRED')
        current = pf.protected(Path(self.proof['nginx_path']))
        need(current in (old, new), 'UNKNOWN_NGINX_CONFIG_NOT_RECOVERED')
        self.boundary(updated=current == new, recovery=True)
        if current == new:
            self.replace_nginx(new, old)
        else:
            pf.run(['nginx', '-t'], 'NGINX_CONFIG_TEST_FAILED')
            pf.run(['nginx', '-s', 'reload'], 'NGINX_RELOAD_FAILED')
        self.retry_boundary(False)
        value = {'stage': 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_ROOT_RESTORED', 'runtime_restarts': False, 'database_writes': False, 'old_frontend_version': pf.BASE_VERSION}
        return {**value, 'receipt_sha256': write_private(self.root / ('recovered-' + str(time.time_ns()) + '.json'), value)}

    def retry_boundary(self, updated):
        for attempt in range(8):
            try:
                return self.boundary(updated)
            except RuntimeError as error:
                if str(error) not in ('EXACT_PUBLIC_VERSION_REQUIRED', 'PUBLIC_VERSION_READ_FAILED') or attempt == 7:
                    raise
                time.sleep(0.4)

    def activate(self):
        prepared = self.reviewed()
        self.boundary()
        need(not (self.root / 'activation-started.json').exists(), 'FRESH_STATIC_ACTIVATION_REQUIRED')
        old = self.pf.protected(Path(self.proof['nginx_path']))
        new = changed_nginx(old, self.pf.BASE_PUBLIC, self.public, self.proof['nginx_sha256'])
        need(sha(new) == prepared['nginx_next_sha256'], 'EXACT_PREPARED_NGINX_REQUIRED')
        write_private(self.root / 'nginx-before.conf', old)
        write_private(self.root / 'activation-started.json', {'prepared_sha256': self.args.prepared_sha256, 'new_sha256': sha(new)})
        try:
            self.replace_nginx(old, new)
            after = self.retry_boundary(True)
            value = {'stage': 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_DEPLOYED', 'source_sha': self.manifest['source_sha'], 'frontend_version': self.manifest['frontend_version'], 'public_root': str(self.public), 'runtime': self.proof['runtime'], 'schema_revision': self.pf.SCHEMA, 'prepared_sha256': self.args.prepared_sha256, 'preflight_sha256': self.manifest['preflight_sha256'], 'boundary': after, 'static_only': True, 'runtime_restarts': False, 'database_writes': False, 'database_migration': False, 'environment_changes': False, 'permissions_changes': False, 'provider_or_publication_actions': False}
            return {**value, 'receipt_sha256': write_private(self.root / 'deployed.json', value)}
        except BaseException:
            self.recover()
            raise

    def status(self):
        path = self.root / 'deployed.json'
        if path.exists():
            value = self.pf.strict_json(self.pf.protected(path, private=True))
            self.boundary(True)
            return value
        self.boundary(False)
        return {'stage': 'CRM_CUSTOMER_MOBILE_LAYOUT_STATIC_NOT_ACTIVE', 'prepared_exists': (self.root / 'prepared.json').exists()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepare', 'activate', 'status', 'recover'), required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--prepared-sha256')
    args = parser.parse_args()
    need(re.fullmatch('[a-f0-9]{64}', args.manifest_sha256), 'EXACT_MANIFEST_HASH_REQUIRED')
    need(os.geteuid() == 0 and socket.gethostname() == 'iZj6c4cj7edgnhdimts4l7Z', 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    lock = Path('/opt/t24-crm/releases/.crm-customer-mobile-layout-static.lock')
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
