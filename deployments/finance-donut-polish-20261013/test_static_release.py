"""Synthetic static publication failures. No real Docker, HTTP or database."""
import copy
from contextlib import contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location("finance_donut_polish_release", Path(__file__).with_name("static_release.py"))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def manifest():
    return {"format_version": 1, "stage": "FINANCE_DONUT_POLISH_STATIC_PAYLOAD_PREPARED", "source_sha": "1" * 40,
        "baseline_source_sha": r.BASELINE_SOURCE, "frontend_version": "2" * 12,
        "baseline_frontend_version": r.BASELINE_VERSION, "static_only": True,
        **{name: False for name in ("backend_changes", "credentials_included", "databases_modified", "services_modified", "environment_modified")},
        "changed_source_files": {name: fingerprint if name.endswith(".tsx") else "3" * 64 for name, fingerprint in r.PREVIOUS_DONUT_FILES.items()},
        "preserved_source_inventories": {"backend": {"app/backend/main.py": "4" * 64},
            "private_frontend": {"app/frontend/src/pages/PrivateWorkspace.tsx": "5" * 64, "app/frontend/src/components/Layout.tsx": "b" * 64}},
        "presentation_preservation_proof_sha256": "d" * 64,
        "presentation_preservation_proof": {"format_version": 1, "stage": "FINANCE_DONUT_PRESENTATION_SOURCE_PROOF", "source_mode": "committed",
            "baseline_source_sha": r.BASELINE_SOURCE, "source_sha": "1" * 40,
            "finance_file_before_sha256": r.BASELINE_FINANCE_SHA, "finance_file_after_sha256": r.PREVIOUS_DONUT_FILES["app/frontend/src/pages/Finance.tsx"],
            "financial_calculations_unchanged": True, "event_handlers_unchanged": True, "table_cells_unchanged": True,
            "dialogs_unchanged": True, "private_workspace_source_unchanged": True,
            "chart_inputs_unchanged": True, "component_presentation_only": True,
            "chart_regions_replaced": 4, "preserved_finance_ast_sha256": "e" * 64,
            "component_file_sha256": r.PREVIOUS_DONUT_FILES["app/frontend/src/components/FinanceDonutChart.tsx"], "styles_file_sha256": "3" * 64},
        "layout_scope": {"chart_presentation_only": True, "private_workspace_source_unchanged": True},
        "payload_files": {"index.html": "6" * 64, "app-version.json": "7" * 64}, "payload_sha256": "8" * 64}


def database():
    return {"identity": {"device": 1, "inode": 2, "uid": 0}, "schema_objects": {"a": {"sql_sha256": "a" * 64}},
        "schema_sha256": "b" * 64, "tables": {"a": {"columns_sha256": "c" * 64, "rows": 1, "rows_sha256": "d" * 64}}}


def boundary_value():
    return {"runtime": {"crm": "current", "roles": "current", "environment_sha256": "a" * 64},
        "databases": r.stable_database({"business": database(), "private": database()}),
        "database_stats": {name: {"device": 1, "inode": index, "uid": 0, "gid": 0, "mode": 0o600,
            "size": 4096, "mtime_ns": 10, "ctime_ns": 10} for index, name in enumerate(("business", "private"))}}


def test_manifest_has_exact_three_donut_files_and_no_private_changes():
    value = manifest()
    assert r.checked_manifest(value, "8" * 64) is value
    assert len(value["changed_source_files"]) == len(r.ALLOWED_SOURCE_FILES)
    assert len(r.ALLOWED_SOURCE_FILES) == 3
    assert "app/frontend/src/components/Layout.tsx" not in r.ALLOWED_SOURCE_FILES
    assert "app/frontend/src/pages/Finance.tsx" in r.ALLOWED_SOURCE_FILES
    assert "app/frontend/src/components/FinanceDonutChart.tsx" in r.ALLOWED_SOURCE_FILES
    assert "app/frontend/src/components/finance-donut-chart.css" in r.ALLOWED_SOURCE_FILES
    assert "app/frontend/src/components/CompactFinanceTable.tsx" not in r.ALLOWED_SOURCE_FILES
    assert not any("Private" in name or "private" in name for name in r.ALLOWED_SOURCE_FILES)


@pytest.mark.parametrize("field,value", [
    ("stage", "CRM_FINANCE_REFINED_STATIC_PAYLOAD_PREPARED"),
    ("static_only", False), ("backend_changes", True), ("databases_modified", True),
    ("services_modified", True), ("environment_modified", True), ("credentials_included", True),
    ("source_sha", "not a commit"), ("baseline_source_sha", "f" * 40),
    ("baseline_frontend_version", "f" * 12), ("payload_sha256", "f" * 64),
    ("preserved_source_inventories", {}), ("changed_source_files", {}),
])
def test_manifest_rejects_scope_or_pin_drift(field, value):
    item = manifest()
    item[field] = value
    with pytest.raises(r.StaticError):
        r.checked_manifest(item, "8" * 64)


@pytest.mark.parametrize("name", ["../index.html", "assets/../../etc/passwd", "/index.html",
    "assets/.env", "assets/source.py", "arbitrary.html", "frontend/dist/index.html"])
def test_manifest_rejects_paths_and_nonstatic_files(name):
    item = manifest()
    if name == "frontend/dist/index.html":
        item["payload_files"] = {name: "6" * 64, "app-version.json": "7" * 64}
    else:
        item["payload_files"][name] = "f" * 64
    with pytest.raises(r.StaticError):
        r.checked_manifest(item, "8" * 64)


@pytest.mark.parametrize("name", ["pages/PrivateWorkspace.tsx", "components/CompactFinanceTable.tsx",
    "components/crm-desktop-refined-type.css"])
def test_private_or_previously_allowed_global_sources_cannot_enter_release(name):
    value = manifest()
    value["changed_source_files"]["app/frontend/src/" + name] = "f" * 64
    with pytest.raises(r.StaticError):
        r.checked_manifest(value, "8" * 64)


@pytest.mark.parametrize("field,value", [
    ("stage", "CRM_FINANCE_REFINED_PRESENTATION_SOURCE_PROOF"),
    ("source_mode", "working_tree_preview"),
    ("source_sha", "f" * 40), ("baseline_source_sha", "f" * 40),
    ("finance_file_after_sha256", "f" * 64), ("financial_calculations_unchanged", False),
    ("event_handlers_unchanged", False), ("table_cells_unchanged", False),
    ("dialogs_unchanged", False), ("chart_inputs_unchanged", False),
    ("private_workspace_source_unchanged", False), ("component_presentation_only", False),
    ("finance_file_before_sha256", "f" * 64), ("component_file_sha256", "f" * 64),
    ("styles_file_sha256", "f" * 64), ("chart_regions_replaced", 3),
    ("chart_regions_replaced", "4"), ("preserved_finance_ast_sha256", "invalid"),
])
def test_manifest_preserves_frozen_finance_mathproof_binding(field, value):
    item = manifest()
    item["presentation_preservation_proof"][field] = value
    with pytest.raises(r.StaticError, match="INDEPENDENT_PRESENTATION_SOURCE_PROOF_REQUIRED"):
        r.checked_manifest(item, "8" * 64)


def test_preserved_inventory_includes_tracked_hidden_files_only_as_metadata():
    value = manifest()
    value["preserved_source_inventories"]["backend"].update({
        "app/backend/.gitignore": "e" * 64,
        "app/backend/alembic/versions/.gitignore": "f" * 64})
    assert r.checked_manifest(value, "8" * 64) is value
    value["payload_files"]["assets/.gitignore"] = "e" * 64
    with pytest.raises(r.StaticError):
        r.checked_manifest(value, "8" * 64)


@pytest.mark.parametrize("name", ["", "/app/backend/.gitignore", "app/backend/../.gitignore",
    "app/backend//.gitignore", "app/backend/./.gitignore", "app/backend\\.gitignore"])
def test_preserved_inventory_still_requires_canonical_paths(name):
    value = manifest()
    value["preserved_source_inventories"]["backend"][name] = "f" * 64
    with pytest.raises(r.StaticError):
        r.checked_manifest(value, "8" * 64)


@pytest.fixture
def pinned_preflight(monkeypatch):
    personal = SimpleNamespace(SOURCE="9" * 40, TARGET_TABLES={"private_" + str(i) for i in range(20)})
    roles = {"crm": {"id": "same-crm"}}
    for index, role in enumerate(("api", "worker"), 1):
        roles[role] = {"id": str(index) * 64, "image": "sha256:" + "a" * 64,
            "source": personal.SOURCE, "attempt": "d" * 32, "runtime": {"id": str(index) * 64}}
    personal_receipt = {"phase": "PERSONAL_FINANCE_DEPLOYED_VERIFIED", "deployed": True,
        "candidate_image": roles["api"]["image"], "attempt": roles["api"]["attempt"], "roles": roles}
    previous = {"phase": "FINANCE_DONUT_STATIC_PUBLIC_VERIFIED", "deployed": True,
        "source_sha": r.PREVIOUS_SOURCE, "frontend_version": r.PREVIOUS_VERSION,
        "public_root": str(r.PREVIOUS_PUBLIC), "new_nginx_sha256": "f" * 64,
        "same_database_identity_and_schema": True, "same_crm_and_private_runtime": True,
        **{key: False for key in ("database_mutation_performed", "services_modified", "environment_modified", "databases_restored")}}
    value = {"stage": "FINANCE_DONUT_POLISH_AUTHENTICATED_READONLY_PREFLIGHT", "host": r.HOST,
        "mutation_performed": False, "frontend_version": r.PREVIOUS_VERSION,
        "backend_source_sha": personal.SOURCE, "roles": roles,
        "databases": {"private": {"tables": {name: {} for name in personal.TARGET_TABLES}},
            "business": {"tables": {"crm_" + str(i): {} for i in range(83)}}},
        "nginx_sha256": "f" * 64, "environment_sha256": "e" * 64, "public_root": str(r.PREVIOUS_PUBLIC),
        "personal_release_receipt": {"path": str(r.PERSONAL_RELEASE / "upgrade-state.json"), "sha256": "9" * 64},
        "previous_static_receipt": {"path": str(r.PREVIOUS_RELEASE / "static-state.json"), "sha256": r.PREVIOUS_RECEIPT_SHA}}
    def receipt(path, expected):
        if path == r.PERSONAL_RELEASE / "upgrade-state.json":
            assert expected == "9" * 64
            return personal_receipt
        assert path == r.PREVIOUS_RELEASE / "static-state.json" and expected == r.PREVIOUS_RECEIPT_SHA
        return previous
    helper = Path(__file__).resolve().parents[1] / "finance-donut-20261013/static_release.py"
    def read_helper(path, maximum=0):
        assert path == r.PREVIOUS_RELEASE / "static_release.py"
        return helper.read_bytes()
    monkeypatch.setattr(r, "fixed_json", receipt)
    monkeypatch.setattr(r, "read", read_helper)
    return SimpleNamespace(value=value, previous=previous, personal=personal)


def test_preflight_accepts_only_the_reviewed_finance_refined_release_lineage(pinned_preflight):
    item = pinned_preflight
    assert r.checked_preflight(item.value, item.personal) is item.value


@pytest.mark.parametrize("field,value", [
    ("phase", "CRM_DESKTOP_COMFORT_STATIC_PUBLIC_VERIFIED"),
    ("phase", "FINANCE_DONUT_POLISH_STATIC_PUBLIC_VERIFIED"),
    ("source_sha", "f" * 40), ("frontend_version", "f" * 12),
    ("public_root", "/var/www/t24-crm-public/unreviewed"), ("new_nginx_sha256", "e" * 64),
    ("deployed", False), ("same_database_identity_and_schema", False),
    ("same_crm_and_private_runtime", False), ("database_mutation_performed", True),
    ("services_modified", True), ("environment_modified", True), ("databases_restored", True),
    ("failure_code", "PREVIOUS_FAILED"), ("rollback_attempted", False),
])
def test_preflight_rejects_previous_receipt_drift(pinned_preflight, field, value):
    item = pinned_preflight
    item.previous[field] = value
    with pytest.raises(r.StaticError, match="ACCEPTED_CRM_STATIC_RUNTIME_LINEAGE_DRIFT"):
        r.checked_preflight(item.value, item.personal)


@pytest.mark.parametrize("field,value", [("path", "/opt/t24-crm/releases/unreviewed/static-state.json"),
    ("sha256", "f" * 64)])
def test_preflight_rejects_unreviewed_previous_receipt_pin(pinned_preflight, field, value):
    item = pinned_preflight
    item.value["previous_static_receipt"][field] = value
    with pytest.raises(r.StaticError, match="EXACT_ACCEPTED_PREVIOUS_STATIC_RECEIPT_REQUIRED"):
        r.checked_preflight(item.value, item.personal)


def test_preflight_rejects_previous_helper_hash_drift(pinned_preflight, monkeypatch):
    item = pinned_preflight
    monkeypatch.setattr(r, "read", lambda path, maximum=0: b"changed helper")
    with pytest.raises(r.StaticError, match="ACCEPTED_PREVIOUS_STATIC_HELPER_HASH_DRIFT"):
        r.checked_preflight(item.value, item.personal)


def test_old_preflight_stage_cannot_authorize_compact_ledger(pinned_preflight):
    item = pinned_preflight
    item.value["stage"] = "CRM_FINANCE_REFINED_AUTHENTICATED_READONLY_PREFLIGHT"
    with pytest.raises(r.StaticError, match="FRESH_AUTHENTICATED_PREFLIGHT_REQUIRED"):
        r.checked_preflight(item.value, item.personal)


def test_normal_business_rows_and_file_timestamps_may_change():
    original = {"business": database(), "private": database()}
    current = copy.deepcopy(original)
    current["business"]["tables"]["a"].update(rows=2, rows_sha256="e" * 64)
    assert r.stable_database(original) == r.stable_database(current)
    before = boundary_value()
    after = copy.deepcopy(before)
    after["database_stats"]["private"].update(size=8192, mtime_ns=20, ctime_ns=20)
    assert r.stable_boundary(before) == r.stable_boundary(after)
    after["database_stats"]["private"]["inode"] += 1
    assert r.stable_boundary(before) != r.stable_boundary(after)


def test_database_receipt_metadata_is_not_a_database_section():
    dbs = {"private": database(), "business": database()}
    receipt = {"format_version": 1, "stage": "STRIPE_REPORT_READONLY_SCHEMA_SNAPSHOT",
        "mutation_performed": False, "owner_id": "4", **copy.deepcopy(dbs)}
    assert r.stable_database(receipt) == r.stable_database(dbs)


@pytest.mark.parametrize("section,field,value", [
    ("private", "identity", None), ("business", "schema_objects", []),
    ("private", "schema_sha256", 1), ("business", "tables", {}),
])
def test_database_section_shape_errors_have_safe_guard_codes(section, field, value):
    receipt = {"private": database(), "business": database()}
    receipt[section][field] = value
    with pytest.raises(r.StaticError, match="VALID_DATABASE_IDENTITY_AND_DDL_PROOF_REQUIRED"):
        r.stable_database(receipt)


def test_actual_retained_snapshot_adapter_preserves_both_databases_and_accepts_metadata(tmp_path, monkeypatch):
    """Invoke the real retained reader on synthetic files, not a mirrored shape."""
    path = Path(__file__).resolve().parents[1] / "stripe-report-20261012/prepare_candidate.py"
    assert r.sha(path.read_bytes()) == "989dc1de81a0b3a39ad978c395bdfd7a3c31725a3e2ebee57a5713cfc8faa613"
    spec = importlib.util.spec_from_file_location("actual_retained_crm_snapshot", path)
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)
    private_parent = tmp_path / "private"
    private_parent.mkdir(mode=0o700)
    private = private_parent / "workspace.db"
    business = tmp_path / "business.db"
    for file, sql in ((private, "CREATE TABLE private_items(id INTEGER PRIMARY KEY,owner_id TEXT NOT NULL)"),
                      (business, "CREATE TABLE merchants(id INTEGER PRIMARY KEY)")):
        with sqlite3.connect(file) as db:
            db.execute(sql)
        file.chmod(0o600)
    snapshot = prep.release_snapshot(private.resolve(), business.resolve())
    assert snapshot["stage"] == "STRIPE_REPORT_READONLY_SCHEMA_SNAPSHOT" and snapshot["owner_id"] == "4"
    assert snapshot["mutation_performed"] is False
    current = {name: r.sha(file.read_bytes()) for name, file in (("business", business), ("private", private))}
    base = SimpleNamespace(PRIVATE_DB=private.resolve(), BUSINESS=business.resolve(),
        NGINX=tmp_path / "nginx.conf", ENV=tmp_path / "runtime.env", crm_check=lambda: {"id": "same-live-crm"})
    base.ENV.write_bytes(b"synthetic-only-not-a-credential")
    personal = SimpleNamespace(old_roles=Mock())
    pins = {"roles": {"crm": base.crm_check(), "api": {"id": "same-api"}, "worker": {"id": "same-worker"}},
        "environment_sha256": r.sha(base.ENV.read_bytes()), "databases": snapshot,
        "private_database": str(base.PRIVATE_DB), "business_database": str(base.BUSINESS),
        "nginx_path": str(base.NGINX), "runtime_env_path": str(base.ENV)}
    monkeypatch.setattr(r, "read", lambda path, maximum=0: path.read_bytes())
    # The local test process may be unprivileged. File identity observations
    # remain real; production root ownership checking is covered separately.
    monkeypatch.setattr(r, "database_stats", lambda base: {name: {
        "device": file.stat().st_dev, "inode": file.stat().st_ino, "mode": 0o600, "uid": os.geteuid(), "gid": os.getegid(),
        "size": file.stat().st_size, "mtime_ns": file.stat().st_mtime_ns, "ctime_ns": file.stat().st_ctime_ns}
        for name, file in (("business", base.BUSINESS), ("private", base.PRIVATE_DB))})
    proof = r.boundary(personal, object(), base, prep, object(), pins)
    assert set(proof["databases"]) == {"business", "private"}
    assert proof["databases"] == r.stable_database(snapshot)
    assert current == {name: r.sha(file.read_bytes()) for name, file in (("business", business), ("private", private))}
    personal.old_roles.assert_called_once()


@pytest.mark.parametrize("suffix", ["", "-retry2"])
def test_new_public_root_explicit_first_or_retry2_release(suffix):
    value = manifest()
    name = "finance-donut-polish-" + value["source_sha"][:12] + "-20261013" + suffix
    assert r.public_root(Path("/opt/t24-crm/releases") / name, value) == Path("/var/www/t24-crm-public") / name


@pytest.mark.parametrize("suffix", ["-retry3", "-other", "/retry2"])
def test_other_release_suffixes_are_rejected(suffix):
    value = manifest()
    name = "finance-donut-polish-" + value["source_sha"][:12] + "-20261013" + suffix
    with pytest.raises(r.StaticError, match="EXACT_NEW_RELEASE_PATH_REQUIRED"):
        r.public_root(Path("/opt/t24-crm/releases") / name, value)


def archive(members):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as stream:
        for name, blob, kind in members:
            item = tarfile.TarInfo(name)
            item.size = len(blob)
            item.type = kind
            if kind == tarfile.SYMTYPE:
                item.linkname = "/etc/passwd"
            stream.addfile(item, io.BytesIO(blob) if kind == tarfile.REGTYPE else None)
    return data.getvalue()


def file_map(root):
    return {p.relative_to(root).as_posix(): r.sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def writer(path, data):
    with path.open("xb") as stream:
        stream.write(data)


def save(path, value, replace=False):
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    with path.open("wb" if replace else "xb") as stream:
        stream.write(data)
    return r.sha(data)


def test_complete_extract_requires_exact_bytes_and_version(tmp_path, monkeypatch):
    version = json.dumps({"version": "2" * 12}).encode()
    files = {"index.html": b"html", "app-version.json": version, "assets/a.js": b"javascript"}
    blob = archive([("payload/" + name, data, tarfile.REGTYPE) for name, data in files.items()])
    value = manifest()
    value.update(payload_files={name: r.sha(data) for name, data in files.items()}, payload_sha256=r.sha(blob))
    monkeypatch.setattr(r, "read", lambda path, maximum=0: path.read_bytes())
    root = r.extract_payload(SimpleNamespace(write_new=writer), SimpleNamespace(file_map=file_map), tmp_path, value, blob)
    assert file_map(root) == value["payload_files"]


@pytest.mark.parametrize("members", [
    [("payload/../index.html", b"x", tarfile.REGTYPE)],
    [("payload/index.html", b"x", tarfile.SYMTYPE)],
    [("payload/index.html", b"wrong", tarfile.REGTYPE)],
    [("payload/index.html", b"html", tarfile.REGTYPE), ("payload/index.html", b"html", tarfile.REGTYPE)],
    [("payload/index.html", b"html", tarfile.REGTYPE)],
])
def test_extract_rejects_traversal_links_wrong_duplicate_or_missing_members(tmp_path, members):
    blob = archive(members)
    value = manifest()
    value.update(payload_sha256=r.sha(blob), payload_files={"index.html": r.sha(b"html"), "app-version.json": r.sha(b"version")})
    with pytest.raises(r.StaticError):
        r.extract_payload(SimpleNamespace(write_new=writer), SimpleNamespace(file_map=file_map), tmp_path, value, blob)


@contextmanager
def no_lock(base):
    yield


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    item = manifest()
    args = SimpleNamespace(release=tmp_path, manifest_sha256="a" * 64, payload_sha256="8" * 64,
        preflight_sha256="b" * 64, prepared_sha256="c" * 64)
    original = b"root /old; proxy8000 proxy8001;"
    changed = b"root /new; proxy8000 proxy8001;"
    current = [original]
    old, public = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "index.html").write_bytes(b"oldhtml")
    (old / "assets").mkdir()
    (old / "assets/old-hash.js").write_bytes(b"oldjs")
    old_files = file_map(old)
    before = boundary_value()
    prepared = {"old_public_root": str(old), "public_root": str(public), "old_public_files": old_files,
        "old_nginx_sha256": r.sha(original), "boundary": before, "source_sha": item["source_sha"],
        "frontend_version": item["frontend_version"], "manifest_sha256": args.manifest_sha256,
        "payload_sha256": args.payload_sha256, "preflight_sha256": args.preflight_sha256,
        "personal_helper_sha256": r.PERSONAL_HELPER_SHA}
    (tmp_path / "prepared.json").write_text(json.dumps(prepared))
    fresh = tmp_path / "payload"
    fresh.mkdir()
    (fresh / "index.html").write_bytes(b"newhtml")
    (fresh / "assets").mkdir()
    (fresh / "assets/new-hash.js").write_bytes(b"newjs")
    commands = []
    base = SimpleNamespace(file_map=file_map, read_nginx=lambda: current[0],
        public_check=Mock(), run=Mock(side_effect=lambda command, code: commands.append(command)),
        atomic_nginx=Mock(side_effect=lambda data, allowed: current.__setitem__(0, data)))
    def install(base, static, old_root, public_root):
        public_root.mkdir()
        desired = file_map(static)
        desired.update({name: value for name, value in file_map(old_root).items() if name.startswith("assets/")})
        for name in desired:
            dest = public_root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            source = static / name if (static / name).exists() else old_root / name
            dest.write_bytes(source.read_bytes())
        return desired
    personal = SimpleNamespace(save=save, write_new=writer, changed_nginx=lambda *a: changed,
        install_public=install, authentication_probe=Mock())
    monkeypatch.setattr(r, "fixed_json", lambda path, expected: json.loads(path.read_bytes()))
    monkeypatch.setattr(r, "checked_prepared", lambda value, *a: value)
    monkeypatch.setattr(r, "payload_check", lambda *a: fresh)
    monkeypatch.setattr(r, "release_lock", no_lock)
    check = Mock(return_value=copy.deepcopy(before))
    monkeypatch.setattr(r, "boundary", check)
    return SimpleNamespace(args=args, manifest=item, pins={"nginx_sha256": r.sha(original)}, prepared=prepared,
        original=original, changed=changed, current=current, base=base, personal=personal, commands=commands,
        before=before, boundary=check, old=old, public=public)


def apply(value):
    return r.activate(value.args, value.personal, None, value.base, None, None, value.manifest, value.pins)


def test_success_only_switches_static_nginx_and_keeps_old_hashed_assets(runtime):
    result = apply(runtime)
    assert result["deployed"] and runtime.current == [runtime.changed]
    assert runtime.commands == [["nginx", "-t"], ["systemctl", "reload", "nginx"]]
    assert (runtime.public / "assets/old-hash.js").read_bytes() == b"oldjs"
    assert (runtime.public / "assets/new-hash.js").read_bytes() == b"newjs"
    state = json.loads((runtime.args.release / "static-state.json").read_bytes())
    assert not state["databases_restored"] and not state["database_mutation_performed"] and not state["services_modified"]


@pytest.mark.parametrize("drift", ["runtime", "schema", "identity"])
def test_boundary_drift_before_switch_preserves_original_static_and_no_commands(runtime, drift):
    value = copy.deepcopy(runtime.before)
    if drift == "runtime":
        value["runtime"]["crm"] = "restarted"
    elif drift == "schema":
        value["databases"]["private"]["schema_sha256"] = "f" * 64
    else:
        value["database_stats"]["private"]["inode"] += 1
    runtime.boundary.return_value = value
    with pytest.raises(r.StaticError):
        apply(runtime)
    assert runtime.current == [runtime.original] and runtime.commands == []
    runtime.base.atomic_nginx.assert_not_called()


def test_post_public_failure_restores_only_root_despite_new_business_data(runtime):
    runtime.base.public_check.side_effect = [r.StaticError("PUBLIC_ASSET_FAILED"), None]
    with pytest.raises(r.StaticError, match="PUBLIC_ASSET_FAILED"):
        apply(runtime)
    assert runtime.current == [runtime.original]
    assert runtime.commands == [["nginx", "-t"], ["systemctl", "reload", "nginx"]] * 2
    state = json.loads((runtime.args.release / "static-state.json").read_bytes())
    assert state["phase"] == "FINANCE_DONUT_POLISH_STATIC_ROLLED_BACK" and not state["databases_restored"]


def test_final_schema_failure_does_not_block_static_recovery(runtime):
    runtime.boundary.side_effect = [runtime.before, runtime.before, r.StaticError("NEW_SCHEMA_UNEXPECTED")]
    with pytest.raises(r.StaticError, match="NEW_SCHEMA_UNEXPECTED"):
        apply(runtime)
    assert runtime.current == [runtime.original]
    assert json.loads((runtime.args.release / "static-state.json").read_bytes())["phase"] == "FINANCE_DONUT_POLISH_STATIC_ROLLED_BACK"


def test_concurrent_nginx_edit_is_not_overwritten_on_failure(runtime):
    def concurrent(*args, **kwargs):
        runtime.current[0] = b"another release root"
        raise r.StaticError("PUBLIC_ASSET_FAILED")
    runtime.base.public_check.side_effect = concurrent
    with pytest.raises(r.StaticError):
        apply(runtime)
    assert runtime.current == [b"another release root"]
    state = json.loads((runtime.args.release / "static-state.json").read_bytes())
    assert state["phase"] == "FINANCE_DONUT_POLISH_STATIC_ROLLBACK_NEEDS_REVIEW"
    assert state["rollback_failure_code"] == "STATIC_ROLLBACK_CONCURRENT_NGINX_CHANGE"
    assert runtime.base.atomic_nginx.call_count == 1


def test_nginx_test_failure_rolls_back_including_validation_and_reload(runtime):
    def command(command, code):
        runtime.commands.append(command)
        if len(runtime.commands) == 1:
            raise r.StaticError(code)
    runtime.base.run.side_effect = command
    with pytest.raises(r.StaticError, match="NGINX_TEST_FAILED"):
        apply(runtime)
    assert runtime.current == [runtime.original]
    assert runtime.commands == [["nginx", "-t"], ["nginx", "-t"], ["systemctl", "reload", "nginx"]]


def test_safe_error_never_prints_sensitive_exception_text():
    assert r.safe_error(RuntimeError("token=secret")) == "STATIC_RELEASE_REJECTED"
    assert r.safe_error(r.StaticError("SAFE_MACHINE_CODE")) == "SAFE_MACHINE_CODE"
    assert r.safe_error(r.StaticError("token=secret")) == "STATIC_RELEASE_REJECTED"


@pytest.mark.parametrize("field", ["chart_inputs_unchanged", "component_presentation_only",
    "chart_regions_replaced", "preserved_finance_ast_sha256", "component_file_sha256", "styles_file_sha256"])
def test_donut_proof_cannot_omit_required_evidence(field):
    item = manifest()
    del item["presentation_preservation_proof"][field]
    with pytest.raises(r.StaticError, match="INDEPENDENT_PRESENTATION_SOURCE_PROOF_REQUIRED"):
        r.checked_manifest(item, "8" * 64)


@pytest.mark.parametrize("scope", [{}, {"chart_presentation_only": False, "private_workspace_source_unchanged": True},
    {"min_width": 1024, "mobile_source_unchanged": True, "private_workspace_source_unchanged": True}])
def test_manifest_requires_honest_donut_scope(scope):
    item = manifest()
    item["layout_scope"] = scope
    with pytest.raises(r.StaticError, match="EXACT_DONUT_PRESENTATION_SCOPE_REQUIRED"):
        r.checked_manifest(item, "8" * 64)


@pytest.mark.parametrize("name", ["app/frontend/src/pages/Finance.tsx", "app/frontend/src/components/FinanceDonutChart.tsx"])
def test_polish_rejects_prior_finance_or_component_change(name):
    item = manifest()
    item["changed_source_files"][name] = "f" * 64
    with pytest.raises(r.StaticError, match="EXACT_CSS_ONLY_POLISH_REQUIRED"):
        r.checked_manifest(item, "8" * 64)


@pytest.mark.parametrize("field,value", [("source_sha", r.PREVIOUS_SOURCE), ("frontend_version", r.PREVIOUS_VERSION)])
def test_polish_rejects_same_predecessor_source_or_version(field, value):
    item = manifest()
    item[field] = value
    with pytest.raises(r.StaticError, match="EXACT_CSS_ONLY_POLISH_REQUIRED"):
        r.checked_manifest(item, "8" * 64)


def test_polish_rejects_unchanged_styles():
    item = manifest()
    name = "app/frontend/src/components/finance-donut-chart.css"
    item["changed_source_files"][name] = r.PREVIOUS_DONUT_FILES[name]
    with pytest.raises(r.StaticError, match="EXACT_CSS_ONLY_POLISH_REQUIRED"):
        r.checked_manifest(item, "8" * 64)
