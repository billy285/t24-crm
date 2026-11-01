"""Synthetic exact194 closure and data-only loader tests; no server execution."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
import pytest

HERE=Path(__file__).resolve().parent


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


retry=load('exact194_retry_test',HERE/'toolchain_retry.py')
maker=load('exact194_retry_maker_test',HERE/'make_toolchain_retry.py')
original=(HERE/'toolchain.py').read_bytes()
variant=retry.derive_variant(original)
module=ModuleType('derived_exact194_test');exec(compile(variant,'<derived-exact194>','exec'),module.__dict__)


def proposal():
    versions={**module.TOP,**{f'libsynthetic{i}':'1.0' for i in range(191)}}
    rows={name:{'version':version,'architecture':'amd64','sha256':'a'*64,'download_bytes':1024,'installed_bytes':2048,'official_pool_path':f'pool/main/s/synthetic/{name}_1.deb'} for name,version in versions.items()}
    return {'stage':'PUBLIC_RENDER_DEPENDENCY_RESOLUTION_PROPOSED','selected_count':194,'selected_new_versions':versions,'selected_packages':rows,'expected_top_versions':module.TOP,'selected_top_versions':module.TOP,'top_versions_match':True,'base_packages_unchanged':True,'installation_performed':False,'package_download_performed':False,'business_or_credentials_mounted':False,'total_download_bytes':194*1024,'estimated_installed_bytes':194*2048}


def downloaded(value):
    return {name:{'version':row['version'],'architecture':row['architecture'],'sha256':row['sha256'],'bytes':row['download_bytes'],'file':name+'_1.deb','official_pool_path':row['official_pool_path']} for name,row in value['selected_packages'].items()}


def test_frozen4fe_and_c1b0_remain_exact_unchanged_and_variant_is_deterministic():
    assert retry.H(original)==retry.TOOL_SHA
    assert retry.H((HERE/'toolchain-command.sh').read_bytes())==retry.COMMAND_SHA
    assert retry.derive_variant(original)==variant and variant!=original
    ast.parse(variant)
    with pytest.raises(RuntimeError,match='EXACT_FROZEN4FE_SOURCE_REQUIRED'):retry.derive_variant(original+b'\n')


def test_extracts_only_pinned33e_preflight_data_from_old_verified_shell_without_execution():
    command=(HERE/'toolchain-command.sh').read_bytes();body=retry.recover_preflight(command,original)
    assert retry.H(body)==retry.PREFLIGHT_SHA and body==(HERE/'preflight.py').read_bytes()
    with pytest.raises(RuntimeError):retry.recover_preflight(command.replace(b'set -eu',b'set +eu'),original)


def test_only_exact194_approved_versions_allowed_not_a_generic_higher_cap():
    value=proposal();assert len(module.validate_approved_proposal(value))==194
    for changed in [{**value,'selected_count':193},{**value,'selected_count':195},{**value,'top_versions_match':False},{**value,'selected_top_versions':{}},{**value,'installation_performed':True}]:
        with pytest.raises(RuntimeError):module.validate_approved_proposal(changed)
    changed=copy.deepcopy(value);changed['selected_packages'].pop(next(iter(changed['selected_packages'])))
    with pytest.raises(RuntimeError):module.validate_approved_proposal(changed)


@pytest.mark.parametrize('field,value',[('version','other'),('architecture','arm64'),('sha256','b'*64),('bytes',999),('official_pool_path','pool/foreign/item.deb')])
def test_downloaded_closure_must_match_each_exact_approved_field(field,value):
    approved=proposal();packages=downloaded(approved);module.validate_downloaded_proposal(packages,approved)
    packages['ffmpeg'][field]=value
    with pytest.raises(RuntimeError,match='DOWNLOADED_PACKAGE_DIFFERS_FROM_APPROVED_PROPOSAL'):module.validate_downloaded_proposal(packages,approved)


def test_original512MiB_and1GiB_total_bounds_remain_unchanged():
    value=proposal();value['selected_packages']['ffmpeg']['download_bytes']=536870913;value['total_download_bytes']=sum(row['download_bytes'] for row in value['selected_packages'].values())
    with pytest.raises(RuntimeError,match='ORIGINAL_DOWNLOAD_AND_INSTALL_BOUNDS_REQUIRED'):module.validate_approved_proposal(value)
    value=proposal();value['selected_packages']['ffmpeg']['installed_bytes']=1073741825;value['estimated_installed_bytes']=sum(row['installed_bytes'] for row in value['selected_packages'].values())
    with pytest.raises(RuntimeError):module.validate_approved_proposal(value)


def test_fetch_pins_readonly_proposal_and_each_current_signed_download_plus_approved_metadata():
    fetch=module.FETCH
    assert retry.APPROVED_SHA in fetch and "Path('/approved/proposal.json').read_bytes()" in fetch
    assert "len(selected)!=194 or selected!=approved['selected_new_versions']" in fetch
    assert 'SIGNED_APT_SHA256_REQUIRED' in fetch and 'SIGNED_DOWNLOAD_DIFFERS_FROM_APPROVED_PROPOSAL' in fetch
    assert "'installed_bytes':int(row.get('Installed-Size','0'))*1024" in fetch
    assert "'--no-remove','--no-upgrade'" in fetch and "'APT::Get::AllowUnauthenticated=false'" in fetch
    assert "3<=len(selected)<=180" not in fetch


def test_host_fetch_mounts_are_exact_newout_rw_and_approvedfile_ro_only():
    source=variant.decode()
    assert "',dst=/approved/proposal.json,readonly'" in source
    assert "len(info['Mounts']) == 2" in source
    assert "'/approved/proposal.json',False,'bind'" in source and "'/out',True,'bind'" in source
    assert 'EXACT_APPROVED194_AGGREGATE_SIZES_REQUIRED' in source
    assert "'approved_proposal_sha256':APPROVED_PROPOSAL_SHA" in source
    assert 'copy_public_package(' in source and 'TOOLCHAIN_MUST_NOT_CHANGE_408_BACKEND_FILES' in source


def test_offline_install_manifest_requires_exact_approved_proposal_receipt():
    assert retry.APPROVED_SHA in module.INSTALL and "len(manifest['packages'])!=194" in module.INSTALL
    assert '--no-download' in module.INSTALL and 'ONLY_REVIEWED_ADDED_PACKAGES_REQUIRED' in module.INSTALL
    assert "'--network=none'" in variant.decode() and "'--pull=false'" in variant.decode()


def test_short_loader_hashes_all_inputs_and_has_no_direct_network_or_mutation_before_reviewed_run():
    source=(HERE/'toolchain_retry.py').read_bytes();command,pins=maker.generate(source)
    assert pins['variant_sha256']==retry.H(variant) and pins['command_bytes']<14000
    assert pins['approved_package_count']==194 and pins['approved_proposal_sha256']==retry.APPROVED_SHA
    assert pins['old_source_modified'] is pins['executed'] is False
    assert retry.H(command.encode())==pins['command_sha256']
    ast.parse(command.split("<<'EXACT194_PUBLIC_TOOLCHAIN_RETRY'\n",1)[1].rsplit('\nEXACT194_PUBLIC_TOOLCHAIN_RETRY\n',1)[0])
    assert b'os.O_NOFOLLOW' in source and b'fields(before)==fields(opened)==fields(path.lstat())' in source
    assert b'write_text' not in source and b'write_bytes' not in source and b'urlopen' not in source
