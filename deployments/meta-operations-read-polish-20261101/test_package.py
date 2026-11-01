"""Synthetic local attacks against the exact four-file nonmigrating package."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

HERE=Path(__file__).resolve().parent
PROJECT_ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('read_polish_package_test',HERE/'build_payload.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


@pytest.fixture
def package(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path);before={};after={}
    for name in b.SOURCE_FILES|{'app/backend/preserved.py','app/frontend/src/preserved.ts'}:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);body=('SYNTHETIC '+name).encode();path.write_bytes(body);after[name]=b.H(body)
        before[name]=b.H(('OLD '+name).encode()) if name in b.SOURCE_FILES else after[name]
    monkeypatch.setattr(b,'BACKEND_BEFORE',{name:before['app/backend/'+name] for name in b.BACKEND_FILES})
    monkeypatch.setattr(b,'BACKEND_AFTER',{name:after['app/backend/'+name] for name in b.BACKEND_FILES})
    monkeypatch.setattr(b,'inventory',lambda ref:dict(before if ref==b.BASE_SOURCE else after));monkeypatch.setattr(b,'frontend_version',lambda:b.FRONTEND)
    def git(*args,**kwargs):
        if args[0]=='rev-parse':return (b.SOURCE_SHA+'\n').encode()
        if args[0]=='diff':return ('\0'.join(sorted(b.SOURCE_FILES))+'\0').encode()
        raise AssertionError('Unexpected Git command')
    monkeypatch.setattr(b,'git',git)
    summary=json.loads((PROJECT_ROOT/'outputs/meta-operations-read-polish-20261101/preflight-summary.json').read_text());summary['backend_changed_before']=b.BACKEND_BEFORE
    dist=tmp_path/'app/frontend/dist';dist.mkdir();(dist/'assets').mkdir();(dist/'index.html').write_text('<html>SYNTHETIC</html>');(dist/'assets/test.js').write_text('SYNTHETIC CHUNK');(dist/'app-version.json').write_text(json.dumps({'version':b.FRONTEND}))
    freeze={'source_sha':b.SOURCE_SHA,'frontend_version':b.FRONTEND,'baseline_source_sha':b.BASE_SOURCE,'baseline_frontend_version':b.BASE_FRONTEND,'schema_revision':b.SCHEMA_REVISION,'old_schema_revision':b.SCHEMA_REVISION,
        'files':{name:after[name] for name in b.SOURCE_FILES},'dist_inventory_sha256':b.static_inventory(b.read_static(dist)),**{key:True for key in b.TRUE_FLAGS},**{key:False for key in b.FALSE_FLAGS}}
    freeze_path=tmp_path/'freeze.json';freeze_path.write_bytes(b.encoded(freeze));args={'source_sha':b.SOURCE_SHA,'frontend':b.FRONTEND,'freeze_path':freeze_path,'freeze_sha':b.H(freeze_path.read_bytes()),'dist':dist}
    return summary,args,before,after,freeze


def test_exact_four_source_change_and_only_one_backend_module_plus_static_are_deterministic(package):
    summary,args,before,after,freeze=package;blob,manifest=b.build(summary,**args);second,again=b.build(summary,**args)
    assert blob==second and manifest==again and set(manifest['changed_source_files'])==b.SOURCE_FILES and len(b.SOURCE_FILES)==4
    assert manifest['schema_revision']==manifest['old_schema_revision']==b.SCHEMA_REVISION and manifest['additive_tables']==[]
    assert all(manifest[key] is True for key in b.TRUE_FLAGS) and all(manifest[key] is False for key in b.FALSE_FLAGS)
    assert manifest['backend_before']==b.BACKEND_BEFORE and manifest['backend_after']==b.BACKEND_AFTER
    assert manifest['protected_source_inventory']=={name:pin for name,pin in before.items() if name not in b.SOURCE_FILES}
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as stream:
        rows=stream.getmembers();assert len(rows)==len({row.name for row in rows})==4 and {row.name for row in rows}==set(manifest['files'])
        assert {row.name[8:] for row in rows if row.name.startswith('backend/')}==b.BACKEND_FILES
        assert all(row.name.startswith(('backend/','static/')) and not any(word in row.name for word in ('vendor/','tests/','.env','migration','requirements')) for row in rows)
        for row in rows:assert row.isfile() and row.uid==row.gid==row.mtime==0 and row.mode==0o644 and row.uname==row.gname=='' and b.H(stream.extractfile(row).read())==manifest['files'][row.name]


@pytest.mark.parametrize('attack',['extra_app','missing_change','deleted_old','new_source','local_source','untracked_frontend','baseline_hash','after_hash','source_pin','frontend_pin','freeze_pin','freeze_content','frozen_source','dist_version','dist_secret','dist_symlink','dist_root_symlink','dist_hardlink','qa_dist_mismatch','freeze_migration','freeze_execution','summary_execution','summary_environment','summary_tables','summary_source'])
def test_any_unreviewed_application_build_scope_or_preservation_claim_is_rejected(package,monkeypatch,attack):
    summary,args,before,after,freeze=package;root=b.ROOT
    if attack=='extra_app':after['app/backend/unapproved.py']='0'*64
    if attack=='missing_change':after['app/backend/services/meta_operations_provider.py']=before['app/backend/services/meta_operations_provider.py']
    if attack=='deleted_old':after.pop('app/backend/preserved.py')
    if attack=='new_source':before.pop('app/backend/services/meta_operations_provider.py')
    if attack=='local_source':(root/'app/backend/services/meta_operations_provider.py').write_text('UNREVIEWED')
    if attack=='untracked_frontend':(root/'app/frontend/src/untracked.ts').write_text('UNREVIEWED')
    if attack=='baseline_hash':monkeypatch.setattr(b,'BACKEND_BEFORE',{'services/meta_operations_provider.py':'0'*64});summary['backend_changed_before']=b.BACKEND_BEFORE
    if attack=='after_hash':monkeypatch.setattr(b,'BACKEND_AFTER',{'services/meta_operations_provider.py':'0'*64})
    if attack=='source_pin':args['source_sha']='0'*40
    if attack=='frontend_pin':args['frontend']='0'*12
    if attack=='freeze_pin':args['freeze_sha']='0'*64
    if attack=='freeze_content':args['freeze_path'].write_text('{}')
    if attack in {'frozen_source','freeze_migration','freeze_execution'}:
        if attack=='frozen_source':freeze['files']['app/backend/services/meta_operations_provider.py']='0'*64
        if attack=='freeze_migration':freeze['database_migration']=True
        if attack=='freeze_execution':freeze['operations_execution_enabled']=True
        args['freeze_path'].write_bytes(b.encoded(freeze));args['freeze_sha']=b.H(args['freeze_path'].read_bytes())
    if attack=='dist_version':(args['dist']/'app-version.json').write_text('{"version":"wrong"}')
    if attack=='dist_secret':(args['dist']/'runtime.env').write_text('SYNTHETIC SECRET')
    if attack=='dist_symlink':(args['dist']/'assets/link.js').symlink_to(args['dist']/'assets/test.js')
    if attack=='dist_root_symlink':
        actual=root/'original-dist';args['dist'].rename(actual);args['dist'].symlink_to(actual,target_is_directory=True)
    if attack=='dist_hardlink':os.link(args['dist']/'assets/test.js',root/'extra-hardlink')
    if attack=='qa_dist_mismatch':(args['dist']/'assets/test.js').write_text('UNREVIEWED BUILD')
    if attack=='summary_execution':summary['ops_execution_enabled']=True
    if attack=='summary_environment':summary['environment_sha256']='0'*64
    if attack=='summary_tables':summary['table_count']=149
    if attack=='summary_source':summary['source_sha']='0'*40
    with pytest.raises((RuntimeError,KeyError,OSError)):b.build(summary,**args)


def test_native_diff_must_exactly_match_full_archive_delta(package,monkeypatch):
    summary,args,*_=package;original=b.git
    monkeypatch.setattr(b,'git',lambda *a,**k:b'app/backend/unapproved.py\0' if a[0]=='diff' else original(*a,**k))
    with pytest.raises(RuntimeError,match='EXACT_FOUR_EXISTING_APPLICATION_DELTA_REQUIRED'):b.build(summary,**args)


@pytest.mark.parametrize('kind',['static','frontend','freeze','runtime'])
def test_concurrent_packaging_changes_are_detected_before_any_artifact_write(package,monkeypatch,kind):
    summary,args,*_=package
    if kind in {'static','freeze'}:
        original=b.read_static;calls=0
        def read(dist):
            nonlocal calls
            calls+=1;value=original(dist)
            if calls==2:
                if kind=='static':value['assets/test.js']=b'CHANGED'
                else:args['freeze_path'].write_text('{}')
            return value
        monkeypatch.setattr(b,'read_static',read)
    if kind=='frontend':
        values=iter([b.FRONTEND,'0'*12]);monkeypatch.setattr(b,'frontend_version',lambda:next(values))
    if kind=='runtime':
        original=b.local_bytes;calls=0
        def read(path,*a,**k):
            nonlocal calls
            body=original(path,*a,**k)
            if Path(path)==b.ROOT/'app/backend/services/meta_operations_provider.py':
                calls+=1
                if calls==2:return b'CHANGED RUNTIME'
            return body
        monkeypatch.setattr(b,'local_bytes',read)
    with pytest.raises(RuntimeError):b.build(summary,**args)
    assert not (b.ROOT/'artifacts').exists()


@pytest.mark.parametrize('attack',['symlink','special','duplicate','traversal'])
def test_committed_archive_link_special_duplicate_and_traversal_are_rejected(monkeypatch,attack):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        item=tarfile.TarInfo('app/file.py');item.size=1;archive.addfile(item,io.BytesIO(b'x'))
        other=tarfile.TarInfo('app/../file.py' if attack=='traversal' else 'app/file.py' if attack=='duplicate' else 'app/extra.py')
        if attack=='symlink':other.type=tarfile.SYMTYPE;other.linkname='/outside'
        if attack=='special':other.type=tarfile.FIFOTYPE
        archive.addfile(other,io.BytesIO(b''))
    monkeypatch.setattr(b,'git',lambda *a,**k:raw.getvalue())
    with pytest.raises(RuntimeError):b.inventory(b.SOURCE_SHA)


def test_inspect_only_is_side_effect_free_and_json_is_strict(package):
    _,args,*_=package;before=set(b.ROOT.rglob('*'));result=b.inspect_static(args['dist'])
    assert result['artifacts_written'] is False and result['frontend_version']==b.FRONTEND and set(b.ROOT.rglob('*'))==before
    for body in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
        with pytest.raises(RuntimeError):b.strict_json(body)


def test_output_is_fresh_private_exact_directory_and_never_overwrites(package,monkeypatch):
    summary,args,*_=package;monkeypatch.setattr(b,'HERE',b.ROOT/'local-tools');b.HERE.mkdir();blob,manifest=b.build(summary,**args);out=b.HERE/'artifacts'
    b.write_artifacts(blob,manifest,out)
    assert (out/'payload.tar.gz').read_bytes()==blob and (out/'manifest.json').read_bytes()==b.encoded(manifest)
    assert out.stat().st_mode&0o777==0o700 and (out/'manifest.json').stat().st_mode&0o777==0o600
    with pytest.raises(RuntimeError,match='FRESH_EXACT_ARTIFACT_DIRECTORY_REQUIRED'):b.write_artifacts(blob,manifest,out)


@pytest.mark.parametrize('swap_at',['directory_open','file_open','parent_file_open'])
def test_output_directory_or_parent_swap_cannot_redirect_artifact_bytes(package,monkeypatch,swap_at):
    summary,args,*_=package;monkeypatch.setattr(b,'HERE',b.ROOT/'local-tools');b.HERE.mkdir();blob,manifest=b.build(summary,**args);out=b.HERE/'artifacts';real_open=b.os.open;swapped=False;dirfds=[]
    def swap():
        nonlocal swapped
        swapped=True
        if swap_at=='parent_file_open':b.HERE.rename(b.ROOT/'held-parent');b.HERE.mkdir();out.mkdir(mode=0o700)
        else:out.rename(b.HERE/'held-artifacts');out.mkdir(mode=0o700)
        (out/'foreign-marker').write_text('must remain untouched')
    def opened(path,flags,mode=0o777,*,dir_fd=None):
        if path in ('payload.tar.gz','manifest.json'):dirfds.append(dir_fd)
        if not swapped and ((swap_at=='directory_open' and path=='artifacts' and flags&b.os.O_DIRECTORY) or (swap_at in {'file_open','parent_file_open'} and path=='payload.tar.gz')):swap()
        return real_open(path,flags,mode,dir_fd=dir_fd)
    monkeypatch.setattr(b.os,'open',opened)
    with pytest.raises(RuntimeError,match='ARTIFACT_.*(DRIFT|REQUIRED)'):b.write_artifacts(blob,manifest,out)
    assert swapped and set(p.name for p in out.iterdir())=={'foreign-marker'} and all(isinstance(fd,int) for fd in dirfds)


def test_missing_explicit_pins_fail_before_git_or_filesystem_reads(monkeypatch):
    monkeypatch.setattr(b,'git',lambda *a,**k:pytest.fail('Git read before explicit pin validation'))
    with pytest.raises(RuntimeError,match='EXPLICIT_FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED'):b.build({},source_sha=None,frontend=None,freeze_path=None,freeze_sha=None)
