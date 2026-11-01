"""Fresh-process recovery uses exact current stopped source, never Docker exec."""
import importlib.util,json,sys
from pathlib import Path
from types import ModuleType,SimpleNamespace
import pytest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_month_recovery_test',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def fixture(monkeypatch):
    original={'Id':r.CURRENT_RUNTIME['id'],'State':{'Running':False},'runtime':dict(r.CURRENT_RUNTIME)}
    inventory={**{k:v for k,v in r.ORIGINAL_BACKEND_HASHES.items() if v is not None},**{f'synthetic/{n}.py':f'{n:064x}' for n in range(419-sum(v is not None for v in r.ORIGINAL_BACKEND_HASHES.values()))}}
    calls=[]
    def no_exec(*args):raise AssertionError('STOPPED_SOURCE_CANNOT_EXEC')
    def boundary(info,expected):
        assert info is original and info['State']['Running'] is False and expected==inventory
        calls.append('exact-stopped-overlay')
    flow=SimpleNamespace(m=SimpleNamespace(inspect=lambda identity:original,runtime=lambda info:info['runtime'],inventory=no_exec),source_boundary=boundary,retained=SimpleNamespace())
    module=ModuleType('_month_loader_fixture');module.flow=flow;module.inventory=inventory
    monkeypatch.setitem(sys.modules,'_month_loader_fixture',module)
    code=("from _month_loader_fixture import flow,inventory\n"+f"SOURCE={r.BASE_SOURCE!r}\nFRONTEND={r.BASE_FRONTEND!r}\nRUNTIME={r.CURRENT_RUNTIME!r}\n"+"def dependencies():return object(),flow,inventory\n").encode()
    monkeypatch.setattr(r,'protected_read',lambda path,sha:code)
    return code,module,flow,original,calls

def test_recovery_loads_exact_stopped_current_parent_without_executing_it(monkeypatch):
    _,module,flow,original,calls=fixture(monkeypatch)
    result=r._load(SimpleNamespace(phase='recover',release=Path('/synthetic')))
    assert result[1] is flow and result[2]==module.inventory and calls==['exact-stopped-overlay']

@pytest.mark.parametrize('attack',['wrong_source','wrong_frontend','wrong_runtime','short_inventory','changed_service','unknown_original','runtime_changed','source_overlay_changed','new_source_preexists'])
def test_recovery_rejects_unpinned_parent_or_inventory_or_stopped_runtime(monkeypatch,attack):
    code,module,flow,original,calls=fixture(monkeypatch)
    if attack=='wrong_source':code=code.replace(r.BASE_SOURCE.encode(),b'a'*40)
    elif attack=='wrong_frontend':code=code.replace(r.BASE_FRONTEND.encode(),b'b'*12)
    elif attack=='wrong_runtime':code=code.replace(r.CURRENT_RUNTIME['id'].encode(),b'c'*64)
    elif attack=='short_inventory':module.inventory.pop('synthetic/1.py')
    elif attack=='changed_service':module.inventory['services/media_workspace.py']='d'*64
    elif attack=='unknown_original':original['Id']='e'*64
    elif attack=='runtime_changed':original['runtime']['restart']=1
    elif attack=='new_source_preexists':module.inventory['services/media_monthly_meta.py']=None
    else:flow.source_boundary=lambda *args:r.need(False,'STOPPED_SOURCE_DRIFT')
    monkeypatch.setattr(r,'protected_read',lambda path,sha:code)
    with pytest.raises(RuntimeError):r._load(SimpleNamespace(phase='recover',release=Path('/synthetic')))
