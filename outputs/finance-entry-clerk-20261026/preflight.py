"""Fresh read-only runtime/schema/source proof; contains no records or secrets."""
import base64
import hashlib
import json
import os
import re
import socket
import sys
import types
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
H = lambda body: hashlib.sha256(body).hexdigest()
HOST = "iZj6c4cj7edgnhdimts4l7Z"
BASE_SOURCE = "967982de56e86da9c6110418c50e705e8c2c5e94"
BASE_FRONTEND = "aba87c858ca3"
BASE_REVISION = "f3c7d1a9b456"
LEGACY = Path("/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py")
LEGACY_SHA = "bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0"
PINS = Path("/opt/t24-crm/releases/commission-service-month-preflight-20261013.json")
PINS_SHA = "af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161"
BACKEND_FILES = {"main.py", "services/schema_readiness.py", "services/role_permissions.py", "routers/app_config.py",
 "models/finance_entry_drafts.py", "services/finance_entry_drafts.py", "routers/finance_entry_drafts.py",
 "models/finance_entry_attachments.py", "services/finance_entry_attachments.py", "routers/finance_entry_attachments.py",
 "alembic/versions/a8d4e2c6f901_finance_entry_drafts.py"}
NEW_TABLES = {"finance_entry_drafts", "finance_entry_draft_audits", "finance_entry_attachments"}


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def snapshot_evidence(rows):
    return {name: {"count": row["count"], "rows_sha256": row["rows_sha256"],
        "shape_sha256": H(json.dumps({key: row[key] for key in ("columns", "schema", "indexes")}, sort_keys=True, separators=(",", ":")).encode())}
        for name, row in rows.items()}


def legacy():
    body = LEGACY.read_bytes()
    need(H(body) == LEGACY_SHA, "IMMUTABLE_RETAINED_HELPER_REQUIRED")
    module = types.ModuleType("_finance_entry_clerk_preflight_legacy")
    module.__file__ = str(LEGACY)
    exec(compile(body, module.__file__, "exec"), module.__dict__)
    return module


def proof():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, "EXACT_SERVER_ROOT_REQUIRED")
    m = legacy()
    pins = json.loads(m.read(PINS, PINS_SHA))
    crm = m.inspect("t24-crm")
    need(crm["State"]["Running"], "CURRENT_CRM_NOT_RUNNING")
    m.retained().require_safe_original_restart(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.private_boundary(pins)
    credential = m.credential_boundary()  # Stat and provisioning-proof identity only.
    inventory = m.inventory(crm["Id"])
    schema = m.schema_signature(m.BUSINESS, BASE_REVISION)
    rows = m.sql_snapshot(m.BUSINESS)
    need(not NEW_TABLES & rows.keys(), "DRAFT_TABLE_ALREADY_PRESENT")
    nginx = m.NGINX.read_bytes()
    roots = re.findall(rb"(?m)^\s*root\s+([^;]+);", nginx)
    need(len(roots) == 1, "EXACT_PUBLIC_ROOT_REQUIRED")
    public_root = Path(os.fsdecode(roots[0]))
    need(public_root.parent == Path("/var/www/t24-crm-public") and public_root.resolve() == public_root, "CURRENT_PUBLIC_ROOT_DRIFT")
    static = m.tree(public_root)
    need(json.loads((public_root / "app-version.json").read_bytes())["version"] == BASE_FRONTEND, "CURRENT_FRONTEND_DRIFT")
    m.ready(crm["Id"])
    need(rows == m.sql_snapshot(m.BUSINESS), "ROWS_CHANGED_DURING_PREFLIGHT")
    need(m.runtime(crm) == m.runtime(m.inspect("t24-crm")), "RUNTIME_CHANGED_DURING_PREFLIGHT")
    need(inventory == m.inventory(crm["Id"]), "SOURCE_CHANGED_DURING_PREFLIGHT")
    need(nginx == m.NGINX.read_bytes() and static == m.tree(public_root), "STATIC_CHANGED_DURING_PREFLIGHT")
    m.private_boundary(pins)
    identity = m.BUSINESS.stat()
    return {
        "stage": "FINANCE_ENTRY_CLERK_READONLY_PREFLIGHT",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "host": HOST,
        "source_sha": BASE_SOURCE,
        "frontend_version": BASE_FRONTEND,
        "schema_revision": BASE_REVISION,
        "schema_sha256": schema,
        "crm": m.runtime(crm),
        "backend_inventory_sha256": m.digest(inventory),
        "backend_file_count": len(inventory),
        "backend_changed_before": {name: inventory.get(name) for name in sorted(BACKEND_FILES)},
        "database_identity": [identity.st_dev, identity.st_ino],
        "rows": snapshot_evidence(rows),
        "nginx_sha256": H(nginx),
        "public_root": str(public_root),
        "public_inventory_sha256": m.digest(static),
        "public_file_count": len(static),
        "private_runtime": {role: pins["roles"][role]["runtime"] for role in ("api", "worker")},
        "private_boundary_verified": True,
        "credential_boundary": credential,
        "provider_requests": False,
        "business_writes": False,
        "container_or_configuration_changed": False,
        "credential_content_read": False,
        "customer_records_exported": False,
    }


def main():
    result = proof()
    body = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    print(json.dumps({"stage": result["stage"], "proof_bytes": len(body), "proof_sha256": H(body),
        "proof_zlib_base64": base64.b64encode(zlib.compress(body, 9)).decode()}))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        code = str(error)
        print(json.dumps({"stage": "FINANCE_ENTRY_CLERK_PREFLIGHT_REJECTED",
            "code": code if re.fullmatch("[A-Z0-9_]+", code) else type(error).__name__.upper()}))
        sys.exit(1)
