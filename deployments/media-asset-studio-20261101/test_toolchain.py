import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import os
import tempfile
import zlib

import pytest

HERE = Path(__file__).resolve().parent


def load(name):
    s = importlib.util.spec_from_file_location('asset_deps_' + name, HERE / (name + '.py'))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def test_only_three_reviewed_top_level_packages_and_current_base():
    m = load('toolchain'); p = load('preflight')
    assert m.TOP == {'ffmpeg': '7:7.1.5-0+deb13u1', 'fonts-noto-cjk': '1:20240730+repack1-1', 'fonts-dejavu-core': '2.37-8'}
    assert m.PREFLIGHT_SHA == hashlib.sha256((HERE / 'preflight.py').read_bytes()).hexdigest()
    assert m.ACTUAL_PROOF_SHA == 'bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
    assert p.RUNTIME['image'] == 'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'


def test_all_three_isolated_phase_programs_compile():
    m = load('toolchain')
    for code in (m.FETCH.replace('__TOP__', repr(m.TOP)), m.INSTALL, m.PROBE): ast.parse(code)


def test_fetch_only_signed_official_sources_and_no_installation():
    m = load('toolchain')
    urls = set(re.findall(r'https?://[^ ]+', m.FETCH))
    assert urls == {'https://deb.debian.org/debian', 'https://deb.debian.org/debian-security'}
    assert 'signed-by=/usr/share/keyrings/debian-archive-keyring.gpg' in m.FETCH
    assert 'AllowUnauthenticated=false' in m.FETCH and 'AllowInsecureRepositories=false' in m.FETCH
    assert "'--download-only'" in m.FETCH and 'FETCH_MUST_NOT_INSTALL_OR_UPGRADE' in m.FETCH
    assert 'EXISTING_PACKAGE_UPGRADE_OR_DUPLICATE_REJECTED' in m.FETCH
    assert 'SIGNED_APT_SHA256_REQUIRED' in m.FETCH and 'COMPLETE_BOUNDED_DOWNLOADED_CLOSURE_REQUIRED' in m.FETCH


@pytest.mark.parametrize('simulation,expected_error', [
    ('Inst libc6 [2.41-1] (2.41-2 Debian:13/stable [amd64])', 'EXISTING_PACKAGE_UPGRADE_OR_DUPLICATE_REJECTED'),
    ('Remv libc6 [2.41-1]', 'NO_REMOVAL_PERMITTED'),
    ('Inst unexpected malformed', 'EXACT_APT_PLAN_FORMAT_REQUIRED'),
])
def test_exact_fetch_plan_loop_rejects_existing_upgrade_removal_or_unknown_format(simulation, expected_error):
    m = load('toolchain'); tree = ast.parse(m.FETCH.replace('__TOP__', repr(m.TOP)))
    node = next(n for n in tree.body if isinstance(n, ast.For) and ast.unparse(n.iter) == 'simulation.splitlines()')
    context = {'simulation': simulation, 'selected': {}, 'before': {'libc6': {'version': '2.41-1'}}, 're': re}
    with pytest.raises(RuntimeError, match=expected_error): exec(compile(ast.Module(body=[node], type_ignores=[]), '<exact-fetch-plan-loop>', 'exec'), context)


def test_exact_fetch_plan_loop_records_new_version_only():
    m = load('toolchain'); tree = ast.parse(m.FETCH.replace('__TOP__', repr(m.TOP)))
    node = next(n for n in tree.body if isinstance(n, ast.For) and ast.unparse(n.iter) == 'simulation.splitlines()')
    context = {'simulation': 'Inst ffmpeg (7:7.1.5-0+deb13u1 Debian:13/stable [amd64])', 'selected': {}, 'before': {}, 're': re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<exact-fetch-plan-loop>', 'exec'), context)
    assert context['selected'] == {'ffmpeg': '7:7.1.5-0+deb13u1'}


def test_offline_install_preserves_every_existing_package_and_exact_new_closure():
    m = load('toolchain')
    assert "'--no-download'" in m.INSTALL and "'--no-remove'" in m.INSTALL and "'--no-upgrade'" in m.INSTALL
    assert 'EXACT_BASE_PACKAGE_INVENTORY_REQUIRED' in m.INSTALL
    assert 'EXACT_FROZEN_DEB_REQUIRED' in m.INSTALL and 'ONLY_REVIEWED_ADDED_PACKAGES_REQUIRED' in m.INSTALL
    assert 'apt-get update' not in m.INSTALL and 'https://' not in m.INSTALL


def test_large_public_package_copy_does_not_change_protected_secret_helpers():
    m = load('toolchain'); source = (HERE / 'toolchain.py').read_text()
    assert 'copy_public_package(data /' in source
    assert 'c.read(data / \'packages\'' not in source
    assert "os.chown(path,0,0);path.chmod(0o600)" in m.FETCH and 'os.umask(0o077)' in m.FETCH
    assert 'stream.read(1048576)' in source and '134217728' in source
    assert 'EXACT_PUBLIC_PACKAGE_HASH_AND_IDENTITY_REQUIRED' in source
    assert 'PUBLIC_PACKAGE_DESTINATION_DRIFT' in source


def local_copy_function():
    # Exercise the exact streaming function as an ordinary local test user;
    # only the production root-UID predicate admits this test user's UID too.
    module = load('toolchain'); tree = ast.parse((HERE / 'toolchain.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'copy_public_package')
    class TestOwner(ast.NodeTransformer):
        def visit_Compare(self, value):
            self.generic_visit(value)
            if len(value.ops) == 1 and isinstance(value.ops[0], ast.Eq) and isinstance(value.left, ast.Attribute) and value.left.attr == 'st_uid' and isinstance(value.comparators[0], ast.Constant) and value.comparators[0].value == 0:
                return ast.copy_location(ast.Compare(left=value.left, ops=[ast.In()], comparators=[ast.Set(elts=[ast.Constant(value=0), ast.Constant(value=os.geteuid())])]), value)
            return value
    unit = ast.fix_missing_locations(ast.Module(body=[TestOwner().visit(node)], type_ignores=[]))
    namespace = dict(vars(module)); exec(compile(unit, '<root-uid-adapted-streaming-test>', 'exec'), namespace)
    return namespace['copy_public_package']


def test_actual_stream_copy_above_old_16mib_limit():
    copy = local_copy_function(); size = 16 * 1024**2 + 37
    with tempfile.TemporaryDirectory(prefix='stream-test-', dir=HERE) as raw:
        root = Path(raw).resolve(); source = root / 'public.deb'; target = root / 'staged.deb'
        body = (b'public-package-data-' * ((size // 20) + 1))[:size]; source.write_bytes(body); source.chmod(0o600)
        assert len(body) == size
        copy(source, target, hashlib.sha256(body).hexdigest(), size)
        assert target.read_bytes() == body and target.stat().st_size > 16 * 1024**2


def test_stream_copy_rejects_wrong_hash_and_symlink():
    copy = local_copy_function()
    with tempfile.TemporaryDirectory(prefix='stream-test-', dir=HERE) as raw:
        root = Path(raw).resolve(); source = root / 'public.deb'; source.write_bytes(b'public'); source.chmod(0o600)
        with pytest.raises(RuntimeError, match='EXACT_PUBLIC_PACKAGE_HASH_AND_IDENTITY_REQUIRED'): copy(source, root / 'wrong.deb', '0' * 64, 6)
        link = root / 'linked.deb'; link.symlink_to(source)
        with pytest.raises(RuntimeError, match='BOUNDED_PUBLIC_PACKAGE_COPY_REQUIRED'): copy(link, root / 'never.deb', hashlib.sha256(b'public').hexdigest(), 6)
        assert not (root / 'never.deb').exists()


def test_toolchain_network_split_and_no_business_mount_or_api_entrypoint():
    source = (HERE / 'toolchain.py').read_text()
    assert "'--network', 'bridge'" in source and "'--network=none'" in source and "'--network', 'none'" in source
    assert "'--entrypoint', '/usr/bin/env'" in source and "'--no-healthcheck'" in source
    assert "'type=bind,src=' + str(data) + ',dst=/out'" in source
    assert 'data = work / \'fetch-data\'' in source
    assert 'EXACT_DATAFREE_FETCH_CONTAINER_REQUIRED' in source and 'OFFLINE_NO_CREDENTIAL_OR_DATA_MOUNTS_REQUIRED' in source
    assert 'docker\', \'stop' not in source and 'docker\', \'start' not in source and 'docker\', \'rename' not in source


def test_engine_canary_uses_real_cjk_and_real_h264_encode():
    m = load('toolchain')
    assert 'NotoSansCJK-Regular.ttc' in m.PROBE and 'index=2' in m.PROBE and 'ImageFont.Layout.BASIC' in m.PROBE
    assert "'libx264'" in m.PROBE and "'-protocol_whitelist','file,pipe'" in m.PROBE and "'yuv420p'" in m.PROBE
    assert "'/usr/bin/ffprobe'" in m.PROBE and 'EXACT_H264_MP4_CANARY_REQUIRED' in m.PROBE
    assert 'backend_inventory_sha256' in m.PROBE and 'TOOLCHAIN_MUST_NOT_CHANGE_408_BACKEND_FILES' in (HERE / 'toolchain.py').read_text()


def test_bad_tool_hash_denied_before_loading_server_or_writing():
    m = load('toolchain')
    class NoServer:
        def __getattr__(self, name): pytest.fail('invalid source must not load server')
    with pytest.raises(RuntimeError, match='EXACT_TOOLCHAIN_TOOL_REQUIRED'): m.run(NoServer(), '0' * 64, b'changed')


def test_wrapper_reproduces_both_exact_modules_without_execution():
    maker = load('make_toolchain'); pf = (HERE / 'preflight.py').read_bytes(); tool = (HERE / 'toolchain.py').read_bytes()
    command, pins = maker.generate(pf, tool); again, second = maker.generate(pf, tool)
    assert (command, pins) == (again, second)
    match = re.search(r'base64.b64decode\(([^,]+),validate=True\)', command)
    data = json.loads(zlib.decompress(base64.b64decode(ast.literal_eval(match[1]), validate=True)))
    assert data['preflight'].encode() == pf and data['toolchain'].encode() == tool
    assert hashlib.sha256(command.encode()).hexdigest() == pins['command_sha256']
    assert pins['executed'] is False and pins['production_or_host_installation'] is False
    assert "sudo python3 -I -S -B" in command and len(command.encode()) < 24000
