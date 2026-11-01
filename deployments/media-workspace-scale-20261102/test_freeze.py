"""Guard the final app/build freeze; synthetic filesystem only."""
import importlib.util,json,sys
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from synthetic import summary as synthetic_summary
spec=importlib.util.spec_from_file_location('scale_freezer_tests',HERE/'freeze.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    b=f.b;tools=tmp_path/'tools';tools.mkdir();monkeypatch.setattr(f,'HERE',tools);monkeypatch.setattr(b,'ROOT',tmp_path)
    names={'app/backend/'+name for name in b.BACKEND_FILES}|{'app/frontend/src/Media.tsx','app/frontend/tests/media.test.mjs'}
    monkeypatch.setattr(b,'SOURCE_FILES',frozenset(names));before={};after={}
    for name in names:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('SYNTHETIC '+name);after[name]=b.H(path.read_bytes())
        if name.startswith('app/backend/'):before[name]=b.H(('OLD '+name).encode())
    monkeypatch.setattr(b,'BACKEND_BEFORE',{name:before['app/backend/'+name] for name in b.BACKEND_FILES})
    monkeypatch.setattr(b,'PREFLIGHT_SHA','e'*64)
    monkeypatch.setattr(b,'inventory',lambda ref:dict(before if ref==b.APP_BASELINE else after))
    source='a'*40;version='b'*12
    monkeypatch.setattr(b,'frontend_version',lambda:version)
    static={'index.html':b'SYNTHETIC','app-version.json':json.dumps({'version':version}).encode()};monkeypatch.setattr(b,'read_static',lambda path:dict(static))
    def git(*args,**kw):return (source+'\n').encode() if args[1]=='--verify' else b'SAME_APP_TREE'
    monkeypatch.setattr(b,'git',git)
    (tools/'release.py').write_text('SOURCE_SHA=None\nFRONTEND=None\nAPPLICATION_FREEZE_SHA=None\nACTUAL_PREFLIGHT_SHA=None\nFINAL_BACKEND_HASHES={}\n')
    (tools/'build_payload.py').write_text('SOURCE_SHA=None\nFRONTEND=None\nAPPLICATION_FREEZE_SHA=None\nPREFLIGHT_SHA=None\nBACKEND_AFTER={}\n')
    return source,synthetic_summary(b),tmp_path/'dist',before,after,static

def test_freeze_only_exact_committed_application_build_and_scope_fills_explicit_pins(fixture):
    source,summary,dist,before,after,static=fixture;result=f.freeze(source,summary,dist)
    receipt=f.HERE/'application-freeze.json';value=json.loads(receipt.read_bytes())
    assert result['source_sha']==source and result['application_freeze_sha256']==f.H(receipt.read_bytes()) and receipt.stat().st_mode&0o777==0o600
    assert value['files']==after and value['preflight_sha256']==summary['sha256'] and value['database_migration'] is False
    namespace={};exec((f.HERE/'release.py').read_text(),namespace)
    assert namespace['SOURCE_SHA']==source and namespace['ACTUAL_PREFLIGHT_SHA']==summary['sha256'] and namespace['FINAL_BACKEND_HASHES']==result['backend_after']
    assert result['deployment_performed'] is False and result['provider_requests'] is False and result['database_writes'] is False
    with pytest.raises(RuntimeError,match='FRESH_APPLICATION_FREEZE_REQUIRED'):f.freeze(source,summary,dist)

@pytest.mark.parametrize('attack',['unreviewed_file','missing_file','dirty_source','wrong_build','wrong_preflight','permission_claim','different_commit','duplicate_pin'])
def test_drift_prevents_any_publishable_freeze(fixture,monkeypatch,attack):
    source,summary,dist,before,after,static=fixture;b=f.b
    if attack=='unreviewed_file':after['app/backend/finance.py']='f'*64
    if attack=='missing_file':after.pop(next(iter(after)))
    if attack=='dirty_source':(b.ROOT/'app/frontend/src/Media.tsx').write_text('UNREVIEWED')
    if attack=='wrong_build':static['app-version.json']=b'{"version":"incorrect"}'
    if attack=='wrong_preflight':summary['sha256']='unreviewed'
    if attack=='permission_claim':summary['permissions_changed']=True
    if attack=='different_commit':monkeypatch.setattr(b,'git',lambda *a,**kw:b'c'*40)
    if attack=='duplicate_pin':
        path=f.HERE/'release.py';path.write_text(path.read_text()+'SOURCE_SHA=None\n')
    with pytest.raises((RuntimeError,KeyError)):f.freeze(source,summary,dist)
    assert not(f.HERE/'application-freeze.json').exists()
