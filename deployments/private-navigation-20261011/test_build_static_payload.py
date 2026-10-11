import io
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import build_static_payload as b
import static_only_upgrade as s


def run_git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def fixture(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    run_git(root, 'init', '-q')
    run_git(root, 'config', 'user.email', 'synthetic@example.com')
    run_git(root, 'config', 'user.name', 'Synthetic Release Test')
    write(root, '.gitignore', 'app/frontend/dist/\n')
    write(root, 'app/frontend/src/pages/PrivateWorkspace.tsx', 'synthetic old private page\n')
    write(root, 'app/frontend/package.json', '{"synthetic":true}\n')
    write(root, 'app/backend/services/synthetic.py', '# synthetic backend\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-qm', 'synthetic baseline')
    baseline = run_git(root, 'rev-parse', 'HEAD')
    write(root, 'app/frontend/src/pages/PrivateWorkspace.tsx', 'synthetic new navigation\n')
    write(root, 'app/frontend/src/lib/private-workspace-navigation.ts', 'synthetic navigation module\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-qm', 'synthetic navigation')
    source = run_git(root, 'rev-parse', 'HEAD')
    write(root, 'app/frontend/dist/index.html', '<script src="/assets/synthetic.js"></script>')
    write(root, 'app/frontend/dist/app-version.json', json.dumps({'version': 'b' * 12}))
    write(root, 'app/frontend/dist/assets/synthetic.js', '// synthetic complete bundle')
    output = tmp_path / 'output'
    output.mkdir()
    args = SimpleNamespace(repo=root, output=output, source_sha=source, version='b' * 12)
    return root, baseline, output, args


def build(baseline, args):
    with patch.object(b, 'BACKEND_SOURCE', baseline):
        return b.main(args)


def test_complete_static_only_freeze_is_deterministic_and_bound_to_navigation_source(tmp_path):
    root, baseline, output, args = fixture(tmp_path)
    result = build(baseline, args)
    manifest = json.loads((output / 'static-manifest.json').read_text())
    assert result['deployed'] is False and result['backend_changes'] is False
    assert manifest['backend_source_sha'] == baseline
    assert manifest['frontend_source_sha'] == args.source_sha
    assert manifest['changed_source_files'] == ['app/frontend/src/lib/private-workspace-navigation.ts',
                                                'app/frontend/src/pages/PrivateWorkspace.tsx']
    blob = (output / 'static-payload.tar.gz').read_bytes()
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        assert all(member.isfile() and not member.pax_headers and member.name.startswith('payload/') for member in archive)
    second = tmp_path / 'second'
    second.mkdir()
    args.output = second
    assert build(baseline, args) == result
    assert (second / 'static-payload.tar.gz').read_bytes() == blob


@pytest.mark.parametrize('name', ['app/frontend/src/pages/Finance.tsx', 'app/frontend/package.json',
                                 'app/backend/services/synthetic.py', 'app/docker-compose.yml', 'docker-compose.yml'])
def test_unrelated_finance_backend_or_dependency_change_cannot_freeze(tmp_path, name):
    root, baseline, _, args = fixture(tmp_path)
    write(root, name, 'changed forbidden source\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-qm', 'synthetic forbidden scope')
    args.source_sha = run_git(root, 'rev-parse', 'HEAD')
    with pytest.raises(s.StaticError):
        build(baseline, args)


@pytest.mark.parametrize('kind', ['wrong_head', 'dirty', 'untracked_source', 'source_deleted', 'symlink',
                                 'secret_file', 'unexpected_html', 'wrong_version', 'existing_artifact'])
def test_unsafe_or_unfrozen_inputs_cannot_produce_reviewed_bundle(tmp_path, kind):
    root, baseline, output, args = fixture(tmp_path)
    if kind == 'wrong_head':
        args.source_sha = 'a' * 40
    elif kind == 'dirty':
        write(root, 'app/frontend/src/pages/PrivateWorkspace.tsx', 'uncommitted navigation')
    elif kind == 'untracked_source':
        write(root, 'app/frontend/src/lib/synthetic-untracked.ts', 'untracked source')
    elif kind == 'source_deleted':
        (root / 'app/frontend/src/pages/PrivateWorkspace.tsx').unlink()
        run_git(root, 'add', '-A')
        run_git(root, 'commit', '-qm', 'synthetic deletion')
        args.source_sha = run_git(root, 'rev-parse', 'HEAD')
    elif kind == 'symlink':
        path = root / 'app/frontend/dist/assets/linked.js'
        path.symlink_to(root / 'app/frontend/src/pages/PrivateWorkspace.tsx')
    elif kind == 'secret_file':
        write(root, 'app/frontend/dist/.env', 'synthetic-secret')
    elif kind == 'unexpected_html':
        write(root, 'app/frontend/dist/extra.html', 'unreviewed html')
    elif kind == 'wrong_version':
        write(root, 'app/frontend/dist/app-version.json', json.dumps({'version': 'c' * 12}))
    else:
        (output / 'static-payload.tar.gz').write_bytes(b'existing')
    with pytest.raises(s.StaticError):
        build(baseline, args)
    assert not (output / 'static-manifest.json').exists()
