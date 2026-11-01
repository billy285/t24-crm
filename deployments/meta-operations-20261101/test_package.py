"""Synthetic local package attacks; no Git commits, network or deployment."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('meta_ops_package_test',HERE/'build_payload.py')
b = importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


@pytest.fixture
def package(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path)
    for key in ('SOURCE_SHA','FRONTEND','APPLICATION_FREEZE_SHA'):monkeypatch.setattr(b.r,key,None)
    source='d'*40;frontend='e'*12;before={};after={}
    old_paths={'app/backend/main.py','app/backend/requirements.txt','app/frontend/src/components/MetaBusinessWorkspace.tsx','app/frontend/src/pages/MediaOperations.tsx','app/frontend/tests/meta-business-workflow.test.mjs'}
    for name in b.r.SOURCE_FILES|{'app/backend/preserved.py','app/frontend/src/preserved.ts'}:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('SYNTHETIC '+name).encode());after[name]=b.H(path.read_bytes())
        if name not in b.r.SOURCE_FILES:before[name]=after[name]
        elif name in old_paths:before[name]=b.H(('OLD '+name).encode())
    monkeypatch.setattr(b.r,'ORIGINAL_BACKEND_HASHES',{name:before['app/backend/'+name] for name in b.r.EXISTING_BACKEND_FILES})
    monkeypatch.setattr(b,'inventory',lambda ref:dict(before if ref==b.r.BASE_SOURCE else after))
    monkeypatch.setattr(b,'frontend_version',lambda:frontend)
    def git(*args,**kw):
        if args[0]=='rev-parse':return (source+'\n').encode()
        if args[0]=='diff':return ('\0'.join(sorted(b.r.SOURCE_FILES))+'\0').encode()
        raise AssertionError('No other Git command')
    monkeypatch.setattr(b,'git',git)
    dist=tmp_path/'app/frontend/dist';dist.mkdir();(dist/'assets').mkdir();(dist/'index.html').write_text('<html>synthetic</html>');(dist/'assets/test.js').write_text('synthetic chunk')
    (dist/'app-version.json').write_text(json.dumps({'version':frontend}))
    wheel_body=b'SYNTHETIC-OFFICIAL-WHEEL';monkeypatch.setattr(b.r,'WHEEL_SHA',b.H(wheel_body));monkeypatch.setattr(b.r,'WHEEL_BYTES',len(wheel_body))
    wheel=tmp_path/b.r.WHEEL;wheel.write_bytes(wheel_body)
    freeze={'source_sha':source,'frontend_version':frontend,'baseline_source_sha':b.r.BASE_SOURCE,'baseline_frontend_version':b.r.BASE_FRONTEND,
        'schema_revision':b.r.NEW_REVISION,'old_schema_revision':b.r.OLD_REVISION,'files':{name:after[name] for name in b.r.SOURCE_FILES},
        'dist_inventory_sha256':b.static_inventory(b.read_static(dist)),**{name:True for name in b.TRUE_FLAGS},**{name:False for name in b.FALSE_FLAGS}}
    freeze_path=tmp_path/'freeze.json';freeze_path.write_bytes(b.r.encoded(freeze))
    summary=json.loads((ROOT/'outputs/meta-operations-20261101/preflight-summary.json').read_text())
    args={'source_sha':source,'frontend':frontend,'freeze_path':freeze_path,'freeze_sha':b.H(freeze_path.read_bytes()),'wheel_path':wheel,'dist':dist}
    return summary,args,before,after,freeze


def test_payload_is_deterministic_exact_runtime_static_and_pinned_wheel(package):
    summary,args,before,after,freeze=package
    blob,manifest=b.build(summary,**args);again,second=b.build(summary,**args)
    assert blob==again and manifest==second
    assert set(manifest['changed_source_files'])==b.r.SOURCE_FILES and len(manifest['changed_source_files'])==18
    assert manifest['backend_before']=={name:b.r.ORIGINAL_BACKEND_HASHES.get(name) for name in b.r.BACKEND_FILES}
    assert manifest['backend_after']=={name:after['app/backend/'+name] for name in b.r.BACKEND_FILES}
    assert manifest['dist_inventory_sha256']==freeze['dist_inventory_sha256']
    assert all(manifest[name] is True for name in b.TRUE_FLAGS) and all(manifest[name] is False for name in b.FALSE_FLAGS)
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as stream:
        rows=stream.getmembers();names={row.name for row in rows}
        assert names==set(manifest['files']) and len(rows)==len(names)
        assert {name[8:] for name in names if name.startswith('backend/')}==b.r.BACKEND_FILES
        assert b.r.WHEEL_MEMBER in names and all(not name.startswith('app/') and '.env' not in name and '/tests/' not in name for name in names)
        for row in rows:
            assert row.isfile() and row.mode==0o644 and row.uid==row.gid==row.mtime==0 and row.uname==row.gname==''
            assert b.H(stream.extractfile(row).read())==manifest['files'][row.name]


@pytest.mark.parametrize('attack',['extra_app','missing_change','deleted_old','local_source','untracked_frontend','baseline_hash','source_pin','frontend_pin','freeze_pin','freeze_content','frozen_source','dist_version','dist_secret','dist_symlink','dist_root_symlink','qa_dist_mismatch','wheel_hash','wheel_size','wheel_filename','changed_release_pin'])
def test_unreviewed_application_dist_wheel_or_identity_is_rejected(package,monkeypatch,attack):
    summary,args,before,after,freeze=package;root=b.ROOT
    if attack=='extra_app':after['app/backend/unapproved.py']='0'*64
    if attack=='missing_change':after['app/backend/main.py']=before['app/backend/main.py']
    if attack=='deleted_old':after.pop('app/backend/preserved.py')
    if attack=='local_source':(root/'app/backend/main.py').write_text('unreviewed')
    if attack=='untracked_frontend':(root/'app/frontend/src/untracked.ts').write_text('unreviewed')
    if attack=='baseline_hash':before['app/backend/requirements.txt']='0'*64
    if attack=='source_pin':args['source_sha']='0'*40
    if attack=='frontend_pin':args['frontend']='0'*12
    if attack=='freeze_pin':args['freeze_sha']='0'*64
    if attack=='freeze_content':args['freeze_path'].write_text('{}')
    if attack=='frozen_source':
        freeze['files']['app/backend/main.py']='0'*64;args['freeze_path'].write_bytes(b.r.encoded(freeze));args['freeze_sha']=b.H(args['freeze_path'].read_bytes())
    if attack=='dist_version':(args['dist']/'app-version.json').write_text('{"version":"wrong"}')
    if attack=='dist_secret':(args['dist']/'runtime.env').write_text('SYNTHETIC-SECRET')
    if attack=='dist_symlink':(args['dist']/'assets/link.js').symlink_to(args['dist']/'assets/test.js')
    if attack=='dist_root_symlink':
        actual=root/'old-dist';args['dist'].rename(actual);args['dist'].symlink_to(actual,target_is_directory=True)
    if attack=='qa_dist_mismatch':(args['dist']/'assets/test.js').write_text('unreviewed build')
    if attack=='wheel_hash':args['wheel_path'].write_bytes(b'X'*b.r.WHEEL_BYTES)
    if attack=='wheel_size':args['wheel_path'].write_bytes(b'X')
    if attack=='wheel_filename':
        path=root/'unapproved.whl';args['wheel_path'].rename(path);args['wheel_path']=path
    if attack=='changed_release_pin':monkeypatch.setattr(b.r,'SOURCE_SHA','a'*40)
    with pytest.raises((RuntimeError,KeyError)):b.build(summary,**args)


def test_native_git_diff_must_match_archive_inventory_and_eighteen_scope(package,monkeypatch):
    summary,args,*_=package;original=b.git
    monkeypatch.setattr(b,'git',lambda *parts,**kw:b'app/backend/unapproved.py\0' if parts[0]=='diff' else original(*parts,**kw))
    with pytest.raises(RuntimeError,match='EXACT_EIGHTEEN_APPLICATION_DELTA_REQUIRED'):b.build(summary,**args)


def test_inspection_only_has_no_artifact_side_effect(package):
    summary,args,*_=package;before=set(b.ROOT.rglob('*'));value=b.inspect_static(args['dist'])
    assert value['frontend_version']==args['frontend'] and value['artifacts_written'] is False and value['file_count']==3
    assert set(b.ROOT.rglob('*'))==before


def test_output_is_fresh_exact_directory_and_never_overwrites(package,monkeypatch):
    summary,args,*_=package;monkeypatch.setattr(b,'HERE',b.ROOT/'local-tools');b.HERE.mkdir()
    blob,manifest=b.build(summary,**args);out=b.HERE/'artifacts'
    b.write_artifacts(blob,manifest,out)
    assert (out/'payload.tar.gz').read_bytes()==blob and (out/'manifest.json').read_bytes()==b.r.encoded(manifest)
    assert out.stat().st_mode&0o777==0o700 and (out/'manifest.json').stat().st_mode&0o777==0o600
    with pytest.raises(RuntimeError,match='FRESH_EXACT_ARTIFACT_DIRECTORY_REQUIRED'):b.write_artifacts(blob,manifest,out)
    with pytest.raises(RuntimeError,match='FRESH_EXACT_ARTIFACT_DIRECTORY_REQUIRED'):b.write_artifacts(blob,manifest,b.ROOT/'elsewhere')


@pytest.mark.parametrize('swap_at',['directory_open','file_open','parent_file_open'])
def test_output_directory_or_parent_swap_is_rejected_and_never_writes_foreign_directory(package,monkeypatch,swap_at):
    summary,args,*_=package;monkeypatch.setattr(b,'HERE',b.ROOT/'local-tools');b.HERE.mkdir()
    blob,manifest=b.build(summary,**args);out=b.HERE/'artifacts';real_open=b.os.open;swapped=False;file_dirfds=[]
    def swap():
        nonlocal swapped
        swapped=True
        if swap_at=='parent_file_open':
            b.HERE.rename(b.ROOT/'held-parent');b.HERE.mkdir();out.mkdir(mode=0o700)
        else:
            out.rename(b.HERE/'held-artifacts');out.mkdir(mode=0o700)
        (out/'foreign-marker').write_text('must remain untouched')
    def guarded_open(path,flags,mode=0o777,*,dir_fd=None):
        if path in ('payload.tar.gz','manifest.json'):file_dirfds.append(dir_fd)
        if not swapped and ((swap_at=='directory_open' and path=='artifacts' and flags&b.os.O_DIRECTORY) or (swap_at in {'file_open','parent_file_open'} and path=='payload.tar.gz')):swap()
        return real_open(path,flags,mode,dir_fd=dir_fd)
    monkeypatch.setattr(b.os,'open',guarded_open)
    with pytest.raises(RuntimeError,match='ARTIFACT_.*(DRIFT|REQUIRED)'):b.write_artifacts(blob,manifest,out)
    assert swapped and (out/'foreign-marker').read_text()=='must remain untouched'
    assert set(path.name for path in out.iterdir())=={'foreign-marker'}
    assert all(isinstance(fd,int) for fd in file_dirfds)


def test_missing_final_inputs_fail_before_git_or_local_reads(monkeypatch):
    monkeypatch.setattr(b,'git',lambda *a,**kw:pytest.fail('Git read before explicit final input validation'))
    with pytest.raises(RuntimeError,match='EXPLICIT_FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED'):b.build({},source_sha=None,frontend=None,freeze_path=None,freeze_sha=None,wheel_path=None)


def test_real_pillow_pin_matches_previously_verified_primary_metadata():
    value=json.loads((ROOT/'outputs/meta-operations-20261101/pillow-wheel-pin.json').read_text())
    assert value['filename']==b.r.WHEEL and value['sha256']==b.r.WHEEL_SHA and value['bytes']==b.r.WHEEL_BYTES and value['source']==b.PILLOW_SOURCE
    wheel=ROOT/'outputs/meta-operations-20261101/vendor'/b.r.WHEEL
    assert wheel.is_file() and wheel.stat().st_size==b.r.WHEEL_BYTES and b.H(b.r.local_bytes(wheel,b.r.WHEEL_BYTES))==b.r.WHEEL_SHA
