"""Synthetic configured merchant-view capture; no live data or provider calls."""
import ast
import base64
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


p=load(HERE/'preflight.py','merchant_capture_test')


def fixture(monkeypatch):
    calls=[];inventory={'main.py':'a'*64,'services/meta_operations_provider.py':'b'*64}
    rows={f'table_{index:03}':{'count':index+1,'rows_sha256':'c'*64,'shape_sha256':'d'*64} for index in range(150)}
    current={'State':{'Running':True},'Config':{'Env':['SYNTHETIC-NOT-EXPORTED']}}
    m=SimpleNamespace(inspect=lambda name:current,runtime=lambda info:p.RUNTIME,verify_secret_mount=lambda info:calls.append('secret-mount-metadata'),
        verify_production_worker_enabled=lambda info:calls.append('existing-workers'),retained=lambda:SimpleNamespace(require_safe_original_restart=lambda info:None),
        credential_boundary=lambda:{'metadata_only':True},BUSINESS=Path('/synthetic/business.db'),schema_signature=lambda *a:'e'*64,verify_public=lambda *a:'f'*64,
        NGINX=SimpleNamespace(read_bytes=lambda:b'synthetic current nginx'),run=lambda *a:b'synthetic active nginx')
    c=SimpleNamespace(ENV_FILE=Path('/synthetic/ops/runtime.env'))
    old=SimpleNamespace(core=SimpleNamespace(ENV_FILE=Path('/synthetic/read/runtime.env'),LEGACY_ENV_FILE=Path('/synthetic/old/runtime.env')),
        pf=SimpleNamespace(google_environment=lambda info:calls.append('google-cutoff')))
    flow=SimpleNamespace(m=m,c=c,environment=lambda info:('1'*64,'2'*64),ctx=SimpleNamespace(workflow=old),source_boundary=lambda info,inv:calls.append(('source-inventory',inv)),
        protections=lambda **kw:calls.append(('schema-private-static-credentials',kw)),rows=lambda:rows,retained=SimpleNamespace(evidence=lambda value:value,live_sequence_boundary=lambda left,right:None),
        proof={'database_identity':[1,2],'private_boundary':{'untouched':True},'content_security_policy_sha256':'3'*64},metadata=lambda path:{'metadata':True},
        safe=SimpleNamespace(GBP_ENV=Path('/synthetic/google/runtime.env'),protected_metadata=lambda path:calls.append(('lstat-only',str(path))) or {'metadata_only':True}),
        public=Path('/synthetic/current/public'),manifest={})
    monkeypatch.setattr(p,'dependencies',lambda:(None,flow,inventory))
    return flow,inventory,rows,calls


def test_current_receipt_pins_match_actual_latest_deployment():
    body=(ROOT/'outputs/meta-operations-read-polish-20261101/deployed.json').read_bytes();value=json.loads(body)
    assert p.H(body)==p.DEPLOYED_SHA and value['crm']==p.RUNTIME and value['source_sha']==p.SOURCE and value['frontend_version']==p.FRONTEND
    assert value['schema_revision']==p.REVISION and value['table_count']==150


def test_sample_preserves_all_nonempty_rows_inventory_and_only_lstats_credential_files(monkeypatch):
    flow,inventory,rows,calls=fixture(monkeypatch);value=p.sample()
    assert value['rows']==rows and value['backend_inventory']==inventory and value['backend_changed_before']=={name:None for name in p.BACKEND_OVERLAY}
    assert len(value['rows'])==150
    assert value['ops_execution_enabled'] is False and value['ops_scheduler_enabled'] is False and value['google_scheduler_enabled'] is True
    assert value['credential_file_content_read'] is False and 'Config' not in value
    assert len([call for call in calls if isinstance(call,tuple) and call[0]=='lstat-only'])==4
    assert ('schema-private-static-credentials',{'updated':True,'recovery':True}) in calls


def test_unknown_existing_projection_runtime_or_wrong_current_identity_is_rejected(monkeypatch):
    flow,inventory,rows,calls=fixture(monkeypatch);inventory['services/media_workspace.py']='9'*64
    with pytest.raises(RuntimeError,match='MERCHANT_PROJECTION_RUNTIME_MUST_START_ABSENT'):p.sample()
    inventory.pop('services/media_workspace.py');flow.m.runtime=lambda info:{**p.RUNTIME,'id':'0'*64}
    with pytest.raises(RuntimeError,match='EXACT_CURRENT_CONFIGURED_RUNTIME_REQUIRED'):p.sample()


def test_capture_writes_stable_full150_aggregate_proof_once(monkeypatch,tmp_path):
    flow,inventory,rows,calls=fixture(monkeypatch);writes=[]
    flow.c.write=lambda path,body:writes.append((path,body));monkeypatch.setattr(p,'ROOT',tmp_path)
    value=p.capture();assert value['table_count']==150 and value['all150_populated_tables_preserved'] is True and len(writes)==1
    assert json.loads(writes[0][1])['rows']==rows and 'SYNTHETIC-NOT-EXPORTED' not in writes[0][1].decode()
    assert value['permissions_changed'] is False and value['schema_changed'] is False and value['business_writes'] is False


@pytest.mark.parametrize('drift',['rows','private','environment','source','static'])
def test_any_populated_table_or_protected_boundary_change_blocks_proof_write(monkeypatch,tmp_path,drift):
    flow,inventory,rows,calls=fixture(monkeypatch);one=p.sample();two=copy.deepcopy(one)
    key={'rows':'rows','private':'private_boundary','environment':'environment_sha256','source':'backend_inventory_sha256','static':'public_inventory_sha256'}[drift]
    if drift=='rows':two['rows']['table_149']['count']+=1
    else:two[key]='changed'
    values=iter((one,two));writes=[];flow.c.write=lambda *a:writes.append(a)
    flow.retained.live_sequence_boundary=lambda a,b:None;monkeypatch.setattr(p,'sample',lambda:next(values));monkeypatch.setattr(p,'ROOT',tmp_path)
    with pytest.raises(RuntimeError,match='CURRENT_ALL150_BOUNDARIES_CHANGED_DURING_CAPTURE'):p.capture()
    assert writes==[]


def test_wrapper_is_exact_small_pinned_readonly_capture():
    m=load(HERE/'make_capture.py','merchant_capture_wrapper_test');body=(HERE/'preflight.py').read_bytes();command,pins=m.generate(body)
    assert command==(HERE/'capture-command.sh').read_text() and pins['command_bytes']<11000 and pins['executed'] is False
    script=command.split("<<'MERCHANT_VIEW_CAPTURE'\n",1)[1].rsplit('\nMERCHANT_VIEW_CAPTURE\n',1)[0];tree=ast.parse(script)
    packed=next(x.args[0].value for x in ast.walk(tree) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='b64decode')
    assert zlib.decompress(base64.b64decode(packed,validate=True))==body
    assert 'key_rotation_eligibility' not in body.decode() and 'new_schema(empty=True)' not in body.decode()
