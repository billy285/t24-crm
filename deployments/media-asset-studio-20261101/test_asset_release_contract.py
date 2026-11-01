import ast
import importlib.util
import os
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location('asset_specific_release_contract', HERE / 'release.py')
    r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r); return r


def nginx(r, count=6):
    return b'root /old-reviewed-static;\n' + (b'    add_header Content-Security-Policy "' + r.CSP_BEFORE.encode() + b'" always;\n') * count + b'    access_log off;\n'


def test_only_exact_csp_media_src_and_static_root_change_and_reverse(monkeypatch):
    r = load(); body = nginx(r); monkeypatch.setattr(r, 'NGINX_BEFORE_SHA', r.H(body))
    changed = r.next_nginx(body, '/old-reviewed-static', '/new-reviewed-static')
    assert changed == body.replace(b'/old-reviewed-static', b'/new-reviewed-static', 1).replace(r.CSP_BEFORE.encode(), r.CSP_AFTER.encode())
    assert r.nginx_policy_count(changed, r.CSP_AFTER.encode()) == 6
    assert changed.replace(b'/new-reviewed-static', b'/old-reviewed-static', 1).replace(r.CSP_AFTER.encode(), r.CSP_BEFORE.encode()) == body
    assert r.CSP_AFTER == r.CSP_BEFORE.replace("img-src 'self' data: https:;", "img-src 'self' data: https:; media-src 'self' blob:;", 1)


@pytest.mark.parametrize('attack', ['zero', 'too_many', 'foreign_policy', 'foreign_csp_header', 'other_config_changed', 'duplicate_root'])
def test_any_unreviewed_csp_nginx_scope_is_rejected(monkeypatch, attack):
    r = load(); body = nginx(r)
    monkeypatch.setattr(r, 'NGINX_BEFORE_SHA', r.H(body))
    if attack == 'zero': body = nginx(r, 0)
    if attack == 'too_many': body = nginx(r, 13)
    if attack == 'foreign_policy': body = body.replace(r.CSP_BEFORE.encode(), b"default-src *", 1)
    if attack == 'foreign_csp_header': body += b'add_header Content-Security-Policy "default-src *" always;\n'
    if attack == 'other_config_changed': body = body.replace(b'access_log off', b'access_log on')
    if attack == 'duplicate_root': body += b'root /old-reviewed-static;\n'
    if attack in {'zero','too_many','foreign_policy','foreign_csp_header'}:
        monkeypatch.setattr(r, 'NGINX_BEFORE_SHA', r.H(body))
    with pytest.raises(RuntimeError): r.next_nginx(body, '/old-reviewed-static', '/new-reviewed-static')


def test_updated_nginx_protection_reverses_both_file_and_active_dump(monkeypatch, tmp_path):
    r = load(); before = nginx(r); after = before.replace(b'/old-reviewed-static', b'/new-reviewed-static').replace(r.CSP_BEFORE.encode(), r.CSP_AFTER.encode())
    path = tmp_path / 'nginx.conf'; path.write_bytes(after)
    active_before = b'# configuration file:\n' + before; active_after = b'# configuration file:\n' + after
    obj = SimpleNamespace(proof={'public_root':'/old-reviewed-static','nginx_sha256':r.H(before),'active_nginx_sha256':r.H(active_before)},
        public=Path('/new-reviewed-static'), m=SimpleNamespace(NGINX=path, run=lambda *a:active_after))
    assert r.Methods.nginx(obj, updated=True) == r.H(active_after)
    path.write_bytes(after.replace(b'access_log off', b'access_log on'))
    with pytest.raises(RuntimeError, match='OTHER_NGINX_BYTES_CHANGED'): r.Methods.nginx(obj, updated=True)


def test_offline_asset_worker_flag_is_used_in_actual_prepare_path():
    r = load(); origin = ['docker','run','--network','none','image']
    cls = SimpleNamespace(offline_args=lambda *a:list(origin)); obj = SimpleNamespace(ctx=SimpleNamespace(module=SimpleNamespace(OperationsMethods=cls)))
    args = r.Methods.offline_args(obj, '/synthetic', 'image')
    assert args == ['docker','run','--network','none','-e','T24_MEDIA_ASSET_WORKER_ENABLED=false','image']
    text = (HERE / 'release.py').read_text(); tree = ast.parse(text); methods = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Methods')
    prepare = ast.get_source_segment(text, next(n for n in methods.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare'))
    assert 'command=self.offline_args(data,image)' in prepare
    assert 'renderer_canary.py' in prepare and 'FINAL_ASSET_RENDERER_OFFLINE_VERIFIED' in prepare


def test_actual_asset_proof_path_and_current155_packet_are_explicit():
    r = load(); source = (HERE / 'release.py').read_text()
    assert "Path('/opt/t24-crm/releases/media-asset-studio-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json')" in source
    assert 'media-ops-monthly-flow-preflight-' not in source
    assert "p['rows']['media_monthly_workflows']['count']==1" in source
    assert 'only_static_root_changes' not in source


def test_asset_probe_keeps_all_existing_monthly_routes_and_denies_roles_before_sql():
    r = load(); code = r.Methods.asset_probe(None); ast.parse(code)
    assert len(r.ASSET_ROUTES) == 9 and len(r.MONTHLY_ROUTES) + len(r.EXISTING_MONTHLY_ROUTES) == 15
    assert "T24_MEDIA_ASSET_WORKER_ENABLED" in code and "'false'" in code
    assert 'NONOWNER_MUST_NOT_QUERY_SQL' in code and "('admin','ops','sales','finance')" in code
    assert 'CONTENT_SECURITY_POLICY' in code and 'iter_route_contexts' in code


def test_app_build_capture_persists_bounded_public_log_and_exact_exit(tmp_path):
    r=load();path=tmp_path/'public-build.log'
    result=r.capture_public_build([sys.executable,'-I','-B','-c',"print('public build failed');raise SystemExit(7)"],path)
    assert result['exit_code']==7 and result['build_daemon_result_known'] is True
    assert result['log_sha256']==r.H(path.read_bytes()) and result['public_tail']=='public build failed\n'
    assert stat.S_IMODE(path.stat().st_mode)==0o600


def test_app_build_capture_limit_stops_client_without_known_daemon_claim(tmp_path):
    r=load();path=tmp_path/'bounded-build.log'
    result=r.capture_public_build([sys.executable,'-I','-B','-c',"print('x'*10000)"],path,maximum=101)
    assert result['log_bytes']==path.stat().st_size==101
    assert result['build_daemon_result_known'] is False
    assert result['client_status']=='BUILD_PUBLIC_LOG_LIMIT_RESULT_UNKNOWN'


def test_app_build_capture_env_is_credential_absent_and_legacy_client_only(tmp_path,monkeypatch):
    r=load();path=tmp_path/'clean-build.log';monkeypatch.setenv('FAKE_CREDENTIAL_MUST_NOT_PASS','secret')
    result=r.capture_public_build([sys.executable,'-I','-B','-c',"import os,json;print(json.dumps(dict(os.environ),sort_keys=True))"],path)
    assert result['exit_code']==0 and 'FAKE_CREDENTIAL_MUST_NOT_PASS' not in path.read_text()
    assert '"DOCKER_BUILDKIT": "0"' in path.read_text()
    source=(HERE/'release.py').read_text()
    assert "'--network=none','--pull=false'" in source and "app-build-public.log" in source


def test_app_build_client_exit_cannot_hide_child_retaining_stdout_deadline(tmp_path):
    r=load();started=time.monotonic()
    script="import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])"
    result=r.capture_public_build([sys.executable,'-I','-B','-c',script],tmp_path/'inherited-pipe.log',timeout=.15)
    assert time.monotonic()-started<3
    assert result['client_status']=='BUILD_CLIENT_TIMEOUT_RESULT_UNKNOWN' and result['build_daemon_result_known'] is False
