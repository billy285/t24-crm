"""Synthetic attacks against the private asset-studio application package."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

HERE=Path(__file__).resolve().parent
PROJECT_ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('asset_studio_package_test',HERE/'build_payload.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


@pytest.fixture
def engine_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'HERE',tmp_path);monkeypatch.setattr(b,'TOOLCHAIN_HELPER_SHA','1'*64)
    monkeypatch.setattr(b,'TOOLCHAIN_IMAGE','sha256:'+'2'*64)
    value={'stage':'MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED','tool_sha256':b.TOOLCHAIN_HELPER_SHA,'toolchain_image':b.TOOLCHAIN_IMAGE,
        'base_image':'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536',
        'approved_proposal_sha256':b.APPROVED_PROPOSAL_SHA,'added_package_count':194,'source_sha':b.BASE_SOURCE,
        'frontend_version':b.BASE_FRONTEND,'preflight_sha256':b.PREFLIGHT_SHA,
        **{key:True for key in ('all155_current_rows_and_private_packet_preserved','all408_backend_files_unchanged','no_existing_package_upgraded_or_removed','fetch_only_official_signed_debian','install_and_engine_probe_network_none')},
        **{key:False for key in ('production_or_host_installation','production_container_changed','credentials_or_business_data_mounted','api_or_worker_started','social_ai_or_payment_provider_requests','publications_performed')},
        'engine_canary':{'python_pillow':'12.3.0','freetype2':True,'cjk_and_latin_glyphs_verified':True,
            'actual_h264_mp4':{'codec_name':'h264','width':32,'height':32,'pix_fmt':'yuv420p','bytes':1000}}}
    def save():
        body=b.encoded(value);(tmp_path/'toolchain-prepared.json').write_bytes(body);monkeypatch.setattr(b,'TOOLCHAIN_RECEIPT_SHA',b.H(body))
    save();return value,save


def test_actual_exact_toolchain_receipt_is_required_and_verified(engine_receipt):
    value,_=engine_receipt;assert b.verified_toolchain()==value


@pytest.mark.parametrize('attack',['bytes','helper','image','old_source','approved_closure','count','rows','credentials','worker','provider','pillow','cjk','not_mp4','oversize'])
def test_any_unverified_toolchain_provenance_or_engine_claim_is_rejected(engine_receipt,attack):
    value,save=engine_receipt
    if attack=='bytes':(b.HERE/'toolchain-prepared.json').write_text('{}')
    else:
        if attack=='helper':value['tool_sha256']='0'*64
        if attack=='image':value['toolchain_image']='sha256:'+'0'*64
        if attack=='old_source':value['source_sha']='0'*40
        if attack=='approved_closure':value['approved_proposal_sha256']='0'*64
        if attack=='count':value['added_package_count']=195
        if attack=='rows':value['all155_current_rows_and_private_packet_preserved']=False
        if attack=='credentials':value['credentials_or_business_data_mounted']=True
        if attack=='worker':value['api_or_worker_started']=True
        if attack=='provider':value['social_ai_or_payment_provider_requests']=True
        if attack=='pillow':value['engine_canary']['python_pillow']='unreviewed'
        if attack=='cjk':value['engine_canary']['cjk_and_latin_glyphs_verified']=False
        if attack=='not_mp4':value['engine_canary']['actual_h264_mp4']['codec_name']='unreviewed'
        if attack=='oversize':value['engine_canary']['actual_h264_mp4']['bytes']=1048576
        save()
    with pytest.raises(RuntimeError):b.verified_toolchain()


@pytest.fixture
def package(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'ROOT',tmp_path);before={};after={}
    monkeypatch.setattr(b,'SOURCE_SHA','a'*40);monkeypatch.setattr(b,'FRONTEND','b'*12)
    monkeypatch.setattr(b,'TOOLCHAIN_RECEIPT_SHA','1'*64);monkeypatch.setattr(b,'TOOLCHAIN_IMAGE','sha256:'+'2'*64);monkeypatch.setattr(b,'RENDERER_CANARY_SHA','3'*64)
    monkeypatch.setattr(b,'TOOLCHAIN_HELPER_SHA','4'*64)
    monkeypatch.setattr(b,'verified_toolchain',lambda:None)
    monkeypatch.setattr(b,'FRONTEND_FILES',frozenset({'app/frontend/src/pages/MediaOperations.tsx','app/frontend/src/components/MerchantWorkspace.tsx'}))
    monkeypatch.setattr(b,'TEST_FILES',frozenset({'app/backend/tests/test_media_workspace.py','app/frontend/tests/merchant-workspace.test.mjs'}))
    monkeypatch.setattr(b,'SOURCE_FILES',frozenset('app/backend/'+name for name in b.BACKEND_FILES)|b.FRONTEND_FILES|b.TEST_FILES)
    existing={'app/frontend/src/pages/MediaOperations.tsx'}|{'app/backend/'+key for key in b.EXISTING_BACKEND_HASHES}
    for name in b.SOURCE_FILES|{'app/backend/preserved.py','app/frontend/src/preserved.ts'}:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);body=('SYNTHETIC '+name).encode();path.write_bytes(body);after[name]=b.H(body)
        if name not in b.SOURCE_FILES or name in existing:before[name]=b.H(('OLD '+name).encode()) if name in b.SOURCE_FILES else after[name]
    monkeypatch.setattr(b,'BACKEND_BEFORE',{name:before.get('app/backend/'+name) for name in b.BACKEND_FILES})
    monkeypatch.setattr(b,'EXISTING_BACKEND_HASHES',{name:before['app/backend/'+name] for name in b.EXISTING_BACKEND_HASHES})
    monkeypatch.setattr(b,'BACKEND_AFTER',{name:after['app/backend/'+name] for name in b.BACKEND_FILES})
    monkeypatch.setattr(b,'inventory',lambda ref:dict(before if ref==b.BASE_SOURCE else after));monkeypatch.setattr(b,'frontend_version',lambda:b.FRONTEND)
    def git(*args,**kwargs):
        if args[0]=='rev-parse':return (b.SOURCE_SHA+'\n').encode()
        if args[0]=='diff':return ('\0'.join(sorted(b.SOURCE_FILES))+'\0').encode()
        raise AssertionError('Unexpected Git command')
    monkeypatch.setattr(b,'git',git)
    summary={'sha256':'d'*64};monkeypatch.setattr(b,'validate_summary',lambda value:b.need(not value.get('ops_execution_enabled') and value.get('environment_sha256')!='0'*64 and value.get('table_count',155)==155 and value.get('source_sha',b.BASE_SOURCE)==b.BASE_SOURCE,'SYNTHETIC_BASELINE_DRIFT'))
    dist=tmp_path/'app/frontend/dist';dist.mkdir();(dist/'assets').mkdir();(dist/'index.html').write_text('<html>SYNTHETIC</html>');(dist/'assets/test.js').write_text('SYNTHETIC CHUNK');(dist/'app-version.json').write_text(json.dumps({'version':b.FRONTEND}))
    freeze={'source_sha':b.SOURCE_SHA,'frontend_version':b.FRONTEND,'baseline_source_sha':b.BASE_SOURCE,'baseline_frontend_version':b.BASE_FRONTEND,'schema_revision':b.NEW_REVISION,'old_schema_revision':b.OLD_REVISION,
        'toolchain_receipt_sha256':b.TOOLCHAIN_RECEIPT_SHA,'toolchain_helper_sha256':b.TOOLCHAIN_HELPER_SHA,'toolchain_image':b.TOOLCHAIN_IMAGE,'renderer_canary_sha256':b.RENDERER_CANARY_SHA,
        'files':{name:after[name] for name in b.SOURCE_FILES},'dist_inventory_sha256':b.static_inventory(b.read_static(dist)),**{key:True for key in b.TRUE_FLAGS},**{key:False for key in b.FALSE_FLAGS}}
    freeze_path=tmp_path/'freeze.json';freeze_path.write_bytes(b.encoded(freeze));args={'source_sha':b.SOURCE_SHA,'frontend':b.FRONTEND,'freeze_path':freeze_path,'freeze_sha':b.H(freeze_path.read_bytes()),'dist':dist}
    monkeypatch.setattr(b,'APPLICATION_FREEZE_SHA',args['freeze_sha'])
    return summary,args,before,after,freeze


def test_exact_reviewed_delta_and_only_five_new_backend_modules_plus_static_are_deterministic(package):
    summary,args,before,after,freeze=package;blob,manifest=b.build(summary,**args);second,again=b.build(summary,**args)
    assert blob==second and manifest==again and set(manifest['changed_source_files'])==b.SOURCE_FILES and len(b.SOURCE_FILES)==len(b.BACKEND_FILES)+len(b.FRONTEND_FILES)+len(b.TEST_FILES)
    assert manifest['schema_revision']==b.NEW_REVISION and manifest['old_schema_revision']==b.OLD_REVISION and manifest['additive_tables']==sorted(b.NEW_TABLES)
    assert all(manifest[key] is True for key in b.TRUE_FLAGS) and all(manifest[key] is False for key in b.FALSE_FLAGS)
    assert manifest['backend_before']==b.BACKEND_BEFORE and manifest['backend_after']==b.BACKEND_AFTER
    assert manifest['protected_source_inventory']=={name:pin for name,pin in before.items() if name not in b.SOURCE_FILES}
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as stream:
        rows=stream.getmembers();assert len(rows)==len({row.name for row in rows})==len(b.BACKEND_FILES)+3 and {row.name for row in rows}==set(manifest['files'])
        assert {row.name[8:] for row in rows if row.name.startswith('backend/')}==b.BACKEND_FILES
        assert all(row.name.startswith(('backend/','static/')) and not any(word in row.name for word in ('vendor/','tests/','.env','requirements')) for row in rows)
        for row in rows:assert row.isfile() and row.uid==row.gid==row.mtime==0 and row.mode==0o644 and row.uname==row.gname=='' and b.H(stream.extractfile(row).read())==manifest['files'][row.name]


@pytest.mark.parametrize('attack',['extra_app','missing_change','deleted_old','new_source','local_source','untracked_frontend','baseline_hash','after_hash','source_pin','frontend_pin','freeze_pin','freeze_content','frozen_source','dist_version','dist_secret','dist_symlink','dist_root_symlink','dist_hardlink','qa_dist_mismatch','freeze_migration','freeze_execution','summary_execution','summary_environment','summary_tables','summary_source'])
def test_any_unreviewed_application_build_scope_or_preservation_claim_is_rejected(package,monkeypatch,attack):
    summary,args,before,after,freeze=package;root=b.ROOT
    if attack=='extra_app':after['app/backend/unapproved.py']='0'*64
    if attack=='missing_change':after.pop('app/backend/services/media_asset_studio.py')
    if attack=='deleted_old':after.pop('app/backend/preserved.py')
    if attack=='new_source':before['app/backend/services/media_asset_studio.py']='f'*64
    if attack=='local_source':(root/'app/backend/services/media_asset_studio.py').write_text('UNREVIEWED')
    if attack=='untracked_frontend':(root/'app/frontend/src/untracked.ts').write_text('UNREVIEWED')
    if attack=='baseline_hash':monkeypatch.setattr(b,'BACKEND_BEFORE',{'services/media_asset_studio.py':'0'*64});summary['backend_changed_before']=b.BACKEND_BEFORE
    if attack=='after_hash':monkeypatch.setattr(b,'BACKEND_AFTER',{'services/media_asset_studio.py':'0'*64})
    if attack=='source_pin':args['source_sha']='0'*40
    if attack=='frontend_pin':args['frontend']='0'*12
    if attack=='freeze_pin':args['freeze_sha']='0'*64
    if attack=='freeze_content':args['freeze_path'].write_text('{}')
    if attack in {'frozen_source','freeze_migration','freeze_execution'}:
        if attack=='frozen_source':freeze['files']['app/backend/services/media_asset_studio.py']='0'*64
        if attack=='freeze_migration':freeze['database_migration']=False
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
    if attack=='summary_tables':summary['table_count']=152
    if attack=='summary_source':summary['source_sha']='0'*40
    with pytest.raises((RuntimeError,KeyError,OSError)):b.build(summary,**args)


def test_native_diff_must_exactly_match_full_archive_delta(package,monkeypatch):
    summary,args,*_=package;original=b.git
    monkeypatch.setattr(b,'git',lambda *a,**k:b'app/backend/unapproved.py\0' if a[0]=='diff' else original(*a,**k))
    with pytest.raises(RuntimeError,match='EXACT_ADDITIVE_UI_PROJECTION_APPLICATION_DELTA_REQUIRED'):b.build(summary,**args)


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
            if Path(path)==b.ROOT/'app/backend/services/media_asset_studio.py':
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
