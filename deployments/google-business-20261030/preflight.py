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
BASE_SOURCE = "d70c28dae860598229c7d81299d8a65db016f764"
BASE_FRONTEND = "dcebcd11552a"
BASE_REVISION = "b7c2d9e4a601"
LEGACY = Path("/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py")
LEGACY_SHA = "bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0"
PINS = Path("/opt/t24-crm/releases/commission-service-month-preflight-20261013.json")
PINS_SHA = "af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161"
BACKEND_FILES = {"routers/google_business.py", "models/google_business.py", "services/google_business.py", "services/google_business_provider.py", "services/media_operations.py", "alembic/versions/c8d3e5f6a702_google_business.py"}
NEW_TABLES = {"google_business_connections", "google_business_oauth_states", "google_business_bindings", "google_business_grants", "google_business_actions"}
PRIOR_RELEASE = Path("/opt/t24-crm/releases/media-operations-d70c28dae860-20261030")
PRIOR_DEPLOYED_SHA = "813d64b72eab69ea623b164af1ad82e4c7890c8e8b611a277b304f8feff1d10c"
BASE_IMAGE = "sha256:e4ea5e98a8f9598ab24625df2b7f9756f595b7f887416a76ed4538394c1be033"


def verify_gbp_environment_absent(info):
    names = {value.split("=", 1)[0] for value in info["Config"]["Env"]}
    need(not any(name.startswith("T24_GBP_") for name in names), "GBP_CONFIG_MUST_REMAIN_ABSENT")


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
    module = types.ModuleType("_google_business_preflight_legacy")
    module.__file__ = str(LEGACY)
    exec(compile(body, module.__file__, "exec"), module.__dict__)
    return module


def proof():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, "EXACT_SERVER_ROOT_REQUIRED")
    m = legacy()
    pins = json.loads(m.read(PINS, PINS_SHA))
    prior = json.loads(m.read(PRIOR_RELEASE / "deployed.json", PRIOR_DEPLOYED_SHA))
    need(prior["stage"] == "MEDIA_OPERATIONS_DEPLOYED_VERIFIED" and prior["deployed"] is True and prior["source_sha"] == BASE_SOURCE and prior["frontend_version"] == BASE_FRONTEND and prior["schema_revision"] == BASE_REVISION, "EXACT_PRIOR_RELEASE_REQUIRED")
    crm = m.inspect("t24-crm")
    need(crm["State"]["Running"] and crm["Image"] == BASE_IMAGE and m.runtime(crm) == prior["crm"], "CURRENT_CRM_RUNTIME_DRIFT")
    verify_gbp_environment_absent(crm)
    m.retained().require_safe_original_restart(crm)
    m.verify_secret_mount(crm)
    m.verify_production_worker_enabled(crm)
    m.private_boundary(pins)
    credential = m.credential_boundary()  # Stat and provisioning-proof identity only.
    inventory = m.inventory(crm["Id"])
    prior_inventory = json.loads(m.read(PRIOR_RELEASE / "backend-candidate-inventory.json", prior["candidate_inventory_sha256"]))
    need(inventory == prior_inventory, "PRIOR_RELEASE_SOURCE_INVENTORY_DRIFT")
    schema = m.schema_signature(m.BUSINESS, BASE_REVISION)
    need(schema == prior["schema_sha256"], "PRIOR_RELEASE_SCHEMA_DRIFT")
    rows = m.sql_snapshot(m.BUSINESS)
    need(not NEW_TABLES & rows.keys(), "GOOGLE_TABLE_ALREADY_PRESENT")
    need(len(rows) == 119, "EXACT_EXISTING_TABLE_COUNT_REQUIRED")
    nginx = m.NGINX.read_bytes()
    roots = re.findall(rb"(?m)^\s*root\s+([^;]+);", nginx)
    need(len(roots) == 1, "EXACT_PUBLIC_ROOT_REQUIRED")
    public_root = Path(os.fsdecode(roots[0]))
    need(public_root.parent == Path("/var/www/t24-crm-public") and public_root.resolve() == public_root, "CURRENT_PUBLIC_ROOT_DRIFT")
    static = m.tree(public_root)
    need(str(public_root) == prior["public_root"] and m.digest(static) == prior["public_inventory_sha256"] and H(nginx) == prior["nginx_sha256"], "PRIOR_RELEASE_STATIC_DRIFT")
    need(json.loads((public_root / "app-version.json").read_bytes())["version"] == BASE_FRONTEND, "CURRENT_FRONTEND_DRIFT")
    m.ready(crm["Id"])
    need(rows == m.sql_snapshot(m.BUSINESS), "ROWS_CHANGED_DURING_PREFLIGHT")
    need(m.runtime(crm) == m.runtime(m.inspect("t24-crm")), "RUNTIME_CHANGED_DURING_PREFLIGHT")
    need(inventory == m.inventory(crm["Id"]), "SOURCE_CHANGED_DURING_PREFLIGHT")
    need(nginx == m.NGINX.read_bytes() and static == m.tree(public_root), "STATIC_CHANGED_DURING_PREFLIGHT")
    m.private_boundary(pins)
    identity = m.BUSINESS.stat()
    return {
        "stage": "GOOGLE_BUSINESS_READONLY_PREFLIGHT",
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
        "prior_deployed_sha256": PRIOR_DEPLOYED_SHA,
        "gbp_environment_absent": True,
        "gbp_feature_enabled": False,
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
        print(json.dumps({"stage": "GOOGLE_BUSINESS_PREFLIGHT_REJECTED",
            "code": code if re.fullmatch("[A-Z0-9_]+", code) else type(error).__name__.upper()}))
        sys.exit(1)
