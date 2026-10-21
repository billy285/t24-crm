"""Release gates are exercised without any server, provider or production data."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("autopost_release_under_test", ROOT / "release.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def snapshot(path):
    con = sqlite3.connect(path)
    try:
        result = {}
        for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            cols = list(con.execute('PRAGMA table_info("' + table + '")'))
            rows = sorted(json.dumps(list(row), ensure_ascii=True) for row in con.execute('SELECT * FROM "' + table + '"'))
            result[table] = {"columns": [row[1] for row in cols], "schema": cols,
                "indexes": list(con.execute('PRAGMA index_list("' + table + '")')),
                "count": len(rows), "rows_sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
        return result
    finally:
        con.close()


def objects(path):
    con = sqlite3.connect(path)
    try:
        return {(row[0], row[1], row[2]): row[3] for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    finally:
        con.close()


def migrated(tmp_path):
    path = tmp_path / "copy.db"
    con = sqlite3.connect(path)
    con.executescript("""
CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES('e2b6c0f8a345');
CREATE TABLE stripe_history_bindings(id INTEGER PRIMARY KEY);
CREATE TABLE stripe_history_invoice_reviews(id INTEGER PRIMARY KEY);
CREATE TABLE payments(id INTEGER PRIMARY KEY,amount INTEGER,note TEXT);
INSERT INTO payments VALUES(17,9900,'pre-existing payment preserved');
CREATE VIEW original_payment_view AS SELECT id,amount FROM payments;
""")
    con.commit()
    con.close()
    before, old_objects = snapshot(path), objects(path)
    migration = ROOT.parents[1] / "app/backend" / r.MIGRATION
    script = r.migration_script().replace("/app/backend/" + r.MIGRATION, str(migration))
    script = script.replace("sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true", "sqlite:///file:" + str(path) + "?mode=rw&uri=true")
    exec(compile(script, "isolated-fixed-migration", "exec"), {})
    return path, before, old_objects


def test_exact_migration_adds_two_empty_tables_and_keeps_every_original_row_and_object(tmp_path):
    path, before, old_objects = migrated(tmp_path)
    r.compare_original_rows(before, snapshot(path))
    r.additive_objects(old_objects, objects(path))
    con = sqlite3.connect(path)
    assert con.execute("SELECT * FROM payments").fetchall() == [(17, 9900, "pre-existing payment preserved")]
    assert con.execute("SELECT count(*) FROM stripe_auto_posting_policies").fetchone() == (0,)
    assert con.execute("SELECT count(*) FROM stripe_auto_posting_jobs").fetchone() == (0,)
    con.close()


@pytest.mark.parametrize("mutation", [
    lambda rows: rows["payments"].update(count=2),
    lambda rows: rows["payments"].update(rows_sha256="0" * 64),
    lambda rows: rows["payments"].update(columns=["unexpected"]),
    lambda rows: rows["stripe_auto_posting_policies"].update(count=1),
    lambda rows: rows["stripe_auto_posting_jobs"].update(count=1),
    lambda rows: rows["alembic_version"].update(rows_sha256="0" * 64),
    lambda rows: rows.pop("payments"),
    lambda rows: rows.update(unapproved_table={}),
])
def test_any_finance_historical_row_or_seed_drift_blocks_release(tmp_path, mutation):
    path, before, _ = migrated(tmp_path)
    after = snapshot(path)
    mutation(after)
    with pytest.raises(RuntimeError):
        r.compare_original_rows(before, after)


def test_original_schema_mutation_and_unapproved_new_index_are_rejected(tmp_path):
    path, _, before = migrated(tmp_path)
    after = objects(path)
    wrong = copy.deepcopy(after)
    wrong[("view", "original_payment_view", "original_payment_view")] = "changed"
    with pytest.raises(RuntimeError, match="ORIGINAL_SCHEMA_OBJECT_CHANGED"):
        r.additive_objects(before, wrong)
    wrong = copy.deepcopy(after)
    wrong[("index", "extra_index", "payments")] = "CREATE INDEX extra_index ON payments(amount)"
    with pytest.raises(RuntimeError, match="EXACT_ADDITIVE_SCHEMA_OBJECTS_REQUIRED"):
        r.additive_objects(before, wrong)


@pytest.mark.parametrize("override", [
    {"HostConfig": {"NetworkMode": "bridge"}},
    {"Config": {"Env": ["STRIPE_AUTO_POSTING_ENABLED=true", "STRIPE_HISTORY_DAILY_SCAN_ENABLED=false"]}},
    {"Config": {"Env": ["STRIPE_AUTO_POSTING_ENABLED=false", "STRIPE_HISTORY_DAILY_SCAN_ENABLED=true"]}},
    {"Config": {"Env": []}},
])
def test_offline_candidate_cannot_have_network_or_active_workers(override):
    info = {"HostConfig": {"NetworkMode": "none"}, "Config": {"Env": ["STRIPE_AUTO_POSTING_ENABLED=false", "STRIPE_HISTORY_DAILY_SCAN_ENABLED=false"]}}
    info.update(override)
    with pytest.raises(RuntimeError):
        r.verify_disabled_environment(info)


def test_same_configuration_comparison_ignores_only_image_hostname_and_labels():
    original = {"Config": {"Image": "old", "Hostname": "old", "Labels": {"old": "value"}, "Env": ["SECRET=not-exported"]}, "HostConfig": {"Mounts": ["readonly-key"]}}
    candidate = copy.deepcopy(original)
    candidate["Config"].update(Image="new", Hostname="new", Labels={"release": "source"})
    runtime = lambda info: {"config": r.digest(info)}
    r.normalized_configuration(candidate, original, runtime)
    for path in ("Env",):
        wrong = copy.deepcopy(candidate)
        wrong["Config"][path] = ["SECRET=changed"]
        with pytest.raises(RuntimeError, match="CLONED_CONFIGURATION_DRIFT"):
            r.normalized_configuration(wrong, original, runtime)
    wrong = copy.deepcopy(candidate)
    wrong["HostConfig"]["Mounts"] = []
    with pytest.raises(RuntimeError, match="CLONED_CONFIGURATION_DRIFT"):
        r.normalized_configuration(wrong, original, runtime)


def test_preflight_command_executes_exact_reviewed_bytes_and_no_mutating_shell_commands():
    source = (ROOT / "preflight.py").read_bytes()
    command = (ROOT / "preflight-command.sh").read_text()
    assert hashlib.sha256(source).hexdigest() in command
    assert "sudo python3 -B" in command and "set -eu" in command
    assert "docker stop" not in command and "docker start" not in command
    for unsafe in ("write_text(", "write_bytes(", "m.write(", "m.backup(", "m.migrate(", "provider.reader("):
        assert unsafe not in source.decode()


def valid_manifest_context():
    obj = r.Release.__new__(r.Release)
    before = {name: "a" * 64 if name in r.EXISTING_BACKEND_FILES else None for name in r.BACKEND_FILES}
    after = {name: "b" * 64 for name in r.BACKEND_FILES}
    obj.args = SimpleNamespace(preflight_sha256="c" * 64, payload_sha256="d" * 64)
    obj.proof = {"stage": "STRIPE_AUTOMATIC_POSTING_READONLY_PREFLIGHT", "host": r.HOST,
        "source_sha": r.BASE_SOURCE, "frontend_version": r.BASE_FRONTEND, "schema_revision": r.OLD_REVISION,
        "provider_requests": False, "business_writes": False, "container_or_configuration_changed": False,
        "credential_content_read": False, "customer_records_exported": False, "private_boundary_verified": True,
        "backend_inventory_sha256": "e" * 64, "backend_changed_before": copy.deepcopy(before)}
    obj.manifest = {"source_sha": "1" * 40, "frontend_version": "2" * 12,
        "baseline_source_sha": r.BASE_SOURCE, "baseline_frontend_version": r.BASE_FRONTEND,
        "preflight_sha256": "c" * 64, "payload_sha256": "d" * 64,
        "old_schema_revision": r.OLD_REVISION, "schema_revision": r.NEW_REVISION,
        "additive_tables": sorted(r.NEW_TABLES), "production_seed_rows": False, "credentials_included": False,
        "preserved": copy.deepcopy(r.PRESERVED), "backend_before": before, "backend_after": after,
        "files": {**{"backend/" + name: value for name, value in after.items()},
            "static/index.html": "f" * 64, "static/app-version.json": "f" * 64}}
    obj.m = SimpleNamespace(static_path=lambda value: value in {"index.html", "app-version.json"})
    return obj


def test_exact_manifest_passes_without_loosening_original_financial_scope():
    valid_manifest_context().validate_manifest()


@pytest.mark.parametrize("mutation", [
    lambda c: c.manifest.update(production_seed_rows=True),
    lambda c: c.manifest.update(credentials_included=True),
    lambda c: c.manifest.update(schema_revision=r.OLD_REVISION),
    lambda c: c.manifest.update(additive_tables=["payments"]),
    lambda c: c.manifest.update(source_sha="moving-branch"),
    lambda c: c.manifest.update(preflight_sha256="0" * 64),
    lambda c: c.manifest["preserved"].update(finance_formulas=False),
    lambda c: c.manifest["files"].update({"backend/services/deal_payment_sync.py": "b" * 64}),
    lambda c: c.manifest["files"].update({"static/../secret.env": "b" * 64}),
    lambda c: c.manifest["backend_after"].update({"services/deal_payment_sync.py": "b" * 64}),
    lambda c: c.proof.update(business_writes=True),
    lambda c: c.proof.update(credential_content_read=True),
    lambda c: c.proof["backend_changed_before"].update({"main.py": "0" * 64}),
])
def test_malicious_manifest_or_nonreadonly_preflight_cannot_pass(mutation):
    context = valid_manifest_context()
    mutation(context)
    with pytest.raises(RuntimeError):
        context.validate_manifest()


def test_compact_snapshot_preserves_rows_and_schema_as_independent_hashes(tmp_path):
    path, before, _ = migrated(tmp_path)
    proof = r.snapshot_evidence(before)
    changed = copy.deepcopy(before)
    changed["payments"]["rows_sha256"] = "0" * 64
    assert r.snapshot_evidence(changed) != proof
    changed = copy.deepcopy(before)
    changed["payments"]["schema"].append((99, "unauthorized", "TEXT", 0, None, 0))
    assert r.snapshot_evidence(changed) != proof
    assert all(set(row) == {"count", "rows_sha256", "shape_sha256"} for row in proof.values())
