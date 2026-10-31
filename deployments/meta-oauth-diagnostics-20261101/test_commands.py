"""Carrier wrapper generation/AST only; no remote or production operations."""
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('diag_immutable_commands_test',HERE/'make_commands.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SUMMARY=json.loads((HERE.parents[1]/'outputs/meta-oauth-diagnostics-20261101/preflight-summary.json').read_bytes());CARRIER='b'*40

@pytest.fixture
def carrier(tmp_path,monkeypatch):
    for name in ('release.py','preflight.py','artifacts/payload.tar.gz','artifacts/manifest.json'):
        target=tmp_path/name;target.parent.mkdir(exist_ok=True);shutil.copyfile(HERE/name,target)
    monkeypatch.setattr(m,'HERE',tmp_path)
    def git(args):
        if args[1]=='rev-parse':return b'EXACT_SYNTHETIC_APP_TREE'
        assert args[1]=='show' and args[2].startswith(CARRIER+':'+m.DIRECTORY+'/');return (HERE/args[2].split(m.DIRECTORY+'/',1)[1]).read_bytes()
    monkeypatch.setattr(m.subprocess,'check_output',git);return tmp_path


def prepared():
    manifest=json.loads((HERE/'artifacts/manifest.json').read_bytes());value={'stage':'META_OAUTH_DIAGNOSTICS_PREPARED','source_sha':m.r.SOURCE_SHA,'frontend_version':m.r.FRONTEND,'schema_revision':m.r.REVISION,'schema_sha256':SUMMARY['schema_sha256'],'table_count':141,'manifest_sha256':m.H((HERE/'artifacts/manifest.json').read_bytes()),'payload_sha256':manifest['payload_sha256'],'preflight_sha256':SUMMARY['sha256'],'_canonical_sha256':'c'*64}
    for key in ('backend_only','all_current_rows_schema_metadata_preserved','existing_meta_rows_preserved','offline_credentials_absent','offline_network_none','offline_workers_off','python310_and_exact_routes_verified','frontend_static_nginx_csp_unchanged'):value[key]=True
    for key in ('original_inspect_credentials_persisted','provider_requests','production_database_written','runtime_environment_changed'):value[key]=False
    return value


def test_only_prepare_until_actual_canonical_prepared_receipt_then_reviewed_switch(carrier):
    commands,pins=m.generate(CARRIER,SUMMARY);assert set(commands)=={'prepare-command.sh'} and pins['executed'] is False
    commands,pins=m.generate(CARRIER,SUMMARY,prepared());assert set(commands)=={'prepare-command.sh','activate-command.sh','recover-command.sh'}
    for name,body in commands.items():
        assert len(body.encode())<11000;code=body.split("<<'WORKFLOW'\n",1)[1].rsplit('WORKFLOW\n',1)[0];ast.parse(code)
        assert 'meta-oauth-diagnostics-' in code and '-20261101' in code
        if name=='prepare-command.sh':assert code.index('os.geteuid()==0')<code.index('opener.open') and 'ProxyHandler({})' in code and 'redirect_request' in code
        else:assert '--review-sha256' in code and 'c'*64 in code and 'urllib' not in code
        assert 'SYNTHETIC_META_SECRET' not in code


@pytest.mark.parametrize('name',['release.py','preflight.py','artifacts/payload.tar.gz','artifacts/manifest.json'])
def test_source_carrier_tamper_refused(carrier,name):
    path=carrier/name;path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(RuntimeError,match='EXACT_COMMITTED_MEMBER_REQUIRED'):m.generate(CARRIER,SUMMARY)


@pytest.mark.parametrize('field,value',[('table_count',140),('frontend_static_nginx_csp_unchanged',False),('original_inspect_credentials_persisted',True),('provider_requests',True),('_canonical_sha256',None)])
def test_incomplete_offline_acceptance_never_emits_switch(carrier,field,value):
    row=prepared();row[field]=value
    with pytest.raises(RuntimeError):m.generate(CARRIER,SUMMARY,row)
