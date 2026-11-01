"""Synthetic configured-runtime capture checks; no server or provider access."""
import ast
import base64
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


p=load(HERE/'preflight.py','read_polish_capture_test')
c=load(ROOT/'deployments/meta-operations-activation-20261101/core.py','read_polish_core_test')


@pytest.fixture
def environment(monkeypatch):
    old=['T24_META_ENABLED=true','T24_META_APP_ID=1139445441758834','T24_META_CONFIG_ID=1146714154579519',
         'T24_META_APP_SECRET=SYNTHETIC-OLD-READ-SECRET','T24_META_TOKEN_KEY='+base64.urlsafe_b64encode(b'O'*32).decode(),'T24_GBP_TOKEN_KEY=SYNTHETIC-OTHER-KEY']
    values={'ENABLED':'true','EXECUTION_ENABLED':'false','SCHEDULER_ENABLED':'false','APP_ID':c.APP_ID,'APP_SECRET':'SYNTHETIC-NEW-PUBLISHER-SECRET',
            'TOKEN_KEY':base64.urlsafe_b64encode(b'N'*32).decode(),'CONFIG_ID':c.CONFIG_ID,'GRAPH_VERSION':c.GRAPH_VERSION,'PUBLIC_URL':c.ORIGIN,'EXPECTED_SCOPES':','.join(c.SCOPES),'LOGIN_CONFIG_REVIEWED':'true'}
    ops=['T24_META_OPS_'+key+'='+value for key,value in sorted(values.items())];rows=old+ops
    monkeypatch.setattr(p,'FULL_ENV_SHA',p.digest(rows));monkeypatch.setattr(p,'OPS_ENV_FILE_SHA',p.H(('\n'.join(ops)+'\n').encode('ascii')))
    ctx=SimpleNamespace(workflow=SimpleNamespace(proof={'environment_sha256':p.digest(old)}))
    return rows,old,ops,ctx


def test_full_current_environment_preserved_with_eleven_ops_keys_and_writes_off(environment):
    rows,old,ops,ctx=environment
    assert p.environment(c,ctx,{'Config':{'Env':rows}})==(p.digest(rows),p.digest(ops))


@pytest.mark.parametrize('change',['old_order','ops_order','extra_ops','execution','scheduler','key_reuse','secret_reuse'])
def test_environment_or_permission_gate_drift_is_rejected(environment,change):
    rows,old,ops,ctx=environment;rows=list(rows)
    if change=='old_order':rows[0],rows[1]=rows[1],rows[0]
    if change=='ops_order':rows[-1],rows[-2]=rows[-2],rows[-1]
    if change=='extra_ops':rows.append('T24_META_OPS_SCHEDULER_ACTIVATION_FROM=2026-11-01T00:00:00Z')
    if change=='execution':rows=[x.replace('EXECUTION_ENABLED=false','EXECUTION_ENABLED=true') for x in rows]
    if change=='scheduler':rows=[x.replace('SCHEDULER_ENABLED=false','SCHEDULER_ENABLED=true') for x in rows]
    if change=='key_reuse':rows=[x if not x.startswith('T24_META_OPS_TOKEN_KEY=') else 'T24_META_OPS_TOKEN_KEY='+dict(x.split('=',1) for x in old)['T24_META_TOKEN_KEY'] for x in rows]
    if change=='secret_reuse':rows=[x if not x.startswith('T24_META_OPS_APP_SECRET=') else 'T24_META_OPS_APP_SECRET=SYNTHETIC-OLD-READ-SECRET' for x in rows]
    with pytest.raises(RuntimeError):p.environment(c,ctx,{'Config':{'Env':rows}})


def proof():
    rows={'table_'+str(index):{'count':index+1,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for index in range(150)}
    value={key:'synthetic' for key in ('schema_sha256','activated_receipt_sha256','environment_sha256','ops_environment_sha256','backend_inventory_sha256','nginx_sha256','active_nginx_sha256','public_root','public_inventory_sha256','content_security_policy_sha256')}
    return {**value,'stage':'META_OPERATIONS_READ_POLISH_READONLY_PREFLIGHT','host':p.HOST,'source_sha':p.SOURCE,'frontend_version':p.FRONTEND,'schema_revision':p.REVISION,
        'rows':rows,'database_metadata':{'synthetic':1},'crm':p.RUNTIME,'backend_file_count':396,'backend_changed_before':{'services/meta_operations_provider.py':'c'*64},
        'all150_populated_tables_preserved':True,'ops_execution_enabled':False,'ops_scheduler_enabled':False,'credential_file_content_read':False,'private_content_read':False,
        'business_writes':False,'provider_requests':False,'runtime_changed':False}


def test_capture_preserves_all_nonempty_tables_and_only_writes_aggregate_proof(monkeypatch,tmp_path):
    value=proof();writes=[];monkeypatch.setattr(p,'ROOT',tmp_path)
    core=SimpleNamespace(write=lambda path,body:writes.append((path,body)))
    ctx=SimpleNamespace(workflow=SimpleNamespace(retained=SimpleNamespace(live_sequence_boundary=lambda left,right:None)))
    monkeypatch.setattr(p,'sample',lambda:dict(value));monkeypatch.setattr(p,'dependencies',lambda:(core,None,ctx))
    result=p.capture();assert result['table_count']==150 and result['all150_populated_tables_preserved'] is True and len(writes)==1
    stored=json.loads(writes[0][1]);assert stored['rows']==value['rows'] and all(row['count']>0 for row in stored['rows'].values())
    assert 'Config' not in stored and result['credential_file_content_read'] is False and result['provider_requests'] is False


def test_capture_detects_independent_row_change_in_any_of_all150_tables(monkeypatch,tmp_path):
    value=proof();calls=iter([value,{**value,'rows':{**value['rows'],'table_149':{'count':999,'rows_sha256':'d'*64,'shape_sha256':'b'*64}}}]);writes=[]
    ctx=SimpleNamespace(workflow=SimpleNamespace(retained=SimpleNamespace(live_sequence_boundary=lambda left,right:None)))
    monkeypatch.setattr(p,'ROOT',tmp_path);monkeypatch.setattr(p,'sample',lambda:next(calls));monkeypatch.setattr(p,'dependencies',lambda:(SimpleNamespace(write=lambda *a:writes.append(a)),None,ctx))
    with pytest.raises(RuntimeError,match='CURRENT_ALL150_BASELINE_CHANGED_DURING_CAPTURE'):p.capture()
    assert writes==[]


def test_wrapper_exact_reproduction_and_no_execution_on_other_host():
    m=load(HERE/'make_capture.py','read_polish_wrapper_test');body=(HERE/'preflight.py').read_bytes();command,pins=m.generate(body)
    assert command==(HERE/'capture-command.sh').read_text() and pins['command_bytes']<11000
    script=command.split("<<'READ_POLISH_CAPTURE'\n",1)[1].rsplit('\nREAD_POLISH_CAPTURE\n',1)[0];tree=ast.parse(script)
    packed=next(x.args[0].value for x in ast.walk(tree) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='b64decode')
    assert zlib.decompress(base64.b64decode(packed,validate=True))==body
    assert "namespace['capture']()" in script and 'CURRENT_ALL150' in body.decode() and 'key_rotation_eligibility' not in body.decode()
