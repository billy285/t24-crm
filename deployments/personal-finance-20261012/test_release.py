"""Synthetic release guards only. Never invoke Docker, a provider, or production."""
import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("personal_finance_release", Path(__file__).with_name("release.py"))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)
ARTIFACTS = Path(__file__).with_name("artifacts")


@pytest.fixture
def manifest():
    return json.loads((ARTIFACTS / "manifest.json").read_bytes())


def database(tables, inode=10, populated=True):
    rows = {name: {"columns_sha256": "a" * 64, "rows": 1 if populated else 0,
                   "rows_sha256": "b" * 64} for name in tables}
    objects = {name: {"type": "table", "table": name, "sql_sha256": "c" * 64} for name in tables}
    objects.update({name + "_owner": {"type": "index", "table": name, "sql_sha256": "d" * 64} for name in tables})
    return {"identity": {"device": 1, "inode": inode, "path_sha256": "e" * 64, "uid": 0, "mode": 384},
            "tables": rows, "schema_objects": objects, "schema_sha256": r.digest(objects), "data_sha256": r.digest(rows)}


@pytest.fixture
def snapshots():
    before = {"private": database(r.BASE_TABLES), "business": database(["business"], inode=20)}
    after = copy.deepcopy(before)
    new = database(r.NEW_TABLES, populated=False)
    after["private"]["tables"].update(new["tables"])
    after["private"]["schema_objects"].update(new["schema_objects"])
    return before, after


def candidate(manifest, snapshots):
    return {"format_version": 1, "stage": "PERSONAL_FINANCE_CANDIDATE_VERIFIED", "source_sha": r.SOURCE,
        "baseline_private_source_sha": r.BASE_SOURCE, "base_image_id": r.BASE_IMAGE,
        "image_id": "sha256:" + "1" * 64, "rollback_image_id": "sha256:" + "2" * 64,
        "manifest_sha256": "3" * 64, "preflight_sha256": "4" * 64, "payload_sha256": manifest["payload_sha256"],
        **{field: True for field in ("rollback_model_registration_only", "all_other_backend_bytes_identical",
            "all_runtime_package_bytes_identical", "bundled_static_bytes_unchanged", "base_layers_verified", "base_pin_verified")},
        **{field: False for field in ("production_environment_loaded", "production_database_access",
            "production_services_modified", "public_assets_published", "deployed")},
        "regressions": {"tests": 1192, "minimum": 1192, "python": "3.10.22", "network": "none",
            "all_private_tests": manifest["private_tests"], "xml_sha256": "5" * 64},
        "synthetic_schema": {"stage": "PERSONAL_FINANCE_ELEVEN_TO_TWENTY_VERIFIED", "source_sha": r.SOURCE,
            "private_tables": 20, "existing_private_tables_preserved": 11,
            **{field: True for field in ("crm_unchanged", "new_personal_tables_empty",
                "populated_new_ledger_preserved", "compatible_old_api_started_and_owner_read",
                "encrypted_existing_credentials_decrypted", "interrupted_ddl_compatible_rollback_verified",
                "business_physically_readonly")},
            "schema_objects": snapshots[1]["private"]["schema_objects"]}}


def test_frozen_actual_payload_scope_and_rollback_recipe(manifest):
    assert r.checked_manifest(manifest) is manifest
    assert r.sha((ARTIFACTS / "payload.tar.gz").read_bytes()) == manifest["payload_sha256"]
    base = "t24-private-personal-base:" + r.SOURCE[:12] + "-abcdef012345"
    normal = r.recipe(base).decode()
    rollback = r.recipe(base, rollback=True).decode()
    assert normal.count("COPY ") == 6 and "/tests/" not in normal and "frontend" not in normal
    assert rollback.count("COPY ") == 2 and "private_workspace_app.py" not in rollback
    original = b"async def private_session_factory():\n pass\n"
    assert r.rollback_service(original) == original + r.ROLLBACK_IMPORT
    with pytest.raises(r.ReleaseError):
        r.rollback_service(original + r.ROLLBACK_IMPORT)


@pytest.mark.parametrize("field,value", [
    ("source_sha", "0" * 40), ("baseline_private_source_sha", "0" * 40),
    ("base_private_image", "sha256:" + "0" * 64), ("credentials_included", True),
    ("runtime_dependency_changes", True), ("production_access", True),
    ("backend_regression_tests_expected_minimum", 1191), ("private_schema_table_count_after", 19),
    ("private_tests", []), ("backend_changes", []),
])
def test_manifest_rejects_scope_drift(manifest, field, value):
    manifest[field] = value
    with pytest.raises(r.ReleaseError):
        r.checked_manifest(manifest)


def test_manifest_rejects_missing_static_and_extra_crm_source(manifest):
    missing = copy.deepcopy(manifest)
    del missing["payload_files"]["frontend/dist/index.html"]
    with pytest.raises(r.ReleaseError):
        r.checked_manifest(missing)
    extra = copy.deepcopy(manifest)
    extra["payload_files"]["backend/main.py"] = "f" * 64
    with pytest.raises(r.ReleaseError):
        r.checked_manifest(extra)


def test_schema_exact_preservation_and_partial_completion(snapshots):
    before, after = snapshots
    objects = after["private"]["schema_objects"]
    proof = r.compare_schema(before, after, objects)
    assert proof["existing_private_tables_preserved"] == 11 and proof["new_personal_tables_empty"]
    partial = copy.deepcopy(before)
    name = next(iter(r.NEW_TABLES))
    partial["private"]["tables"][name] = after["private"]["tables"][name]
    partial["private"]["schema_objects"].update({
        key: value for key, value in objects.items() if value["table"] == name})
    r.checked_partial_schema(before, partial, objects)
    wrong = copy.deepcopy(partial)
    wrong["private"]["schema_objects"][name]["sql_sha256"] = "0" * 64
    with pytest.raises(r.ReleaseError):
        r.checked_partial_schema(before, wrong, objects)


@pytest.mark.parametrize("mutate", [
    lambda a: a["private"]["identity"].update(inode=99),
    lambda a: a["business"]["tables"]["business"].update(rows=2),
    lambda a: a["private"]["tables"]["private_items"].update(rows=2),
    lambda a: a["private"]["tables"]["private_pf_accounts"].update(rows=1),
    lambda a: a["private"]["schema_objects"]["private_items_owner"].update(sql_sha256="0" * 64),
])
def test_schema_rejects_original_data_or_owner_book_changes(snapshots, mutate):
    before, after = snapshots
    target = copy.deepcopy(after["private"]["schema_objects"])
    mutate(after)
    with pytest.raises(r.ReleaseError):
        r.compare_schema(before, after, target)


def test_nginx_switch_changes_one_root_only():
    original = b"root /var/www/old;\nproxy_pass 127.0.0.1:8000;\nproxy_pass 127.0.0.1:8001;\nsecurity-header literal;"
    changed = r.changed_nginx(original, Path("/var/www/old"), Path("/var/www/new"), r.sha(original))
    assert changed.replace(b"/var/www/new", b"/var/www/old") == original
    with pytest.raises(r.ReleaseError):
        r.changed_nginx(original + b"/var/www/old", Path("/var/www/old"), Path("/var/www/new"),
            r.sha(original + b"/var/www/old"))


@pytest.mark.parametrize("field", [
    "all_other_backend_bytes_identical", "all_runtime_package_bytes_identical",
    "rollback_model_registration_only", "base_pin_verified",
])
def test_candidate_requires_every_offline_proof(manifest, snapshots, field):
    value = candidate(manifest, snapshots)
    assert r.checked_candidate(value, manifest, "3" * 64, "4" * 64) is value
    value[field] = False
    with pytest.raises(r.ReleaseError):
        r.checked_candidate(value, manifest, "3" * 64, "4" * 64)


def test_candidate_rejects_network_or_deployed_python_drift(manifest, snapshots):
    value = candidate(manifest, snapshots)
    for field, invalid in (("network", "bridge"), ("python", "3.13"), ("tests", 1191)):
        wrong = copy.deepcopy(value)
        wrong["regressions"][field] = invalid
        with pytest.raises(r.ReleaseError):
            r.checked_candidate(wrong, manifest, "3" * 64, "4" * 64)


def test_rehearsal_code_contains_no_provider_calls_and_compiles():
    compile(r.LEDGER_REHEARSAL, "<synthetic-personal-ledger>", "exec")
    assert "services.private_personal_finance" not in r.LEDGER_REHEARSAL  # imports services facade
    assert "from services import private_personal_finance" in r.LEDGER_REHEARSAL
    assert not any(name in r.LEDGER_REHEARSAL for name in ("httpx", "requests", "urllib", "sync_source"))


def test_failure_receipts_do_not_echo_provider_or_secret_text():
    assert r.safe_failure(r.ReleaseError("PRIVATE_ROWS_CHANGED")) == "PRIVATE_ROWS_CHANGED"
    assert r.safe_failure(ValueError("synthetic-secret-never-echo")) == "VALUEERROR"


@pytest.mark.parametrize("changed_field", [None, "st_atime_ns", "st_dev", "st_ino", "st_uid", "st_gid",
    "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_frozen_wheel_reader_allows_only_read_access_time_change(monkeypatch, tmp_path, changed_field):
    path = tmp_path / "test-wheel-manifest.json"
    data = b'{"synthetic-pytest-wheel.whl":"reviewed-synthetic-hash"}'
    path.write_bytes(data)
    info = path.stat()
    names = ["st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size",
             "st_atime_ns", "st_mtime_ns", "st_ctime_ns"]
    baseline = {name: getattr(info, name) for name in names}
    calls = []
    def observed(_path):
        values = dict(baseline)
        if calls and changed_field:
            values[changed_field] += 1
        calls.append(_path)
        return SimpleNamespace(**values)
    monkeypatch.setattr(r, "protected", observed)
    prep = SimpleNamespace(BASE_TEST_ROOT=tmp_path, BASE_WHEEL_MANIFEST_SHA=r.sha(data))
    if changed_field in {None, "st_atime_ns"}:
        assert r.retained_wheel_manifest(prep) == json.loads(data)
    else:
        with pytest.raises(r.ReleaseError, match="PROTECTED_FILE_CHANGED"):
            r.retained_wheel_manifest(prep)
    assert len(calls) == 2


def test_frozen_wheel_manifest_still_requires_approved_bytes(monkeypatch, tmp_path):
    path = tmp_path / "test-wheel-manifest.json"
    path.write_bytes(b'{"synthetic":"unexpected"}')
    monkeypatch.setattr(r, "protected", lambda _path: Path(_path).stat())
    prep = SimpleNamespace(BASE_TEST_ROOT=tmp_path, BASE_WHEEL_MANIFEST_SHA="0" * 64)
    with pytest.raises(r.ReleaseError, match="RETAINED_TEST_WHEEL_MANIFEST_HASH_DRIFT"):
        r.retained_wheel_manifest(prep)


def test_prepare_offline_test_mount_preserves_real_test_paths(monkeypatch, tmp_path):
    calls = []
    class BaseRunner:
        def __init__(self, release):
            self.release = release
        def run(self, stage, command, **kwargs):
            calls.append(command)
            return b"{}"
    prep = SimpleNamespace(Runner=BaseRunner, SYNTHETIC_ENV={"PRIVATE_WORKSPACE_OWNER_IDS": "4"},
        BASE_TEST_ROOT=tmp_path / "offline-wheels", protected=lambda *a, **k: None)
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    runner = r.preparation_runner(prep, tmp_path)
    source = tmp_path / "payload/backend/tests"
    runner.isolated("tests", "sha256:" + "1" * 64, "pass", mounts=[(source, "/app/backend/tests", True)])
    command = calls[-1]
    assert command[command.index("--network") + 1] == "none"
    assert "type=bind,src=" + str(source) + ",dst=/app/backend/tests,readonly" in command
    with pytest.raises(r.ReleaseError):
        runner.isolated("tests", "sha256:" + "1" * 64, "pass", mounts=[(source, "/app/backend/tests", False)])
    with pytest.raises(r.ReleaseError):
        runner.isolated("tests", "sha256:" + "1" * 64, "pass", mounts=[(Path("/production"), "/synthetic/private", False)])


@pytest.mark.parametrize("failure", [None, "initializer", "public", "backup", "crm_write", "private_write", "crm_during_recovery"])
def test_activation_recovers_without_crm_mutation_or_database_restore(
        monkeypatch, tmp_path, manifest, snapshots, failure):
    # A complete fake runtime exercises both success and every destructive
    # boundary. All filesystem state is temporary; no Docker call is possible.
    before, after = copy.deepcopy(snapshots)
    before["business"]["tables"] = {"crm_" + str(n): {"rows": 1} for n in range(83)}
    after["business"] = copy.deepcopy(before["business"])
    preimage = "sha256:" + "1" * 64
    value = candidate(manifest, (before, after))
    public = tmp_path / "old-public"
    public.mkdir()
    nginx = b"root " + str(public).encode() + b"; 127.0.0.1:8000; 127.0.0.1:8001;"
    crm = {"id": "c" * 64}
    runtime = {role: {"id": letter * 64, "image": r.BASE_IMAGE, "source_sha": r.BASE_SOURCE,
        "configuration_sha256": role + "-configuration", "restart_count": 0, "started_at": "synthetic"}
        for role, letter in (("api", "a"), ("worker", "b"))}
    pins = {"stage": "PERSONAL_FINANCE_AUTHENTICATED_READONLY_PREFLIGHT", "host": r.HOST,
        "backend_source_sha": r.BASE_SOURCE, "private_image": r.BASE_IMAGE, "mutation_performed": False,
        "roles": {role: {"id": row["id"], "image": r.BASE_IMAGE, "source": r.BASE_SOURCE,
            "attempt": "f" * 32, "runtime": row} for role, row in runtime.items()},
        "snapshot": before, "crm": crm, "environment_sha256": r.sha(b"original-env"),
        "nginx_sha256": r.sha(nginx), "frontend_version": "0123456789ab", "public_root": str(public),
        "private_database": "/private/workspace.db", "business_database": "/business/crm.db",
        "nginx_path": "/nginx/config", "runtime_env_path": "/private/runtime.env",
        "primitives": {"prepare_candidate": {"path": str(r.LEGACY / "prepare_candidate.py"),
            "sha256": r.LEGACY_HASHES["prepare_candidate.py"]},
            "stripe_upgrade": {"path": str(r.LEGACY / "upgrade.py"), "sha256": r.LEGACY_HASHES["upgrade.py"]}}}
    state = SimpleNamespace(database=before, nginx=nginx, calls=[], failed=False)
    infos = {row["id"]: {"Image": r.BASE_IMAGE, "State": {"Running": True}, "hash": row["configuration_sha256"]}
        for row in runtime.values()}
    monkeypatch.setattr(r, "protected", lambda path, **kwargs: Path(path).stat())
    monkeypatch.setattr(r, "verify_prepared_files", lambda *args: tmp_path / "static")
    monkeypatch.setattr(r, "install_public", lambda *args: {"index.html": "f" * 64})
    monkeypatch.setattr(r, "authentication_probe", lambda **kwargs: None)
    def public_check(files, version, root):
        state.calls.append(("public", version))
        if failure == "public" and version == manifest["frontend_version"] and not state.failed:
            state.failed = True
            raise r.ReleaseError("SYNTHETIC_PUBLIC_FAILURE")
        if failure in {"crm_write", "private_write", "crm_during_recovery"} and version == manifest["frontend_version"] and not state.failed:
            state.failed = True
            if failure in {"crm_write", "crm_during_recovery"}:
                state.database["business"]["tables"]["crm_0"]["rows"] = 2
            else:
                state.database["private"]["tables"]["private_items"]["rows"] = 2
    base = SimpleNamespace(PRIVATE_DB=Path(pins["private_database"]), BUSINESS=Path(pins["business_database"]),
        NGINX=Path(pins["nginx_path"]), ENV=Path(pins["runtime_env_path"]),
        crm_check=lambda: crm, read_protected=lambda *args: b"original-env",
        inspect=lambda identity: infos[identity], config_hash=lambda info: info["hash"],
        read_nginx=lambda: state.nginx, file_map=lambda root: {"index.html": "f" * 64},
        public_check=public_check, run=lambda *args: state.calls.append(("nginx", args[0])),
        save=lambda path, value, **kwargs: r.save(path, value, **kwargs), write_new=r.write_new)
    def atomic(data, allowed):
        assert r.sha(state.nginx) in allowed
        state.nginx = data
    base.atomic_nginx = atomic
    def docker(command, **kwargs):
        state.calls.append(("docker", command))
        assert crm["id"] not in command
        if command[0] in {"start", "stop"}:
            infos[command[-1]]["State"]["Running"] = command[0] == "start"
    switch = SimpleNamespace(environment=lambda info: {"PRIVATE_WORKSPACE_OWNER_IDS": "4"},
        docker=docker, stable_records=lambda path: {}, preserved=lambda *a, **k: None)
    @contextmanager
    def lock(_base):
        yield
    def backup(*args):
        state.calls.append(("backup",))
        if failure == "backup":
            raise r.ReleaseError("SYNTHETIC_BACKUP_FAILURE")
        return "8" * 64
    def initializer(_base, _switch, image, attempt, journal, path):
        state.database = after
        state.calls.append(("initializer",))
        if failure == "initializer":
            raise r.ReleaseError("SYNTHETIC_POST_DDL_FAILURE")
    def start_role(_base, _switch, release, journal, role, image, source, values, rollback=False):
        state.calls.append(("role", role, rollback))
        if failure == "crm_during_recovery" and rollback and role == "api":
            state.database["business"]["tables"]["crm_1"]["rows"] = 3
        # Compatibility startup completes reviewed DDL but never deletes rows.
        if rollback and set(state.database["private"]["tables"]) == r.BASE_TABLES:
            state.database = after
        key = "rollback_roles" if rollback else "roles"
        journal.setdefault(key, {})[role] = {"id": ("d" if role == "api" else "e") * 64}
        return journal[key][role]["id"]
    legacy = SimpleNamespace(retained_tools=lambda path: (base, None, prep, switch), release_lock=lock,
        own_role=lambda _b, _s, identity, role, image, attempt, source, env, running: runtime[role],
        no_writers=lambda *args: None, backup_private=backup, run_initializer=initializer,
        stable_authorization=lambda *args: {}, start_role=start_role, stop_owned=lambda *args: state.calls.append(("stop-owned",)))
    def image_info(image):
        labels = {"t24.private.source.sha": r.SOURCE} if image == preimage else {
            "t24.private.rollback.schema-compatible": "eleven-to-twenty-personal"}
        return {"Config": {"Labels": labels}}
    prep = SimpleNamespace(inspect_image=image_info, verify_candidate_base=lambda *args: None,
        release_snapshot=lambda *args: copy.deepcopy(state.database))
    monkeypatch.setattr(r, "load_legacy", lambda name: legacy)
    if failure:
        with pytest.raises(r.ReleaseError, match="ACTIVATION_FAILED_ROLLBACK_VERIFIED"):
            r.activate(tmp_path, manifest, pins, value,
                manifest_sha256="3" * 64, preflight_sha256="4" * 64, candidate_sha256="9" * 64)
        if failure != "backup":
            assert ("role", "api", True) in state.calls and ("role", "worker", True) in state.calls
            assert set(state.database["private"]["tables"]) == r.TARGET_TABLES
        assert state.nginx == nginx
        receipt = json.loads((tmp_path / "upgrade-state.json").read_bytes())
        assert receipt["failure_code"] and "failure_phase" in receipt
        if failure == "crm_write":
            assert state.database["business"]["tables"]["crm_0"]["rows"] == 2
        if failure == "private_write":
            assert state.database["private"]["tables"]["private_items"]["rows"] == 2
        if failure == "crm_during_recovery":
            assert state.database["business"]["tables"]["crm_1"]["rows"] == 3
            assert receipt["rollback_crm_data_changed_during_recovery"]
    else:
        result = r.activate(tmp_path, manifest, pins, value,
            manifest_sha256="3" * 64, preflight_sha256="4" * 64, candidate_sha256="9" * 64)
        assert result["deployed"] and result["owner_ui_verified"] is False
    assert not any(any(word in str(call) for word in ("restore-db", "delete-db", "DROP TABLE")) for call in state.calls)
