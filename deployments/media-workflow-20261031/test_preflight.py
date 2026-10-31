"""Independent synthetic tests for the scheduler-ON read-only preflight."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("workflow_readonly_preflight", HERE / "preflight.py")
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


@pytest.fixture
def synthetic_baseline(tmp_path, monkeypatch):
    site = tmp_path / "static"; site.mkdir()
    (site / "app-version.json").write_text(json.dumps({"version": p.BASE_FRONTEND}))
    nginx = tmp_path / "site.conf"; nginx.write_text("root " + str(site) + ";\nlocation = /api/v1/google-business/oauth/callback { access_log off; }\n")
    active = b"# full active nginx\n" + nginx.read_bytes()
    database = tmp_path / "synthetic.db"; database.write_bytes(b"SYNTHETIC-NOT-A-LIVE-DATABASE")
    inventory = {name: "a" * 64 for name in {"main.py", "routers/media_operations.py", "services/google_business.py", "services/google_business_management.py", "services/media_operations.py"}}
    inventory["protected-module.py"] = "b" * 64
    runtime = {"id": p.ORIGINAL_ID, "image": p.IMAGE, "config": "c" * 64, "started": "2026-10-30T19:40:12.644333025Z", "restart": 0}
    env = ["T24_GBP_" + key + "=" + value for key, value in {
        "ENABLED": "true", "API_APPROVED": "true", "CLIENT_ID": "SYNTHETIC-CLIENT",
        "CLIENT_SECRET": "DO_NOT_EXPORT_CLIENT_SECRET", "TOKEN_KEY": "DO_NOT_EXPORT_TOKEN_KEY",
        "PUBLIC_URL": "https://t24-crm.com", "SCHEDULER_ENABLED": "true",
        "SCHEDULER_ACTIVATION_FROM": p.ACTIVATION_FROM}.items()]
    crm = {"Id": p.ORIGINAL_ID, "State": {"Running": True}, "Config": {"Env": env}, "_runtime": runtime}
    receipt = {"stage": "MEDIA_PUBLICATION_DEPLOYED_VERIFIED", "deployed": True, "source_sha": p.BASE_SOURCE,
        "frontend_version": p.BASE_FRONTEND, "schema_revision": p.REVISION, "public_root": str(site),
        "candidate_inventory_sha256": p.H((json.dumps(inventory, sort_keys=True, indent=2) + "\n").encode()),
        "schema_sha256": "d" * 64, "public_inventory_sha256": "e" * 64, "nginx_sha256": p.H(nginx.read_bytes()),
        "preflight_sha256": "f" * 64, "crm": copy.deepcopy(runtime), "scheduler_enabled": True,
        "scheduler_activation_from": p.ACTIVATION_FROM, **{key: True for key in (
            "original_env_mounts_network_unchanged", "existing_google_environment_preserved", "original_business_rows_unchanged", "private_runtime_unchanged", "no_new_policy_task_schedule_or_post")}}
    oldproof = {"public_root": "/previous-public-root", "active_nginx_config_sha256": p.H(active.replace(str(site).encode(), b"/previous-public-root", 1))}
    rows = {"table_" + str(i): {"count": i, "rows_sha256": str(i % 10) * 64,
        "columns": ["id", "private_content"], "schema": ["SYNTHETIC"], "indexes": [],
        "unexported_raw_record": "DO_NOT_EXPORT_ORIGINAL_RECORD"} for i in range(129)}
    rows["media_operation_publication_specs"] = copy.deepcopy(rows["table_0"])
    calls = []
    def read(path, sha=None):
        choices = {p.OLD / "deployed.json": (receipt, p.DEPLOYED_SHA),
            Path("/opt/t24-crm/releases/media-publication-preflight-" + receipt["preflight_sha256"][:12] + ".json"): (oldproof, receipt["preflight_sha256"])}
        value, expected = choices[path]; assert sha == expected
        return json.dumps(value).encode()
    monkeypatch.setattr(p, "read", read)
    def command(argv, code):
        assert argv == ["nginx", "-T"]
        calls.append("nginx-T"); return active
    m = SimpleNamespace(inspect=lambda name: crm if name == "t24-crm" else (_ for _ in ()).throw(AssertionError("unknown container")),
        runtime=lambda row: row["_runtime"], verify_secret_mount=lambda _: calls.append("mount-metadata"),
        verify_production_worker_enabled=lambda _: calls.append("existing-stripe-worker"),
        retained=lambda: SimpleNamespace(require_safe_original_restart=lambda _: calls.append("restart-policy")),
        inventory=lambda _: inventory, schema_signature=lambda *_: "d" * 64, digest=lambda value: value,
        tree=lambda _: "e" * 64, NGINX=nginx, run=command,
        read=lambda *_: b'{"metadata_only":true}', BUSINESS=database, sql_snapshot=lambda _: rows,
        credential_boundary=lambda: {"credential_file_metadata": True})
    def private_metadata(*_): calls.append("private-metadata-only"); return {"private_boundary_scope": "metadata_only"}
    safe = SimpleNamespace(safe_private_boundary=private_metadata, protected_metadata=lambda _: {"uid": 0, "mode": 384}, GBP_ENV=Path("/synthetic-google.env"))
    base = SimpleNamespace(PRIVATE_PINS=Path("/synthetic-private-pins.json"), PRIVATE_PINS_SHA="1" * 64)
    helper = SimpleNamespace(db_metadata=lambda _: {"pragma_sha256": "2" * 64, "sequence_exists": True,
        "sequence_sha256": "3" * 64, "sequence_values": {"only_in_protected_proof": 123}}, docker_timestamp_probe=lambda: True)
    return SimpleNamespace(helper=helper, m=m, base=base, safe=safe, crm=crm, receipt=receipt,
        oldproof=oldproof, rows=rows, inventory=inventory, calls=calls, active=active)


def collect(s):
    return p.baseline(s.helper, s.m, s.base, s.safe)


def test_positive_baseline_exports_hashes_not_business_records_or_secret_values(synthetic_baseline):
    s = synthetic_baseline; proof = collect(s)
    assert proof["scheduler_enabled"] is True and proof["scheduler_activation_from"] == p.ACTIVATION_FROM
    assert proof["crm"]["id"] == p.ORIGINAL_ID and len(proof["rows"]) == 130
    assert all(set(row) == {"count", "rows_sha256", "shape_sha256"} for row in proof["rows"].values())
    encoded = json.dumps(proof)
    for canary in ("DO_NOT_EXPORT_ORIGINAL_RECORD", "DO_NOT_EXPORT_CLIENT_SECRET", "DO_NOT_EXPORT_TOKEN_KEY"):
        assert canary not in encoded
    assert s.calls.count("private-metadata-only") == 1
    assert proof["provider_requests"] is proof["business_writes"] is False


@pytest.mark.parametrize("key,value", [("T24_GBP_SCHEDULER_ENABLED", "false"),
    ("T24_GBP_SCHEDULER_ACTIVATION_FROM", "2026-10-31T00:00:00Z"), ("T24_GBP_ENABLED", "false")])
def test_scheduler_or_cutoff_cannot_be_silently_disabled_or_reset(synthetic_baseline, key, value):
    s = synthetic_baseline; s.crm["Config"]["Env"] = [key + "=" + value if row.startswith(key + "=") else row for row in s.crm["Config"]["Env"]]
    with pytest.raises(RuntimeError): collect(s)


@pytest.mark.parametrize("change", ["duplicate_env", "new_gbp_env", "runtime", "inventory", "schema", "table_added", "table_removed", "callback", "enabled_receipt"])
def test_existing_boundary_drift_fails_closed(synthetic_baseline, change):
    s = synthetic_baseline
    if change == "duplicate_env": s.crm["Config"]["Env"].append("T24_GBP_ENABLED=true")
    elif change == "new_gbp_env": s.crm["Config"]["Env"].append("T24_GBP_NEW_FEATURE=true")
    elif change == "runtime": s.crm["_runtime"] = {**s.crm["_runtime"], "config": "0" * 64}
    elif change == "inventory": s.inventory["protected-module.py"] = "0" * 64
    elif change == "schema": s.m.schema_signature = lambda *_: "0" * 64
    elif change == "table_added": s.rows["media_publication_images"] = copy.deepcopy(s.rows["table_0"])
    elif change == "table_removed": del s.rows["table_0"]
    elif change == "callback": s.m.run = lambda *_: s.active + b"# unreviewed callback change\n"
    else: s.receipt["scheduler_enabled"] = False
    with pytest.raises(RuntimeError): collect(s)


def test_collect_root_guard_precedes_loading_or_docker_access(monkeypatch):
    calls = []
    monkeypatch.setattr(p.os, "geteuid", lambda: 501)
    monkeypatch.setattr(p, "dependencies", lambda: calls.append("unexpected"))
    with pytest.raises(RuntimeError, match="EXACT_ROOT_SERVER_REQUIRED"): p.collect()
    assert calls == []


def test_two_readonly_baselines_must_match(monkeypatch):
    monkeypatch.setattr(p.os, "geteuid", lambda: 0)
    monkeypatch.setattr(p.socket, "gethostname", lambda: p.HOST)
    monkeypatch.setattr(p.resource, "setrlimit", lambda *_: None)
    monkeypatch.setattr(p.os, "umask", lambda *_: 0)
    monkeypatch.setattr(p, "dependencies", lambda: (SimpleNamespace(docker_timestamp_probe=lambda: True), None, None, None))
    count = [0]
    def baseline(*_): count[0] += 1; return {"rows_hash": str(count[0])}
    monkeypatch.setattr(p, "baseline", baseline)
    with pytest.raises(RuntimeError, match="PREFLIGHT_CHANGED_DURING_READ"): p.collect()


def test_retained_helper_and_live_receipt_pins_match_reviewed_local_evidence():
    repository = HERE.parents[1]
    assert p.OLD_PREFLIGHT_SHA == hashlib.sha256((repository / "deployments/media-publication-20261031/preflight.py").read_bytes()).hexdigest()
    assert p.DEPLOYED_SHA == hashlib.sha256((repository / "outputs/media-publication-20261031/actual-deployed.json").read_bytes()).hexdigest()


def test_delivery_log_prefix_must_not_preexist(synthetic_baseline):
    s = synthetic_baseline
    s.receipt["nginx_sha256"] = p.H(s.m.NGINX.read_bytes())
    s.m.run = lambda *_: s.active + b"location ^~ /api/v1/media-publication-images/delivery/ { access_log off; }"
    with pytest.raises(RuntimeError): collect(s)


def test_actual_phase_one_dependency_contract_returns_four_modules(monkeypatch):
    modules = tuple(SimpleNamespace(name=name) for name in ('helper','legacy','base','safe'))
    monkeypatch.setattr(p,'load',lambda path,sha,name:SimpleNamespace(dependencies=lambda:modules))
    assert p.dependencies() == modules


def test_retained_dependency_contract_drift_has_named_rejection(monkeypatch):
    monkeypatch.setattr(p,'load',lambda path,sha,name:SimpleNamespace(dependencies=lambda:(1,2,3)))
    with pytest.raises(RuntimeError,match='RETAINED_DEPENDENCY_ARITY_REQUIRED'):p.dependencies()
