"""Offline authoring/attack tests; no real server, business DB or provider calls."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
import zlib

import pytest

HERE=Path(__file__).resolve().parent


def load(name):
    spec=importlib.util.spec_from_file_location('onboarding_capture_'+name,HERE/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_pins_current_deployment_and_fresh158_not_old_empty_tables():
    p=load('preflight');source=(HERE/'preflight.py').read_text()
    assert p.SOURCE=='f595f3acfb5bfc4a28dadd3ec181b65f7c540fdd' and p.FRONTEND=='c1d87dd771d8' and p.REVISION=='f21dc345d681'
    assert p.RUNTIME['id'].startswith('8671f4b6') and p.RUNTIME['image'].startswith('sha256:3b203190')
    assert "len(rows)==158" in source and "len(inventory)==414" in source
    assert 'recovery=True,head=REVISION,schema=SCHEMA_SHA' in source
    assert 'three_new_asset_studio_tables_empty' not in source
    assert set(p.NEW_TABLES)=={'google_business_onboarding_catalogs','google_business_onboarding_batches','google_business_onboarding_items','google_business_onboarding_requests'}


def test_readonly_business_markers_are_aggregates_and_do_not_replay_pilot_counts(tmp_path):
    p=load('preflight');path=tmp_path/'synthetic.db'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE google_business_bindings(id INTEGER PRIMARY KEY,active INTEGER)');con.executemany('INSERT INTO google_business_bindings VALUES(?,1)',[(i,) for i in range(15)])
        con.execute('CREATE TABLE media_monthly_workflows(status TEXT)');con.execute("INSERT INTO media_monthly_workflows VALUES('prepared')")
        con.execute('CREATE TABLE media_asset_jobs(status TEXT)');con.executemany('INSERT INTO media_asset_jobs VALUES(?)',[('adopted',)]*3)
    before=hashlib.sha256(path.read_bytes()).hexdigest();result=p.business_markers(path)
    assert result=={'google_binding_count':15,'google_active_binding_count':15,'monthly_workflow_status_counts':{'prepared':1},'asset_job_status_counts':{'adopted':3}}
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    with sqlite3.connect(path) as con:con.execute('UPDATE google_business_bindings SET active=0 WHERE id=0')
    with pytest.raises(RuntimeError,match='EXACT_CURRENT15_ACTIVE_BINDINGS_REQUIRED'):p.business_markers(path)


def test_engine_metadata_is_fixed_readonly_without_app_import_or_apt():
    p=load('preflight');tree=ast.parse(p.ENGINE_METADATA)
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):assert node.func.attr not in {'write_text','write_bytes','mkdir','unlink','rename','replace','chmod','chown'}
        if isinstance(node,ast.ImportFrom):assert node.module in {'pathlib','PIL'}
    assert "socket.socket.connect=blocked" in p.ENGINE_METADATA
    assert "subprocess.check_output([ffmpeg,'-version']" in p.ENGINE_METADATA
    assert 'apt-get' not in p.ENGINE_METADATA and 'pip install' not in p.ENGINE_METADATA
    assert '/app/backend/data' not in p.ENGINE_METADATA and 'services.' not in p.ENGINE_METADATA


def synthetic():
    p=load('preflight');names=['old_'+str(i) for i in range(154)]+['google_business_bindings','media_asset_profiles','media_asset_jobs','media_asset_requests','media_monthly_workflows']
    names.remove('old_153');assert len(names)==158
    rows={name:{'count':1,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for name in names}
    rows['google_business_bindings']['count']=15;rows['media_asset_jobs']['count']=2;rows['media_asset_requests']['count']=5
    keys=('host','source_sha','frontend_version','schema_revision','deployed_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256','backend_inventory_sha256','backend_file_count','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','csp_environment_override_present','new_onboarding_worker_env_present','all158_current_tables_preserved','ops_execution_enabled','ops_scheduler_enabled','google_scheduler_enabled','google_scheduler_activation_from','existing_asset_worker_enabled','business_markers')
    first={k:None for k in keys};first.update(rows=rows,database_metadata={'counter':1})
    engine={'pillow':'12.3.0','font_name':['Noto Sans CJK SC','Regular']}
    return p,first,engine


def setup_capture(monkeypatch,tmp_path,values):
    p,_,engine=synthetic();writes=[];monkeypatch.setattr(p,'ROOT',tmp_path)
    monkeypatch.setattr(p,'sample',lambda:copy.deepcopy(values.pop(0)));monkeypatch.setattr(p,'engine_metadata',lambda:engine)
    core=SimpleNamespace(write=lambda path,body:writes.append((path,body)),read=lambda *a,**k:pytest.fail('Unexpected old receipt read'))
    flow=SimpleNamespace(c=core,retained=SimpleNamespace(live_sequence_boundary=lambda *a:None));monkeypatch.setattr(p,'dependencies',lambda:(None,flow,None))
    return p,writes


def test_two_fresh158_samples_write_only_aggregate_new_receipt(monkeypatch,tmp_path):
    _,first,_=synthetic();p,writes=setup_capture(monkeypatch,tmp_path,[first,first]);summary=p.capture()
    assert len(writes)==1 and writes[0][0].name.startswith('google-business-onboarding-preflight-')
    assert summary['sha256']==p.H(writes[0][1]) and summary['table_count']==158 and 'rows' not in summary
    assert json.loads(writes[0][1])['rows']==first['rows']
    assert summary['observed_asset_job_count']==2 and summary['observed_asset_request_count']==5
    assert all(summary[k] is False for k in ('installation_performed','worker_started','schema_changed','permissions_changed','credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed'))


@pytest.mark.parametrize('kind',['finance','packet','binding','asset','source','environment','nginx'])
def test_any_current_row_or_protection_drift_stops_before_write(monkeypatch,tmp_path,kind):
    _,first,_=synthetic();changed=copy.deepcopy(first)
    if kind in {'finance','packet','binding','asset'}:
        key={'finance':'old_0','packet':'media_monthly_workflows','binding':'google_business_bindings','asset':'media_asset_jobs'}[kind]
        changed['rows'][key]['rows_sha256']='c'*64
    else:changed[{'source':'backend_inventory_sha256','environment':'environment_sha256','nginx':'nginx_sha256'}[kind]]='c'*64
    p,writes=setup_capture(monkeypatch,tmp_path,[first,changed])
    with pytest.raises(RuntimeError,match='CURRENT158_BOUNDARIES_CHANGED_DURING_CAPTURE'):p.capture()
    assert not writes


def test_short_capture_exact_embedded_source_reproduced():
    maker=load('make_capture');body=(HERE/'preflight.py').read_bytes();command,pins=maker.generate(body);again,pins2=maker.generate(body)
    assert command==again and pins==pins2 and len(command.encode())<14000
    data=ast.parse(command.split("<<'GOOGLE_ONBOARDING_READONLY_CAPTURE'\n",1)[1].rsplit('\nGOOGLE_ONBOARDING_READONLY_CAPTURE',1)[0])
    strings=[node.value for node in ast.walk(data) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
    packed=next(x for x in strings if len(x)>2000 and re.fullmatch('[A-Za-z0-9+/=]+',x))
    assert zlib.decompress(base64.b64decode(packed,validate=True))==body
    assert pins['preflight_sha256']==hashlib.sha256(body).hexdigest() and pins['command_sha256']==hashlib.sha256(command.encode()).hexdigest()
    assert pins['executed'] is False and pins['business_writes'] is False and pins['provider_requests'] is False


def test_capture_body_size_failclosed():
    maker=load('make_capture')
    for body in (b'',b'x'*65536):
        with pytest.raises(RuntimeError,match='BOUNDED_CAPTURE_SOURCE_REQUIRED'):maker.generate(body)
