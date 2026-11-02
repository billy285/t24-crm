"""Synthetic filesystem/runtime attacks against the actual static-only release."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('mobile_static_release_tested', HERE / 'release.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


@pytest.fixture(autouse=True)
def pins(monkeypatch):
    for key, value in {'PREFLIGHT_CODE_SHA': '1' * 64, 'PREFLIGHT_SHA': '2' * 64,
                       'APPLICATION_FREEZE_SHA': '3' * 64, 'SOURCE_SHA':'a'*40, 'FRONTEND':'a'*12, 'CHANGED_SOURCE_HASHES': {name:'4'*64 for name in r.FILES}}.items():
        monkeypatch.setattr(r, key, value)


def prepared():
    return {'stage': 'MEDIA_OPS_UI_REFINED_STATIC_PREPARED', 'source_sha': r.SOURCE_SHA,
            'backend_source_sha': r.BACKEND_SOURCE, 'frontend_version': r.FRONTEND,
            'manifest_sha256': '5' * 64, 'payload_sha256': '6' * 64,
            'preflight_sha256': r.PREFLIGHT_SHA,
            'public_root': '/var/www/t24-crm-public/' + r.SCOPE + '-' + r.SOURCE_SHA[:12] + '-20261102',
            'public_inventory_sha256': '7' * 64, 'nginx_next_sha256': '8' * 64,
            'boundary': {'runtime': copy.deepcopy(r.RUNTIME), **{key: True for key in (
                'original169_schema_preserved', 'backend_source_unchanged', 'private_boundary_preserved',
                'credentials_preserved', 'content_security_policy_unchanged')}, **{key: '9' * 64 for key in (
                'schema_sha256', 'environment_sha256', 'ordered_environment_sha256')}},
            'static_only': True, **{key: False for key in ('database_writes', 'container_restarts',
            'schema_changes', 'permissions_changes', 'provider_or_publication_actions')}}


def test_exact_root_substitution_preserves_csp_and_full_reverse_equality():
    old, new = Path('/public/original'), Path('/public/mobile')
    body = b'server { root /public/original;\nadd_header Content-Security-Policy "unchanged" always;\nproxy_pass http://127.0.0.1:8000; }\n'
    updated = r.changed_nginx(body, old, new, r.H(body))
    assert updated.replace(b'root /public/mobile;', b'root /public/original;', 1) == body
    assert b'Content-Security-Policy "unchanged"' in updated


@pytest.mark.parametrize('attack', ['wrong_hash', 'duplicate_root', 'missing_root', 'already_new', 'csp_change'])
def test_unknown_nginx_or_any_other_bytes_are_rejected(attack):
    original = b'root /public/old;\nCSP=original\n'
    body, sha = original, r.H(original)
    if attack == 'wrong_hash': sha = '0' * 64
    elif attack == 'duplicate_root': body = original + original
    elif attack == 'missing_root': body = b'root /other;\n'
    elif attack == 'already_new': body = original + b'root /public/new;'
    else: body = original.replace(b'CSP=original', b'CSP=changed')
    with pytest.raises(RuntimeError): r.changed_nginx(body, Path('/public/old'), Path('/public/new'), sha)


def test_prepared_requires_actual_static_only_scope(pins):
    r.validate_prepared(prepared(), '5' * 64, '6' * 64, r.PREFLIGHT_SHA)


@pytest.mark.parametrize('field,value', [('source_sha', '0' * 40), ('backend_source_sha', '0' * 40),
    ('frontend_version', '0' * 12), ('manifest_sha256', '0' * 64), ('payload_sha256', '0' * 64),
    ('preflight_sha256', '0' * 64), ('public_root', '/unknown'), ('public_inventory_sha256', 'bad'),
    ('static_only', False), ('database_writes', True), ('container_restarts', True),
    ('schema_changes', True), ('permissions_changes', True), ('provider_or_publication_actions', True)])
def test_prepared_rejects_scope_hash_or_any_business_mutation_claim(pins, field, value):
    v = prepared(); v[field] = value
    with pytest.raises(RuntimeError): r.validate_prepared(v, '5' * 64, '6' * 64, r.PREFLIGHT_SHA)


@pytest.mark.parametrize('key', ['runtime', 'original169_schema_preserved'])
def test_prepared_rejects_runtime_or_row_preservation_drift(pins, key):
    v = prepared(); v['boundary'][key] = {} if key == 'runtime' else False
    with pytest.raises(RuntimeError): r.validate_prepared(v, '5' * 64, '6' * 64, r.PREFLIGHT_SHA)


@pytest.mark.parametrize('key', ['backend_source_unchanged', 'private_boundary_preserved',
    'credentials_preserved', 'content_security_policy_unchanged', 'schema_sha256',
    'environment_sha256', 'ordered_environment_sha256'])
def test_every_prepared_privacy_and_full_hash_protection_is_required(pins, key):
    v = prepared(); v['boundary'][key] = 'invalid' if key.endswith('_sha256') else False
    with pytest.raises(RuntimeError, match='ALL_STATIC_PREPARED_PROTECTIONS_REQUIRED'):
        r.validate_prepared(v, '5' * 64, '6' * 64, r.PREFLIGHT_SHA)


@pytest.fixture
def boundary_subject(tmp_path):
    value=r.Release.__new__(r.Release)
    db=tmp_path/'business.db';db.write_bytes(b'SYNTHETIC_NO_SQLITE_WRITES')
    nginx=tmp_path/'nginx.conf';nginx.write_bytes(b'root /public/old;\nCSP=unchanged\n')
    inventory={'main.py':'a'*64};tree={'index.html':'b'*64};definitions=[['table','example','example','CREATE TABLE example(id)']]
    info={'State':{'Running':True},'runtime':copy.deepcopy(r.RUNTIME)}
    credentials={key:{'path':key} for key in ('ops','google','meta_read','meta_legacy')}
    state={'env':('e'*64,'f'*64),'private':{'safe':True},'credentials':copy.deepcopy(credentials),'metadata':{'pragma_sha256':'d'*64,'sequence_exists':True},'schema':'c'*64,'definitions':copy.deepcopy(definitions),'inventory':copy.deepcopy(inventory),'tree':copy.deepcopy(tree),'business_heartbeat':0}
    c=SimpleNamespace(environment=lambda _:None,pf=SimpleNamespace(environment=lambda *_:state['env']),base=SimpleNamespace(c=SimpleNamespace(pins={},safe=SimpleNamespace(safe_private_boundary=lambda *_:state['private']))),definitions=lambda:state['definitions'],metadata=lambda:state['metadata'])
    m=SimpleNamespace(BUSINESS=db,NGINX=nginx,inspect=lambda _:info,runtime=lambda x:x['runtime'],inventory=lambda _:state['inventory'],credential_boundary=lambda:{'safe':True},schema_signature=lambda *_:state['schema'],tree=lambda _:state['tree'],run=lambda args,*_:nginx.read_bytes())
    value.ctx,value.m,value.inventory=c,m,inventory;value.pf=SimpleNamespace(credential_metadata=lambda _:state['credentials']);value.old_public,value.public=Path('/public/old'),Path('/public/new')
    value.proof={'environment_sha256':state['env'][0],'ordered_environment_sha256':state['env'][1],'private_boundary':{'safe':True},'credential_metadata':credentials,'credential_boundary':{'safe':True},'database_identity':[db.stat().st_dev,db.stat().st_ino],'schema_sha256':state['schema'],'table_definitions':definitions,'database_pragmas_sha256':state['metadata']['pragma_sha256'],'sequence_table_exists':True,'public_inventory_sha256':r.digest(tree),'nginx_sha256':r.H(nginx.read_bytes()),'active_nginx_sha256':r.H(nginx.read_bytes())}
    return value,state,info

def test_actual_boundary_preserves169_schema_and_never_reads_or_freezes_rows(boundary_subject):
    value,state,_=boundary_subject;before=value.m.BUSINESS.read_bytes();proof=value.boundary();state['business_heartbeat']+=1
    assert value.boundary()==proof and proof['original169_schema_preserved'] and proof['business_rows_read_or_frozen'] is False and value.m.BUSINESS.read_bytes()==before

@pytest.mark.parametrize('attack',['runtime','running','source','env','private','credential','schema','definitions','metadata','static','nginx'])
def test_actual_boundary_rejects_immutable_drift_before_static_switch(boundary_subject,attack):
    value,state,info=boundary_subject
    if attack=='runtime':info['runtime']['restart']+=1
    elif attack=='running':info['State']['Running']=False
    elif attack=='source':state['inventory']['main.py']='0'*64
    elif attack=='env':state['env']=('0'*64,'f'*64)
    elif attack=='private':state['private']={'safe':False}
    elif attack=='credential':state['credentials']['google']={'changed':True}
    elif attack=='schema':state['schema']='0'*64
    elif attack=='definitions':state['definitions'].append(['table','unknown','unknown','CREATE TABLE unknown(id)'])
    elif attack=='metadata':state['metadata']['pragma_sha256']='0'*64
    elif attack=='static':state['tree']['index.html']='0'*64
    else:value.m.NGINX.write_bytes(b'unknown config')
    with pytest.raises(RuntimeError):value.boundary()


@pytest.fixture
def flow(tmp_path, monkeypatch):
    value = r.Release.__new__(r.Release); value.root = tmp_path / 'release'; value.root.mkdir()
    value.old_public, value.public = tmp_path / 'old-public', tmp_path / 'new-public'
    nginx = tmp_path / 'nginx.conf'; old = ('root ' + str(value.old_public) + ';\nCSP=unchanged\n').encode(); nginx.write_bytes(old)
    state = {'calls': [], 'fail_public': False, 'active_body':old, 'fail_first_recovery_reload':False, 'reload_count':0}
    value.args = SimpleNamespace(review_sha256='1' * 64)
    value.proof = {'nginx_sha256': r.H(old)}
    next_body = r.changed_nginx(old, value.old_public, value.public, r.H(old))
    receipt = {'public_inventory_sha256': '2' * 64, 'nginx_next_sha256': r.H(next_body)}
    def write(path, data):
        body = data if isinstance(data, bytes) else r.encoded(data); path.write_bytes(body); state['calls'].append(('record', path.name)); return r.H(body)
    def replace(before, after):
        assert nginx.read_bytes() == before; nginx.write_bytes(after); state['calls'].append(('replace-root', after))
    def reload():
        state['calls'].append(('reload-nginx',));state['reload_count']+=1
        if state['fail_first_recovery_reload'] and state['reload_count']==2:raise RuntimeError('SYNTHETIC_RECOVERY_RELOAD_FAILED')
        state['active_body']=nginx.read_bytes()
    value.m = SimpleNamespace(NGINX=nginx, write=write, replace_nginx=replace,
        cleanup_nginx_temp=lambda *_:state['calls'].append(('clean-known-temp',)),
        retained=lambda: SimpleNamespace(reload_nginx=reload))
    value.reviewed = lambda: receipt
    def boundary(updated=False):
        assert nginx.read_bytes() == (next_body if updated else old)
        state['calls'].append(('boundary', updated)); return {'original169_schema_preserved': True}
    value.boundary = boundary
    def public(frontend=None):
        state['calls'].append(('public-read',frontend))
        assert state['active_body']==(old if frontend==r.BASE_FRONTEND else next_body)
        if state['fail_public'] and frontend!=r.BASE_FRONTEND:raise RuntimeError('SYNTHETIC_PUBLIC_VERSION_FAILED')
    value.public_check = public
    monkeypatch.setattr(r, 'protected', lambda path, *a, **kw: path.read_bytes())
    return value, state, old, next_body


def test_activation_changes_only_root_and_records_receipt_no_container_lifecycle(flow):
    value, state, _, new = flow; result = value.activate()
    assert value.m.NGINX.read_bytes() == new and result['all169_schema_preserved']
    assert result['container_restarts'] is result['database_writes'] is result['environment_changes'] is False
    assert [x[0] for x in state['calls']].count('replace-root') == 1


def test_failed_public_acceptance_automatically_restores_only_original_root(flow):
    value, state, old, _ = flow; state['fail_public'] = True
    with pytest.raises(RuntimeError, match='SYNTHETIC_PUBLIC_VERSION_FAILED'): value.activate()
    assert value.m.NGINX.read_bytes() == old
    assert [x[0] for x in state['calls']].count('replace-root') == 2
    result = json.loads((value.root / 'recovered.json').read_bytes())
    assert result['database_restored'] is result['container_restarts'] is False


def test_unknown_nginx_during_recovery_is_never_overwritten(flow):
    value, state, old, _ = flow; (value.root / 'nginx-before.conf').write_bytes(old)
    value.m.NGINX.write_bytes(b'UNKNOWN_OTHER_ADMIN_CHANGE')
    with pytest.raises(RuntimeError, match='UNKNOWN_NGINX_CONFIG_NOT_REPLACED'): value.recover()
    assert not any(x[0] == 'replace-root' for x in state['calls'])


def test_second_recovery_reloads_even_when_disk_already_old_after_reload_failure(flow):
    value,state,old,new=flow;state['fail_public']=True;state['fail_first_recovery_reload']=True
    with pytest.raises(RuntimeError,match='SYNTHETIC_RECOVERY_RELOAD_FAILED'):value.activate()
    assert value.m.NGINX.read_bytes()==old and state['active_body']==new
    assert not(value.root/'recovered.json').exists()
    result=value.recover()
    assert state['active_body']==old and state['reload_count']==3 and result['old_public_frontend_verified'] is True
    assert ('public-read',r.BASE_FRONTEND) in state['calls']


@pytest.mark.parametrize('unsafe',[False,True])
def test_retained_temp_cleanup_accepts_only_known_config_prefix_and_preserves_unknown(tmp_path,unsafe):
    import os,stat
    source=(HERE.parent/'stripe-history-reconciliation-20261018/release.py').read_text()
    tree=ast.parse(source);node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='cleanup_nginx_temp')
    nginx=tmp_path/'nginx.conf';old=b'root /public/old;';new=b'root /public/new;';nginx.write_bytes(old)
    scope='synthetic-navigation';temp=tmp_path/('.t24-'+scope+'-next');temp.write_bytes(b'UNKNOWN' if unsafe else new[:8]);temp.chmod(0o644)
    # The published function requires root ownership; the local fixture emulates
    # that UID while retaining actual inode, size, type and prefix checks.
    class RootOwnedTemp:
        def __fspath__(self):return str(temp)
        def exists(self):return temp.exists()
        def is_symlink(self):return temp.is_symlink()
        def lstat(self):
            row=temp.lstat();return SimpleNamespace(**{key:getattr(row,key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns')},st_uid=0)
        def unlink(self):return temp.unlink()
    class Parent:
        def __truediv__(self,name):assert name==temp.name;return RootOwnedTemp()
    context={'NGINX':SimpleNamespace(parent=Parent(),read_bytes=nginx.read_bytes),'SCOPE':scope,'os':os,'stat':stat,'need':r.need};exec(compile(ast.Module(body=[node],type_ignores=[]),'<retained-known-byte-temp-cleanup>','exec'),context)
    if unsafe:
        with pytest.raises(RuntimeError,match='UNKNOWN_NGINX_TEMP'):context['cleanup_nginx_temp'](old,new)
        assert temp.read_bytes()==b'UNKNOWN'
    else:context['cleanup_nginx_temp'](old,new);assert not temp.exists()


def test_release_run_calls_are_only_nginx_read_and_loopback_public_version():
    tree = ast.parse((HERE / 'release.py').read_text()); calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'run':
            assert isinstance(node.args[0], (ast.List,ast.Name))
            calls.append(ast.literal_eval(node.args[0].elts[0]) if isinstance(node.args[0],ast.List) else 'public-spa-header')
        assert not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {'run_migration', 'migrate', 'clone_config', 'docker_request'})
    assert calls == ['public-spa-header','nginx', 'curl']


def test_static_controller_never_invokes_live_row_or_backend_release_phases():
    source=(HERE/'release.py').read_text()
    for text in ('.rows(','.sample(','.immutable(','.shape(','.activate_candidate(','.environment_file(','.stop(','.start(','.migrate(','.worker_enable('):
        assert text not in source
    assert 'business_rows_read_or_frozen' in source
