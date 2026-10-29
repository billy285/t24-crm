import copy
import io
import json
import os
import re
import resource
import socket
import stat
import subprocess
import sys
import types
import urllib.request
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_carrier_command as g


@pytest.fixture
def carrier(tmp_path, monkeypatch):
    directory = tmp_path / g.DIRECTORY
    directory.mkdir(parents=True)
    for name in (*g.PINS, 'make_carrier_command.py'):
        (directory / name).write_bytes((HERE / name).read_bytes())

    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), '-c', 'core.hooksPath=/dev/null', *args], stderr=subprocess.DEVNULL)

    git('init', '-q')
    git('config', 'user.name', 'Synthetic Packaging Test')
    git('config', 'user.email', 'synthetic@example.invalid')
    git('add', '.')
    git('commit', '-qm', 'Synthetic immutable carrier fixture')
    sha = git('rev-parse', 'HEAD').decode().strip()
    monkeypatch.setattr(g, 'ROOT', directory)
    return types.SimpleNamespace(sha=sha, root=directory, git=git)


def args_fixture(phase):
    review = {'stage': 'GBP_ACTIVATION_MANUAL_REVIEW_APPROVED', 'plan_sha256': 'a' * 64,
        'project_id': 't24-beauty-os-20260823', 'callback': 'https://t24-crm.com/api/v1/google-business/oauth/callback',
        'scope': 'https://www.googleapis.com/auth/business.manage',
        'tool_sha256': {name: g.PINS[name][0] for name in ('core.py', 'preflight.py', 'activation.py')},
        'business_writes': False, 'provider_writes': False,
        **{name: True for name in ('independent_security_review_passed', 'approved_dedicated_client_project',
            'existing_consent_screen_and_clients_preserved', 'external_callback_logs_checked',
            'allow_exact_callback_logging_change', 'allow_exact_six_environment_additions')}}
    value = {'plan_sha256': 'a' * 64, 'review': review,
        'review_sha256': g.H((json.dumps(review, sort_keys=True, indent=2) + '\n').encode())}
    if phase in {'enable', 'rollback'}:
        value['logging_receipt_sha256'] = 'b' * 64
    return value


@pytest.mark.parametrize('phase', ['plan', 'protect', 'enable', 'rollback'])
def test_committed_real_fixture_produces_small_hash_bound_wrapper(carrier, phase):
    text = g.command(carrier.sha, phase, {} if phase == 'plan' else args_fixture(phase))
    assert len(text.encode()) < 8192
    assert carrier.sha in text and 'raw.githubusercontent.com/billy285/t24-crm/' in text
    assert 'NoRedirect' in text and 'response.read(size+1)' in text
    assert 'module.__tool_sha256__=members[name][0]' in text
    assert 'ProxyHandler({})' in text and 'CLIENT_SECRET' not in text
    assert all(digest in text for name, (digest, _) in g.PINS.items() if name != 'make_commands.py')


@pytest.mark.parametrize('value', ['HEAD', 'main', 'a' * 39, 'a' * 41, '../bad', 'a' * 40 + '; echo bad', 'https://evil'])
def test_unpinned_or_injected_carrier_is_rejected(carrier, value):
    with pytest.raises(g.PackagingError, match='FULL_IMMUTABLE_CARRIER_REQUIRED'):
        g.command(value, 'plan', {})


@pytest.mark.parametrize('phase', ['preflight', 'transport-init', 'plan-nginx', '../enable', 'plan;echo bad'])
def test_unapproved_phase_is_rejected(carrier, phase):
    with pytest.raises(g.PackagingError):
        g.command(carrier.sha, phase, {})


def test_local_frozen_source_drift_cannot_be_packaged(carrier):
    (carrier.root / 'core.py').write_text('print("unreviewed")\n')
    with pytest.raises(g.PackagingError, match='REVIEWED_LOCAL_TOOL_BYTES_DRIFT'):
        g.command(carrier.sha, 'plan', {})


def test_carrier_blob_drift_cannot_be_packaged_even_when_local_restored(carrier):
    path = carrier.root / 'core.py'
    correct = path.read_bytes()
    path.write_text('print("wrong committed bytes")\n')
    carrier.git('add', '.')
    carrier.git('commit', '-qm', 'Synthetic wrong carrier member')
    wrong = carrier.git('rev-parse', 'HEAD').decode().strip()
    path.write_bytes(correct)
    with pytest.raises(g.PackagingError, match='IMMUTABLE_CARRIER_TOOL_BYTES_DRIFT'):
        g.command(wrong, 'plan', {})


def test_missing_generator_in_carrier_is_rejected(carrier):
    path = carrier.root / 'make_carrier_command.py'
    correct = path.read_bytes()
    carrier.git('rm', str(path))
    carrier.git('commit', '-qm', 'Synthetic carrier missing generator')
    missing = carrier.git('rev-parse', 'HEAD').decode().strip()
    path.write_bytes(correct)
    with pytest.raises(g.PackagingError, match='LOCAL_IMMUTABLE_CARRIER_LOOKUP_FAILED'):
        g.command(missing, 'plan', {})


@pytest.mark.parametrize('mutation', [
    lambda value: value.__setitem__('client_secret', 'SENSITIVE'),
    lambda value: value['review'].__setitem__('client_secret', 'SENSITIVE'),
    lambda value: value['review'].__setitem__('callback', 'https://evil.example'),
    lambda value: value['review'].__setitem__('external_callback_logs_checked', False),
    lambda value: value.__setitem__('review_sha256', 'f' * 64),
])
def test_only_exact_public_review_arguments_can_be_embedded(carrier, mutation):
    value = args_fixture('protect')
    mutation(value)
    with pytest.raises(g.PackagingError):
        g.command(carrier.sha, 'protect', value)


def test_wrong_reviewed_tool_hash_is_rejected_before_wrapper_output(carrier):
    value = args_fixture('protect')
    value['review']['tool_sha256']['core.py'] = 'f' * 64
    value['review_sha256'] = g.H((json.dumps(value['review'], sort_keys=True, indent=2) + '\n').encode())
    with pytest.raises(g.PackagingError, match='PUBLIC_REVIEW_TOOL_HASH_DRIFT'):
        g.command(carrier.sha, 'protect', value)


def test_plan_has_no_public_argument_escape_hatch(carrier):
    with pytest.raises(g.PackagingError, match='PLAN_ACCEPTS_NO_ARGUMENTS'):
        g.command(carrier.sha, 'plan', {'path': '/any'})


def test_duplicate_json_public_fields_rejected():
    with pytest.raises(g.PackagingError, match='DUPLICATE_PUBLIC_ARGUMENT_FIELD'):
        g.strict_json('{"review":{},"review":{"client_secret":"SENSITIVE"}}')


def bootstrap_body(text):
    return text.split("<<'GBP_IMMUTABLE_CARRIER_BOOTSTRAP'\n", 1)[1].split('\nGBP_IMMUTABLE_CARRIER_BOOTSTRAP\n', 1)[0]


def run_bootstrap(text, carrier, monkeypatch, capsys, *, user=0, host=None, changed_member=None, redirect=False, unsafe_root=False):
    events = []
    original_lstat, original_resolve = Path.lstat, Path.resolve
    original_exists = Path.exists
    marker = g.SERVER_ROOT

    def lstat(path):
        if str(path).startswith('/opt') or str(path) == '/':
            return types.SimpleNamespace(st_mode=stat.S_IFDIR | (0o700 if str(path) == marker else 0o755),
                st_uid=1 if unsafe_root and str(path) == marker else 0)
        return original_lstat(path)

    def resolve(path, **kwargs):
        if str(path).startswith('/opt'):
            return path
        return original_resolve(path, **kwargs)

    monkeypatch.setattr(os, 'geteuid', lambda: user)
    monkeypatch.setattr(socket, 'gethostname', lambda: g.HOST if host is None else host)
    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(Path, 'resolve', resolve)
    monkeypatch.setattr(Path, 'exists', lambda path: True if str(path) == marker else original_exists(path))
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: events.append('core-disabled'))

    class Response:
        code = 200
        def __init__(self, url): self.url = url
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def geturl(self): return 'https://evil.example/redirect' if redirect else self.url
        def read(self, maximum):
            name = self.url.rsplit('/', 1)[-1]
            blob = (carrier.root / name).read_bytes()
            return (blob + b'bad' if name == changed_member else blob)[:maximum]

    class Opener:
        def open(self, url, timeout):
            events.append(('network', url, timeout))
            assert url.startswith('https://raw.githubusercontent.com/billy285/t24-crm/' + carrier.sha + '/' + g.DIRECTORY + '/')
            return Response(url)

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    for name in ('core', 'preflight', 'activation'):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name))
    body = bootstrap_body(text).replace("result=loaded['activation'].dispatch(phase,arguments)", "result={'stage':'SYNTHETIC_ENTRY_REACHED','phase':phase}")
    try:
        exec(compile(body, 'synthetic-carrier-bootstrap', 'exec'), {})
    except SystemExit as result:
        assert result.code == 1
    output = capsys.readouterr().out.strip().splitlines()
    return events, json.loads(output[-1])


def test_loader_downloads_all_exact_bytes_then_preserves_tool_hash_identity(carrier, monkeypatch, capsys):
    text = g.command(carrier.sha, 'plan', {})
    events, output = run_bootstrap(text, carrier, monkeypatch, capsys)
    assert output == {'stage': 'SYNTHETIC_ENTRY_REACHED', 'phase': 'plan-nginx'}
    requests = [row for row in events if isinstance(row, tuple)]
    assert len(requests) == 3 and events[0] == 'core-disabled'
    assert [row[1].rsplit('/', 1)[-1] for row in requests] == ['core.py', 'preflight.py', 'activation.py']


@pytest.mark.parametrize('kwargs', [{'user': 501}, {'host': 'wrong-host'}, {'unsafe_root': True}])
def test_root_host_and_release_guards_run_before_network(carrier, monkeypatch, capsys, kwargs):
    text = g.command(carrier.sha, 'plan', {})
    events, output = run_bootstrap(text, carrier, monkeypatch, capsys, **kwargs)
    assert output['stage'] == 'GBP_CARRIER_BOOTSTRAP_REJECTED'
    assert not any(isinstance(row, tuple) for row in events)


@pytest.mark.parametrize('kwargs,code', [({'changed_member': 'core.py'}, 'IMMUTABLE_SOURCE_BYTES_DRIFT'),
    ({'changed_member': 'activation.py'}, 'IMMUTABLE_SOURCE_BYTES_DRIFT'), ({'redirect': True}, 'IMMUTABLE_SOURCE_RESPONSE_REQUIRED')])
def test_changed_bytes_or_redirect_never_reach_activation_entry(carrier, monkeypatch, capsys, kwargs, code):
    text = g.command(carrier.sha, 'plan', {})
    events, output = run_bootstrap(text, carrier, monkeypatch, capsys, **kwargs)
    assert output == {'stage': 'GBP_CARRIER_BOOTSTRAP_REJECTED', 'code': code}


def test_unapproved_local_member_path_rejected_before_file_read(carrier, monkeypatch):
    monkeypatch.setattr(g, 'PINS', {**g.PINS, '../../secret': ('0' * 64, 12)})
    with pytest.raises(g.PackagingError, match='EXACT_LOCAL_MEMBER_SET_REQUIRED'):
        g.command(carrier.sha, 'plan', {})


def test_unapproved_remote_member_path_rejected_before_network(carrier, monkeypatch, capsys):
    text = g.command(carrier.sha, 'plan', {}).replace("'core': (", "'../../escape': (", 1)
    events, output = run_bootstrap(text, carrier, monkeypatch, capsys)
    assert output['code'] == 'EXACT_THREE_MEMBERS_REQUIRED'
    assert not any(isinstance(row, tuple) for row in events)


def test_unapproved_runtime_phase_rejected_before_network(carrier, monkeypatch, capsys):
    text = g.command(carrier.sha, 'plan', {}).replace("phase='plan-nginx'", "phase='transport-install'", 1)
    events, output = run_bootstrap(text, carrier, monkeypatch, capsys)
    assert output['code'] == 'EXACT_CARRIER_PHASE_REQUIRED'
    assert not any(isinstance(row, tuple) for row in events)
