"""Local synthetic credentials/files only; no server, browser or provider."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('meta_transport_core_test',HERE/'core.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


@pytest.fixture
def pins(monkeypatch):
    monkeypatch.setattr(c,'CONFIG_ID','2222222222222222');monkeypatch.setattr(c,'CONFIG_FREEZE_SHA','a'*64)


@pytest.fixture
def protected(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);monkeypatch.setattr(c,'OWNER_UID',os.getuid());monkeypatch.setattr(c,'FS_ANCHOR',tmp_path)
    leaf=tmp_path/'private';c.mkdir(leaf);return leaf


def env():
    values={'ENABLED':'true','APP_ID':c.APP_ID,'APP_SECRET':'SYNTHETIC_META_SECRET_12345678','TOKEN_KEY':base64.urlsafe_b64encode(b'x'*32).decode(),'CONFIG_ID':c.CONFIG_ID,'GRAPH_VERSION':c.GRAPH_VERSION,'PUBLIC_URL':c.ORIGIN,'EXPECTED_SCOPES':','.join(c.READ_SCOPES),'LOGIN_CONFIG_REVIEWED':'true'}
    return ['T24_META_'+key+'='+value for key,value in sorted(values.items())]


def test_unknown_config_and_review_freeze_fail_closed(monkeypatch):
    monkeypatch.setattr(c,'CONFIG_ID',None)
    with pytest.raises(c.GuardError,match='ACTUAL_USER_CONFIG_VERSION_AND_REVIEW_FREEZE_REQUIRED'):c.pins_ready()


@pytest.mark.parametrize('name,value',[('CONFIG_ID',c.FORBIDDEN_CONFIG_ID),('CONFIG_ID','not-id'),('GRAPH_VERSION',None),('GRAPH_VERSION','latest'),('CONFIG_FREEZE_SHA','0'*64),('CONFIG_FREEZE_SHA',None)])
def test_no_system_user_or_unreviewed_version_allowed(pins,monkeypatch,name,value):
    monkeypatch.setattr(c,name,value)
    with pytest.raises(c.GuardError):c.pins_ready()


def test_exact_nine_meta_env_only(pins):
    result=c.validate_meta_env(env());assert set(result)==c.META_KEYS and result['T24_META_APP_ID']=='1625116099132983'
    assert result['T24_META_GRAPH_VERSION']=='v26.0' and result['T24_META_ENABLED']=='true'


@pytest.mark.parametrize('change',['extra','duplicate','missing','newline','system','scopes','version','url','key','secret','disabled','review'])
def test_meta_env_rejects_injection_scope_or_identity_drift(pins,change):
    rows=env()
    if change=='extra':rows.append('T24_GBP_ENABLED=false')
    if change=='duplicate':rows[-1]=rows[0]
    if change=='missing':rows.pop()
    if change=='newline':rows[0]+='\nT24_GBP_ENABLED=false'
    for tag,key,value in [('system','CONFIG_ID',c.FORBIDDEN_CONFIG_ID),('scopes','EXPECTED_SCOPES',','.join(c.READ_SCOPES)+',instagram_content_publish'),('version','GRAPH_VERSION','v25.0'),('url','PUBLIC_URL','https://external.example'),('key','TOKEN_KEY','invalid'),('secret','APP_SECRET','bad secret'),('disabled','ENABLED','false'),('review','LOGIN_CONFIG_REVIEWED','false')]:
        if change==tag:rows=[('T24_META_'+key+'='+value) if row.startswith('T24_META_'+key+'=') else row for row in rows]
    with pytest.raises(c.GuardError):c.validate_meta_env(rows)


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
def test_wrong_or_unbounded_secret_object_rejected_without_echo(value):
    with pytest.raises(c.GuardError) as error:c.validate_credentials(value)
    assert 'SYNTHETIC' not in str(error.value)
