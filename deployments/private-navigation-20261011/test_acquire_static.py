from copy import deepcopy
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zipfile

import pytest

import acquire_static as a


def fixture():
    carrier, source = 'c' * 40, 'a' * 40
    payload = b'synthetic frozen static payload'
    manifest = {'format_version': 1, 'stage': 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE',
                'frontend_source_sha': source, 'frontend_version': 'b' * 12,
                'backend_source_sha': a.BACKEND_SOURCE, 'previous_frontend_version': a.PREVIOUS_VERSION,
                'static_only': True, 'backend_changes': False, 'databases_modified': False,
                'credentials_included': False, 'payload_sha256': a.sha(payload),
                'changed_source_files': ['app/frontend/src/pages/PrivateWorkspace.tsx']}
    files = {a.PREFIX + 'static_only_upgrade.py': b'# synthetic hash reviewed static helper\n',
             a.PREFIX + 'artifacts/static-manifest.json': json.dumps(manifest).encode(),
             a.PREFIX + 'artifacts/static-payload.tar.gz': payload}
    digests = {target: a.sha(files[selected]) for selected, target in a.SELECTED.items()}
    return carrier, source, manifest, files, digests


def archive(carrier, files, *, link=None, duplicate=False):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as stream:
        top = 't24-crm-' + carrier + '/'
        stream.writestr(top, b'')
        for name, data in files.items():
            info = zipfile.ZipInfo(top + name)
            info.external_attr = ((stat.S_IFLNK if name == link else stat.S_IFREG) | 0o644) << 16
            stream.writestr(info, data)
        if duplicate:
            stream.writestr(top + a.PREFIX + 'static_only_upgrade.py', b'duplicate')
    return out.getvalue()


def reviewed(files=None, **kwargs):
    carrier, source, _, normal, digests = fixture()
    return a.reviewed_files(archive(carrier, normal if files is None else files, **kwargs), carrier, source, digests)


@pytest.mark.parametrize('value', ['main', 'c' * 12, '../path', 'c' * 40 + '?secret=ignored', 'C' * 40])
def test_only_exact_immutable_origin_carrier_allowed(value):
    with pytest.raises(a.AcquireError):
        a.archive_url(value)


def test_archive_url_is_fixed_public_github_origin():
    assert a.archive_url('c' * 40) == 'https://codeload.github.com/billy285/t24-crm/zip/' + 'c' * 40


def test_only_three_approved_files_are_selected_and_unrelated_content_never_installed():
    _, _, _, files, _ = fixture()
    selected = reviewed({**files, 'app/backend/private.db': b'unselected synthetic bytes',
                         'other/runtime.env': b'not selected'})
    assert set(selected) == set(a.SELECTED.values())
    assert not any('backend' in name or name.endswith('.env') for name in selected)


@pytest.mark.parametrize('selected', list(a.SELECTED))
def test_missing_or_tampered_selected_file_rejected(selected):
    _, _, _, files, _ = fixture()
    changed = deepcopy(files)
    changed[selected] += b'changed'
    with pytest.raises(a.AcquireError, match='REVIEWED_SELECTED_HASH_DRIFT'):
        reviewed(changed)
    del files[selected]
    with pytest.raises(a.AcquireError, match='COMPLETE_STATIC_CARRIER_REQUIRED'):
        reviewed(files)


@pytest.mark.parametrize('selected', list(a.SELECTED))
def test_selected_symlink_never_installed(selected):
    with pytest.raises(a.AcquireError, match='REGULAR_UNENCRYPTED_SELECTED_FILE_REQUIRED'):
        reviewed(link=selected)


def test_duplicate_zip_entry_rejected():
    with patch('warnings.warn'), pytest.raises(a.AcquireError, match='UNIQUE_BOUNDED_ARCHIVE_INVENTORY_REQUIRED'):
        reviewed(duplicate=True)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'app/../../escape', 'app//uncanonical', 'app\\escape'])
def test_every_archive_entry_has_canonical_bound_path(name):
    _, _, _, files, _ = fixture()
    with pytest.raises(a.AcquireError, match='CANONICAL_ARCHIVE_PATH_REQUIRED'):
        reviewed({**files, name: b'unselected'})


@pytest.mark.parametrize('key,value', [
    ('frontend_source_sha', 'd' * 40), ('frontend_version', 'bad'),
    ('frontend_version', a.PREVIOUS_VERSION), ('backend_source_sha', 'd' * 40),
    ('previous_frontend_version', 'd' * 12), ('static_only', False), ('backend_changes', True),
    ('databases_modified', True), ('credentials_included', True), ('payload_sha256', 'd' * 64),
    ('changed_source_files', ['app/frontend/src/pages/Finance.tsx']),
    ('changed_source_files', ['app/frontend/src/pages/PrivateWorkspace.tsx'] * 2),
])
def test_even_rehashed_manifest_cannot_expand_or_rebind_release(key, value):
    carrier, source, manifest, files, digests = fixture()
    manifest[key] = value
    files[a.PREFIX + 'artifacts/static-manifest.json'] = json.dumps(manifest).encode()
    digests['static-manifest.json'] = a.sha(files[a.PREFIX + 'artifacts/static-manifest.json'])
    with pytest.raises(a.AcquireError, match='EXACT_NAVIGATION_MANIFEST_BINDING_REQUIRED'):
        a.reviewed_files(archive(carrier, files), carrier, source, digests)


@pytest.mark.parametrize('kind', ['hash', 'size', 'origin', 'status'])
def test_download_rejects_wrong_hash_oversize_origin_or_status(kind):
    response = Mock()
    response.status = 200
    response.geturl.return_value = a.archive_url('c' * 40)
    response.read.return_value = b'expected'
    if kind == 'hash':
        response.read.return_value = b'changed'
    elif kind == 'size':
        response.read.return_value = b'x' * (a.MAX_ARCHIVE_BYTES + 1)
    elif kind == 'origin':
        response.geturl.return_value = 'https://other.example.invalid/'
    else:
        response.status = 302
    opener = Mock()
    from contextlib import nullcontext
    opener.open.return_value = nullcontext(response)
    with patch.object(a.urllib.request, 'build_opener', return_value=opener), pytest.raises(a.AcquireError):
        a.download('c' * 40, a.sha(b'expected'))


def test_redirect_is_rejected_without_following_other_url():
    with pytest.raises(a.AcquireError, match='DOWNLOAD_REDIRECT_REJECTED'):
        a.NoRedirect().redirect_request(None, None, 302, None, None, 'https://other.example.invalid/')


def test_install_only_fresh_regular_protected_files(tmp_path):
    root = tmp_path.resolve()
    destination = root / 'release'
    files = reviewed()
    a.install(files, destination, b'{}\n')
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert {path.name for path in destination.iterdir()} == set(files) | {'acquired.json'}
    for name, data in files.items():
        assert (destination / name).read_bytes() == data
        assert stat.S_IMODE((destination / name).stat().st_mode) == 0o600
    with pytest.raises(a.AcquireError, match='FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED'):
        a.install(files, destination, b'{}\n')


def test_writable_parent_or_symlink_destination_rejected_without_write(tmp_path):
    parent = tmp_path.resolve()
    parent.chmod(0o777)
    with pytest.raises(a.AcquireError, match='PROTECTED_DIRECTORY_REQUIRED'):
        a.install(reviewed(), parent / 'release', b'{}\n')
    assert not (parent / 'release').exists()
    parent.chmod(0o700)
    (parent / 'linked').symlink_to(parent / 'missing')
    with pytest.raises(a.AcquireError, match='FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED'):
        a.install(reviewed(), parent / 'linked', b'{}\n')


def test_replaced_parent_cannot_redirect_descriptor_bound_writes(tmp_path):
    parent = tmp_path.resolve() / 'protected'
    parent.mkdir(mode=0o700)
    target = parent / 'release'
    real_open = os.open
    replaced = False
    def replacement(name, flags, *args, **kwargs):
        nonlocal replaced
        if kwargs.get('dir_fd') is not None and flags & os.O_CREAT and not replaced:
            parent.rename(tmp_path / 'retained')
            parent.mkdir(mode=0o700)
            target.mkdir(mode=0o700)
            replaced = True
        return real_open(name, flags, *args, **kwargs)
    with patch.object(a.os, 'open', side_effect=replacement), pytest.raises(a.AcquireError, match='RELEASE_DIRECTORY_IDENTITY_DRIFT'):
        a.install(reviewed(), target, b'{}\n')
    assert replaced and list(target.iterdir()) == []
    assert (tmp_path / 'retained/release/static_only_upgrade.py').read_bytes() == reviewed()['static_only_upgrade.py']


def args():
    carrier, source, _, files, digests = fixture()
    return SimpleNamespace(source_sha=source, carrier_sha=carrier, archive_sha256='d' * 64,
                           manifest_sha256=digests['static-manifest.json'], payload_sha256=digests['static-payload.tar.gz'],
                           helper_sha256=digests['static_only_upgrade.py'])


def test_bad_archive_hash_or_binding_writes_nothing(tmp_path):
    value = args()
    with patch.object(a.os, 'geteuid', return_value=0), patch.object(a.socket, 'gethostname', return_value=a.HOST), \
            patch.object(a, 'ROOT', tmp_path.resolve()), patch.object(a, 'protected_directory'), \
            patch.object(a, 'download', return_value=b'not a zip'), patch.object(a, 'install') as install:
        with pytest.raises(zipfile.BadZipFile):
            a.main(value)
    install.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_success_acquires_exact_source_directory_and_only_safe_hash_receipt(tmp_path):
    value = args()
    carrier, _, _, files, _ = fixture()
    with patch.object(a.os, 'geteuid', return_value=0), patch.object(a.socket, 'gethostname', return_value=a.HOST), \
            patch.object(a, 'ROOT', tmp_path.resolve()), patch.object(a, 'protected_directory'), \
            patch.object(a, 'download', return_value=archive(carrier, files)), patch.object(a, 'install') as install:
        report = a.main(value)
    assert report['deployed'] is False and report['backend_services_modified'] is False and report['databases_modified'] is False
    assert install.call_args.args[1] == tmp_path / ('private-navigation-' + value.source_sha[:12] + '-20261011')
    saved = json.loads(install.call_args.args[2])
    assert saved == report
    assert set(install.call_args.args[0]) == set(a.SELECTED.values())


@pytest.mark.parametrize('user,host', [(1000, a.HOST), (0, 'wrong-host')])
def test_wrong_server_or_user_cannot_download_or_install(user, host):
    with patch.object(a.os, 'geteuid', return_value=user), patch.object(a.socket, 'gethostname', return_value=host), \
            patch.object(a, 'download') as download, patch.object(a, 'install') as install, pytest.raises(a.AcquireError):
        a.main(args())
    download.assert_not_called()
    install.assert_not_called()


def test_safe_cli_rejects_without_echoing_accidental_sensitive_arguments():
    parser = a.SafeParser()
    with pytest.raises(a.AcquireError, match='^ARGUMENTS_REJECTED$'):
        parser.parse_args(['--sensitive=synthetic-secret'])
