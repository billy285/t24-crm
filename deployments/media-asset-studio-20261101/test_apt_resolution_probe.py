"""Synthetic proposal/transport tests; no Docker, APT or network execution."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name,path);module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


probe = load('resolution_probe_test',HERE/'apt_resolution_probe.py')
tool = load('resolution_original_4fe_test',HERE/'toolchain.py')
maker = load('resolution_probe_maker_test',HERE/'make_apt_resolution_probe.py')


def test_existing_frozen_toolchain_is_exact_and_never_rewritten():
    assert probe.H((HERE/'toolchain.py').read_bytes()) == probe.TOOL_SHA == '4fe7ee52647ff1775c8b3e7ac9bce60208aa66806324d3c4a51f80ff23f16fe7'
    assert probe.TOP == tool.TOP
    assert probe.H((HERE/'toolchain-command.sh').read_bytes()) == 'c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075'


def test_exact_prefix_keeps_official_signed_sources_no_upgrades_and_stops_before_download_install():
    value = probe.probe_source(tool);ast.parse(value)
    assert "'--simulate'" in value and "'--no-remove','--no-upgrade'" in value
    assert "'APT::Get::AllowUnauthenticated=false'" in value and "'Acquire::AllowInsecureRepositories=false'" in value
    assert 'https://deb.debian.org/debian' in value and 'signed-by=/usr/share/keyrings/debian-archive-keyring.gpg' in value
    assert '--download-only' not in value and "'--assume-yes'" not in value and "SIGNED_APT_SHA256_REQUIRED" not in value
    assert "(OUT/'apt-error.log').write_bytes(p.stdout[:65536])" in value
    assert 'EXISTING_PACKAGE_UPGRADE_OR_DUPLICATE_REJECTED' in value and 'NO_REMOVAL_PERMITTED' in value


def test_changed_prefix_or_root_versions_fail_closed():
    with pytest.raises(RuntimeError):probe.probe_source(SimpleNamespace(TOP={**tool.TOP,'ffmpeg':'changed'},FETCH=tool.FETCH))
    with pytest.raises(RuntimeError):probe.probe_source(SimpleNamespace(TOP=tool.TOP,FETCH=tool.FETCH.replace(probe.MARKER,'')))


def collect(tmp_path, count=3, top_patch=None, metadata_patch=None):
    selected={**probe.TOP, **{f'libsynthetic{i}':'1.0' for i in range(count-3)}}
    if top_patch:selected.update(top_patch)
    rows=[]
    for name,version in selected.items():
        row={'Package':name,'Version':version,'Architecture':'all' if name.startswith('fonts-') else 'amd64','Filename':f'pool/main/s/synthetic/{name}_1.deb','SHA256':'a'*64,'Size':'1024','Installed-Size':'3'}
        if metadata_patch and name=='ffmpeg':row.update(metadata_patch)
        rows.append('\n'.join(f'{key}: {value}' for key,value in row.items()))
    (tmp_path/'lists').mkdir();(tmp_path/'lists'/'official_InRelease').write_bytes(b'SYNTHETIC SIGNED INDEX METADATA')
    def path(value):
        if value=='/var/lib/apt/lists':return tmp_path/'lists'
        if value=='/out/proposal.json':return tmp_path/'proposal.json'
        raise AssertionError('Unexpected proposal filesystem path')
    calls=[]
    def run(argv,timeout):
        calls.append(argv);assert argv[:2]==['/usr/bin/apt-cache','show'];return '\n\n'.join(rows)
    scope={'selected':selected,'TOP':probe.TOP,'before':{'existing-base':{'version':'unchanged'}},'run':run,'simulation':'PUBLIC SYNTHETIC APT PLAN','source':'FIXED OFFICIAL SIGNED SOURCES','Path':path,'H':probe.H,'re':__import__('re'),'json':json,'packages':lambda:{'existing-base':{'version':'unchanged'}}}
    exec(compile(probe.PROPOSAL,'<synthetic-proposal>','exec'),scope)
    return json.loads((tmp_path/'proposal.json').read_bytes()),calls


def test_public_proposal_has_complete_sha256_estimates_and_exact_top_diagnosis(tmp_path):
    value,calls=collect(tmp_path);probe.validate_proposal(value)
    assert value['selected_count']==3 and value['top_versions_match'] is True
    assert value['total_download_bytes']==3*1024 and value['estimated_installed_bytes']==3*3*1024
    assert len(calls)==1 and len(value['signed_inrelease_sha256'])==1
    assert value['installation_performed'] is value['package_download_performed'] is False


def test_over180_is_diagnosed_without_relaxing_installation_bounds_or_downloading(tmp_path):
    value,_=collect(tmp_path,count=181);probe.validate_proposal(value)
    assert value['selected_count']==181 and value['within_original_package_count_bound'] is False
    assert value['top_versions_match'] is True and value['package_download_performed'] is False


def test_root_version_mismatch_is_reported_separately_from_selected_count(tmp_path):
    value,_=collect(tmp_path,top_patch={'ffmpeg':'0.0-synthetic'});probe.validate_proposal(value)
    assert value['selected_count']==3 and value['within_original_package_count_bound'] is True and value['top_versions_match'] is False
    assert value['selected_top_versions']['ffmpeg']=='0.0-synthetic'


@pytest.mark.parametrize('patch',[{'SHA256':'bad'},{'Filename':'https://untrusted.invalid/a.deb'},{'Size':'-1'},{'Installed-Size':'not-a-number'}])
def test_unsigned_unsafe_or_unbounded_metadata_is_refused(tmp_path,patch):
    with pytest.raises(RuntimeError):collect(tmp_path,metadata_patch=patch)


def test_foreign_architecture_cannot_satisfy_complete_proposal(tmp_path):
    with pytest.raises(RuntimeError,match='COMPLETE_SIGNED_RESOLUTION_METADATA_REQUIRED'):collect(tmp_path,metadata_patch={'Architecture':'arm64'})


def test_only_new_isolated_container_and_new_public_bind_no_current_database_or_secrets():
    source=(HERE/'apt_resolution_probe.py').read_text();tree=ast.parse(source)
    assert "'--network','bridge'" in source and "'--entrypoint','/usr/bin/env'" in source
    assert "IMAGE,'-i','PATH=" in source and "'--no-healthcheck'" in source and "'--restart','no'" in source
    assert "'--mount','type=bind,src='+str(out)+',dst=/out'" in source
    assert 'Config.Env' not in source and 'crm_prod.db' not in source and 'docker exec' not in source
    assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'unlink','rmdir','remove'} for node in ast.walk(tree))
    assert 'old_toolchain_install_bounds_relaxed' in source


def test_generator_is_exact_small_hash_pinned_and_does_not_execute():
    body=(HERE/'apt_resolution_probe.py').read_bytes();command,pins=maker.generate(body)
    assert len(command.encode())==pins['command_bytes']<14000 and probe.H(body)==pins['probe_sha256']
    assert probe.H(command.encode())==pins['command_sha256'] and pins['executed'] is False
    ast.parse(command.split("<<'ASSET_PUBLIC_APT_PROPOSAL'\n",1)[1].rsplit('\nASSET_PUBLIC_APT_PROPOSAL\n',1)[0])
    assert 'DOCKER' not in command and 'installation_performed' in command
