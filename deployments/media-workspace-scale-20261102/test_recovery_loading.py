"""Fresh-process recovery loading, synthetic stopped containers only."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('scale_recovery_loading_test',HERE/'release.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def fixture(monkeypatch):
    runtime={'id':'1'*64,'config':'2'*64,'image':'sha256:'+'3'*64,'restart':0,'started':'2026-11-01T19:00:56Z'}
    original={'Id':runtime['id'],'State':{'Running':False},'runtime':dict(runtime)}
    inventory={**r.ORIGINAL_BACKEND_HASHES,**{f'synthetic/{n}.py':f'{n:064x}' for n in range(417)}}
    calls=[]
    def no_exec(*args): raise AssertionError('STOPPED_ORIGINAL_MUST_NOT_EXEC')
    def source_boundary(info,expected):
        assert info is original and info['State']['Running'] is False and expected==inventory
        calls.append('stopped-source-overlay-verified')
    retained=SimpleNamespace()
    flow=SimpleNamespace(m=SimpleNamespace(inspect=lambda identity:original,runtime=lambda info:info['runtime'],inventory=no_exec),source_boundary=source_boundary,retained=retained)
    marker=object();wrapper=SimpleNamespace(pf=SimpleNamespace(dependencies=lambda:(marker,flow,inventory)))
    fixtures=ModuleType('_scale_recovery_fixture');fixtures.wrapper=wrapper
    monkeypatch.setitem(sys.modules,'_scale_recovery_fixture',fixtures)
    pf=SimpleNamespace(HOST='synthetic-host',OLD=Path('/synthetic/old'),ROOT=Path('/synthetic'),
        HELPER='a'*64,STATIC_SOURCE='b'*40,SOURCE='c'*40,FRONTEND='d'*12,REVISION='synthetic-head',
        MANIFEST='e'*64,PAYLOAD='f'*64,PREFLIGHT='1'*64,PREPARED='2'*64,DEPLOYED='3'*64,
        RUNTIME=runtime,PUBLIC=Path('/synthetic/public'),_CACHE=None)
    code=("from _scale_recovery_fixture import wrapper\n"
        f"SOURCE_SHA={pf.STATIC_SOURCE!r}\nBASE_SOURCE={pf.SOURCE!r}\nFRONTEND={pf.FRONTEND!r}\nHEAD={pf.REVISION!r}\n"
        "def Release(args):return wrapper\ndef validate_prepared(*args):pass\n").encode()
    deployed={'stage':'GOOGLE_ONBOARDING_MOBILE_STATIC_DEPLOYED','source_sha':pf.STATIC_SOURCE,'backend_source_sha':pf.SOURCE,
        'frontend_version':pf.FRONTEND,'runtime':runtime,'public_root':str(pf.PUBLIC),'prepared_sha256':pf.PREPARED,
        **{key:True for key in ('all162_rows_preserved','static_only','content_security_policy_unchanged','old_hashed_assets_preserved')},
        **{key:False for key in ('database_writes','schema_changes','container_restarts','permissions_changes','environment_changes','provider_or_publication_actions')}}
    contents={pf.OLD/'release.py':(pf.HELPER,code),pf.OLD/'prepared.json':(pf.PREPARED,b'{}'),pf.OLD/'deployed.json':(pf.DEPLOYED,json.dumps(deployed).encode())}
    def read(path,sha,*args):
        expected,body=contents[path];assert sha==expected;calls.append(('read',path.name));return body
    pf.read=read
    monkeypatch.setattr(r.os,'geteuid',lambda:0);monkeypatch.setattr(r.socket,'gethostname',lambda:pf.HOST)
    return pf,flow,inventory,original,deployed,contents,calls


def test_recovery_loader_accepts_exact_stopped_original_without_docker_exec(monkeypatch):
    pf,flow,inventory,original,deployed,contents,calls=fixture(monkeypatch)
    value=r._recovery_dependencies(pf)
    assert value[1] is flow and value[2]==inventory
    assert 'stopped-source-overlay-verified' in calls and pf._CACHE[:3]==value
    assert original['State']['Running'] is False


@pytest.mark.parametrize('change',['runtime','inventory','receipt','source'])
def test_recovery_loader_rejects_changed_runtime_inventory_parent_receipt_or_source(monkeypatch,change):
    pf,flow,inventory,original,deployed,contents,calls=fixture(monkeypatch)
    if change=='runtime':original['runtime']['config']='9'*64
    elif change=='inventory':inventory['services/media_workspace.py']='0'*64
    elif change=='receipt':
        deployed['permissions_changes']=True
        contents[pf.OLD/'deployed.json']=(pf.DEPLOYED,json.dumps(deployed).encode())
    else:flow.source_boundary=lambda *args:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_STOPPED_SOURCE_DRIFT'))
    with pytest.raises(RuntimeError):r._recovery_dependencies(pf)
    assert pf._CACHE is None and original['State']['Running'] is False


@pytest.mark.parametrize('phase',['prepare','activate','recover'])
def test_phase_loader_uses_recovery_only_for_explicit_recover(monkeypatch,phase):
    fixture_module=ModuleType('_scale_load_phase_fixture');calls=[]
    retained=SimpleNamespace();flow=SimpleNamespace(retained=retained)
    def strict():calls.append('strict-live-inventory');raise RuntimeError('STOPPED_ORIGINAL_CANNOT_EXEC')
    fixture_module.strict=strict
    monkeypatch.setitem(sys.modules,'_scale_load_phase_fixture',fixture_module)
    monkeypatch.setattr(r,'protected_read',lambda *args:b'from _scale_load_phase_fixture import strict\ndependencies=strict\n')
    def recovery(pf):calls.append('validated-stopped-source');return None,flow,{'exact':'inventory'}
    monkeypatch.setattr(r,'_recovery_dependencies',recovery)
    args=SimpleNamespace(release=Path('/synthetic'),phase=phase)
    if phase=='recover':
        result=r._load(args);assert result[1] is flow and calls==['validated-stopped-source']
    else:
        with pytest.raises(RuntimeError,match='STOPPED_ORIGINAL_CANNOT_EXEC'):r._load(args)
        assert calls==['strict-live-inventory']
