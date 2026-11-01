"""Local-only release attacks/regressions. No Docker, account or server calls."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tarfile
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load(HERE / "release.py", "meta_ops_release_test")
c = load(HERE / "make_commands.py", "meta_ops_commands_test")
retained = load(ROOT / "deployments/meta-business-20261031/release.py", "meta_ops_retained_test")


def test_unknown_final_pins_prevent_any_release_or_command_generation(monkeypatch):
    monkeypatch.setattr(r, "SOURCE_SHA", None)
    with pytest.raises(RuntimeError, match="FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED"): r.Release(None)
    monkeypatch.setattr(c.r, "SOURCE_SHA", None)
    with pytest.raises(RuntimeError, match="FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED"): c.generate("f" * 40, {})


def test_actual_preflight_summary_required_and_drift_rejected():
    summary = json.loads((ROOT / "outputs/meta-operations-20261101/preflight-summary.json").read_text())
    r.validate_summary(summary)
    for key,value in (("sha256", "0"*64), ("table_count", 140), ("google_scheduler_enabled", False), ("google_scheduler_activation_from", "2020-01-01T00:00:00Z")):
        changed = {**summary, key:value}
        with pytest.raises(RuntimeError): r.validate_summary(changed)


def test_transport_envelope_pins_underlying_canonical_prepared_bytes():
    value = {"stage":"SYNTHETIC", "source_sha":"a"*40, "proof":True}
    canonical = r.encoded(value); sha = r.H(canonical)
    raw = c.canonical_prepared(canonical)
    envelope = c.canonical_prepared(json.dumps({**value,"receipt_sha256":sha}).encode())
    assert raw == envelope == {**value,"_canonical_sha256":sha}
    assert sha != r.H(json.dumps({**value,"receipt_sha256":sha}).encode())


@pytest.mark.parametrize("body", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{"_canonical_sha256":"forged"}', b'{"a": 1}', b'{"a":1,"receipt_sha256":"'+b'0'*64+b'"}'])
def test_malformed_noncanonical_or_forged_prepared_receipt_rejected(body):
    with pytest.raises((RuntimeError, ValueError)): c.canonical_prepared(body)


class LocalCore:
    def mkdir(self, path): path.mkdir(mode=0o700, exist_ok=True)
    def write(self, path, body): path.write_bytes(body)


def archive(path, entries):
    with tarfile.open(path, "w:gz") as stream:
        for name, body, kind in entries:
            info = tarfile.TarInfo(name); info.size = len(body)
            if kind == "link": info.type = tarfile.SYMTYPE; info.linkname = "/etc/passwd"
            stream.addfile(info, io.BytesIO(body) if kind == "file" else None)


def test_payload_only_extracts_exact_regular_hashed_members(tmp_path, monkeypatch):
    wheel = b"SYNTHETIC-OFFLINE-WHEEL"; main = b"approved main\n"
    monkeypatch.setattr(r, "WHEEL_SHA", r.H(wheel))
    manifest = {"files":{r.WHEEL_MEMBER:r.H(wheel), "backend/main.py":r.H(main)}}
    archive(tmp_path/"payload.tar.gz", [(r.WHEEL_MEMBER,wheel,"file"),("backend/main.py",main,"file")])
    r.extract_payload(tmp_path,manifest,LocalCore())
    assert (tmp_path/"backend/main.py").read_bytes() == main
    assert (tmp_path/r.WHEEL_MEMBER).read_bytes() == wheel


@pytest.mark.parametrize("attack", ["traversal", "duplicate", "symlink", "foreign", "corrupt", "missing"])
def test_payload_attacks_fail_before_foreign_file_can_be_written(tmp_path, monkeypatch, attack):
    wheel = b"SYNTHETIC-WHEEL"; monkeypatch.setattr(r,"WHEEL_SHA",r.H(wheel))
    manifest = {"files":{r.WHEEL_MEMBER:r.H(wheel),"backend/main.py":r.H(b"approved")}}
    entries = [(r.WHEEL_MEMBER,wheel,"file"),("backend/main.py",b"approved","file")]
    if attack == "traversal": entries.append(("../escape",b"secret","file"))
    if attack == "duplicate": entries.append(entries[-1])
    if attack == "symlink": entries[-1] = ("backend/main.py",b"","link")
    if attack == "foreign": entries.append(("backend/finance.py",b"unauthorized","file"))
    if attack == "corrupt": entries[-1] = ("backend/main.py",b"different","file")
    if attack == "missing": entries.pop()
    archive(tmp_path/"payload.tar.gz",entries)
    with pytest.raises(RuntimeError): r.extract_payload(tmp_path,manifest,LocalCore())
    assert not (tmp_path.parent/"escape").exists() and not (tmp_path/"backend/finance.py").exists()


def nginx():
    return b"""# Preserve these exact bytes and the existing read-only route.
server {
 listen 443 ssl;
 server_name t24-crm.com;
 root /var/www/t24-crm-public/old;
 add_header Content-Security-Policy \"default-src 'self'\";
 location = /api/v1/google-business/oauth/callback {
  access_log off;
  error_log /dev/null crit;
  proxy_pass http://127.0.0.1:8000;
 }
 location = /api/v1/meta-business/oauth/callback {
  access_log off;
  error_log /dev/null crit;
  proxy_pass http://127.0.0.1:8000;
 }
 location ^~ /api/v1/media-publication-images/delivery/ {
  access_log off;
  error_log /dev/null crit;
  proxy_pass http://127.0.0.1:8000;
 }
 location /private-workspace {
  proxy_pass http://127.0.0.1:8001;
 }
}
"""


def test_nginx_only_copies_two_protected_blocks_and_changes_single_root(monkeypatch):
    monkeypatch.setattr(retained,"META_CALLBACK",r.OPS_CALLBACK)
    original=nginx(); updated=r.next_nginx(retained,original,"/var/www/t24-crm-public/old","/var/www/t24-crm-public/new")
    _,added=r.added_nginx(retained,original)
    normalized=updated.replace(b"/var/www/t24-crm-public/new",b"/var/www/t24-crm-public/old",1)
    for block in reversed(added): normalized=normalized.replace(block,b"",1)
    assert normalized == original and updated.count(r.OPS_CALLBACK.encode())==1 and updated.count(r.OPS_DELIVERY.encode())==1
    assert b"location = /api/v1/meta-business/oauth/callback" in updated
    assert updated.count(b"access_log off;")==5 and b"/private-workspace" in updated


@pytest.mark.parametrize("attack", ["unprotected", "remote", "duplicate", "already_added", "foreign_server"])
def test_nginx_cannot_copy_unreviewed_or_unprotected_delivery_template(monkeypatch, attack):
    monkeypatch.setattr(retained,"META_CALLBACK",r.OPS_CALLBACK); original=nginx()
    if attack=="unprotected": original=original.replace(b"  access_log off;",b"  access_log /var/log/nginx/access.log;",1)
    if attack=="remote": original=original.replace(b"http://127.0.0.1:8000",b"https://evil.invalid",1)
    if attack=="duplicate": original=original.replace(b" location ^~ /api/v1/media-publication-images/delivery/ {",b" location ^~ /api/v1/media-publication-images/delivery/ {\n }\n location ^~ /api/v1/media-publication-images/delivery/ {")
    if attack=="already_added": original+=b"# "+r.OPS_DELIVERY.encode()+b"\n"
    if attack=="foreign_server": original=original.replace(b" location ^~ /api/v1/media-publication-images/delivery/ {",b"}\nserver {\n listen 443 ssl;\n server_name other.invalid;\n location ^~ /api/v1/media-publication-images/delivery/ {")
    with pytest.raises(RuntimeError): r.next_nginx(retained,original,"/var/www/t24-crm-public/old","/var/www/t24-crm-public/new")


def test_image_build_uses_official_pinned_wheel_offline_only(tmp_path, monkeypatch):
    wheel=b"SYNTHETIC-WHEEL"; monkeypatch.setattr(r,"WHEEL_SHA",r.H(wheel));monkeypatch.setattr(r,"WHEEL_BYTES",len(wheel));monkeypatch.setattr(r,"SOURCE_SHA","a"*40)
    (tmp_path/"vendor").mkdir();(tmp_path/r.WHEEL_MEMBER).write_bytes(wheel)
    base="sha256:"+"b"*64; built="sha256:"+"c"*64; aliases={base:base}; calls=[]; written={}
    class M:
        BASE_IMAGE=base
        def image_id(self,name):return aliases.get(name)
        def write(self,path,body):written[path.name]=body
        def run(self,argv,code,*args):
            calls.append(argv)
            if argv[1:3]==["image","tag"]: aliases[argv[-1]]=base
            if argv[1]=="build":aliases[argv[argv.index("-t")+1]]=built
    class Core:
        def read(self,path,maximum,sha):
            body=path.read_bytes();assert len(body)<=maximum and r.H(body)==sha;return body
    probe=SimpleNamespace(m=M(),core=Core(),args=SimpleNamespace(release=tmp_path))
    assert r.OperationsMethods.image(probe)==built
    assert "--network=none" in calls[-1] and "--pull=false" in calls[-1]
    docker=written["Dockerfile"].decode()
    assert "--no-index --no-deps" in docker and r.WHEEL_MEMBER in docker and "https://" not in docker and "COPY backend/requirements.txt" in docker
    assert b"secrets" not in written[".dockerignore"] and b"!vendor/**" in written[".dockerignore"]


def test_offline_nonowner_asgi_probe_and_no_provider_sql_access():
    import subprocess
    python=ROOT.parents[2]/"experience-python/bin/python"
    result=subprocess.run([str(python),"-c",r.OperationsMethods.owner_denied_probe(None)],cwd=ROOT/"app/backend",capture_output=True,text=True,check=True)
    assert result.stdout.strip()=="EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK"


def test_route_probe_checks_registered_and_openapi_routes_with_network_blocked():
    import subprocess
    base=load(ROOT/'deployments/media-ops-management-20261031/release.py','meta_ops_base_routes_test')
    probe=SimpleNamespace(base=base,retained=retained,old_meta_routes=retained.META_ROUTES)
    code=r.OperationsMethods.route_probe(probe)
    result=subprocess.run([str(ROOT.parents[2]/'experience-python/bin/python'),'-c',code],cwd=ROOT/'app/backend',capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='EXACT_OPERATIONS_AND_EXISTING_ROUTES'


def test_only_forward_recovery_and_fingerprint_runtime_journal_are_in_new_tool():
    source=(HERE/"release.py").read_text();tree=ast.parse(source)
    assert "original-container.json" not in source and "original-runtime.json" in source
    assert "self.record('candidate-created.json'" in source
    activate=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) and cls.name=="OperationsMethods" for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=="activate")
    text=ast.get_source_segment(source,activate)
    assert text.index("self.record('candidate-created.json'") < text.index("['docker','stop'")
    assert "database_restored':False" in source and "self.retained.Release.recover_internal" in source
    assert "migrationsdowngrade" not in source.replace(" ","") and "docker','rm" not in source
    recovery=__import__('inspect').getsource(retained.Release.recover_internal)
    assert "rows=False, empty=False" in recovery and "self.new_schema(m.BUSINESS, empty=False)" in recovery
    assert "old_application_started_after_migration': False" in recovery


def test_retained_additive_comparison_preserves_nonempty_existing_meta_and_independent_recovery_rows(monkeypatch):
    monkeypatch.setattr(retained,"NEW_TABLES",r.NEW_TABLES);monkeypatch.setattr(retained,"NEW_REVISION",r.NEW_REVISION)
    table=lambda count,sha:{"columns":["id"],"schema":"same","indexes":[],"count":count,"rows_sha256":sha}
    before={"alembic_version":table(1,"old-head"),"meta_business_connections":table(2,"old-encrypted-rows"),"finance":table(9,"old-finance")}
    after=copy.deepcopy(before);after["alembic_version"]["rows_sha256"]=r.H(json.dumps([r.NEW_REVISION]).encode());after.update({name:table(0,"empty") for name in r.NEW_TABLES})
    retained.compare_original(before,after)
    after["finance"].update(count=10,rows_sha256="independent-business-write")
    with pytest.raises(RuntimeError,match="ORIGINAL_BUSINESS_ROWS_CHANGED"):retained.compare_original(before,after)
    after[sorted(r.NEW_TABLES)[0]].update(count=1,rows_sha256="independent-new-row")
    retained.compare_original(before,after,rows=False,empty=False)
    after["meta_business_connections"]["schema"]="changed"
    with pytest.raises(RuntimeError,match="ORIGINAL_TABLE_SHAPE_CHANGED"):retained.compare_original(before,after,rows=False,empty=False)


@pytest.fixture
def command_inputs(tmp_path,monkeypatch):
    monkeypatch.setattr(c,"HERE",tmp_path)
    monkeypatch.setattr(c.r,"SOURCE_SHA","a"*40);monkeypatch.setattr(c.r,"FRONTEND","b"*12);monkeypatch.setattr(c.r,"APPLICATION_FREEZE_SHA","c"*64)
    monkeypatch.setattr(c.r,"pins_ready",lambda:None)
    (tmp_path/"artifacts").mkdir();payload=b"SYNTHETIC-NONEXECUTABLE-PAYLOAD"
    manifest={"source_sha":c.r.SOURCE_SHA,"frontend_version":c.r.FRONTEND,"baseline_source_sha":c.r.BASE_SOURCE,"baseline_frontend_version":c.r.BASE_FRONTEND,
              "schema_revision":c.r.NEW_REVISION,"old_schema_revision":c.r.OLD_REVISION,"additive_tables":sorted(c.r.NEW_TABLES),"preflight_sha256":c.r.ACTUAL_PREFLIGHT_SHA,
              "changed_source_files":sorted(c.r.SOURCE_FILES),"backend_before":{name:c.r.ORIGINAL_BACKEND_HASHES.get(name) for name in c.r.BACKEND_FILES},
              "backend_after":{name:"e"*64 for name in c.r.BACKEND_FILES},"payload_sha256":r.H(payload),"application_freeze_sha256":c.r.APPLICATION_FREEZE_SHA,
              "files":{c.r.WHEEL_MEMBER:c.r.WHEEL_SHA}}
    for name in ("database_migration","existing_meta_environment_preserved","ops_environment_keys_absent"):manifest[name]=True
    for name in ("credentials_included","runtime_environment_changed","production_seed_rows","ops_feature_enabled","ops_execution_enabled","ops_scheduler_enabled"):manifest[name]=False
    values={"release.py":(HERE/"release.py").read_bytes(),"preflight.py":(HERE/"preflight.py").read_bytes(),"artifacts/manifest.json":r.encoded(manifest),"artifacts/payload.tar.gz":payload}
    for name,body in values.items():(tmp_path/name).write_bytes(body)
    def git(argv):
        assert argv[0]=="git"
        if argv[1]=="rev-parse":return b"SYNTHETIC-IDENTICAL-APPLICATION-TREE\n"
        assert argv[1]=="show";return values[argv[2].split(":"+c.DIRECTORY+"/",1)[1]]
    monkeypatch.setattr(c.subprocess,"check_output",git)
    summary=json.loads((ROOT/"outputs/meta-operations-20261101/preflight-summary.json").read_text())
    return values,summary


def prepared_for_commands(values):
    prepared={"stage":"META_OPERATIONS_PREPARED_OFFLINE_VERIFIED","source_sha":c.r.SOURCE_SHA,"frontend_version":c.r.FRONTEND,"old_schema_revision":c.r.OLD_REVISION,
              "schema_revision":c.r.NEW_REVISION,"original_table_count":141,"new_table_count":150,"additive_tables":sorted(c.r.NEW_TABLES),
              "manifest_sha256":r.H(values["artifacts/manifest.json"]),"payload_sha256":r.H(values["artifacts/payload.tar.gz"]),"preflight_sha256":c.r.ACTUAL_PREFLIGHT_SHA,"pillow_wheel_sha256":c.r.WHEEL_SHA}
    for key in ('schema_after_sha256','original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256'):prepared[key]="d"*64
    prepared.update(candidate_image="sha256:"+"e"*64,public_root='/var/www/t24-crm-public/'+c.r.SCOPE+'-'+c.r.SOURCE_SHA[:12]+'-20261101')
    for name in ("offline_additive_only","offline_original_rows_unchanged","offline_new_tables_empty","offline_own_metadata_exact","actual_python310_pillow_verified","exact_routes_verified","offline_nonowner_role_denied_without_sql","offline_network_none","offline_credentials_absent","offline_workers_off","google_on_cutoff_preserved","existing_meta_environment_preserved","operations_env_absent","operations_execution_disabled","operations_scheduler_disabled","new_callback_and_delivery_privacy_prepared"):prepared[name]=True
    for name in ("provider_requests","production_database_migrated","credential_values_journaled","sequence_written_by_tool"):prepared[name]=False
    return prepared


def test_commands_are_bounded_exact_carrier_wrappers_and_switch_pins_server_receipt(command_inputs):
    values,summary=command_inputs
    prepared=prepared_for_commands(values);sha=r.H(r.encoded(prepared))
    transport=c.canonical_prepared(json.dumps({**prepared,"receipt_sha256":sha}).encode())
    commands,pins=c.generate("f"*40,summary,transport)
    assert set(commands)=={"prepare-command.sh","activate-command.sh","recover-command.sh"} and pins["prepared_sha256"]==sha and pins["executed"] is False
    for text in commands.values():
        assert len(text.encode())<11000
        ast.parse(text.split("<<'WORKFLOW'\n",1)[1].rsplit("WORKFLOW\n",1)[0])
        assert "T24_META_OPS_APP_SECRET=" not in text
    assert "--review-sha256',"+repr(sha) in commands["activate-command.sh"]
    assert "ProxyHandler({})" in commands["prepare-command.sh"] and "CARRIER_REDIRECT_REJECTED" in commands["prepare-command.sh"]
    assert len(pins["members"])==4 and "files.pythonhosted.org" not in commands["prepare-command.sh"]


def test_commands_reject_uncommitted_artifact_and_bad_prepared_flags(command_inputs,monkeypatch):
    values,summary=command_inputs
    original=c.subprocess.check_output
    def changed(argv):
        body=original(argv)
        return body+b"changed" if argv[1]=="show" and argv[2].endswith("/release.py") else body
    monkeypatch.setattr(c.subprocess,"check_output",changed)
    with pytest.raises(RuntimeError,match="EXACT_COMMITTED_MEMBER_REQUIRED"):c.generate("f"*40,summary)
    monkeypatch.setattr(c.subprocess,"check_output",original)
    prepared=prepared_for_commands(values);prepared["operations_execution_disabled"]=False
    prepared=c.canonical_prepared(r.encoded(prepared))
    with pytest.raises(RuntimeError,match="EXACT_OFFLINE_ACCEPTANCE_REQUIRED"):c.generate("f"*40,summary,prepared)


def synthetic_141(path):
    with sqlite3.connect(path) as db:
        db.executescript("""PRAGMA user_version=37; PRAGMA application_id=123;
CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY);
INSERT INTO alembic_version VALUES('bde8da01f247');
CREATE TABLE legacy_counter(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT);
INSERT INTO legacy_counter(value) VALUES('independent synthetic business row');
CREATE TABLE meta_business_connections(id INTEGER PRIMARY KEY,token_encrypted TEXT);
INSERT INTO meta_business_connections VALUES(1,'synthetic old encrypted grant'),(2,'synthetic new legitimate grant');
CREATE TABLE meta_business_bindings(id INTEGER PRIMARY KEY,connection_id INTEGER);
INSERT INTO meta_business_bindings VALUES(1,1),(2,2);
CREATE TABLE meta_business_oauth_states(id INTEGER PRIMARY KEY,flow_encrypted TEXT);
INSERT INTO meta_business_oauth_states VALUES(1,'synthetic unconsumed legitimate flow');
""")
        for index in range(136):
            db.execute('CREATE TABLE original_'+str(index)+'(id INTEGER PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO original_'+str(index)+' VALUES(1,?)',('synthetic-'+str(index),))


def db_snapshot(path):
    with sqlite3.connect(path) as db:
        names={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        rows={name:db.execute('SELECT * FROM '+name).fetchall() for name in names}
        metadata=[db.execute('PRAGMA '+name).fetchall() for name in ('user_version','application_id')]+[db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()]
        return names,rows,metadata


@pytest.mark.parametrize('failure',[False,True])
def test_generated_transaction_adds_nine_empty_tables_or_rolls_back_without_restoring_rows(tmp_path,monkeypatch,failure):
    path=tmp_path/'synthetic.db';synthetic_141(path);before=db_snapshot(path);assert len(before[0])==141
    monkeypatch.setattr(retained,'OLD_REVISION',r.OLD_REVISION);monkeypatch.setattr(retained,'NEW_REVISION',r.NEW_REVISION)
    monkeypatch.setattr(retained,'NEW_TABLES',r.NEW_TABLES);monkeypatch.setattr(retained,'NEW_INDEXES',r.NEW_INDEXES)
    migration=(ROOT/'app/backend'/r.MIGRATION).read_text()
    if failure:migration=migration.replace('\ndef downgrade():',"\n    raise RuntimeError('SYNTHETIC_MIGRATION_FAILURE')\n\ndef downgrade():",1)
    (tmp_path/'migration.py').write_text(migration)
    monkeypatch.setattr(retained,'MIGRATIONS',(('migration.py',r.NEW_REVISION,r.OLD_REVISION),))
    before_objects=retained.objects(path)
    script=retained.migration_script().replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true','sqlite:///file:'+str(path)+'?mode=rw&uri=true').replace("'/app/backend/'+path",repr(str(tmp_path)+'/')+'+path')
    if failure:
        with pytest.raises(RuntimeError,match='SYNTHETIC_MIGRATION_FAILURE'):exec(compile(script,'<synthetic migration>','exec'),{})
        assert db_snapshot(path)==before and retained.objects(path)==before_objects
    else:
        exec(compile(script,'<synthetic migration>','exec'),{})
        after=db_snapshot(path);assert len(after[0])==150 and after[0]==before[0]|r.NEW_TABLES
        assert after[2]==before[2] and all(after[1][name]==rows for name,rows in before[1].items() if name!='alembic_version')
        assert after[1]['alembic_version']==[(r.NEW_REVISION,)] and all(not after[1][name] for name in r.NEW_TABLES)
        retained.additive_objects(before_objects,retained.objects(path))
        with sqlite3.connect(path) as db:assert {name:retained.table_shape(db,name) for name in r.NEW_TABLES}==r.NEW_TABLE_SHAPES
