"""Real read-only SQLite key gates and synthetic current-boundary capture."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
c=load('crm_rotation_core',HERE/'core.py');b=load('crm_rotation_baseline',HERE/'baseline.py');r=load('crm_rotation_metadata_guard',HERE.parent/'meta-business-20261031/release.py');b.configure(c)


def database(path):
    with sqlite3.connect(path) as con:
        for name in ('meta_business_connections','meta_business_assets','meta_business_bindings','meta_business_requests'):con.execute('CREATE TABLE '+name+'(id INTEGER PRIMARY KEY)')
        con.execute('CREATE TABLE meta_business_oauth_states(id INTEGER PRIMARY KEY,consumed INTEGER,flow_encrypted TEXT,expires_at TEXT)')
        con.executemany('INSERT INTO meta_business_oauth_states VALUES(?,1,?,?)',[(i,'','2020-01-01') for i in (1,2,3)])


def test_initial_exact_three_consumed_empty_is_readonly_and_key_safe(tmp_path):
    path=tmp_path/'db';database(path);before=path.read_bytes();facts=b.key_rotation_eligibility(path,initial=True)
    assert facts['oauth_flow_count']==3 and facts['safe_to_rotate'] is True and facts['unconsumed_or_encrypted_flow_count']==0 and path.read_bytes()==before


@pytest.mark.parametrize('kind',['connection','asset','binding','request','encrypted','pending','expired_encrypted','missing','extra'])
def test_key_rotation_refuses_any_potential_old_encryption_or_unexpected_flow_count(tmp_path,kind):
    path=tmp_path/'db';database(path)
    with sqlite3.connect(path) as con:
        if kind in {'connection','asset','binding','request'}:con.execute('INSERT INTO '+{'connection':'meta_business_connections','asset':'meta_business_assets','binding':'meta_business_bindings','request':'meta_business_requests'}[kind]+' VALUES(1)')
        elif kind in {'encrypted','expired_encrypted'}:con.execute("UPDATE meta_business_oauth_states SET flow_encrypted='OPAQUE_ENCRYPTED_VALUE' WHERE id=1")
        elif kind=='pending':con.execute('UPDATE meta_business_oauth_states SET consumed=0 WHERE id=1')
        elif kind=='missing':con.execute('DELETE FROM meta_business_oauth_states WHERE id=3')
        else:con.execute("INSERT INTO meta_business_oauth_states VALUES(4,1,'','2020-01-01')")
    before=path.read_bytes()
    with pytest.raises(c.GuardError,match='META_DATA_REQUIRES_EXISTING_KEY_OR_MANUAL_RECOVERY'):b.key_rotation_eligibility(path,initial=True)
    assert path.read_bytes()==before


def test_recovery_allows_only_later_consumed_empty_flows_but_never_new_key_dependent_data(tmp_path):
    path=tmp_path/'db';database(path)
    with sqlite3.connect(path) as con:con.execute("INSERT INTO meta_business_oauth_states VALUES(4,1,'','2020-01-01')")
    assert b.key_rotation_eligibility(path,initial=False)['oauth_flow_count']==4
    with sqlite3.connect(path) as con:con.execute("UPDATE meta_business_oauth_states SET flow_encrypted='NEW_KEY_CIPHERTEXT' WHERE id=4")
    with pytest.raises(c.GuardError):b.key_rotation_eligibility(path,initial=False)


def sample():
    counters={'monthly_deduction_rates':326419,'other':7}
    return {'rows':{str(i):{'count':1,'rows_sha256':'x'} for i in range(141)},'database_metadata':{'pragma_sha256':'p','sequence_exists':True,'sequence_values':counters,'sequence_sha256':r.digest(sorted(counters.items()))},'crm':{'id':'current'},'key_rotation_eligibility':{'oauth_flow_count':3,'safe_to_rotate':True},'private':'same'}


def test_capture_with_unknown_new_pins_allows_only_known_independent_counter(monkeypatch):
    first=sample();latest=copy.deepcopy(first);latest['database_metadata']['sequence_values']['monthly_deduction_rates']+=1;latest['database_metadata']['sequence_sha256']=r.digest(sorted(latest['database_metadata']['sequence_values'].items()));values=iter([first,latest]);saved={}
    fake=SimpleNamespace(server_guard=lambda:None,pins_ready=lambda:pytest.fail('No App pins required for old-state capture'),need=c.need,ROOT=Path('/synthetic'),mkdir=lambda _:None,write=lambda path,value:saved.setdefault('proof',value) and 'a'*64,SOURCE_SHA=c.SOURCE_SHA,FRONTEND=c.FRONTEND,SCHEMA_REVISION=c.SCHEMA_REVISION,ACTIVATION_FROM=c.ACTIVATION_FROM)
    b.configure(fake);monkeypatch.setattr(b,'collect',lambda:next(values));monkeypatch.setattr(b,'dependencies',lambda:SimpleNamespace(ctx=SimpleNamespace(release=r)))
    result=b.capture();assert result['table_count']==141 and result['credential_file_content_read'] is False and saved['proof']==latest
    b.configure(c)


def test_capture_wrapper_exactly_embeds_new_core_and_baseline():
    import ast,base64,zlib
    g=load('crm_rotation_capture_generator',HERE/'generate_baseline_command.py');body,pins=g.capture_command();assert len(body.encode())<11000
    code=body.split("<<'META_CAPTURE'\n",1)[1].rsplit('META_CAPTURE\n',1)[0];tree=ast.parse(code);node=next(x for x in ast.walk(tree) if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='files' for t in x.targets));files=ast.literal_eval(node.value)
    for name,row in files.items():assert zlib.decompress(base64.b64decode(row[0],validate=True))==(HERE/name).read_bytes()


def test_historical_reviewed_capture_remains_immutable_after_public_pin_finalization():
    import hashlib
    freeze=json.loads((HERE.parents[1]/'outputs/meta-business-crm-activation-20261101/baseline-capture-freeze.json').read_bytes())
    path=HERE/'capture-baseline-command.sh';key=str(path.relative_to(HERE.parents[1]))
    record=freeze['files'][key]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256'] and path.stat().st_size==record['bytes']
    import ast,base64,zlib
    code=path.read_text().split("<<'META_CAPTURE'\n",1)[1].rsplit('META_CAPTURE\n',1)[0]
    tree=ast.parse(code);node=next(x for x in ast.walk(tree) if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='files' for t in x.targets))
    for name,row in ast.literal_eval(node.value).items():
        body=zlib.decompress(base64.b64decode(row[0],validate=True));frozen=freeze['files'][str((HERE/name).relative_to(HERE.parents[1]))]
        assert hashlib.sha256(body).hexdigest()==frozen['sha256'] and len(body)==frozen['bytes']
