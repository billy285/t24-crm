"""Reviewed additive opt-in release. No task is created or published by deployment tooling.

Uses the hash-pinned retained release primitives for Docker configuration,
private-runtime verification, source inventories and filesystem safety. Only
the exact manifest payload and five empty Google management/schedule/AI tables are admitted.
The existing connection, OAuth state, binding, grant and action tables may contain
real records: only reviewed columns are added, and every original column value
remains frozen alongside financial, account, grant and app-settings rows.
After migration, recovery always starts the reviewed new image, never old code.
"""
import argparse
import base64
import copy
import fcntl
import hashlib
import json
import os
import re
import resource
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
BASE_SOURCE = "7431d1986b81328fcc822e3e13641e4d03b6b9bf"
BASE_FRONTEND = "c648c284143e"
SOURCE_SHA = "6b47aefa201fb5e4963e4cfa522b7a5776e5a2c4"
SOURCE_FILES = frozenset(['app/backend/alembic/versions/d9e4f6a7b803_google_business_management.py', 'app/backend/main.py', 'app/backend/models/google_business.py', 'app/backend/routers/google_business.py', 'app/backend/services/google_business.py', 'app/backend/services/google_business_ai.py', 'app/backend/services/google_business_management.py', 'app/backend/services/google_business_scheduler.py', 'app/backend/tests/test_google_business.py', 'app/backend/tests/test_google_business_ai.py', 'app/backend/tests/test_google_business_management.py', 'app/backend/tests/test_google_business_management_unit.py', 'app/frontend/src/components/GoogleBusinessManagement.tsx', 'app/frontend/src/components/GoogleBusinessWorkspace.tsx', 'app/frontend/src/components/GoogleReviewAssistant.tsx', 'app/frontend/src/lib/google-business-ai-api.ts', 'app/frontend/src/lib/google-business-api.ts', 'app/frontend/src/lib/google-management-api.ts', 'app/frontend/src/pages/MediaOperations.tsx', 'app/frontend/src/pages/google-management.css'])

OLD_REVISION = "c8d3e5f6a702"
NEW_REVISION = "d9e4f6a7b803"
NEW_TABLES = {'google_business_management_requests', 'google_business_assignment_previews', 'google_business_schedules', 'google_business_ai_consents', 'google_business_ai_drafts'}
MIGRATION = "alembic/versions/d9e4f6a7b803_google_business_management.py"
BACKEND_FILES = {'main.py', 'models/google_business.py', 'routers/google_business.py', 'services/google_business.py', 'services/google_business_management.py', 'services/google_business_scheduler.py', 'services/google_business_ai.py', MIGRATION}
EXISTING_BACKEND_FILES = {'main.py', 'models/google_business.py', 'routers/google_business.py', 'services/google_business.py'}
ADDITIONS = {
    'google_business_bindings': {'lifecycle', 'primary_operator_id', 'primary_operator_name', 'lifecycle_reason'},
    'google_business_oauth_states': {'reconnect_connection_id'},
    'google_business_actions': {'confirmed_at', 'approval_id'},
}
ADDITIVE_COLUMN_SQL = {
    'google_business_bindings': ("lifecycle VARCHAR(16) DEFAULT 'active' NOT NULL", 'primary_operator_id INTEGER', 'primary_operator_name VARCHAR(255)', 'lifecycle_reason VARCHAR(500)'),
    'google_business_oauth_states': ('reconnect_connection_id INTEGER',),
    'google_business_actions': ('confirmed_at DATETIME', 'approval_id VARCHAR(36)'),
}
PROJECTION = None
BASE_ENABLED_RECEIPT = Path('/opt/t24-crm/releases/google-business-activation-7431d1986b81-20261030/attempt-v3/completion-oom-default/enabled.json')
PREFLIGHT_TOOL_SHA = '12a65720a072901bbeb55cdc91ca69a3430c06da178d8d6d0b80d46e8787d95b'
BASE_ENABLED_SHA = 'fc1fb80477a00839246dab0ef818abe766285f99db905adca12d8f84298e341d'

UNCHANGED_BACKEND_FILES = set()
NEW_OBJECTS = set()  # Bound to the exact offline-reviewed manifest, never inferred from writes.
SCOPE = "media-ops-management"
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
    "existing_google_environment_preserved": True, "scheduler_remains_disabled": True, "no_new_oauth_or_ai_authorization": True,
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
    rows = module.retained().sql_snapshot(path, PROJECTION) if PROJECTION is not None else module.sql_snapshot(path)
    return json.loads(json.dumps(rows))


def compare_original_rows(before, after):
    need(set(after) == set(before) | NEW_TABLES, 'EXACT_FIVE_ADDITIVE_TABLES_REQUIRED')
    for table, row in before.items():
        current = after[table]
        need(set(current['columns']) == set(row['columns']) | ADDITIONS.get(table, set()), 'UNAPPROVED_COLUMN_CHANGE')
        need(current['indexes'] == row['indexes'], 'ORIGINAL_INDEX_CHANGED')
        need(all(current['schema'].get(name) == value for name, value in row['schema'].items()), 'ORIGINAL_COLUMN_SCHEMA_CHANGED')
        if table == 'alembic_version':
            need(current['count'] == 1 and current['rows_sha256'] == H(json.dumps([NEW_REVISION]).encode()), 'EXACT_NEW_REVISION_REQUIRED')
        else:
            need((current['count'], current['rows_sha256']) == (row['count'], row['rows_sha256']), 'ORIGINAL_PROJECTED_ROWS_CHANGED_' + table.upper())
    need(all(after[name]['count'] == 0 for name in NEW_TABLES), 'NEW_GOOGLE_TABLES_MUST_START_EMPTY')


def additive_objects(before, after):
    for key, value in before.items():
        if key[0] == 'table' and key[1] in ADDITIONS:
            # SQLite inserts new columns before table-level constraints. Remove
            # only each exact approved clause, then require every old byte equal.
            new = after.get(key, '')
            for clause in ADDITIVE_COLUMN_SQL[key[1]]:
                literal = ', ' + clause
                need(new.count(literal) == 1, 'EXACT_ADDITIVE_COLUMN_SQL_REQUIRED')
                new = new.replace(literal, '', 1)
            need(new == value, 'ORIGINAL_GOOGLE_TABLE_REWRITTEN')
        else:
            need(after.get(key) == value, 'ORIGINAL_SCHEMA_OBJECT_CHANGED')
    need(set(after) - set(before) == NEW_OBJECTS, 'EXACT_ADDITIVE_SCHEMA_OBJECTS_REQUIRED')


def migration_script():
    return f'''import importlib.util,json,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
spec=importlib.util.spec_from_file_location('fixed_media_ops_management_migration',{('/app/backend/' + MIGRATION)!r})
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.revision=={NEW_REVISION!r} and m.down_revision=={OLD_REVISION!r}
e=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[({OLD_REVISION!r},)]
 sequence_exists=c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
 sequences_before=c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall() if sequence_exists else []
 pragma_before=[c.exec_driver_sql('PRAGMA '+name).fetchone() for name in ('user_version','application_id')]
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 sequence_exists_after=c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
 sequences_after=c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall() if sequence_exists_after else []
 assert sequences_after==sequences_before,'ORIGINAL_AUTOINCREMENT_SEQUENCE_DRIFT'
 assert [c.exec_driver_sql('PRAGMA '+name).fetchone() for name in ('user_version','application_id')]==pragma_before,'DATABASE_APPLICATION_METADATA_DRIFT'
 r=c.exec_driver_sql("UPDATE alembic_version SET version_num='{NEW_REVISION}' WHERE version_num='{OLD_REVISION}'")
 assert r.rowcount==1
 c.commit()
print('EXACT_ADDITIVE_MEDIA_MANAGEMENT_MIGRATION_OK')
'''


GBP_ROUTES = {
    ("/api/v1/google-business/status", "GET"), ("/api/v1/google-business/options", "GET"),
    ("/api/v1/google-business/oauth/start", "POST"), ("/api/v1/google-business/oauth/callback", "GET"),
    ("/api/v1/google-business/connections/{connection_id}/locations", "GET"),
    ("/api/v1/google-business/connections/{connection_id}/disconnect", "POST"),
    ("/api/v1/google-business/bindings", "POST"),
    ("/api/v1/google-business/bindings/{binding_id}/grants", "GET"), ("/api/v1/google-business/bindings/{binding_id}/grants", "PUT"),
    ("/api/v1/google-business/bindings/{binding_id}/disconnect", "POST"),
    ("/api/v1/google-business/bindings/{binding_id}/reviews", "GET"), ("/api/v1/google-business/bindings/{binding_id}/review-replies", "POST"),
    ("/api/v1/google-business/bindings/{binding_id}/ready-tasks", "GET"), ("/api/v1/google-business/bindings/{binding_id}/posts", "POST"),
    ("/api/v1/google-business/bindings/{binding_id}/actions", "GET"), ("/api/v1/google-business/actions/{action_id}", "GET"),
    ("/api/v1/google-business/requests/{request_id}", "GET"), ("/api/v1/google-business/actions/{action_id}/reconcile", "POST"),
}
MEDIA_ROUTES = {
    ("/api/v1/media-operations/options", "GET"), ("/api/v1/media-operations", "GET"), ("/api/v1/media-operations", "POST"),
    ("/api/v1/media-operations/{task_id}", "GET"), ("/api/v1/media-operations/{task_id}", "PUT"),
    ("/api/v1/media-operations/{task_id}/transition", "POST"),
}


GBP_ROUTES |= {
    ('/api/v1/google-business/portfolio', 'GET'), ('/api/v1/google-business/bindings/{binding_id}/lifecycle', 'POST'),
    ('/api/v1/google-business/assignments/preview', 'POST'), ('/api/v1/google-business/assignments/apply', 'POST'),
    ('/api/v1/google-business/management-requests/{request_id}', 'GET'), ('/api/v1/google-business/statistics', 'GET'),
    ('/api/v1/google-business/calendar', 'GET'), ('/api/v1/google-business/bindings/{binding_id}/schedules', 'POST'),
    ('/api/v1/google-business/schedules/{schedule_id}/cancel', 'POST'), ('/api/v1/google-business/ai/status', 'GET'),
    ('/api/v1/google-business/ai/consent', 'POST'), ('/api/v1/google-business/bindings/{binding_id}/ai-reply-drafts', 'POST'),
    ('/api/v1/google-business/bindings/{binding_id}/reply-drafts', 'POST'), ('/api/v1/google-business/bindings/{binding_id}/reply-drafts', 'GET'),
    ('/api/v1/google-business/bindings/{binding_id}/reply-drafts/{draft_id}/approve', 'POST'),
}

def route_registration_probe():
    expected = {"/api/v1/google-business": ("routers.google_business", GBP_ROUTES), "/api/v1/media-operations": ("routers.media_operations", MEDIA_ROUTES)}
    return ("from main import app\nimport fastapi.routing\nexpected=" + repr(expected) + "\n"
        + "schema=app.openapi()\n"
        + "contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\n"
        + "for prefix,(module,methods) in expected.items():\n"
        + " documented={(path,method.upper()) for path,operations in schema.get('paths',{}).items() if path.startswith(prefix) for method in operations if method.lower() in {'get','post','put','patch','delete','head','options','trace'}}\n"
        + " assert documented==methods,'EXACT_GOOGLE_MEDIA_OPENAPI_REQUIRED'\n"
        + " registered=[(route.path,method,getattr(getattr(route,'endpoint',None),'__module__','')) for route in contexts if getattr(route,'path','').startswith(prefix) for method in (getattr(route,'methods',set()) or set())]\n"
        + " assert len(registered)==len(methods) and {(path,method) for path,method,mod in registered}==methods,'EXACT_GOOGLE_MEDIA_ROUTES_REQUIRED'\n"
        + " assert all(mod==module for path,method,mod in registered),'EXACT_GOOGLE_MEDIA_MODULE_REQUIRED'\n"
        + "print('EXACT_GOOGLE_MEDIA_ROUTES_REGISTERED')\n")


GBP_CONFIG_NAMES = {'T24_GBP_ENABLED', 'T24_GBP_API_APPROVED', 'T24_GBP_CLIENT_ID', 'T24_GBP_CLIENT_SECRET', 'T24_GBP_TOKEN_KEY', 'T24_GBP_PUBLIC_URL'}


def environment_values(info):
    rows = info['Config']['Env']; values = {}
    for row in rows:
        need(isinstance(row, str) and '=' in row and not any(x in row for x in '\r\n\0'), 'ENV_FORMAT_REJECTED')
        name, value = row.split('=', 1)
        need(name not in values, 'DUPLICATE_ENV_KEY')
        values[name] = value
    return values


def verify_gbp_environment_enabled(info):
    values = environment_values(info)
    expected = GBP_CONFIG_NAMES | {'T24_GBP_SCHEDULER_ENABLED', 'T24_GBP_SCHEDULER_ACTIVATION_FROM'}
    need({key for key in values if key.startswith('T24_GBP_')} <= expected and GBP_CONFIG_NAMES <= values.keys(), 'EXACT_GOOGLE_ENV_NAMES_REQUIRED')
    need(values['T24_GBP_ENABLED'] == values['T24_GBP_API_APPROVED'] == 'true' and values['T24_GBP_PUBLIC_URL'] == 'https://t24-crm.com', 'EXISTING_GOOGLE_CONFIGURATION_REQUIRED')
    need(values.get('T24_GBP_SCHEDULER_ENABLED', 'false') == 'false' and not values.get('T24_GBP_SCHEDULER_ACTIVATION_FROM', ''), 'SCHEDULER_MUST_REMAIN_DISABLED')


def gbp_disabled_probe():
    return ("import socket\ndef blocked(*args,**kwargs):raise AssertionError('NO_PROVIDER_REQUESTS_PERMITTED')\n"
        "socket.socket.connect=blocked\nfrom services.google_business_provider import enabled,settings\n"
        "from services.google_business_scheduler import enabled as scheduled\n"
        "from services import google_business_ai as ai\n"
        "assert all(callable(getattr(ai,name)) for name in ('status','consent','generate_draft','save_reply_draft','list_drafts','approve_draft','ensure_reply_approval'))\n"
        "assert enabled() is False and scheduled() is False\nconfig,missing=settings()\n"
        "assert set(missing)==" + repr(GBP_CONFIG_NAMES) + "\nassert all(not value for value in config.values())\n"
        "print('EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK')\n")


def active_configuration_probe():
    return ("import socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_REQUESTS_PERMITTED')\n"
        "socket.socket.connect=blocked\nfrom services.google_business_provider import enabled,settings\n"
        "from services.google_business_scheduler import enabled as scheduler\n"
        "assert enabled() is True and scheduler() is False\nassert not settings()[1]\n"
        "print('EXACT_GBP_PRESERVED_SCHEDULER_OFF_NO_NETWORK')\n")


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
    need(all(not value or name in {"T24_GBP_ENABLED", "T24_GBP_API_APPROVED", "T24_GBP_SCHEDULER_ENABLED"} and value == "false" for name, value in env.items() if name.startswith("T24_GBP_")), "OFFLINE_GOOGLE_SECRETS_REJECTED")
    need(not env.get("APP_AI_KEY") and not env.get("OPENAI_API_KEY"), "OFFLINE_AI_KEYS_REJECTED")
    need(env.get("T24_GBP_SCHEDULER_ENABLED") == "false", "OFFLINE_GOOGLE_WORKER_DISABLED")
    synthetic = {'JWT_SECRET_KEY':'offline-only-synthetic-jwt-key-not-production-0123456789', 'MASK_KEY':'offline-only-synthetic-mask-key-not-production-0123456789'}
    for name, value in env.items():
        if not value or not re.search(r'(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)', name, re.I): continue
        if name == 'GPG_KEY' and re.fullmatch('[A-F0-9]{40}', value): continue  # Public image signing fingerprint.
        need(name in synthetic and value == synthetic[name], 'OFFLINE_INHERITED_CREDENTIAL_REJECTED')
    need(not any('/run/secrets' in row.get('Destination','') or '/opt/t24-crm/secrets' in row.get('Source','') for row in info.get('Mounts',[])), 'OFFLINE_SECRET_MOUNT_REJECTED')
    need(info["HostConfig"]["NetworkMode"] == "none", "OFFLINE_NETWORK_NONE_REQUIRED")
    need(env.get("STRIPE_AUTO_POSTING_ENABLED") == "false" and env.get("STRIPE_HISTORY_DAILY_SCAN_ENABLED") == "false", "OFFLINE_WORKERS_MUST_BE_DISABLED")


class Release:
    def __init__(self, args):
        self.args = args
        body = LEGACY.read_bytes()
        need(H(body) == LEGACY_SHA, "IMMUTABLE_RETAINED_HELPER_REQUIRED")
        self.m = types.ModuleType("_google_business_release_primitives")
        self.m.__file__ = str(LEGACY)
        exec(compile(body, self.m.__file__, "exec"), self.m.__dict__)
        m = self.m
        helper = m.read(args.release / "preflight.py", PREFLIGHT_TOOL_SHA)
        self.safe = types.ModuleType("_reviewed_management_preflight")
        self.safe.__file__ = str(args.release / "preflight.py")
        exec(compile(helper, self.safe.__file__, "exec"), self.safe.__dict__)
        self.manifest = json.loads(m.read(args.release / "manifest.json", args.manifest_sha256))
        m.read(args.release / "payload.tar.gz", args.payload_sha256)
        self.proof = json.loads(m.read(args.preflight, args.preflight_sha256))
        self.validate_manifest()
        global PROJECTION
        PROJECTION = {name: {"columns": value} for name, value in self.proof["original_columns"].items()}
        global NEW_OBJECTS
        NEW_OBJECTS = {tuple(item) for item in self.manifest['additive_objects']}
        self.pins = json.loads(m.read(PRIVATE_PINS, PRIVATE_PINS_SHA))
        self.source = self.manifest["source_sha"]
        self.version = self.manifest["frontend_version"]
        self.public = Path("/var/www/t24-crm-public/media-ops-management-" + self.source[:12] + "-20261031")
        need(args.release == Path("/opt/t24-crm/releases/media-ops-management-" + self.source[:12] + "-20261031"), "EXACT_RELEASE_PATH_REQUIRED")
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
        need(p["stage"] == "MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT" and p["host"] == HOST, "EXACT_FRESH_PREFLIGHT_REQUIRED")
        need(p["source_sha"] == BASE_SOURCE and p["frontend_version"] == BASE_FRONTEND and p["schema_revision"] == OLD_REVISION, "PREFLIGHT_BASELINE_DRIFT")
        need(all(p[key] is False for key in ("provider_requests", "business_writes", "container_or_configuration_changed", "credential_content_read", "customer_records_exported")), "READONLY_PROOF_REQUIRED")
        need(p.get("gbp_feature_enabled") is True and p.get("scheduler_disabled") is True, "ENABLED_GBP_DISABLED_SCHEDULER_REQUIRED")
        need(p.get("enabled_receipt_sha256") == BASE_ENABLED_SHA, "EXACT_ENABLED_GOOGLE_PROOF_REQUIRED")
        need(set(p.get("original_columns", {})) == set(p["rows"]) and len(p["rows"]) == 124, "EXACT_ORIGINAL_COLUMN_PROJECTION_REQUIRED")
        need(p.get("callback_logging_protection_retained") is True and re.fullmatch("[a-f0-9]{64}", p.get("active_nginx_config_sha256", "")), "CALLBACK_PROTECTION_REQUIRED")
        need(p["private_boundary_verified"] is True and re.fullmatch("[a-f0-9]{64}", p["backend_inventory_sha256"]), "PREFLIGHT_BOUNDARY_REQUIRED")
        need(SOURCE_SHA != "0" * 40, "PIN_REVIEWED_APPLICATION_SOURCE_FIRST")
        need(v["source_sha"] == SOURCE_SHA and re.fullmatch("[a-f0-9]{12}", v["frontend_version"]), "SOURCE_AND_FRONTEND_PINS_REQUIRED")
        need(set(v.get("changed_source_files", [])) == SOURCE_FILES and len(v["changed_source_files"]) == len(SOURCE_FILES), "EXACT_APPLICATION_SOURCE_SCOPE_REQUIRED")
        need(v["baseline_source_sha"] == BASE_SOURCE and v["baseline_frontend_version"] == BASE_FRONTEND, "EXACT_BASELINE_REQUIRED")
        need(v["preflight_sha256"] == a.preflight_sha256 and v["payload_sha256"] == a.payload_sha256, "EXACT_PREFLIGHT_AND_PAYLOAD_REQUIRED")
        need(v["old_schema_revision"] == OLD_REVISION and v["schema_revision"] == NEW_REVISION and set(v["additive_tables"]) == NEW_TABLES, "EXACT_FIVE_TABLE_MIGRATION_REQUIRED")
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
        tag = 't24-crm:media-ops-management-base-' + self.source[:12]
        existing = m.image_id(tag)
        need(existing is None or existing == m.BASE_IMAGE, 'BASE_TAG_DRIFT')
        if existing is None:
            m.run(['docker', 'image', 'tag', m.BASE_IMAGE, tag], 'BASE_TAG_CREATE_FAILED')
        dockerfile = 'FROM ' + tag + '\n' + ''.join('COPY backend/' + path + ' /app/backend/' + path + '\n' for path in sorted(BACKEND_FILES))
        m.write(release / 'Dockerfile', dockerfile.encode()); m.write(release / '.dockerignore', m.dockerignore())
        candidate = 't24-crm:media-ops-management-' + self.source[:12]
        m.run(['docker', 'build', '--network=none', '--pull=false', '-t', candidate, str(release)], 'CANDIDATE_BUILD_FAILED', 300)
        need(m.image_id(tag) == m.BASE_IMAGE, 'BASE_TAG_DRIFT')
        image = m.image_id(candidate)
        need(bool(re.fullmatch('sha256:[a-f0-9]{64}', image or '')), 'CANDIDATE_IMAGE_PIN_REQUIRED')
        return image

    def current_boundary(self, *, rows=True):
        m, p = self.m, self.proof
        self.private_boundary()
        need(m.credential_boundary() == p["credential_boundary"], "CREDENTIAL_METADATA_DRIFT")
        need(self.safe.protected_metadata(self.safe.GBP_ENV) == p["google_credential_metadata"], "GOOGLE_CREDENTIAL_METADATA_DRIFT")
        identity = m.BUSINESS.stat()
        need([identity.st_dev, identity.st_ino] == p["database_identity"], "DATABASE_INODE_DRIFT")
        need(m.schema_signature(m.BUSINESS, OLD_REVISION) == p["schema_sha256"], "CURRENT_SCHEMA_DRIFT")
        crm = m.inspect("t24-crm")
        need(crm["State"]["Running"] and m.runtime(crm) == p["crm"], "CURRENT_RUNTIME_DRIFT")
        verify_gbp_environment_enabled(crm)
        need(digest(sorted(crm["Config"]["Env"])) == p["environment_sha256"], "EXISTING_ENVIRONMENT_DRIFT")
        m.verify_secret_mount(crm)
        m.verify_production_worker_enabled(crm)
        m.retained().require_safe_original_restart(crm)
        inventory = m.inventory(crm["Id"])
        need(digest(inventory) == p["backend_inventory_sha256"] and len(inventory) == p["backend_file_count"], "CURRENT_BACKEND_SOURCE_DRIFT")
        need(m.static_boundary() == p["public_inventory_sha256"], "CURRENT_STATIC_DRIFT")
        if rows:
            need(snapshot_evidence(database_snapshot(m, m.BUSINESS)) == p["rows"], "CURRENT_ROWS_CHANGED_REFRESH_PREFLIGHT")
        self.nginx_boundary()
        m.ready(crm["Id"])
        return crm

    def private_boundary(self):
        actual = self.safe.safe_private_boundary(self.m, self.pins)
        need(actual == {key: self.proof[key] for key in actual}, 'PRIVATE_METADATA_OR_RUNTIME_DRIFT')

    def nginx_boundary(self, *, updated=False):
        body = self.m.NGINX.read_bytes()
        active = self.m.run(['nginx', '-T'], 'ACTIVE_NGINX_PARSE_FAILED')
        old = os.fsencode(self.proof['public_root']); new = os.fsencode(str(self.public))
        if updated:
            need(body.count(new) == 1 and active.count(new) == 1, 'EXACT_NEW_PUBLIC_ROOT_REQUIRED')
            body, active = body.replace(new, old, 1), active.replace(new, old, 1)
        need(H(body) == self.proof['nginx_sha256'] and H(active) == self.proof['active_nginx_config_sha256'], 'CALLBACK_OR_NONROOT_NGINX_CONFIGURATION_DRIFT')

    def offline_args(self, data, image):
        # No production env file, Google credential or credential mount enters
        # the network-none startup/migration candidate.
        env = {'APP_ENV':'test', 'ENVIRONMENT':'test', 'ENV':'test',
            'JWT_SECRET_KEY':'offline-only-synthetic-jwt-key-not-production-0123456789',
            'MASK_KEY':'offline-only-synthetic-mask-key-not-production-0123456789',
            'DATABASE_URL':'sqlite:///./data/crm_prod.db', 'AUTOMATION_SCAN_ENABLED':'false',
            'STRIPE_HISTORY_DAILY_SCAN_ENABLED':'false', 'STRIPE_AUTO_POSTING_ENABLED':'false',
            'T24_GBP_SCHEDULER_ENABLED':'false', 'T24_GBP_ENABLED':'false', 'T24_GBP_API_APPROVED':'false',
            'T24_GBP_CLIENT_ID':'', 'T24_GBP_CLIENT_SECRET':'', 'T24_GBP_TOKEN_KEY':'', 'T24_GBP_PUBLIC_URL':'',
            'APP_AI_KEY':'', 'OPENAI_API_KEY':'', 'ENABLE_MOCK_DATA':'false', 'MGX_LOAD_INIT_DATA':'false'}
        return ['docker','run','--rm','--network=none','--read-only','--tmpfs','/tmp:rw,nosuid,noexec',
            '--mount','type=bind,src='+str(data)+',dst=/app/backend/data',
            '--mount','type=bind,src='+str(self.args.release/'probe-logs')+',dst=/app/backend/logs',
            *[item for key,value in env.items() for item in ('-e',key+'='+value)],image]

    def new_schema(self, path):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            need(con.execute("SELECT version_num FROM alembic_version").fetchall() == [(NEW_REVISION,)], "EXACT_NEW_SCHEMA_HEAD_REQUIRED")
            need(con.execute("PRAGMA quick_check").fetchall() == [("ok",)], "NEW_DATABASE_INTEGRITY_FAILED")
            for table in NEW_TABLES:
                need(con.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] == 0, "GOOGLE_TABLES_NOT_EMPTY")

        finally:
            con.close()
        return self.m.schema_signature(path, NEW_REVISION)

    def prepare(self):
        m, a, v, p = self.m, self.args, self.manifest, self.proof
        old = self.current_boundary()
        self.nginx_boundary()
        need(set(path.name for path in a.release.iterdir()) == {"release.py", "preflight.py", "manifest.json", "payload.tar.gz"}, "FRESH_STAGING_REQUIRED")
        m.extract(a.release, v)
        before_inventory = m.inventory(old["Id"])
        need(digest(before_inventory) == p["backend_inventory_sha256"], "CURRENT_BACKEND_INVENTORY_DRIFT")
        expected = {**before_inventory, **v["backend_after"]}
        m.write(a.release / "original-container.json", old)
        original_inventory_sha = m.write(a.release / "backend-original-inventory.json", before_inventory)
        inventory_sha = m.write(a.release / "backend-candidate-inventory.json", expected)
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
        self.run_migration(data, image)
        schema = self.new_schema(data / "crm_prod.db")
        additive_objects(objects, m.schema_objects(data / "crm_prod.db"))
        migrated = database_snapshot(m, data / "crm_prod.db")
        compare_original_rows(rows, migrated)
        name = "t24-media-ops-management-probe-" + self.source[:12]
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
            need(b"EXACT_GOOGLE_MEDIA_ROUTES_REGISTERED" in output, "EXACT_GOOGLE_MEDIA_ROUTES_REQUIRED")
            output = m.run(["docker", "exec", name, "python", "-B", "-c", gbp_disabled_probe()], "OFFLINE_GBP_DISABLED_CHECK_FAILED")
            need(b"EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK" in output, "DISABLED_GBP_PROOF_REQUIRED")
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
            "stage": "MEDIA_OPS_MANAGEMENT_PREPARED_OFFLINE_VERIFIED", "source_sha": self.source,
            "frontend_version": self.version, "candidate_image": image, "old_crm": m.runtime(old),
            "preflight_sha256": a.preflight_sha256, "manifest_sha256": a.manifest_sha256, "payload_sha256": a.payload_sha256,
            "old_schema_revision": OLD_REVISION, "schema_revision": NEW_REVISION,
            "schema_before_sha256": p["schema_sha256"], "schema_after_sha256": schema,
            "additive_tables": sorted(NEW_TABLES), "original_table_count": len(rows),
            "candidate_inventory_sha256": inventory_sha, "original_inventory_sha256": original_inventory_sha, "offline_row_proof_sha256": row_sha,
            "public_root": str(root), "public_inventory_sha256": static, "nginx_next_sha256": next_nginx,
            "offline_original_rows_unchanged": True, "offline_new_tables_empty": True,
            "offline_workers_disabled": True, "offline_network_none": True, "offline_credentials_not_mounted": True,
            "offline_google_media_routes_registered": True, "offline_media_timezones_available": True,
            "gbp_disabled_unconfigured_verified": True, "offline_google_secrets_absent": True,
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
        need(receipt["stage"] == "MEDIA_OPS_MANAGEMENT_PREPARED_OFFLINE_VERIFIED" and receipt["source_sha"] == self.source, "PREPARED_SOURCE_DRIFT")
        need(receipt["manifest_sha256"] == a.manifest_sha256 and receipt["payload_sha256"] == a.payload_sha256 and receipt["preflight_sha256"] == a.preflight_sha256, "PREPARED_IDENTITIES_DRIFT")
        need(receipt["schema_before_sha256"] == self.proof["schema_sha256"] and receipt["old_schema_revision"] == OLD_REVISION and receipt["schema_revision"] == NEW_REVISION, "PREPARED_SCHEMA_DRIFT")
        need(set(receipt["additive_tables"]) == NEW_TABLES and receipt["original_table_count"] == len(self.proof["rows"]), "PREPARED_TABLE_SCOPE_DRIFT")
        need(all(receipt[key] is True for key in ("offline_original_rows_unchanged", "offline_new_tables_empty", "offline_workers_disabled", "offline_network_none", "offline_credentials_not_mounted", "offline_google_media_routes_registered", "offline_media_timezones_available", "actual_python310_startup_verified", "private_runtime_unchanged", "gbp_disabled_unconfigured_verified", "offline_google_secrets_absent")), "OFFLINE_PROOF_REQUIRED")
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
        self.private_boundary()
        need(m.credential_boundary() == self.proof["credential_boundary"], "CREDENTIAL_METADATA_DRIFT")
        need(self.safe.protected_metadata(self.safe.GBP_ENV) == self.proof["google_credential_metadata"], "GOOGLE_CREDENTIAL_METADATA_DRIFT")
        candidate = m.inspect("t24-crm")
        need(candidate["State"]["Running"] and candidate["Image"] == receipt["candidate_image"], "EXACT_NEW_CANDIDATE_REQUIRED")
        need(candidate["Config"].get("Labels") == m.expected_labels(original), "NEW_CANDIDATE_LABELS_DRIFT")
        normalized_configuration(candidate, original, m.runtime)
        verify_gbp_environment_enabled(candidate)
        need(candidate["Config"]["Env"] == original["Config"]["Env"], "EXACT_EXISTING_ENVIRONMENT_VALUES_REQUIRED")
        output = m.run(["docker", "exec", candidate["Id"], "python", "-B", "-c", active_configuration_probe()], "PRODUCTION_GBP_PRESERVATION_FAILED")
        need(b"EXACT_GBP_PRESERVED_SCHEDULER_OFF_NO_NETWORK" in output, "EXISTING_GBP_PROOF_REQUIRED")
        m.verify_secret_mount(candidate)
        m.verify_production_worker_enabled(candidate)
        need(m.inventory(candidate["Id"]) == expected, "NEW_CANDIDATE_SOURCE_DRIFT")
        need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "CANDIDATE_SCHEMA_DRIFT")
        need(digest(m.tree(m.PUBLIC)) == self.proof["public_inventory_sha256"], "ORIGINAL_STATIC_FILES_CHANGED")
        m.ready(candidate["Id"])
        return candidate

    def migration_identity(self, data):
        phase = 'production' if data == self.m.BUSINESS.parent else 'offline'
        return phase, self.args.release / ('migration-' + phase + '-container.json')

    def settle_migration(self, data, *, required=False):
        phase, path = self.migration_identity(data)
        if not path.exists():
            need(not required, 'KNOWN_MIGRATION_IDENTITY_REQUIRED')
            return None
        saved = json.loads(self.m.read(path))
        identity = (data / 'crm_prod.db').stat()
        need(saved['source_sha'] == self.source and saved['phase'] == phase and
            saved['database_identity'] == [identity.st_dev, identity.st_ino], 'MIGRATION_DATABASE_IDENTITY_DRIFT')
        info = self.m.inspect(saved['id'])
        need(info['Id'] == saved['id'] and info['Name'] == '/' + saved['name'] and info['Image'] == saved['image'], 'KNOWN_MIGRATION_CONTAINER_DRIFT')
        verify_disabled_environment(info)
        need(info['HostConfig'].get('ReadonlyRootfs') is True and info['Config'].get('Cmd') == ['python','-B','-c',migration_script()], 'MIGRATION_COMMAND_OR_ROOTFS_DRIFT')
        mounts = {(row.get('Source'), row.get('Destination'), row.get('RW')) for row in info.get('Mounts', []) if row.get('Type') == 'bind'}
        need(all(row.get('Type') == 'bind' or row.get('Type') == 'tmpfs' and row.get('Destination') == '/tmp' for row in info.get('Mounts', [])), 'MIGRATION_UNEXPECTED_MOUNT_TYPE')
        need(mounts == {(str(data), '/app/backend/data', True), (str(self.args.release / 'probe-logs'), '/app/backend/logs', True)}, 'MIGRATION_MOUNTS_DRIFT')
        if info['State']['Running']:
            self.m.run(['docker','wait',saved['id']], 'KNOWN_MIGRATION_STILL_RUNNING', 95)
            info = self.m.inspect(saved['id'])
        need(not info['State']['Running'], 'MIGRATION_MUST_EXIT_BEFORE_APPLICATION')
        return info

    def run_migration(self, data, image, *, retry=False):
        m = self.m; phase, path = self.migration_identity(data)
        if path.exists():
            known = self.settle_migration(data, required=True)
            need(known['Image'] == image, 'REVIEWED_MIGRATION_IMAGE_REQUIRED')
            if known['State'].get('Status') == 'exited' and known['State'].get('ExitCode') == 0:
                return
            need(retry and known['State'].get('Status') in {'created','exited'}, 'MIGRATION_RESULT_REQUIRES_REVIEW')
            identity = known['Id']
        else:
            name = 't24-management-migration-' + self.source[:12] + '-' + phase
            need(m.inspect_optional(name) is None, 'UNKNOWN_MIGRATION_NAME_OCCUPIED')
            command = self.offline_args(data, image)
            command[1] = 'create'; command.remove('--rm'); command[2:2] = ['--name', name]
            raw = m.run(command + ['python','-B','-c',migration_script()], 'MIGRATION_CONTAINER_CREATE_FAILED', 30)
            identity = raw.decode().strip()
            need(re.fullmatch('[a-f0-9]{64}', identity), 'EXACT_MIGRATION_CONTAINER_ID_REQUIRED')
            statrow = (data / 'crm_prod.db').stat()
            m.write(path, {'id': identity, 'name': name, 'image': image, 'phase': phase, 'source_sha': self.source,
                'database_identity': [statrow.st_dev, statrow.st_ino]})
            self.settle_migration(data, required=True)
        m.run(['docker','start',identity], 'MIGRATION_START_FAILED', 30)
        m.run(['docker','wait',identity], 'MIGRATION_WAIT_INCOMPLETE', 95)
        info = self.settle_migration(data, required=True)
        need(info['State'].get('Status') == 'exited' and info['State'].get('ExitCode') == 0, 'MIGRATION_PROCESS_FAILED')

    def migrate(self, image):
        self.run_migration(self.m.BUSINESS.parent, image, retry=True)

    def record_candidate(self, identity, receipt):
        value = {'id': identity, 'image': receipt['candidate_image'], 'source_sha': self.source, 'original_id': self.proof['crm']['id']}
        path = self.args.release / 'candidate-identity.json'
        if path.exists(): need(json.loads(self.m.read(path)) == value, 'CANDIDATE_IDENTITY_DRIFT')
        else: self.m.write(path, value)

    def known_candidate(self, receipt):
        path = self.args.release / 'candidate-identity.json'
        if not path.exists(): return None
        row = json.loads(self.m.read(path))
        need(row['image'] == receipt['candidate_image'] and row['source_sha'] == self.source and
            row['original_id'] == self.proof['crm']['id'] and re.fullmatch('[a-f0-9]{64}',row['id']), 'SAVED_CANDIDATE_IDENTITY_DRIFT')
        return row['id']

    def source_overlay_boundary(self, info, expected):
        if info['State']['Running']:
            need(self.m.inventory(info['Id']) == expected, 'RECOVERY_RUNNING_SOURCE_DRIFT')
            return
        parents = {'/app', '/app/backend'}
        for name in expected:
            parts = name.split('/')
            parents.update('/app/backend/' + '/'.join(parts[:index]) for index in range(1,len(parts)))
        checked = set(); excluded = {'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules'}
        for raw in self.m.run(['docker','diff',info['Id']], 'RECOVERY_SOURCE_DIFF_FAILED').decode().splitlines():
            need(len(raw) >= 3 and raw[0] in 'ACD' and raw[1] == ' ', 'RECOVERY_SOURCE_DIFF_REJECTED')
            path = raw[2:]
            if path in parents:
                need(raw[0] == 'C', 'RECOVERY_SOURCE_DIRECTORY_DRIFT'); checked.add(path); continue
            if not path.startswith('/app/backend/'): continue
            name = path[len('/app/backend/'):]; parts = name.split('/')
            if not set(parts) & excluded: raise RuntimeError('RECOVERY_SOURCE_FILE_CHANGED')
            first = next(index for index, part in enumerate(parts) if part in excluded)
            checked.add('/app/backend/' + '/'.join(parts[:first+1]))
        # Check all source parents and excluded-directory roots via HEAD only;
        # no stopped-container code, directory archive, or credential is read.
        for path in sorted(parents | checked):
            conn = self.m.retained().DockerConnection('localhost', timeout=5)
            try:
                import urllib.parse
                conn.request('HEAD','/containers/'+info['Id']+'/archive?path='+urllib.parse.quote(path,safe=''))
                response=conn.getresponse();need(response.status==200,'RECOVERY_SOURCE_DIRECTORY_MISSING')
                value=response.getheader('X-Docker-Container-Path-Stat')
                need(isinstance(value,str) and len(value)<8192,'RECOVERY_SOURCE_STAT_REQUIRED')
                statrow=json.loads(base64.b64decode(value,validate=True))
                need(statrow.get('name')==path.rsplit('/',1)[-1] and statrow.get('linkTarget')=='' and
                    type(statrow.get('mode')) is int and statrow['mode'] & ~0o777 == 1 << 31,'RECOVERY_SOURCE_PARENT_NOT_DIRECTORY')
            finally: conn.close()

    def recovery_boundary(self, receipt, original, expected):
        m, p = self.m, self.proof
        self.private_boundary()
        need(m.credential_boundary() == p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV) == p['google_credential_metadata'], 'RECOVERY_CREDENTIAL_METADATA_DRIFT')
        identity=m.BUSINESS.stat();need([identity.st_dev,identity.st_ino]==p['database_identity'],'RECOVERY_DATABASE_IDENTITY_DRIFT')
        need(digest(m.tree(Path(p['public_root']))) == p['public_inventory_sha256'] and m.verify_public(self.public,self.manifest)==receipt['public_inventory_sha256'],'RECOVERY_STATIC_DRIFT')
        self.nginx_boundary(updated=os.fsencode(str(self.public)) in m.NGINX.read_bytes())
        retained=m.inspect(original['Id'])
        need(retained['Image']==original['Image'] and m.runtime(retained)['config']==m.runtime(original)['config'],'RECOVERY_ORIGINAL_RUNTIME_DRIFT')
        verify_gbp_environment_enabled(retained);m.verify_secret_mount(retained)
        self.source_overlay_boundary(retained,json.loads(m.read(self.args.release/'backend-original-inventory.json',receipt['original_inventory_sha256'])))
        self.settle_migration(m.BUSINESS.parent)
        revision=self.revision()
        schema=self.proof['schema_sha256'] if revision==OLD_REVISION else receipt['schema_after_sha256']
        need(m.schema_signature(m.BUSINESS,revision)==schema,'RECOVERY_SCHEMA_DRIFT')
        active=m.inspect_optional('t24-crm'); known=self.known_candidate(receipt)
        need(not active or active['Id']==original['Id'] or known is not None and active['Id']==known,'UNKNOWN_FORWARD_CONTAINER')
        if active and active['Id']!=original['Id']:
            need(active['Image']==receipt['candidate_image'] and active['Config'].get('Labels')==m.expected_labels(original),'RECOVERY_CANDIDATE_IMAGE_OR_LABEL_DRIFT')
            normalized_configuration(active,original,m.runtime);verify_gbp_environment_enabled(active);m.verify_secret_mount(active)
            self.source_overlay_boundary(active,expected)
        if known is not None and (not active or active['Id']!=known):
            pending=m.inspect(known)
            need(pending['Name']=='/t24-crm' and pending['Image']==receipt['candidate_image'] and pending['Config'].get('Labels')==m.expected_labels(original),'SAVED_CANDIDATE_ROLE_DRIFT')
            normalized_configuration(pending,original,m.runtime);verify_gbp_environment_enabled(pending);m.verify_secret_mount(pending)
            self.source_overlay_boundary(pending,expected)
        return active

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
        active = self.recovery_boundary(receipt, original, expected)
        before_path = a.release / "production-before-rows.json"
        identity_path = a.release / 'production-baseline-identity.json'
        if not identity_path.exists():
            need(self.known_candidate(receipt) is None, 'PRE_MIGRATION_CANDIDATE_MUST_BE_ABSENT')
            need(self.revision()==OLD_REVISION and m.schema_signature(m.BUSINESS,OLD_REVISION)==self.proof['schema_sha256'],'PRE_MIGRATION_OLD_HEAD_REQUIRED')
            need(snapshot_evidence(database_snapshot(m,m.BUSINESS))==self.proof['rows'],'PRE_MIGRATION_ORIGINAL_ROWS_DRIFT')
            need(active is not None and active['Id']==original['Id'],'PRE_MIGRATION_KNOWN_ORIGINAL_REQUIRED')
            if not active['State']['Running']:m.run(['docker','start',original['Id']],'PRE_MIGRATION_RESUME_FAILED')
            m.ready(original['Id'])
            return {'stage':'MEDIA_OPS_MANAGEMENT_PRE_MIGRATION_RESUMED','old_application_started':True,'schema_revision':OLD_REVISION,'database_restored':False}
        saved = json.loads(m.read(identity_path))
        need(saved['source_sha']==self.source and saved['original_id']==original['Id'],'PRODUCTION_BASELINE_IDENTITY_DRIFT')
        before=json.loads(m.read(before_path,saved['rows_sha256']))
        need(snapshot_evidence(before)==self.proof['rows'],'PRODUCTION_BASELINE_PROOF_DRIFT')
        if active and active['State']['Running']:
            m.run(["docker", "stop", "-t", "30", active["Id"]], "FORWARD_STOP_FAILED", 60)
            active=m.inspect(active['Id'])
            need(not active['State']['Running'],'FORWARD_CONTAINER_STILL_RUNNING')
        if self.revision() == OLD_REVISION:
            need(database_snapshot(m, m.BUSINESS) == before, "FORWARD_ORIGINAL_ROWS_CHANGED")
            backup_path = a.release / ("business-forward-before-" + str(time.time_ns()) + ".db")
            m.backup(m.BUSINESS, backup_path)
            need(database_snapshot(m, backup_path) == before, "FORWARD_RESTORABLE_BACKUP_MISMATCH")
            self.migrate(receipt["candidate_image"])
        compare_original_rows(before, database_snapshot(m, m.BUSINESS))
        need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "FORWARD_NEW_SCHEMA_REQUIRED")
        if active and active["Id"] == original["Id"]:
            m.run(["docker", "rename", active["Id"], "t24-crm-before-media-ops-management-" + self.source[:12]], "FORWARD_RETAIN_ORIGINAL_FAILED")
            active = None
        known=self.known_candidate(receipt)
        candidate=active['Id'] if active else known
        if candidate is None:
            candidate=m.docker_create(receipt['candidate_image'],original);self.record_candidate(candidate,receipt)
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
        self.nginx_boundary(updated=True)
        compare_original_rows(before, database_snapshot(m, m.BUSINESS))
        result = {"stage": "MEDIA_OPS_MANAGEMENT_FORWARD_RECOVERED", "source_sha": self.source,
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
            m.write(a.release / "production-baseline-identity.json", {"source_sha": self.source, "original_id": original["Id"], "rows_sha256": before_sha})
            m.backup(m.BUSINESS, a.release / "business-before.db")
            need(database_snapshot(m, a.release / "business-before.db") == before, "RESTORABLE_BACKUP_MISMATCH")
            objects = m.schema_objects(m.BUSINESS)
            self.migrate(receipt["candidate_image"])
            additive_objects(objects, m.schema_objects(m.BUSINESS))
            need(self.new_schema(m.BUSINESS) == receipt["schema_after_sha256"], "PRODUCTION_SCHEMA_DRIFT")
            migrated = database_snapshot(m, m.BUSINESS)
            compare_original_rows(before, migrated)
            m.write(a.release / "production-after-migration-rows.json", migrated)
            m.run(["docker", "rename", current["Id"], "t24-crm-before-media-ops-management-" + self.source[:12]], "RETAIN_ORIGINAL_FAILED")
            candidate = m.docker_create(receipt["candidate_image"], original)
            self.record_candidate(candidate,receipt)
            m.run(["docker", "start", candidate], "NEW_CANDIDATE_START_FAILED")
            self.candidate_boundary(receipt, original, expected)
            need(database_snapshot(m, m.BUSINESS) == migrated, "NEW_STARTUP_CHANGED_ORIGINAL_ROWS")
            m.replace_nginx(original_nginx, updated_nginx)
            m.retained().reload_nginx()
            need(m.verify_public(self.public, self.manifest) == receipt["public_inventory_sha256"], "NEW_PUBLIC_INVENTORY_DRIFT")
            need(H(m.NGINX.read_bytes()) == receipt["nginx_next_sha256"], "NEW_NGINX_DRIFT")
            self.nginx_boundary(updated=True)
            version = json.loads(m.run(["curl", "-q", "--noproxy", "*", "-fsS", "--max-time", "20", "https://t24-crm.com/app-version.json"], "PUBLIC_VERSION_FAILED", 25))
            ready = json.loads(m.run(["curl", "-q", "--noproxy", "*", "-fsS", "--max-time", "20", "https://t24-crm.com/ready"], "PUBLIC_READY_FAILED", 25))
            need(version.get("version") == self.version and ready.get("status") == "ready", "PUBLIC_RELEASE_NOT_READY")
            current_new = self.candidate_boundary(receipt, original, expected)
            final = database_snapshot(m, m.BUSINESS)
            need(final == migrated, "FINAL_ORIGINAL_ROWS_CHANGED")
            final_sha = m.write(a.release / "production-after-rows.json", final)
            result = {"stage": "MEDIA_OPS_MANAGEMENT_DEPLOYED_VERIFIED", "deployed": True,
                "source_sha": self.source, "frontend_version": self.version, "crm": m.runtime(current_new),
                "schema_revision": NEW_REVISION, "schema_sha256": receipt["schema_after_sha256"],
                "additive_tables": sorted(NEW_TABLES), "original_table_count": len(before),
                "original_rows_unchanged": True, "new_google_tables_empty": True,
                "production_before_rows_sha256": before_sha, "production_after_rows_sha256": final_sha,
                "candidate_inventory_sha256": receipt["candidate_inventory_sha256"],
                "public_root": str(self.public), "public_inventory_sha256": receipt["public_inventory_sha256"],
                "nginx_sha256": receipt["nginx_next_sha256"], "nginx_only_public_root_changed": True,
                "private_runtime_unchanged": True, "environment_network_mounts_unchanged": True,
                "existing_google_environment_preserved": True, "scheduler_disabled": True,
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
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    need(args.release.resolve() == args.release and args.release.parent == Path("/opt/t24-crm/releases"), "EXACT_RELEASE_PARENT_REQUIRED")
    info = args.release.lstat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700, "PROTECTED_RELEASE_REQUIRED")
    for sha in (args.manifest_sha256, args.payload_sha256, args.preflight_sha256):
        need(bool(re.fullmatch("[a-f0-9]{64}", sha)), "EXACT_HASH_PINS_REQUIRED")
    lock = os.open("/opt/t24-crm/releases/.media-ops-management-release.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    release = Release(args)
    getattr(release, args.phase)()


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        print(json.dumps({"stage": "MEDIA_OPS_MANAGEMENT_RELEASE_REJECTED", "code": safe_error(error),
            "database_restored": False, "old_application_started_after_migration": False}))
        sys.exit(1)
