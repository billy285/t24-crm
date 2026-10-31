"""Deterministic backend-only package/scope gates on synthetic local sources."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('diag_exact_package_test',HERE/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
REAL_SUMMARY=json.loads((HERE.parents[1]/'outputs/meta-oauth-diagnostics-20261101/preflight-summary.json').read_bytes())

@pytest.fixture
def package(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);before={};after={}
    for name in b.r.SOURCE_FILES|{'app/frontend/src/preserved.ts','app/backend/main.py'}:
        path=Path(name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('SYNTHETIC '+name).encode());after[name]=b.H(path.read_bytes())
        if name not in b.r.TEST_FILES:before[name]=b.H(('BEFORE '+name).encode()) if name.startswith('app/backend/') and name!='app/backend/main.py' else after[name]
    monkeypatch.setattr(b,'inventory',lambda ref:dict(before if ref==b.r.BASE_SOURCE else after))
    freeze={'source_sha':b.r.SOURCE_SHA,'frontend_version':b.r.FRONTEND,'baseline_source_sha':b.r.BASE_SOURCE,'schema_revision':b.r.REVISION,'files':{name:after[name] for name in b.r.SOURCE_FILES}}
    for key in ('database_migration','frontend_changed','nginx_changed','runtime_environment_changed','production_seed_rows'):freeze[key]=False
    path=Path('outputs/meta-oauth-diagnostics-20261101/application-freeze.json');path.parent.mkdir(parents=True);path.write_text(json.dumps(freeze));monkeypatch.setattr(b.r,'APPLICATION_FREEZE_SHA',b.H(path.read_bytes()))
    value=json.loads(json.dumps(REAL_SUMMARY));value['backend_changed_before']={name:before['app/backend/'+name] for name in b.r.BACKEND_FILES};return value,before,after


def test_payload_exact_two_python_members_no_static_secret_test_or_data(package):
    first,manifest=b.build(package[0]);second,again=b.build(package[0]);assert first==second and manifest==again
    with tarfile.open(fileobj=io.BytesIO(first),mode='r:gz') as archive:
        names={x.name for x in archive};assert names=={'backend/'+name for name in b.r.BACKEND_FILES} and len(names)==2
    assert manifest['frontend_changed'] is manifest['nginx_changed'] is manifest['runtime_environment_changed'] is manifest['database_migration'] is False
    assert manifest['protected_source_inventory']['app/frontend/src/preserved.ts']==package[1]['app/frontend/src/preserved.ts']


@pytest.mark.parametrize('kind',['extra_source','missing_change','local_change','untracked_frontend','freeze','baseline','symlink','summary'])
def test_package_refuses_any_unreviewed_app_or_baseline_change(package,kind):
    value,before,after=package;runtime=next(iter(b.r.BACKEND_FILES));path=Path('app/backend/'+runtime)
    if kind=='extra_source':after['app/backend/unapproved.py']='0'*64
    if kind=='missing_change':after[str(path)]=before[str(path)]
    if kind=='local_change':path.write_text('unreviewed')
    if kind=='untracked_frontend':Path('app/frontend/src/untracked.ts').write_text('unreviewed')
    if kind=='freeze':Path('outputs/meta-oauth-diagnostics-20261101/application-freeze.json').write_text('{}')
    if kind=='baseline':value['backend_changed_before'][runtime]='0'*64
    if kind=='symlink':path.rename(path.with_suffix('.other'));path.symlink_to(path.with_suffix('.other').resolve())
    if kind=='summary':value['meta_enabled_configured']=False
    with pytest.raises(RuntimeError):b.build(value)
