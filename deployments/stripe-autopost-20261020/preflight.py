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
BASE_SOURCE = "7caf0f652525e593c33d6bfea9724c72efd3aab8"
BASE_FRONTEND = "0f8ad5c23245"
BASE_REVISION = "e2b6c0f8a345"
LEGACY = Path("/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py")
LEGACY_SHA = "bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0"
COMPAT = Path("/opt/t24-crm/releases/daily-scan-py310-7caf0f652525-20261020")
PINS = Path("/opt/t24-crm/releases/commission-service-month-preflight-20261013.json")
PINS_SHA = "af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161"
BACKEND_FILES = {"main.py", "models/stripe_auto_posting.py", "schemas/stripe_auto_posting.py",
    "routers/stripe_auto_posting.py", "services/stripe_auto_posting.py",
    "routers/management_decisions.py",
    "services/stripe_history_reconciliation.py", "services/stripe_history_daily_scan.py",
    "alembic/versions/f3c7d1a9b456_stripe_auto_posting.py"}


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
    module = types.ModuleType("_stripe_autopost_preflight_legacy")
    module.__file__ = str(LEGACY)
    exec(compile(body, module.__file__, "exec"), module.__dict__)
    return module


def proof():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, "EXACT_SERVER_ROOT_REQUIRED")
    m = legacy()
    pins = json.loads(m.read(PINS, PINS_SHA))
    prepared = json.loads(m.read(COMPAT / "prepared.json", "fb2f61522e06500303945ccb9c6f37f8fd1556a8366bc9a6d948550fa21228fb"))
    expected = json.loads(m.read(COMPAT / "expected-inventory.json", prepared["candidate_inventory_sha256"]))
    crm = m.inspect("t24-crm")
    labels = crm["Config"].get("Labels") or {}
    need(crm["State"]["Running"] and crm["Image"] == prepared["candidate_image"], "CURRENT_CRM_IMAGE_DRIFT")
    need(labels.get("t24.release.source") == BASE_SOURCE, "CURRENT_APPLICATION_SOURCE_DRIFT")
    need(labels.get("t24.release.scope") == "stripe-history-daily-scan-py310-compat", "CURRENT_APPLICATION_SCOPE_DRIFT")
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.private_boundary(pins)
    credential = m.credential_boundary()  # Stat and provisioning-proof identity only.
    inventory = m.inventory(crm["Id"])
    need(inventory == expected, "CURRENT_BACKEND_SOURCE_DRIFT")
    schema = m.schema_signature(m.BUSINESS, BASE_REVISION)
    rows = m.sql_snapshot(m.BUSINESS)
    need(not {"stripe_auto_posting_policies", "stripe_auto_posting_jobs"} & rows.keys(), "AUTOMATIC_POSTING_TABLE_ALREADY_PRESENT")
    nginx = m.NGINX.read_bytes()
    roots = re.findall(rb"(?m)^\s*root\s+([^;]+);", nginx)
    need(len(roots) == 1, "EXACT_PUBLIC_ROOT_REQUIRED")
    public_root = Path(os.fsdecode(roots[0]))
    need(public_root == m.public_root() and public_root.resolve() == public_root, "CURRENT_PUBLIC_ROOT_DRIFT")
    static = m.tree(public_root)
    need(json.loads((public_root / "app-version.json").read_bytes())["version"] == BASE_FRONTEND, "CURRENT_FRONTEND_DRIFT")
    m.ready(crm["Id"])
    identity = m.BUSINESS.stat()
    return {
        "stage": "STRIPE_AUTOMATIC_POSTING_READONLY_PREFLIGHT",
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
        "financial_tables": m.FINANCIAL_TABLES,
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
        print(json.dumps({"stage": "STRIPE_AUTOMATIC_POSTING_PREFLIGHT_REJECTED",
            "code": code if re.fullmatch("[A-Z0-9_]+", code) else type(error).__name__.upper()}))
        sys.exit(1)
