"""Local synthetic credentials/files only; no server, browser or provider."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('meta_crm_transport_core_test',HERE/'core.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


@pytest.fixture
def pins(monkeypatch):
    monkeypatch.setattr(c,'APP_ID','7777777777777777');monkeypatch.setattr(c,'SOURCE_SHA','a'*40);monkeypatch.setattr(c,'FRONTEND','6'*12);monkeypatch.setattr(c,'ORIGINAL_ID','1'*64);monkeypatch.setattr(c,'IMAGE','sha256:'+'2'*64);monkeypatch.setattr(c,'DEPLOYED_SHA','3'*64);monkeypatch.setattr(c,'RELEASE_TOOL_SHA','4'*64);monkeypatch.setattr(c,'BUSINESS_ID','1772407487098568');monkeypatch.setattr(c,'GRAPH_VERSION','v26.0');monkeypatch.setattr(c,'CONFIG_ID','2222222222222222');monkeypatch.setattr(c,'CONFIG_FREEZE_SHA','a'*64)


@pytest.fixture
def protected(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);monkeypatch.setattr(c,'OWNER_UID',os.getuid());monkeypatch.setattr(c,'FS_ANCHOR',tmp_path)
    leaf=tmp_path/'private';c.mkdir(leaf);return leaf


def env():
    values={'EXECUTION_ENABLED':'false','SCHEDULER_ENABLED':'false','ENABLED':'true','APP_ID':c.APP_ID,'APP_SECRET':'SYNTHETIC_META_SECRET_12345678','TOKEN_KEY':base64.urlsafe_b64encode(b'x'*32).decode(),'CONFIG_ID':c.CONFIG_ID,'GRAPH_VERSION':c.GRAPH_VERSION,'PUBLIC_URL':c.ORIGIN,'EXPECTED_SCOPES':','.join(c.SCOPES),'LOGIN_CONFIG_REVIEWED':'true'}
    return ['T24_META_OPS_'+key+'='+value for key,value in sorted(values.items())]


def test_unknown_config_and_review_freeze_fail_closed(pins,monkeypatch):
    monkeypatch.setattr(c,'CONFIG_ID',None)
    with pytest.raises(c.GuardError,match='ACTUAL_SEPARATE_PUBLISHER_APP_CONFIG_AND_REVIEW_REQUIRED'):c.pins_ready()


def test_unknown_deployment_blocks_before_credentials(pins, monkeypatch):
    monkeypatch.setattr(c, 'DEPLOYED_SHA', None)
    with pytest.raises(c.GuardError, match='ACTUAL_DEPLOYED_OPERATIONS_RUNTIME_REQUIRED'): c.pins_ready()


@pytest.mark.parametrize('key', ['EXECUTION_ENABLED', 'SCHEDULER_ENABLED'])
def test_initial_activation_cannot_enable_real_execution_or_scheduler(pins, key):
    rows = [('T24_META_OPS_'+key+'=true') if row.startswith('T24_META_OPS_'+key+'=') else row for row in env()]
    with pytest.raises(c.GuardError, match='EXACT_REVIEWED_PUBLISHER_CONFIG_EXECUTION_OFF_REQUIRED'): c.validate_ops_env(rows)


@pytest.mark.parametrize('name,value',[('CONFIG_ID','1146714154579519'),('CONFIG_ID','not-id'),('GRAPH_VERSION',None),('GRAPH_VERSION','latest'),('CONFIG_FREEZE_SHA','0'*64),('CONFIG_FREEZE_SHA',None)])
def test_no_system_user_or_unreviewed_version_allowed(pins,monkeypatch,name,value):
    monkeypatch.setattr(c,name,value)
    with pytest.raises(c.GuardError):c.pins_ready()


def test_exact_nine_meta_env_only(pins):
    result=c.validate_ops_env(env());assert set(result)==c.OPS_KEYS and result['T24_META_OPS_APP_ID']=='7777777777777777'
    assert result['T24_META_OPS_GRAPH_VERSION']=='v26.0' and result['T24_META_OPS_ENABLED']=='true'


@pytest.mark.parametrize('change',['extra','duplicate','missing','newline','system','scopes','version','url','key','secret','disabled','review'])
def test_meta_env_rejects_injection_scope_or_identity_drift(pins,change):
    rows=env()
    if change=='extra':rows.append('T24_GBP_ENABLED=false')
    if change=='duplicate':rows[-1]=rows[0]
    if change=='missing':rows.pop()
    if change=='newline':rows[0]+='\nT24_GBP_ENABLED=false'
    for tag,key,value in [('system','CONFIG_ID','1146714154579519'),('scopes','EXPECTED_SCOPES',','.join(c.SCOPES)+',business_management'),('version','GRAPH_VERSION','v25.0'),('url','PUBLIC_URL','https://external.example'),('key','TOKEN_KEY','invalid'),('secret','APP_SECRET','bad secret'),('disabled','ENABLED','false'),('review','LOGIN_CONFIG_REVIEWED','false')]:
        if change==tag:rows=[('T24_META_OPS_'+key+'='+value) if row.startswith('T24_META_OPS_'+key+'=') else row for row in rows]
    with pytest.raises(c.GuardError):c.validate_ops_env(rows)


@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'{"a":NaN}',b'[]',b'{bad',b'null'])
def test_json_duplicate_nonfinite_and_nonobject_rejected(raw):
    with pytest.raises(c.GuardError):c.strict_json(raw)


def test_file_write_exclusive_root_mode_and_bounded_read(protected):
    path=protected/'value.json';sha=c.write(path,{'only':'synthetic'});assert c.read(path,sha=sha)==b'{\n  "only": "synthetic"\n}\n'
    assert path.stat().st_mode&0o777==0o600 and protected.stat().st_mode&0o777==0o700
    with pytest.raises(FileExistsError):c.write(path,b'overwrite')
    with pytest.raises(c.GuardError):c.read(path,maximum=1)
    with pytest.raises(c.GuardError):c.read(path,sha='0'*64)


@pytest.mark.parametrize('kind',['symlink','hardlink','world','parent','outside'])
def test_private_file_path_metadata_is_not_relaxed(protected,tmp_path,kind):
    path=protected/'original';c.write(path,b'SYNTHETIC_ONLY')
    if kind=='symlink':(protected/'link').symlink_to(path);path=protected/'link'
    if kind=='hardlink':os.link(path,protected/'other')
    if kind=='world':path.chmod(0o644)
    if kind=='parent':protected.chmod(0o777)
    if kind=='outside':path=tmp_path.parent/'outside'
    with pytest.raises(c.GuardError):c.read(path)


@pytest.mark.parametrize('value',[{'app_id':'other','app_secret':'SYNTHETIC_META_SECRET_12345678'},{'app_id':c.APP_ID,'app_secret':'SYNTHETIC_META_SECRET_12345678','extra':'x'},{'app_id':c.APP_ID,'app_secret':'short'},{'app_id':c.APP_ID,'app_secret':'SYNTHETIC_META_SECRET\nINJECT=true'}])
def test_wrong_or_unbounded_secret_object_rejected_without_echo(value,pins):
    with pytest.raises(c.GuardError) as error:c.validate_credentials(value)
    assert 'SYNTHETIC' not in str(error.value)


def test_both_old_apps_and_all_old_configurations_are_rejected(pins,monkeypatch):
    for value in ('1139445441758834','1625116099132983'):
        monkeypatch.setattr(c,'APP_ID',value)
        with pytest.raises(c.GuardError):c.pins_ready()
    monkeypatch.setattr(c,'APP_ID','7777777777777777')
    for value in ('1146714154579519','1786801695686024','941072098875174'):
        monkeypatch.setattr(c,'CONFIG_ID',value)
        with pytest.raises(c.GuardError):c.pins_ready()


def test_new_key_retries_collision_with_any_available_old_runtime_key(monkeypatch):
    old=base64.urlsafe_b64encode(b'x'*32).decode();fresh=base64.urlsafe_b64encode(b'y'*32).decode();values=iter([b'x'*32,b'y'*32]);monkeypatch.setattr(c.os,'urandom',lambda size:next(values))
    assert c.independent_fernet_key(['T24_META_ENABLED=true','T24_META_APP_ID=1139445441758834','T24_META_CONFIG_ID=1146714154579519','T24_META_APP_SECRET=READ_SECRET_CANARY_1234','T24_META_TOKEN_KEY='+old,'T24_GBP_TOKEN_KEY=OTHER'])==fresh
    monkeypatch.setattr(c.os,'urandom',lambda size:b'x'*32)
    with pytest.raises(c.GuardError,match='PUBLISHER_KEY_COLLIDES_WITH_EXISTING_RUNTIME_KEY'):c.independent_fernet_key(['T24_META_ENABLED=true','T24_META_APP_ID=1139445441758834','T24_META_CONFIG_ID=1146714154579519','T24_META_APP_SECRET=READ_SECRET_CANARY_1234','T24_META_TOKEN_KEY='+old])
