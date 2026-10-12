"""Synthetic static publication failures. No real Docker, HTTP or database."""
import copy
from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location("crm_desktop_release", Path(__file__).with_name("static_release.py"))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def manifest():
    return {"format_version": 1, "stage": "CRM_DESKTOP_COMFORT_STATIC_PAYLOAD_PREPARED", "source_sha": "1" * 40,
        "baseline_source_sha": r.BASELINE_SOURCE, "frontend_version": "2" * 12,
        "baseline_frontend_version": r.BASELINE_VERSION, "static_only": True,
        **{name: False for name in ("backend_changes", "credentials_included", "databases_modified", "services_modified", "environment_modified")},
        "changed_source_files": {name: "3" * 64 for name in r.ALLOWED_SOURCE_FILES},
        "preserved_source_inventories": {"backend": {"app/backend/main.py": "4" * 64},
            "private_frontend": {"app/frontend/src/pages/PrivateWorkspace.tsx": "5" * 64}},
        "payload_files": {"index.html": "6" * 64, "app-version.json": "7" * 64}, "payload_sha256": "8" * 64}


def database():
    return {"identity": {"device": 1, "inode": 2, "uid": 0}, "schema_objects": {"a": {"sql_sha256": "a" * 64}},
        "schema_sha256": "b" * 64, "tables": {"a": {"columns_sha256": "c" * 64, "rows": 1, "rows_sha256": "d" * 64}}}


def boundary_value():
    return {"runtime": {"crm": "current", "roles": "current", "environment_sha256": "a" * 64},
        "databases": r.stable_database({"business": database(), "private": database()}),
        "database_stats": {name: {"device": 1, "inode": index, "uid": 0, "gid": 0, "mode": 0o600,
            "size": 4096, "mtime_ns": 10, "ctime_ns": 10} for index, name in enumerate(("business", "private"))}}


def test_manifest_has_exact_five_layout_files_and_no_private_changes():
    value = manifest()
    assert r.checked_manifest(value, "8" * 64) is value
    assert len(value["changed_source_files"]) == 5
    assert not any("Private" in name or "private" in name for name in r.ALLOWED_SOURCE_FILES)


@pytest.mark.parametrize("field,value", [
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


def test_new_private_source_cannot_be_added_to_changed_files():
    value = manifest()
    value["changed_source_files"]["app/frontend/src/pages/PrivateWorkspace.tsx"] = "f" * 64
    with pytest.raises(r.StaticError):
        r.checked_manifest(value, "8" * 64)


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
    assert state["phase"] == "CRM_DESKTOP_COMFORT_STATIC_ROLLED_BACK" and not state["databases_restored"]


def test_final_schema_failure_does_not_block_static_recovery(runtime):
    runtime.boundary.side_effect = [runtime.before, runtime.before, r.StaticError("NEW_SCHEMA_UNEXPECTED")]
    with pytest.raises(r.StaticError, match="NEW_SCHEMA_UNEXPECTED"):
        apply(runtime)
    assert runtime.current == [runtime.original]
    assert json.loads((runtime.args.release / "static-state.json").read_bytes())["phase"] == "CRM_DESKTOP_COMFORT_STATIC_ROLLED_BACK"


def test_concurrent_nginx_edit_is_not_overwritten_on_failure(runtime):
    def concurrent(*args, **kwargs):
        runtime.current[0] = b"another release root"
        raise r.StaticError("PUBLIC_ASSET_FAILED")
    runtime.base.public_check.side_effect = concurrent
    with pytest.raises(r.StaticError):
        apply(runtime)
    assert runtime.current == [b"another release root"]
    state = json.loads((runtime.args.release / "static-state.json").read_bytes())
    assert state["phase"] == "CRM_DESKTOP_COMFORT_STATIC_ROLLBACK_NEEDS_REVIEW"
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
