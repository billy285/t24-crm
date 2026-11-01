"""Public synthetic offline-build capture tests; no Docker/server execution."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
import pytest

HERE=Path(__file__).resolve().parent


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


d=load('public_build_diagnostic_test',HERE/'diagnose_toolchain_build.py')
maker=load('public_build_diagnostic_maker_test',HERE/'make_toolchain_build_diagnostic.py')
retry=load('public_build_diagnostic_exact194_test',HERE/'toolchain_retry.py')
variant=retry.derive_variant((HERE/'toolchain.py').read_bytes())
tool=ModuleType('frozen_public_build_variant_test');exec(compile(variant,'<frozen-public-build-variant>','exec'),tool.__dict__)


def test_build_uses_exact_frozen8c_source_and_original_unmodified_offline_command():
    assert d.H(variant)==d.TOOL_SHA
    assert d.build_command(Path('/synthetic/build'))==['docker','build','--network=none','--pull=false','--memory','768m','--cpu-period','100000','--cpu-quota','100000','-t',d.TAG,'/synthetic/build']
    assert d.IMAGE=='sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'


def fixture(tmp_path,monkeypatch):
    root=tmp_path.resolve();work=root/'work';context=work/'build';context.mkdir(parents=True);(context/'packages').mkdir();(work/'fetch-data/packages').mkdir(parents=True)
    versions={**tool.TOP,**{f'libsynthetic{i}':'1.0' for i in range(191)}};blob=b'SYNTHETIC PUBLIC DEB';sha=d.H(blob)
    proposed={name:{'version':version,'architecture':'amd64','sha256':sha,'download_bytes':len(blob),'installed_bytes':1024,'official_pool_path':f'pool/main/s/synthetic/{name}_1.deb'} for name,version in versions.items()}
    approved={'stage':'PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED','selected_count':194,'expected_top_versions':tool.TOP,'selected_top_versions':tool.TOP,'top_versions_match':True,'selected_packages':proposed,'selected_new_versions':versions,'base_packages_unchanged':True,'installation_performed':False,'package_download_performed':False,'business_or_credentials_mounted':False,'total_download_bytes':194*len(blob),'estimated_installed_bytes':194*1024}
    packages={name:{'version':row['version'],'architecture':row['architecture'],'sha256':sha,'bytes':len(blob),'file':name+'_1.deb','official_pool_path':row['official_pool_path']} for name,row in proposed.items()}
    manifest={'approved_proposal_sha256':d.APPROVED_SHA,'top_packages':tool.TOP,'base_packages_unchanged':True,'installation_performed':False,'business_or_credentials_mounted':False,'packages':packages,'base_packages':{'existing-base':{'version':'unchanged'}},'total_download_bytes':approved['total_download_bytes'],'estimated_installed_bytes':approved['estimated_installed_bytes'],'signed_inrelease_sha256':{'official_InRelease':'a'*64}}
    proposal=root/'proposal.json';proposal.write_text(json.dumps(approved));(work/'fetch-data/packages.json').write_text(json.dumps(manifest));(context/'packages.json').write_bytes((work/'fetch-data/packages.json').read_bytes());(context/'install.py').write_bytes(tool.INSTALL.encode())
    dockerfile='FROM '+d.IMAGE+'\nCOPY packages /tmp/t24-render-deps/packages\nCOPY packages.json install.py /tmp/t24-render-deps/\nRUN /usr/local/bin/python -I -B /tmp/t24-render-deps/install.py && rm -rf /tmp/t24-render-deps\n';(context/'Dockerfile').write_text(dockerfile)
    for row in packages.values():
        (context/'packages'/row['file']).write_bytes(blob);(work/'fetch-data/packages'/row['file']).write_bytes(blob)
    monkeypatch.setattr(d,'WORK',work);monkeypatch.setattr(d,'APPROVED',proposal);monkeypatch.setattr(d,'secure',lambda path:None)
    monkeypatch.setattr(d,'read_private',lambda path,maximum=1048576,sha=None:path.read_bytes())
    calls=[]
    def verify(path,expected,size):
        calls.append(path);assert path.stat().st_size==size and d.H(path.read_bytes())==expected
    monkeypatch.setattr(d,'hash_package',verify)
    return work,context,calls


def test_exact194_signed_proposal_fetch_manifest_installer_dockerfile_and_both_package_sets_verified(tmp_path,monkeypatch):
    _,_,calls=fixture(tmp_path,monkeypatch);proof=d.validate_context(tool)
    assert proof['package_count']==194 and len(calls)==388
    assert proof['installer_sha256']==d.H(tool.INSTALL.encode())


@pytest.mark.parametrize('name',['Dockerfile','install.py','packages.json'])
def test_unreviewed_context_change_blocks_before_build(tmp_path,monkeypatch,name):
    _,context,_=fixture(tmp_path,monkeypatch);(context/name).write_bytes(b'UNREVIEWED CHANGE')
    with pytest.raises(RuntimeError):d.validate_context(tool)


def test_foreign_context_or_deb_member_is_rejected(tmp_path,monkeypatch):
    _,context,_=fixture(tmp_path,monkeypatch);(context/'packages'/'foreign.deb').write_bytes(b'foreign')
    with pytest.raises(RuntimeError,match='EXACT194_PUBLIC_DEB_MEMBER_SET_REQUIRED'):d.validate_context(tool)


def test_successful_bounded_public_log_and_real_failure_reason_are_persisted(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'secure',lambda path:None);path=tmp_path/'build.log'
    result=d.capture_build([sys.executable,'-c',"print('PUBLIC SYNTHETIC APT ERROR');raise SystemExit(7)"],path,timeout=10)
    assert result['exit_code']==7 and result['client_status']=='BUILD_CLIENT_FINISHED'
    assert result['log_sha256']==d.H(path.read_bytes()) and 'PUBLIC SYNTHETIC APT ERROR' in result['public_tail']
    assert path.stat().st_mode&0o777==0o600 and result['build_daemon_result_known'] is True


def test_output_limit_is_bounded_and_never_claims_daemon_build_cancelled(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'secure',lambda path:None);path=tmp_path/'bounded.log'
    result=d.capture_build([sys.executable,'-c',"print('X'*4000)"],path,timeout=10,maximum=100)
    assert path.stat().st_size==100 and result['log_bytes']==100 and result['client_status']=='BUILD_PUBLIC_LOG_LIMIT_RESULT_UNKNOWN'
    assert result['build_daemon_result_known'] is False


def test_timeout_marks_daemon_result_unknown_and_records_only_new_log(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'secure',lambda path:None)
    result=d.capture_build([sys.executable,'-c','import time;time.sleep(3)'],tmp_path/'timeout.log',timeout=.01)
    assert result['client_status']=='BUILD_CLIENT_TIMEOUT_RESULT_UNKNOWN' and result['build_daemon_result_known'] is False


def test_existing_candidate_image_never_rebuilds_or_gets_overwritten(monkeypatch):
    monkeypatch.setattr(d.os,'geteuid',lambda:0);monkeypatch.setattr(d.socket,'gethostname',lambda:'iZj6c4cj7edgnhdimts4l7Z')
    monkeypatch.setattr(d,'runtime',lambda:d.RUNTIME);monkeypatch.setattr(d,'read_private',lambda *a,**k:variant);monkeypatch.setattr(d,'validate_context',lambda _:{'package_count':194})
    monkeypatch.setattr(d,'image_id',lambda _:d.IMAGE);monkeypatch.setattr(d,'capture_build',lambda *a,**k:pytest.fail('Existing image was rebuilt'))
    result=d.run(b'synthetic probe source');assert result['stage']=='ASSET_TOOLCHAIN_EXISTING_CANDIDATE_NOT_REBUILT' and result['rebuild_performed'] is False


def test_no_current_credentials_database_install_or_network_relaxation_in_diagnostic():
    source=(HERE/'diagnose_toolchain_build.py').read_text()
    assert 'Config.Env' not in source and 'crm_prod.db' not in source and '--download-only' not in source
    assert 'apt-get' not in source and 'os.execve' not in source and 'unlink' not in source
    assert "'--network=none'" in source and "'--pull=false'" in source
    assert "'public_tail':safe" in source and '[-8192:]' in source


def test_small_generator_hashes_exact_source_without_executing_build():
    body=(HERE/'diagnose_toolchain_build.py').read_bytes();command,pins=maker.generate(body)
    assert pins['command_bytes']==len(command.encode())<14000 and pins['diagnostic_sha256']==d.H(body)
    assert pins['executed'] is False and pins['installer_or_network_flags_changed'] is False
    ast.parse(command.split("<<'EXACT194_OFFLINE_BUILD_DIAGNOSTIC'\n",1)[1].rsplit('\nEXACT194_OFFLINE_BUILD_DIAGNOSTIC\n',1)[0])
