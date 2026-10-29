"""Reviewed additive opt-in release. No task is created or published by deployment tooling.

Uses the hash-pinned retained release primitives for Docker configuration,
private-runtime verification, source inventories and filesystem safety. Only
the exact manifest payload and two empty media-task and event tables are admitted.
Every original financial, account, grant and app-settings row remains frozen;
only the Alembic revision changes in existing tables.
After migration, recovery always starts the reviewed new image, never old code.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import socket
import sqlite3
import stat
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

H = lambda body: hashlib.sha256(body).hexdigest()
HOST = "iZj6c4cj7edgnhdimts4l7Z"
BASE_SOURCE = "3eac5daaf881bc5398cfa67223485cf12cf9ff2c"
BASE_FRONTEND = "197e83470ec1"
SOURCE_SHA = "d70c28dae860598229c7d81299d8a65db016f764"
SOURCE_FILES = frozenset(['app/backend/alembic/versions/b7c2d9e4a601_media_operations.py', 'app/backend/models/media_operations.py', 'app/backend/routers/app_config.py', 'app/backend/routers/media_operations.py', 'app/backend/services/media_operations.py', 'app/backend/tests/test_media_operations.py', 'app/frontend/src/App.tsx', 'app/frontend/src/components/MediaOperationsEntry.tsx', 'app/frontend/src/components/MobileAppHome.tsx', 'app/frontend/src/components/MobileAppLauncher.tsx', 'app/frontend/src/components/crm-route-modules.ts', 'app/frontend/src/lib/app-navigation.ts', 'app/frontend/src/lib/media-operations-api.ts', 'app/frontend/src/lib/mobile-more-navigation.ts', 'app/frontend/src/lib/permissions.ts', 'app/frontend/src/lib/role-context.tsx', 'app/frontend/src/pages/MediaOperations.tsx', 'app/frontend/src/pages/OperationsWorkbench.tsx', 'app/frontend/src/pages/media-operations.css'])
OLD_REVISION = "a8d4e2c6f901"
NEW_REVISION = "b7c2d9e4a601"
NEW_TABLES = {"media_operation_tasks", "media_operation_events"}
MIGRATION = "alembic/versions/b7c2d9e4a601_media_operations.py"
BACKEND_FILES = {"routers/app_config.py", "models/media_operations.py", "services/media_operations.py", "routers/media_operations.py", MIGRATION}
EXISTING_BACKEND_FILES = {"routers/app_config.py"}
UNCHANGED_BACKEND_FILES = set()
NEW_OBJECTS = set()  # Bound to the exact offline-reviewed manifest, never inferred from writes.
SCOPE = "media-operations"
LEGACY = Path("/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py")
LEGACY_SHA = "bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0"
PRIVATE_PINS = Path("/opt/t24-crm/releases/commission-service-month-preflight-20261013.json")
PRIVATE_PINS_SHA = "af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161"
PRESERVED = {
    "finance_formulas": True, "close_conditions": True, "commission_attribution": True,
    "customer_permissions": True, "private_workspace": True, "original_rows_during_release": True,
    "environment_network_mounts": True, "original_static_files": True,
    "historical_pending_not_automatically_posted": True, "no_provider_writes": True,
    "app_settings_and_all_roles_unchanged": True, "no_accounts_or_grants_modified": True,
    "no_automatic_policies_enabled_by_release": True,
}


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def safe_error(error):
    value = str(error)
    return value if re.fullmatch("[A-Z0-9_]+", value) else type(error).__name__.upper()


def digest(value):
    return H(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def snapshot_evidence(rows):
    return {name: {"count": row["count"], "rows_sha256": row["rows_sha256"],
        "shape_sha256": digest({key: row[key] for key in ("columns", "schema", "indexes")})}
        for name, row in rows.items()}


def database_snapshot(module, path):
    return module.sql_snapshot(path)


def compare_original_rows(before, after):
    need(set(after) == set(before) | NEW_TABLES, "EXACT_TWO_ADDITIVE_TABLES_REQUIRED")
    for table, row in before.items():
        current = after[table]
        need(all(current[key] == row[key] for key in ("columns", "schema", "indexes")), "ORIGINAL_TABLE_SCHEMA_CHANGED")
        if table == "alembic_version":
            need(current["count"] == 1 and current["rows_sha256"] == H(json.dumps([NEW_REVISION]).encode()), "EXACT_NEW_REVISION_REQUIRED")
        else:
            need(current == row, "ORIGINAL_FILLED_ROWS_CHANGED_" + table.upper())
    need(all(after[name]["count"] == 0 for name in NEW_TABLES), "MEDIA_TABLES_MUST_START_EMPTY")


def additive_objects(before, after):
    need(all(after.get(key) == value for key, value in before.items()), "ORIGINAL_SCHEMA_OBJECT_CHANGED")
    need(set(after) - set(before) == NEW_OBJECTS, "EXACT_ADDITIVE_SCHEMA_OBJECTS_REQUIRED")


def migration_script():
    return f'''import importlib.util,json,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
spec=importlib.util.spec_from_file_location('fixed_media_operations_migration',{('/app/backend/' + MIGRATION)!r})
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.revision=={NEW_REVISION!r} and m.down_revision=={OLD_REVISION!r}
e=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[({OLD_REVISION!r},)]
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 r=c.exec_driver_sql("UPDATE alembic_version SET version_num='{NEW_REVISION}' WHERE version_num='{OLD_REVISION}'")
 assert r.rowcount==1
 c.commit()
print('EXACT_ADDITIVE_MEDIA_OPERATIONS_MIGRATION_OK')
'''


MEDIA_ROUTES = {
    ("/api/v1/media-operations/options", "GET"),
    ("/api/v1/media-operations", "GET"), ("/api/v1/media-operations", "POST"),
    ("/api/v1/media-operations/{task_id}", "GET"), ("/api/v1/media-operations/{task_id}", "PUT"),
    ("/api/v1/media-operations/{task_id}/transition", "POST"),
}


def route_registration_probe():
    # OpenAPI expands FastAPI 0.143 lazy included routers. Resolved route contexts
    # additionally preserve multiplicity, so duplicate mounts cannot be masked.
    return ("from main import app\nimport fastapi.routing\n"
        + "expected=" + repr(MEDIA_ROUTES) + "\n"
        + "prefix='/api/v1/media-operations'\n"
        + "schema=app.openapi()\n"
        + "documented={(path,method.upper()) for path,operations in schema.get('paths',{}).items() if path.startswith(prefix) for method in operations if method.lower() in {'get','post','put','patch','delete','head','options','trace'}}\n"
        + "assert documented==expected,'EXACT_MEDIA_OPENAPI_PATHS_REQUIRED'\n"
        + "contexts=fastapi.routing.iter_route_contexts(app.routes) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\n"
        + "registered=[(route.path,method,getattr(getattr(route,'endpoint',None),'__module__','')) for route in contexts if getattr(route,'path','').startswith(prefix) for method in (getattr(route,'methods',set()) or set())]\n"
        + "assert len(registered)==len(expected) and {(path,method) for path,method,module in registered}==expected,'EXACT_MEDIA_ROUTES_NOT_REGISTERED'\n"
        + "assert all(module=='routers.media_operations' for path,method,module in registered),'EXACT_MEDIA_ROUTER_MODULES_REQUIRED'\n"
        + "print('EXACT_MEDIA_ROUTES_REGISTERED')\n")


BUSINESS_ZONES = ("Asia/Shanghai", "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "America/Phoenix", "Pacific/Honolulu")


def timezone_probe():
    return "from zoneinfo import ZoneInfo\nexpected=" + repr(BUSINESS_ZONES) + "\nassert all(ZoneInfo(name).key==name for name in expected)\nprint('EXACT_SEVEN_MEDIA_TIMEZONES_AVAILABLE')\n"


def normalized_configuration(candidate, original, runtime):
    normalized = copy.deepcopy(candidate)
    for key in ("Image", "Hostname", "Labels"):
        normalized["Config"][key] = copy.deepcopy(original["Config"].get(key))
    need(runtime(normalized)["config"] == runtime(original)["config"], "CLONED_CONFIGURATION_DRIFT")


def verify_disabled_environment(info):
    env = dict(value.split("=", 1) for value in info["Config"]["Env"] if "=" in value)
    need(info["HostConfig"]["NetworkMode"] == "none", "OFFLINE_NETWORK_NONE_REQUIRED")
    need(env.get("STRIPE_AUTO_POSTING_ENABLED") == "false" and env.get("STRIPE_HISTORY_DAILY_SCAN_ENABLED") == "false", "OFFLINE_WORKERS_MUST_BE_DISABLED")


class Release:
    def __init__(self, args):
        self.args = args
        body = LEGACY.read_bytes()
        need(H(body) == LEGACY_SHA, "IMMUTABLE_RETAINED_HELPER_REQUIRED")
        self.m = types.ModuleType("_media_operations_release_primitives")
        self.m.__file__ = str(LEGACY)
        exec(compile(body, self.m.__file__, "exec"), self.m.__dict__)
        m = self.m
        self.manifest = json.loads(m.read(args.release / "manifest.json", args.manifest_sha256))
        m.read(args.release / "payload.tar.gz", args.payload_sha256)
        self.proof = json.loads(m.read(args.preflight, args.preflight_sha256))
        self.validate_manifest()
        global NEW_OBJECTS
        NEW_OBJECTS = {tuple(item) for item in self.manifest['additive_objects']}
        self.pins = json.loads(m.read(PRIVATE_PINS, PRIVATE_PINS_SHA))
        self.source = self.manifest["source_sha"]
        self.version = self.manifest["frontend_version"]
        self.public = Path("/var/www/t24-crm-public/media-operations-" + self.source[:12] + "-20261030")
        need(args.release == Path("/opt/t24-crm/releases/media-operations-" + self.source[:12] + "-20261030"), "EXACT_RELEASE_PATH_REQUIRED")
        # Retained methods resolve these module globals at call time.
        m.SOURCE, m.SCOPE = self.source, SCOPE
        m.BASELINE_FRONTEND, m.FRONTEND_VERSION = BASE_FRONTEND, self.version
        m.PUBLIC, m.NGINX_SHA, m.STATIC_SHA = Path(self.proof["public_root"]), self.proof["nginx_sha256"], self.proof["public_inventory_sha256"]
        m.OLD_ID, m.BASE_IMAGE, m.OLD_CONFIG = (self.proof["crm"][key] for key in ("id", "image", "config"))
        m.BACKEND = set(self.manifest["backend_after"])
        m.build_image = self.build_image
        m.public_root = lambda: self.public

    def validate_manifest(self):
        v, p, a = self.manifest, self.proof, self.args
        need(p["stage"] == "MEDIA_OPERATIONS_READONLY_PREFLIGHT" and p["host"] == HOST, "EXACT_FRESH_PREFLIGHT_REQUIRED")
        need(p["source_sha"] == BASE_SOURCE and p["frontend_version"] == BASE_FRONTEND and p["schema_revision"] == OLD_REVISION, "PREFLIGHT_BASELINE_DRIFT")
        need(all(p[key] is False for key in ("provider_requests", "business_writes", "container_or_configuration_changed", "credential_content_read", "customer_records_exported")), "READONLY_PROOF_REQUIRED")
        need(p["private_boundary_verified"] is True and re.fullmatch("[a-f0-9]{64}", p["backend_inventory_sha256"]), "PREFLIGHT_BOUNDARY_REQUIRED")
        need(v["source_sha"] == SOURCE_SHA and re.fullmatch("[a-f0-9]{12}", v["frontend_version"]), "SOURCE_AND_FRONTEND_PINS_REQUIRED")
        need(set(v.get("changed_source_files", [])) == SOURCE_FILES and len(v["changed_source_files"]) == len(SOURCE_FILES), "EXACT_APPLICATION_SOURCE_SCOPE_REQUIRED")
        need(v["baseline_source_sha"] == BASE_SOURCE and v["baseline_frontend_version"] == BASE_FRONTEND, "EXACT_BASELINE_REQUIRED")
        need(v["preflight_sha256"] == a.preflight_sha256 and v["payload_sha256"] == a.payload_sha256, "EXACT_PREFLIGHT_AND_PAYLOAD_REQUIRED")
        need(v["old_schema_revision"] == OLD_REVISION and v["schema_revision"] == NEW_REVISION and set(v["additive_tables"]) == NEW_TABLES, "EXACT_TWO_TABLE_MIGRATION_REQUIRED")
        objects = v.get('additive_objects', [])
        need(isinstance(objects, list) and len(objects) == len({tuple(item) for item in objects}), 'EXACT_ADDITIVE_OBJECTS_REQUIRED')
        need({tuple(item) for item in objects if item[0] == 'table'} == {('table', n, n) for n in NEW_TABLES}, 'EXACT_NEW_TABLE_OBJECTS_REQUIRED')
        need(all(len(item) == 3 and item[0] in {'table', 'index'} and item[2] in NEW_TABLES for item in objects), 'EXISTING_SCHEMA_OR_TRIGGER_REJECTED')
        need("finance_role_configuration" not in v, "NO_ROLE_CONFIG_MUTATION_ALLOWED")
        need(v["production_seed_rows"] is False and v["credentials_included"] is False and v["preserved"] == PRESERVED, "SOURCE_SCOPE_REJECTED")
        names = set(v["backend_after"])
        need(names == set(v["backend_before"]) == BACKEND_FILES, "EXACT_BACKEND_PINS_REQUIRED")
        need(set(p["backend_changed_before"]) == BACKEND_FILES, "EXACT_PREFLIGHT_SOURCE_SCOPE_REQUIRED")
        need(all(bool(re.fullmatch("[a-f0-9]{64}", value or "")) if name in EXISTING_BACKEND_FILES else value is None
            for name, value in v["backend_before"].items()), "EXACT_EXISTING_AND_NEW_SOURCE_PINS_REQUIRED")
        need(all(v["backend_before"][path] == v["backend_after"][path] for path in UNCHANGED_BACKEND_FILES), "UNCHANGED_DISCOVERY_SOURCE_REQUIRED")
        need({name[8:] for name in v["files"] if name.startswith("backend/")} == names, "BACKEND_PAYLOAD_SCOPE_REJECTED")
        need(all(name in {"backend/" + path for path in names} or name.startswith("static/") and self.m.static_path(name[7:]) for name in v["files"]), "PAYLOAD_SCOPE_REJECTED")
        need({"static/index.html", "static/app-version.json"} <= set(v["files"]), "STATIC_ENTRYPOINTS_REQUIRED")
        need(all(re.fullmatch("[a-f0-9]{64}", value) for value in [*v["files"].values(), *v["backend_after"].values()]), "FILE_HASH_PINS_REQUIRED")
        need(all(p["backend_changed_before"].get(path) == value for path, value in v["backend_before"].items()), "DEPLOYED_SOURCE_BASELINE_DRIFT")
        need(all(v["files"]["backend/" + path] == value for path, value in v["backend_after"].items()), "BACKEND_HASH_IDENTITY_DRIFT")

    def build_image(self, release, manifest):
        m = self.m
        need(m.image_id(m.BASE_IMAGE) == m.BASE_IMAGE, 'CURRENT_BASE_IMAGE_REQUIRED')
        tag = 't24-crm:media-operations-base-' + self.source[:12]
        existing = m.image_id(tag)
        need(existing is None or existing == m.BASE_IMAGE, 'BASE_TAG_DRIFT')
        if existing is None:
            m.run(['docker', 'image', 'tag', m.BASE_IMAGE, tag], 'BASE_TAG_CREATE_FAILED')
        dockerfile = 'FROM ' + tag + '\n' + ''.join('COPY backend/' + path + ' /app/backend/' + path + '\n' for path in sorted(BACKEND_FILES))
        m.write(release / 'Dockerfile', dockerfile.encode()); m.write(release / '.dockerignore', m.dockerignore())
        candidate = 't24-crm:media-operations-' + self.source[:12]
        m.run(['docker', 'build', '--network=none', '--pull=false', '-t', candidate, str(release)], 'CANDIDATE_BUILD_FAILED', 300)
        need(m.image_id(tag) == m.BASE_IMAGE, 'BASE_TAG_DRIFT')
        image = m.image_id(candidate)
        need(bool(re.fullmatch('sha256:[a-f0-9]{64}', image or '')), 'CANDIDATE_IMAGE_PIN_REQUIRED')
        return image

    def current_boundary(self, *, rows=True):
        m, p = self.m, self.proof
        m.private_boundary(self.pins)
        need(m.credential_boundary() == p["credential_boundary"], "CREDENTIAL_METADATA_DRIFT")
        identity = m.BUSINESS.stat()
        need([identity.st_dev, identity.st_ino] == p["database_identity"], "DATABASE_INODE_DRIFT")
        need(m.schema_signature(m.BUSINESS, OLD_REVISION) == p["schema_sha256"], "CURRENT_SCHEMA_DRIFT")
        crm = m.inspect("t24-crm")
        need(crm["State"]["Running"] and m.runtime(crm) == p["crm"], "CURRENT_RUNTIME_DRIFT")
        m.verify_secret_mount(crm)
        m.verify_production_worker_enabled(crm)
        m.retained().require_safe_original_restart(crm)
        inventory = m.inventory(crm["Id"])
        need(digest(inventory) == p["backend_inventory_sha256"] and len(inventory) == p["backend_file_count"], "CURRENT_BACKEND_SOURCE_DRIFT")
        need(m.static_boundary() == p["public_inventory_sha256"], "CURRENT_STATIC_DRIFT")
        if rows:
            need(snapshot_evidence(database_snapshot(m, m.BUSINESS)) == p["rows"], "CURRENT_ROWS_CHANGED_REFRESH_PREFLIGHT")
        m.ready(crm["Id"])
        return crm

    def offline_args(self, data, image):
        args = self.m.retained().offline_args(self.args.release, data, image)
        need(args[-1] == image, "OFFLINE_IMAGE_POSITION_DRIFT")
        # No credential mount is provided to the offline candidate.
        return args[:-1] + ["-e", "STRIPE_HISTORY_DAILY_SCAN_ENABLED=false", "-e", "STRIPE_AUTO_POSTING_ENABLED=false", image]

    def new_schema(self, path):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            need(con.execute("SELECT version_num FROM alembic_version").fetchall() == [(NEW_REVISION,)], "EXACT_NEW_SCHEMA_HEAD_REQUIRED")
            need(con.execute("PRAGMA quick_check").fetchall() == [("ok",)], "NEW_DATABASE_INTEGRITY_FAILED")
            for table in NEW_TABLES:
                need(con.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] == 0, "MEDIA_TABLES_NOT_EMPTY")

        finally:
            con.close()
        return self.m.schema_signature(path, NEW_REVISION)

    def prepare(self):
        m, a, v, p = self.m, self.args, self.manifest, self.proof
        old = self.current_boundary()
        need(set(path.name for path in a.release.iterdir()) == {"release.py", "manifest.json", "payload.tar.gz"}, "FRESH_STAGING_REQUIRED")
        m.extract(a.release, v)
        before_inventory = m.inventory(old["Id"])
        need(digest(before_inventory) == p["backend_inventory_sha256"], "CURRENT_BACKEND_INVENTORY_DRIFT")
        expected = {**before_inventory, **v["backend_after"]}
        m.write(a.release / "original-container.json", old)
        original_inventory_sha = m.write(a.release / "backend-original-inventory.json", before_inventory)
        inventory_sha = m.write(a.release / "backend-candidate-inventory.json", expected)
        m.retained().environment_file(a.release, old)
        for name in ("services/stripe_auto_posting.py", "services/stripe_history_daily_scan.py"):
            body = (a.release / "backend" / name).read_bytes() if name in m.BACKEND else None
            if body is not None:
                m.verify_startup_delay(body)
        image = m.build_image(a.release, v)
        data = a.release / "probe-data"
        data.mkdir(mode=0o700)
        (a.release / "probe-logs").mkdir(mode=0o700)
        m.backup(m.BUSINESS, data / "crm_prod.db")
        rows = database_snapshot(m, data / "crm_prod.db")
        need(snapshot_evidence(rows) == p["rows"], "ISOLATED_COPY_DRIFT")
        objects = m.schema_objects(data / "crm_prod.db")
        m.run(self.offline_args(data, image) + ["python", "-B", "-c", migration_script()], "OFFLINE_MIGRATION_FAILED", 90)
        schema = self.new_schema(data / "crm_prod.db")
        additive_objects(objects, m.schema_objects(data / "crm_prod.db"))
        migrated = database_snapshot(m, data / "crm_prod.db")
        compare_original_rows(rows, migrated)
        name = "t24-media-operations-probe-" + self.source[:12]
        command = self.offline_args(data, image)
        command[2:2] = ["--name", name, "-d"]
        m.run(command, "OFFLINE_STARTUP_FAILED")
        try:
            m.ready(name)
            verify_disabled_environment(m.inspect(name))
            need(m.inventory(name) == expected, "OFFLINE_SOURCE_INVENTORY_DRIFT")
            code = "import sys;from services.stripe_auto_posting import enabled;assert enabled() is False;print(sys.version_info[:2])"
            output = m.run(["docker", "exec", name, "python", "-B", "-c", code], "OFFLINE_DISABLED_WORKER_CHECK_FAILED")
            need(b"(3, 10)" in output, "ACTUAL_PYTHON310_REQUIRED")
            output = m.run(["docker", "exec", name, "python", "-B", "-c", route_registration_probe()], "OFFLINE_MEDIA_ROUTE_REGISTRATION_FAILED")
            need(b"EXACT_MEDIA_ROUTES_REGISTERED" in output, "EXACT_MEDIA_ROUTES_REQUIRED")
            output = m.run(["docker", "exec", name, "python", "-B", "-c", timezone_probe()], "OFFLINE_MEDIA_TIMEZONES_UNAVAILABLE")
            need(b"EXACT_SEVEN_MEDIA_TIMEZONES_AVAILABLE" in output, "EXACT_MEDIA_TIMEZONES_REQUIRED")
        finally:
            m.run(["docker", "stop", "-t", "20", name], "OFFLINE_STOP_FAILED", 45)
        need(database_snapshot(m, data / "crm_prod.db") == migrated and self.new_schema(data / "crm_prod.db") == schema, "OFFLINE_STARTUP_CHANGED_ROWS")
        row_sha = m.write(a.release / "offline-row-proof.json", {"before": rows, "after": migrated})
        root, static = m.stage_public(a.release, v)
        next_nginx = H(m.next_nginx(m.NGINX.read_bytes()))
        self.current_boundary()
        result = {
            "stage": "MEDIA_OPERATIONS_PREPARED_OFFLINE_VERIFIED", "source_sha": self.source,
            "frontend_version": self.version, "candidate_image": image, "old_crm": m.runtime(old),
            "preflight_sha256": a.preflight_sha256, "manifest_sha256": a.manifest_sha256, "payload_sha256": a.payload_sha256,
            "old_schema_revision": OLD_REVISION, "schema_revision": NEW_REVISION,
            "schema_before_sha256": p["schema_sha256"], "schema_after_sha256": schema,
            "additive_tables": sorted(NEW_TABLES), "original_table_count": len(rows),
            "candidate_inventory_sha256": inventory_sha, "original_inventory_sha256": original_inventory_sha, "offline_row_proof_sha256": row_sha,
            "public_root": str(root), "public_inventory_sha256": static, "nginx_next_sha256": next_nginx,
            "offline_original_rows_unchanged": True, "offline_new_tables_empty": True,
            "offline_workers_disabled": True, "offline_network_none": True, "offline_credentials_not_mounted": True,
            "offline_media_routes_registered": True, "offline_media_timezones_available": True,
            "actual_python310_startup_verified": True, "private_runtime_unchanged": True,
            "production_database_migrated": False, "database_restored": False,
            "automatic_policies_enabled": False, "provider_requests": False,
        }
        sha = m.write(a.release / "prepared.json", result)
        print(json.dumps({**result, "receipt_sha256": sha}))

    def reviewed(self):
        m, a = self.m, self.args
        need(bool(re.fullmatch("[a-f0-9]{64}", a.review_sha256 or "")), "INDEPENDENT_PREPARED_REVIEW_REQUIRED")
        receipt = json.loads(m.read(a.release / "prepared.json", a.review_sha256))
        need(receipt["stage"] == "MEDIA_OPERATIONS_PREPARED_OFFLINE_VERIFIED" and receipt["source_sha"] == self.source, "PREPARED_SOURCE_DRIFT")
        need(receipt["manifest_sha256"] == a.manifest_sha256 and receipt["payload_sha256"] == a.payload_sha256 and receipt["preflight_sha256"] == a.preflight_sha256, "PREPARED_IDENTITIES_DRIFT")
        need(receipt["schema_before_sha256"] == self.proof["schema_sha256"] and receipt["old_schema_revision"] == OLD_REVISION and receipt["schema_revision"] == NEW_REVISION, "PREPARED_SCHEMA_DRIFT")
        need(set(receipt["additive_tables"]) == NEW_TABLES and receipt["original_table_count"] == len(self.proof["rows"]), "PREPARED_TABLE_SCOPE_DRIFT")
        need(all(receipt[key] is True for key in ("offline_original_rows_unchanged", "offline_new_tables_empty", "offline_workers_disabled", "offline_network_none", "offline_credentials_not_mounted", "offline_media_routes_registered", "offline_media_timezones_available", "actual_python310_startup_verified", "private_runtime_unchanged")), "OFFLINE_PROOF_REQUIRED")
        need(all(receipt[key] is False for key in ("production_database_migrated", "database_restored", "automatic_policies_enabled", "provider_requests")), "PREPARED_SIDE_EFFECTS_REJECTED")
        original = json.loads(m.read(a.release / "original-container.json"))
        need(m.runtime(original) == self.proof["crm"] == receipt["old_crm"], "SAVED_ORIGINAL_DRIFT")
        expected = json.loads(m.read(a.release / "backend-candidate-inventory.json", receipt["candidate_inventory_sha256"]))
        original_inventory = json.loads(m.read(a.release / "backend-original-inventory.json", receipt["original_inventory_sha256"]))
        need(digest(original_inventory) == self.proof["backend_inventory_sha256"] and expected == {**original_inventory, **self.manifest["backend_after"]}, "PREPARED_INVENTORY_DRIFT")
        rowproof = json.loads(m.read(a.release / "offline-row-proof.json", receipt["offline_row_proof_sha256"]))
        need(snapshot_evidence(rowproof["before"]) == self.proof["rows"], "PREPARED_COPY_BASELINE_DRIFT")
        compare_original_rows(rowproof["before"], rowproof["after"])
        need(m.verify_public(self.public, self.manifest) == receipt["public_inventory_sha256"], "PREPARED_PUBLIC_DRIFT")
        need(m.image_id(receipt["candidate_image"]) == receipt["candidate_image"], "REVIEWED_LOCAL_IMAGE_REQUIRED")
        return receipt, original, expected

    def candidate_boundary(self, receipt, original, expected):
        m = self.m
        m.private_boundary(self.pins)
        need(m.credential_boundary() == self.proof["credential_boundary"], "CREDENTIAL_METADATA_DRIFT")
        candidate = m.inspect("t24-crm")
        need(candidate["State"]["Running"] and candidate["Image"] == receipt["candidate_image"], "EXACT_NEW_CANDIDATE_REQUIRED")
        need(candidate["Config"].get("Labels") == m.expected_labels(original), "NEW_CANDIDATE_LABELS_DRIFT")
        normalized_configuration(candidate, original, m.runtime)
        m.verify_secret_mount(candidate)
        m.verify_production_worker_enabled(candidate)
        need(m.inventory(candidate["Id"]) == expected, "NEW_CANDIDATE_SOURCE_DRIFT")
        need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "CANDIDATE_SCHEMA_DRIFT")
        need(digest(m.tree(m.PUBLIC)) == self.proof["public_inventory_sha256"], "ORIGINAL_STATIC_FILES_CHANGED")
        m.ready(candidate["Id"])
        return candidate

    def migrate(self, image):
        self.m.run(self.offline_args(self.m.BUSINESS.parent, image) + ["python", "-B", "-c", migration_script()], "PRODUCTION_ADDITIVE_MIGRATION_FAILED", 90)

    def revision(self):
        con = sqlite3.connect(f"file:{self.m.BUSINESS}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT version_num FROM alembic_version").fetchall()
            need(len(rows) == 1 and rows[0][0] in (OLD_REVISION, NEW_REVISION), "UNKNOWN_SCHEMA_HEAD")
            return rows[0][0]
        finally:
            con.close()

    def forward(self, receipt, original, expected, reason):
        """Recover only the current reviewed candidate against the additive head."""
        m, a = self.m, self.args
        m.private_boundary(self.pins)
        active = m.inspect_optional("t24-crm")
        if active:
            is_original = active["Id"] == original["Id"]
            need(is_original or active["Image"] == receipt["candidate_image"] and active["Config"].get("Labels") == m.expected_labels(original), "UNKNOWN_FORWARD_CONTAINER")
            if active["State"]["Running"]:
                m.run(["docker", "stop", "-t", "30", active["Id"]], "FORWARD_STOP_FAILED", 60)
        before_path = a.release / "production-before-rows.json"
        need(before_path.exists(), "FORWARD_PRE_MIGRATION_ROWS_REQUIRED")
        before = json.loads(m.read(before_path))
        if self.revision() == OLD_REVISION:
            need(database_snapshot(m, m.BUSINESS) == before, "FORWARD_ORIGINAL_ROWS_CHANGED")
            backup_path = a.release / ("business-forward-before-" + str(time.time_ns()) + ".db")
            m.backup(m.BUSINESS, backup_path)
            need(database_snapshot(m, backup_path) == before, "FORWARD_RESTORABLE_BACKUP_MISMATCH")
            self.migrate(receipt["candidate_image"])
        compare_original_rows(before, database_snapshot(m, m.BUSINESS))
        need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "FORWARD_NEW_SCHEMA_REQUIRED")
        if active and active["Id"] == original["Id"]:
            m.run(["docker", "rename", active["Id"], "t24-crm-before-media-operations-" + self.source[:12]], "FORWARD_RETAIN_ORIGINAL_FAILED")
            active = None
        candidate = active["Id"] if active else m.docker_create(receipt["candidate_image"], original)
        m.run(["docker", "start", candidate], "FORWARD_START_FAILED")
        self.candidate_boundary(receipt, original, expected)
        old_nginx = m.read(a.release / "nginx-before.conf", self.proof["nginx_sha256"])
        new_nginx = m.next_nginx(old_nginx)
        m.cleanup_nginx_temp(old_nginx, new_nginx)
        if m.NGINX.read_bytes() == old_nginx:
            m.replace_nginx(old_nginx, new_nginx)
        else:
            need(m.NGINX.read_bytes() == new_nginx, "FORWARD_NGINX_DRIFT")
        m.retained().reload_nginx()
        compare_original_rows(before, database_snapshot(m, m.BUSINESS))
        result = {"stage": "MEDIA_OPERATIONS_FORWARD_RECOVERED", "source_sha": self.source,
            "crm_id": candidate, "schema_revision": NEW_REVISION, "database_restored": False,
            "old_application_started": False, "original_rows_unchanged": True, "automatic_policies_enabled": False, "reason": reason}
        m.write(a.release / ("forward-recovery-" + str(time.time_ns()) + ".json"), result)
        return result

    def activate(self):
        m, a = self.m, self.args
        receipt, original, expected = self.reviewed()
        current = self.current_boundary()
        need(not (a.release / "deployed.json").exists() and not (a.release / "activation-started.json").exists(), "FRESH_ACTIVATION_REQUIRED")
        original_nginx = m.NGINX.read_bytes()
        updated_nginx = m.next_nginx(original_nginx)
        need(H(updated_nginx) == receipt["nginx_next_sha256"], "REVIEWED_NGINX_REQUIRED")
        m.write(a.release / "nginx-before.conf", original_nginx)
        m.write(a.release / "activation-started.json", {"source_sha": self.source, "review_sha256": a.review_sha256, "candidate_image": receipt["candidate_image"], "old_id": current["Id"]})
        try:
            m.run(["docker", "stop", "-t", "30", current["Id"]], "CURRENT_CRM_STOP_FAILED", 60)
            need(not m.inspect(current["Id"])["State"]["Running"], "CURRENT_CRM_NOT_STOPPED")
            before = database_snapshot(m, m.BUSINESS)
            need(snapshot_evidence(before) == self.proof["rows"], "CURRENT_ROWS_CHANGED_BEFORE_MIGRATION")
            before_sha = m.write(a.release / "production-before-rows.json", before)
            m.backup(m.BUSINESS, a.release / "business-before.db")
            need(database_snapshot(m, a.release / "business-before.db") == before, "RESTORABLE_BACKUP_MISMATCH")
            objects = m.schema_objects(m.BUSINESS)
            self.migrate(receipt["candidate_image"])
            additive_objects(objects, m.schema_objects(m.BUSINESS))
            need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "PRODUCTION_SCHEMA_DRIFT")
            migrated = database_snapshot(m, m.BUSINESS)
            compare_original_rows(before, migrated)
            m.write(a.release / "production-after-migration-rows.json", migrated)
            m.run(["docker", "rename", current["Id"], "t24-crm-before-media-operations-" + self.source[:12]], "RETAIN_ORIGINAL_FAILED")
            candidate = m.docker_create(receipt["candidate_image"], original)
            m.run(["docker", "start", candidate], "NEW_CANDIDATE_START_FAILED")
            self.candidate_boundary(receipt, original, expected)
            need(database_snapshot(m, m.BUSINESS) == migrated, "NEW_STARTUP_CHANGED_ORIGINAL_ROWS")
            m.replace_nginx(original_nginx, updated_nginx)
            m.retained().reload_nginx()
            need(m.verify_public(self.public, self.manifest) == receipt["public_inventory_sha256"], "NEW_PUBLIC_INVENTORY_DRIFT")
            need(H(m.NGINX.read_bytes()) == receipt["nginx_next_sha256"], "NEW_NGINX_DRIFT")
            version = json.loads(m.run(["curl", "-fsS", "--max-time", "20", "https://t24-crm.com/app-version.json"], "PUBLIC_VERSION_FAILED", 25))
            ready = json.loads(m.run(["curl", "-fsS", "--max-time", "20", "https://t24-crm.com/ready"], "PUBLIC_READY_FAILED", 25))
            need(version.get("version") == self.version and ready.get("status") == "ready", "PUBLIC_RELEASE_NOT_READY")
            current_new = self.candidate_boundary(receipt, original, expected)
            final = database_snapshot(m, m.BUSINESS)
            need(final == migrated, "FINAL_ORIGINAL_ROWS_CHANGED")
            final_sha = m.write(a.release / "production-after-rows.json", final)
            result = {"stage": "MEDIA_OPERATIONS_DEPLOYED_VERIFIED", "deployed": True,
                "source_sha": self.source, "frontend_version": self.version, "crm": m.runtime(current_new),
                "schema_revision": NEW_REVISION, "schema_sha256": receipt["schema_after_sha256"],
                "additive_tables": sorted(NEW_TABLES), "original_table_count": len(before),
                "original_rows_unchanged": True, "new_media_tables_empty": True,
                "production_before_rows_sha256": before_sha, "production_after_rows_sha256": final_sha,
                "candidate_inventory_sha256": receipt["candidate_inventory_sha256"],
                "public_root": str(self.public), "public_inventory_sha256": receipt["public_inventory_sha256"],
                "nginx_sha256": receipt["nginx_next_sha256"], "nginx_only_public_root_changed": True,
                "private_runtime_unchanged": True, "environment_network_mounts_unchanged": True,
                "automatic_policies_enabled": False, "provider_requests_by_deployment": False,
                "database_restored": False, "old_application_started_after_migration": False}
            sha = m.write(a.release / "deployed.json", result)
            print(json.dumps({**result, "receipt_sha256": sha}))
        except BaseException as error:
            # Once the old container was stopped, never auto-start old code.
            if (a.release / "production-before-rows.json").exists():
                self.forward(receipt, original, expected, safe_error(error))
            elif self.revision() == OLD_REVISION:
                # No migration or candidate creation occurred. Resume only the
                # exact original runtime, still against its exact old schema.
                stopped = m.inspect("t24-crm")
                need(stopped["Id"] == original["Id"] and m.runtime(stopped)["config"] == m.runtime(original)["config"], "PRE_MIGRATION_ORIGINAL_DRIFT")
                need(m.schema_signature(m.BUSINESS, OLD_REVISION) == self.proof["schema_sha256"], "PRE_MIGRATION_SCHEMA_DRIFT")
                if not stopped["State"]["Running"]:
                    m.run(["docker", "start", stopped["Id"]], "PRE_MIGRATION_RESUME_FAILED")
                    m.ready(stopped["Id"])
            raise

    def recover(self):
        receipt, original, expected = self.reviewed()
        need(not (self.args.release / "deployed.json").exists(), "SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW")
        started = json.loads(self.m.read(self.args.release / "activation-started.json"))
        need(started == {"source_sha": self.source, "review_sha256": self.args.review_sha256,
            "candidate_image": receipt["candidate_image"], "old_id": original["Id"]}, "ACTIVATION_IDENTITY_DRIFT")
        print(json.dumps(self.forward(receipt, original, expected, "INTERRUPTED_ACTIVATION")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["prepare", "activate", "recover"], required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--review-sha256")
    args = parser.parse_args()
    need(socket.gethostname() == HOST and os.geteuid() == 0, "EXACT_SERVER_ROOT_REQUIRED")
    sys.dont_write_bytecode = True
    os.umask(0o077)
    need(args.release.resolve() == args.release and args.release.parent == Path("/opt/t24-crm/releases"), "EXACT_RELEASE_PARENT_REQUIRED")
    info = args.release.lstat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700, "PROTECTED_RELEASE_REQUIRED")
    for sha in (args.manifest_sha256, args.payload_sha256, args.preflight_sha256):
        need(bool(re.fullmatch("[a-f0-9]{64}", sha)), "EXACT_HASH_PINS_REQUIRED")
    lock = os.open("/opt/t24-crm/releases/.media-operations-release.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    release = Release(args)
    getattr(release, args.phase)()


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        print(json.dumps({"stage": "MEDIA_OPERATIONS_RELEASE_REJECTED", "code": safe_error(error),
            "database_restored": False, "old_application_started_after_migration": False}))
        sys.exit(1)
