"""Two-edit resumer derivation, synthetic only; never execute Docker."""
import ast
import base64
import importlib.util
from pathlib import Path
from types import ModuleType,SimpleNamespace
import zlib
import pytest

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


l=load('synthetic_local_acquire_loader',HERE/'resume_local_acquire.py')
maker=load('synthetic_local_acquire_maker',HERE/'make_resume_local_acquire.py')
base=load('synthetic_base_resume_tests',HERE/'test_resume_toolchain.py')
old=(HERE/'resume_toolchain.py').read_bytes();derived=l.derive(old)
r=ModuleType('synthetic_derived_local_acquire_resumer');exec(compile(derived,'<local-acquire>','exec'),r.__dict__)


def test_derivation_requires_exact_protected8f_bytes_and_rejects_any_drift():
    assert len(old)==13775 and l.H(old)==l.BASE_SHA
    with pytest.raises(RuntimeError,match='EXACT_FROZEN8F_RESUMER_REQUIRED'):l.derive(old+b' ')
    assert '/8f007897d478-' not in str(l.BASE)  # Full scope is pinned below.
    assert str(l.BASE).endswith('media-asset-studio-toolchain-8f007897d478-20261101/resume_toolchain.py')


def test_only_three_function_bodies_change_and_all_baseline_probe_copy_capture_code_is_identical():
    functions=lambda source:{row.name:ast.dump(row,include_attributes=False) for row in ast.parse(source).body if isinstance(row,ast.FunctionDef)}
    before=functions(old);after=functions(derived)
    assert before.keys()==after.keys()
    assert {name for name in before if before[name]!=after[name]}=={'installer','verify_copy','perform'}
    assert all(getattr(r,name)==getattr(base.r,name) for name in ('ROOT','OLD','OLD_SHA','ORIGINAL','ORIGINAL_SHA','COMMAND','COMMAND_SHA','DIAGNOSTIC','DIAGNOSTIC_SHA','PREFLIGHT_SHA','PROOF_SHA','APPROVED_SHA','IMAGE','OLD_PATH','NEW_PATH'))


def test_installer_has_only_two_explicit_approved_differences_from_frozen8c():
    result=r.installer(base.tool).decode();expected=base.tool.INSTALL.replace(r.OLD_PATH,r.NEW_PATH,1).replace("'--no-download',",'',1)
    assert result==expected and '--no-download' not in result
    assert result.replace(r.NEW_PATH,r.OLD_PATH,1).replace("'--assume-yes','--no-remove'","'--assume-yes','--no-download','--no-remove'",1)==base.tool.INSTALL
    assert all(value in result for value in ('--no-remove','--no-upgrade','--no-install-recommends',"ROOT=Path('/tmp/t24-render-deps')",'paths.append(str(path))','if after!=expected'))


@pytest.mark.parametrize('change',['missing_flag','duplicate_flag','anchor_drift'])
def test_unreviewed_installer_forms_rejected(change):
    text=base.tool.INSTALL
    if change=='missing_flag':text=text.replace("'--no-download',",'')
    elif change=='duplicate_flag':text+='\n'+"'--no-download',"
    else:text=text.replace("'--assume-yes'","'--unreviewed-yes'")
    with pytest.raises(RuntimeError):r.installer(SimpleNamespace(INSTALL=text))


def test_new_scope_receipt_reflects_two_edits_and_still_runs_exact_offline_probe(tmp_path,monkeypatch):
    pf,tool,d,state,_=base.harness(tmp_path,monkeypatch)
    monkeypatch.setattr(r,'ROOT',base.r.ROOT);monkeypatch.setattr(r,'OLD',base.r.OLD)
    result=r.perform(pf,tool,d,derived)
    assert result['stage']=='MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED'
    assert result['tool_sha256']==l.H(derived) and result['base_resumer_sha256']==l.BASE_SHA
    assert result['installer_edits']==['trusted_sbin_path','local_absolute_deb_acquisition']
    assert result['physical_offline_build'] is True and result['local_absolute_deb_acquisition_without_no_download'] is True
    assert result['official_debian_package_network_fetch_performed'] is False and result['added_package_count']==194
    assert '--network=none' in state['calls'][0] and '--pull=false' in state['calls'][0]
    assert state['calls'][1][-1]==base.tool.PROBE and state['baseline']==3 and state['old_reads']==3
    assert Path(result['receipt_path']).parent.name=='media-asset-studio-toolchain-'+l.H(derived)[:12]+'-20261101'


def test_original8f_and_all194_source_objects_are_never_modified():
    assert (HERE/'resume_toolchain.py').read_bytes()==old and l.H(old)==l.BASE_SHA
    assert r.copy_context.__code__.co_code==base.r.copy_context.__code__.co_code
    assert r.probe_command('x',r.IMAGE,base.tool.PROBE)==base.r.probe_command('x',r.IMAGE,base.tool.PROBE)
    assert r.dockerfile()==base.r.dockerfile()


def test_small_command_pins_loader_and_derived_bytes_without_any_server_execution():
    body=(HERE/'resume_local_acquire.py').read_bytes();command,pins=maker.generate(body,derived)
    assert pins['command_bytes']==len(command.encode())<14000 and pins['loader_sha256']==l.H(body) and pins['derived_resumer_sha256']==l.H(derived)
    assert pins['executed'] is False and pins['network_fetch_performed'] is False and pins['physical_offline_build'] is True
    script=command.split("<<'EXACT194_PHYSICAL_OFFLINE_LOCAL_ACQUIRE'\n",1)[1].rsplit('\nEXACT194_PHYSICAL_OFFLINE_LOCAL_ACQUIRE\n',1)[0];tree=ast.parse(script)
    payload=next(row for row in ast.walk(tree) if isinstance(row,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='body' for target in row.targets))
    assert zlib.decompress(base64.b64decode(ast.literal_eval(payload.value.args[0].args[0])))==body
    assert l.H(derived) in command and 'sys.exit(2)' in script


def test_no_new_network_package_download_or_production_operation_is_introduced():
    assert "'--network=none'" not in derived.decode()  # Delegates to exact reviewed capture helper.
    assert 'd.build_command(context)' in derived.decode() and "d.ENV={**d.ENV,'DOCKER_BUILDKIT':'0'}" in derived.decode()
    assert '--network=bridge' not in derived.decode() and '--download-only' not in derived.decode()
    assert 'unlink(' not in derived.decode() and 'rmtree' not in derived.decode()
