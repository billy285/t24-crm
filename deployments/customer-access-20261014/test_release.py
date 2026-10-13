"""Failure-injected release rehearsals. SQLite/tempfiles and fake Docker only."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


r = module("commission_release_tested", "release.py")
b = module("commission_payload_tested", "build_payload.py")
REAL_PRIVATE_BOUNDARY = r.private_boundary
SOURCE = "1" * 40
CANDIDATE = "sha256:" + "2" * 64
ROLLBACK = "sha256:" + "3" * 64


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real process or Docker access is forbidden in synthetic tests")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    monkeypatch.setattr(r, "docker_request", forbidden)
    monkeypatch.setattr(r, "_TOOLS_CACHE", None)


def original_container():
    return {"Id": r.OLD_ID, "Image": r.BASE_IMAGE, "Name": "/t24-crm", "RestartCount": 0,
        "State": {"StartedAt": "2026-10-12T00:00:00Z", "Running": True},
        "Config": {"Image": "crm:previous", "Hostname": r.OLD_ID[:12], "Env": [
            "APP_ENV=production", "SYNTHETIC_SECRET=space = unicode测试 $literal", "EMPTY="],
            "Labels": {"com.docker.compose.service": "crm"}, "Cmd": ["uvicorn", "main:app"],
            "Entrypoint": None, "WorkingDir": "/app/backend", "User": "", "Healthcheck": {"Test": ["CMD", "curl", "/ready"]}},
        "HostConfig": {"NetworkMode": "app_default", "AutoRemove": False,
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "Binds": ["/opt/t24-crm/app/data:/app/backend/data:rw"],
            "PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]},
            "ReadonlyRootfs": False, "SecurityOpt": None},
        "Mounts": [{"Source": "/opt/t24-crm/app/data", "Destination": "/app/backend/data", "RW": True}],
        "NetworkSettings": {"Networks": {
            "app_default": {"Aliases": ["t24-crm", "crm", r.OLD_ID[:12]], "NetworkID": "net-a", "EndpointID": "endpoint-a",
                "IPAddress": "172.18.0.2", "GlobalIPv6Address": "fd00::2", "IPAMConfig": {"IPv4Address": "172.18.0.2"}, "DriverOpts": {"test": "value"}},
            "observability": {"Aliases": ["crm-metrics"], "IPAddress": "172.19.0.2", "Links": ["collector"]},
        }}}


def create_database(path, revision=r.OLD_REVISION):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (r.OLD_REVISION,))
        connection.execute("CREATE TABLE commission_agreements(id INTEGER PRIMARY KEY, historical_rate REAL)")
        connection.execute("INSERT INTO commission_agreements VALUES (1, .2)")
        connection.execute("CREATE TABLE customer_commission_attributions(id INTEGER PRIMARY KEY, customer_id INTEGER)")
        connection.execute("INSERT INTO customer_commission_attributions VALUES (1, 45)")
        connection.execute("CREATE TABLE customers(id INTEGER PRIMARY KEY, notes TEXT)")
        connection.execute("INSERT INTO customers VALUES (45, 'old team note')")
        connection.execute("CREATE TABLE employees(id INTEGER PRIMARY KEY, role TEXT, status TEXT)")
        connection.execute("INSERT INTO employees VALUES (2, 'ops', 'active')")
        connection.execute("CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY, customer_id INTEGER, employee_id INTEGER, access_level TEXT)")
        connection.execute("INSERT INTO customer_access_grants VALUES (1,45,2,'read_write')")
        connection.execute("CREATE TABLE customer_materials(id INTEGER PRIMARY KEY, customer_id INTEGER)")
        connection.execute("INSERT INTO customer_materials VALUES (1,45)")
        connection.execute("CREATE TABLE payments(id INTEGER PRIMARY KEY, amount REAL, note TEXT)")
        connection.execute("INSERT INTO payments VALUES (7, 987.65, 'preserve synthetic ledger')")
    if revision == r.NEW_REVISION:
        apply_additive_migration(path)


def apply_additive_migration(path):
    guard = Path(path).parent / "release/authorization-guard.json"
    if guard.parent.exists() and not guard.exists():
        guard.write_text(json.dumps(r.authorization_snapshot(path)))
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for table, additions in r.ADDITIONS.items():
            for name in sorted(additions):
                connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" TEXT')
        for table, columns in r.NEW_TABLES.items():
            connection.execute('CREATE TABLE "'+table+'" ('+','.join('"'+name+'" TEXT' for name in sorted(columns))+')')
        connection.execute("UPDATE alembic_version SET version_num=?", (r.NEW_REVISION,))


@pytest.fixture
def lab(tmp_path, monkeypatch):
    release = tmp_path / "release"
    release.mkdir()
    public = tmp_path / "public"
    public.mkdir()
    version_bytes = json.dumps({"version": "4" * 12}).encode()
    (public / "app-version.json").write_bytes(version_bytes)
    nginx = tmp_path / "nginx.conf"
    orig_nginx = ("server { root " + str(r.OLD_PUBLIC) + "; }\n").encode()
    next_nginx = ("server { root " + str(public) + "; }\n").encode()
    nginx.write_bytes(orig_nginx)
    business = tmp_path / "crm_prod.db"
    create_database(business)
    monkeypatch.setattr(r, "BUSINESS", business)
    monkeypatch.setattr(r, "NGINX", nginx)
    monkeypatch.setattr(r, "NGINX_SHA", r.H(orig_nginx))
    original = original_container()
    containers = {r.OLD_ID: copy.deepcopy(original)}
    receipt = {"stage": "CUSTOMER_ACCESS_PREPARED_OFFLINE_VERIFIED", "source_sha": SOURCE, "version": "4" * 12,
        "candidate_image": CANDIDATE, "rollback_image": ROLLBACK, "old_crm": r.runtime(original), "public_root": str(public),
        "manifest_sha256": "a" * 64, "payload_sha256": "b" * 64, "preflight_sha256": "c" * 64}
    (release / "prepared.json").write_text(json.dumps(receipt))
    (release / "original-container.json").write_text(json.dumps(original))
    args = SimpleNamespace(review_sha256=r.H((release / "prepared.json").read_bytes()), manifest_sha256="a" * 64,
        payload_sha256="b" * 64, preflight_sha256="c" * 64)
    manifest = {"source_sha": SOURCE, "frontend_version": "4" * 12,
        "files": {"static/app-version.json": r.H(version_bytes)}, "backend_after": {name: "d" * 64 for name in r.BACKEND}}
    events = []
    faults = set()

    def protected_read(path, expected=None):
        value = Path(path).read_bytes()
        assert expected is None or r.H(value) == expected
        return value

    def find(name):
        return next((value for value in containers.values() if value["Id"] == name or value["Name"] == "/" + name), None)

    def inspect_optional(name):
        value = find(name)
        return copy.deepcopy(value) if value else None

    def inspect(name):
        value = inspect_optional(name)
        if value is None:
            raise RuntimeError("CONTAINER_NOT_FOUND")
        return value

    def create(name, image, config, source):
        assert source == SOURCE
        assert find(name) is None, "Container name collision was not recovered"
        value = copy.deepcopy(config)
        identity = ("candidate-" if image == CANDIDATE else "rollback-") + str(len(containers))
        value.update(Id=identity, Image=image, Name="/" + name)
        value["State"]["Running"] = False
        value["Config"] = r.clone_config(image, config, source)
        value["Config"].pop("HostConfig")
        value["Config"].pop("NetworkingConfig")
        containers[identity] = value
        events.append(("create", identity, image))
        failure = "candidate_create_lost" if image == CANDIDATE else "rollback_create_lost"
        if failure in faults:
            faults.remove(failure)
            raise TimeoutError("synthetic lost Docker response")
        return identity

    def run(command, code, timeout=180):
        events.append(tuple(command[:6]))
        if command[:2] == ["docker", "run"]:
            assert command[-1] == r.MIGRATE and "--network=none" in command
            assert "--read-only" in command
            if "migration_before_commit" in faults:
                raise RuntimeError("PRODUCTION_ADDITIVE_MIGRATION_FAILED")
            apply_additive_migration(business)
            if "migration_after_commit" in faults:
                raise subprocess.TimeoutExpired("synthetic migration", timeout)
            return b"ADDITIVE_MIGRATION_OK"
        if command[:2] == ["docker", "stop"]:
            value = find(command[-1])
            assert value is not None
            if "migration_stop_failure" in faults and value["Name"].startswith("/t24-customer-access-migrate-"):
                raise RuntimeError("MIGRATION_STOP_FAILED")
            value["State"]["Running"] = False
        elif command[:2] == ["docker", "start"]:
            value = find(command[-1])
            assert value is not None
            if "rollback_start" in faults and value["Image"] == ROLLBACK:
                raise RuntimeError("ROLLBACK_START_FAILED")
            value["State"]["Running"] = True
        elif command[:2] == ["docker", "rename"]:
            value = find(command[2])
            assert value is not None and find(command[3]) is None
            value["Name"] = "/" + command[3]
        elif command[:2] == ["docker", "rm"]:
            value = find(command[-1])
            assert value is not None and not value["State"]["Running"]
            del containers[value["Id"]]
        elif command == ["nginx", "-t"]:
            if "nginx_test" in faults and nginx.read_bytes() == next_nginx:
                raise RuntimeError("NGINX_TEST_FAILED")
        elif command == ["systemctl", "reload", "nginx"]:
            if "nginx_reload" in faults and nginx.read_bytes() == next_nginx:
                raise RuntimeError("NGINX_RELOAD_FAILED")
        elif command[:2] == ["curl", "-fsS"]:
            assert command[-1] == "https://t24-crm.com/ready"
        else:
            raise AssertionError("Unexpected synthetic command " + repr(command))
        return b""

    def ready(identity):
        assert find(identity)["State"]["Running"]
        if "candidate_ready" in faults and find(identity)["Image"] == CANDIDATE:
            raise RuntimeError("CANDIDATE_READINESS_TIMEOUT")

    base = SimpleNamespace(public_check=Mock(), file_map=lambda root: {})
    private_boundary = Mock(return_value=(None, None, base, None, None))
    monkeypatch.setattr(r, "read", protected_read)
    monkeypatch.setattr(r, "inspect", inspect)
    monkeypatch.setattr(r, "inspect_optional", inspect_optional)
    monkeypatch.setattr(r, "docker_create", create)
    monkeypatch.setattr(r, "run", run)
    monkeypatch.setattr(r, "ready", ready)
    monkeypatch.setattr(r, "private_boundary", private_boundary)
    monkeypatch.setattr(r, "inventory_in_container", lambda name, paths: manifest["backend_after"])
    return SimpleNamespace(release=release, public=public, nginx=nginx, orig_nginx=orig_nginx, next_nginx=next_nginx,
        business=business, original=original, containers=containers, receipt=receipt, args=args, manifest=manifest,
        events=events, faults=faults, find=find, create=create, run=run, private_boundary=private_boundary)


def assert_ledger_preserved(lab):
    with sqlite3.connect(lab.business) as connection:
        assert connection.execute("SELECT * FROM payments").fetchall() == [(7, 987.65, "preserve synthetic ledger")]
        assert connection.execute("SELECT id,historical_rate FROM commission_agreements").fetchall() == [(1, .2)]
        assert connection.execute("SELECT id,customer_id FROM customer_commission_attributions").fetchall() == [(1, 45)]
    assert all("private" not in str(part) for event in lab.events for part in event)


@pytest.mark.parametrize("fault", ["migration_after_commit", "candidate_create_lost", "candidate_ready", "nginx_test", "nginx_reload"])
def test_committed_migration_failure_recovers_forward_schema_without_restoring_financial_rows(lab, fault):
    lab.faults.add(fault)
    with pytest.raises((RuntimeError, TimeoutError, subprocess.TimeoutExpired)):
        r.activate(lab.release, lab.args, lab.manifest, {})
    proof = json.loads((lab.release / "rollback.json").read_bytes())
    assert proof["stage"] == "ROLLED_BACK" and proof["schema_retained"] is True
    assert proof["database_restored"] is False and proof["failures"] == []
    assert lab.find("t24-crm")["Image"] == ROLLBACK and lab.find("t24-crm")["State"]["Running"]
    assert lab.nginx.read_bytes() == lab.orig_nginx
    assert r.committed_revision() == r.NEW_REVISION
    assert not (lab.release / "deployed.json").exists()
    assert_ledger_preserved(lab)


def test_failed_migration_before_commit_restarts_exact_original(lab):
    lab.faults.add("migration_before_commit")
    with pytest.raises(RuntimeError, match="PRODUCTION_ADDITIVE_MIGRATION_FAILED"):
        r.activate(lab.release, lab.args, lab.manifest, {})
    assert lab.find("t24-crm")["Id"] == r.OLD_ID
    assert lab.find("t24-crm")["State"]["Running"]
    assert not any(event[0] == "create" for event in lab.events)
    assert r.committed_revision() == r.OLD_REVISION
    proof = json.loads((lab.release / "rollback.json").read_bytes())
    assert proof["schema_retained"] is False and proof["database_restored"] is False
    assert_ledger_preserved(lab)


def test_nginx_is_restored_even_when_backend_recovery_fails(lab):
    lab.faults.update({"nginx_reload", "rollback_start"})
    with pytest.raises(RuntimeError, match="ROLLBACK_INCOMPLETE"):
        r.activate(lab.release, lab.args, lab.manifest, {})
    assert lab.nginx.read_bytes() == lab.orig_nginx
    proof = json.loads((lab.release / "rollback.json").read_bytes())
    assert proof["stage"] == "ROLLBACK_INCOMPLETE"
    assert proof["failures"] == ["CRM_ROLLBACK_START_FAILED"]
    assert proof["database_restored"] is False
    assert_ledger_preserved(lab)


def test_recover_retries_ambiguous_rollback_creation_without_name_collision(lab):
    lab.faults.update({"candidate_ready", "rollback_create_lost"})
    with pytest.raises(RuntimeError, match="ROLLBACK_INCOMPLETE"):
        r.activate(lab.release, lab.args, lab.manifest, {})
    existing_id = lab.find("t24-crm")["Id"]
    assert lab.find("t24-crm")["Image"] == ROLLBACK
    r.recover(lab.release, lab.args, lab.manifest, {})
    assert lab.find("t24-crm")["Id"] == existing_id and lab.find("t24-crm")["State"]["Running"]
    proofs = list(lab.release.glob("rollback-recovery-*.json"))
    assert len(proofs) == 1 and json.loads(proofs[0].read_bytes())["stage"] == "ROLLED_BACK"
    assert_ledger_preserved(lab)


def test_success_is_pinned_and_cannot_be_rolled_back_as_interruption(lab):
    r.activate(lab.release, lab.args, lab.manifest, {})
    assert lab.find("t24-crm")["Image"] == CANDIDATE
    assert lab.nginx.read_bytes() == lab.next_nginx
    proof = json.loads((lab.release / "deployed.json").read_bytes())
    assert proof["deployed"] is True and proof["financial_rows_unchanged_during_migration"] is True
    assert lab.private_boundary.call_count >= 3
    before = copy.deepcopy(lab.containers)
    with pytest.raises(RuntimeError, match="SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_ROLLBACK_REVIEW"):
        r.recover(lab.release, lab.args, lab.manifest, {})
    assert lab.containers == before
    assert_ledger_preserved(lab)


def test_recovery_never_touches_unknown_container_named_crm(lab):
    apply_additive_migration(lab.business)
    lab.containers[r.OLD_ID]["Name"] = "/retained-original"
    unknown = copy.deepcopy(lab.original)
    unknown.update(Id="unknown-owner", Image="sha256:" + "9" * 64)
    lab.containers[unknown["Id"]] = unknown
    lab.nginx.write_bytes(lab.next_nginx)
    before = copy.deepcopy(lab.containers)
    with pytest.raises(RuntimeError, match="ROLLBACK_AUTHORIZATION_GUARD_REJECTED"):
        r.rollback(lab.release, lab.receipt, lab.manifest, {}, lab.orig_nginx, lab.next_nginx, "TimeoutError")
    assert lab.containers == before and lab.nginx.read_bytes() == lab.next_nginx
    proof = json.loads(next(lab.release.glob("rollback-blocked-*.json")).read_bytes())
    assert proof["reason_type"] == "UNKNOWN_ACTIVE_CRM_CONTAINER"


def test_unfinished_migration_is_stopped_before_revision_is_read(lab, monkeypatch):
    migration = copy.deepcopy(lab.original)
    migration.update(Id="migration-id", Image=CANDIDATE, Name="/" + r.migration_name(lab.manifest))
    migration["Config"]["Labels"].update({"t24.release.scope": "customer-access", "t24.release.source": SOURCE})
    lab.containers[migration["Id"]] = migration
    original_revision = r.committed_revision
    def revision():
        assert lab.find(r.migration_name(lab.manifest)) is None
        return original_revision()
    monkeypatch.setattr(r, "committed_revision", revision)
    r.rollback(lab.release, lab.receipt, lab.manifest, {}, lab.orig_nginx, lab.next_nginx, "TimeoutError")
    assert any(event[:2] == ("docker", "stop") and event[-1] == r.migration_name(lab.manifest) for event in lab.events)


def test_unstoppable_migration_blocks_backend_and_static_rollback(lab, monkeypatch):
    migration = copy.deepcopy(lab.original)
    migration.update(Id="migration-id", Image=CANDIDATE, Name="/" + r.migration_name(lab.manifest))
    migration["Config"]["Labels"].update({"t24.release.scope": "customer-access", "t24.release.source": SOURCE})
    lab.containers[migration["Id"]] = migration
    lab.faults.add("migration_stop_failure")
    lab.nginx.write_bytes(lab.next_nginx)
    revision = Mock(side_effect=AssertionError("must not infer schema while migration is running"))
    monkeypatch.setattr(r, "committed_revision", revision)
    with pytest.raises(RuntimeError, match="ROLLBACK_AUTHORIZATION_GUARD_REJECTED"):
        r.rollback(lab.release, lab.receipt, lab.manifest, {}, lab.orig_nginx, lab.next_nginx, "TimeoutError")
    revision.assert_not_called()
    assert not any(event[:2] == ("docker", "start") for event in lab.events)
    assert lab.nginx.read_bytes() == lab.next_nginx


def test_revision_and_additive_columns_must_agree(lab):
    with sqlite3.connect(lab.business) as connection:
        connection.execute("ALTER TABLE customers ADD COLUMN private_notes TEXT")
    with pytest.raises(RuntimeError, match="MIGRATION_REVISION_SCHEMA_MISMATCH"):
        r.committed_revision()


def test_docker_clone_preserves_env_mounts_security_and_all_network_aliases_without_ips():
    original = original_container()
    before = copy.deepcopy(original)
    config = r.clone_config(CANDIDATE, original, SOURCE)
    assert original == before
    assert config["Env"] == original["Config"]["Env"]
    assert config["HostConfig"] == original["HostConfig"]
    assert config["Cmd"] == original["Config"]["Cmd"] and config["WorkingDir"] == "/app/backend"
    assert config["Healthcheck"] == original["Config"]["Healthcheck"]
    assert config["NetworkingConfig"]["EndpointsConfig"] == {
        "app_default": {"Aliases": ["t24-crm", "crm"], "DriverOpts": {"test": "value"}},
        "observability": {"Aliases": ["crm-metrics"], "Links": ["collector"]}}
    assert config["Labels"]["com.docker.compose.service"] == "crm"
    assert config["Labels"]["t24.release.source"] == SOURCE


def test_environment_file_preserves_literal_equal_signs_spaces_and_unicode(tmp_path):
    original = original_container()
    r.environment_file(tmp_path, original)
    assert (tmp_path / "crm.env").read_text().splitlines() == original["Config"]["Env"]
    assert (tmp_path / "crm.env").stat().st_mode & 0o777 == 0o600


def test_public_tree_is_nginx_traversable_under_real_umask_077_without_opening_private_paths(tmp_path):
    previous_umask = os.umask(0o077)
    try:
        protected_parent = tmp_path / "protected-parent"
        protected_parent.mkdir(mode=0o755)
        private = protected_parent / "release-secrets"
        private.mkdir(mode=0o755)
        r.write(private / "crm.env", b"SYNTHETIC_SECRET=private\n")
        public = protected_parent / "public"
        r.public_directory(public, public)
        # Nested directories are created with 0700 by Path.mkdir(parents=True)
        # under this mask; all public ancestors must be repaired explicitly.
        for child in (public / "assets" / "fonts", public / "assets" / "legacy" / "chunks"):
            r.public_directory(child, public)
        assert public.stat().st_mode & 0o777 == 0o755
        assert all(path.stat().st_mode & 0o777 == 0o755 for path in public.rglob("*") if path.is_dir())
        assert protected_parent.stat().st_mode & 0o777 == 0o700
        assert private.stat().st_mode & 0o777 == 0o700
        assert (private / "crm.env").stat().st_mode & 0o777 == 0o600
        # The public helper must not loosen the process-wide restrictive mask.
        marker = private / "after-public-creation"
        marker.mkdir(mode=0o755)
        assert marker.stat().st_mode & 0o777 == 0o700
    finally:
        os.umask(previous_umask)


def test_public_directory_helper_rejects_scope_escape(tmp_path):
    root = tmp_path / "public"
    forbidden = tmp_path / "private"
    with pytest.raises(RuntimeError, match="PUBLIC_DIRECTORY_SCOPE_REJECTED"):
        r.public_directory(forbidden, root)
    assert not forbidden.exists()


@pytest.mark.parametrize("bad", ["TOKEN=line\nbreak", "TOKEN=carriage\rreturn", "NO_EQUALS"])
def test_environment_file_rejects_docker_env_file_ambiguity(tmp_path, bad):
    original = original_container()
    original["Config"]["Env"].append(bad)
    with pytest.raises(RuntimeError, match="ENV_FORMAT_REJECTED"):
        r.environment_file(tmp_path, original)
    assert not (tmp_path / "crm.env").exists()


def test_migration_only_runs_isolated_and_docker_context_excludes_credentials(tmp_path):
    command = r.production_migration_args(tmp_path, CANDIDATE, {"source_sha": SOURCE})
    assert "--network=none" in command and "--read-only" in command
    assert command[command.index("--name") + 1] == "t24-customer-access-migrate-" + SOURCE[:12]
    assert command[-3:] == ["python", "-c", r.MIGRATE]
    included_patterns = [line[1:] for line in r.DOCKERIGNORE.decode().splitlines() if line.startswith("!")]
    assert set(included_patterns) == {"Dockerfile", "Dockerfile.rollback", "backend", "backend/**"}
    assert r.DOCKERIGNORE.startswith(b"*\n")
    assert not any(name in included_patterns for name in ("crm.env", "original-container.json", "probe-data", "business-before.db"))


@pytest.mark.parametrize("name", ["assets/.env", "assets/private.db", "assets/backup.sqlite", "assets/source.py", "credentials.json", "assets/../logo.svg", "/index.html", "assets//index.js", "assets\\index.js", "arbitrary.html"])
def test_static_payload_rejects_credentials_backups_and_noncanonical_paths(name):
    assert not b.static_path(name) and not r.static_path(name)


@pytest.mark.parametrize("name", ["index.html", "offline.html", "app-version.json", "sw.js", "manifest.webmanifest", "favicon.svg", "pwa-icon-512.png", "assets/index-hash.js", "assets/font.woff2"])
def test_existing_static_asset_types_remain_allowed(name):
    assert b.static_path(name) and r.static_path(name)


def test_additive_verification_rejects_even_same_total_financial_row_changes(lab):
    before = r.sql_snapshot(lab.business)
    apply_additive_migration(lab.business)
    r.original_rows_unchanged(before, r.sql_snapshot(lab.business, before))
    with sqlite3.connect(lab.business) as connection:
        connection.execute("UPDATE payments SET note='rewritten audit note'")
    with pytest.raises(RuntimeError, match="BUSINESS_ROWS_CHANGED_PAYMENTS"):
        r.original_rows_unchanged(before, r.sql_snapshot(lab.business, before))


def test_payload_tar_rejects_symlink_even_with_hash_match(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        item = tarfile.TarInfo("static/index.html")
        item.type = tarfile.SYMTYPE
        item.linkname = "/etc/passwd"
        output.addfile(item)
    (tmp_path / "payload.tar.gz").write_bytes(archive.getvalue())
    monkeypatch.setattr(r, "read", lambda path, expected=None: Path(path).read_bytes())
    with pytest.raises(RuntimeError, match="PAYLOAD_MEMBER_REJECTED"):
        r.extract(tmp_path, {"files": {"static/index.html": "a" * 64}})
    assert not (tmp_path / "static").exists()


def test_payload_builder_scopes_exact_six_backend_files_and_five_ui_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allowed = {"app/backend/" + name for name in b.BACKEND} | {"app/frontend/src/" + name for name in b.FRONTEND}
    protected = "app/backend/services/private_workspace.py"
    before = {name: b.H(b"old") for name in allowed}
    after = {}
    for name in allowed | {protected}:
        file = Path(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"protected" if name == protected else b"approved change")
        after[name] = b.H(file.read_bytes())
    before[protected] = after[protected]
    dist = Path("app/frontend/dist")
    dist.mkdir(parents=True)
    (dist / "app-version.json").write_text(json.dumps({"version": "4" * 12}))
    (dist / "index.html").write_text("synthetic app")
    monkeypatch.setattr(b, "git", lambda *args: (SOURCE + "\n").encode())
    monkeypatch.setattr(b, "inventory", lambda ref: before if ref == b.BASE else after)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: ("4" * 12).encode())
    monkeypatch.setattr(sys, "argv", ["build_payload.py", "--source", SOURCE, "--out", str(tmp_path / "out")])
    b.main()
    manifest = json.loads((tmp_path / "out/manifest.json").read_bytes())
    assert set(manifest["backend_after"]) == r.BACKEND
    assert manifest["protected_source_inventory"] == {protected: after[protected]}
    with tarfile.open(tmp_path / "out/payload.tar.gz") as archive:
        assert set(archive.getnames()) == {"backend/" + name for name in r.BACKEND} | {"static/index.html", "static/app-version.json"}
    # Same app tree with one private-file mutation is rejected before packaging.
    after[protected] = "f" * 64
    with pytest.raises(RuntimeError, match="SOURCE_SCOPE_DRIFT"):
        b.main()


def test_recover_after_process_disappeared_preserves_newly_written_financial_rows(lab):
    # State after the OS killed the publisher: no exception handler or rollback
    # receipt ran; the API and static switch happened, final proof did not.
    lab.run(["docker", "stop", "-t", "30", "t24-crm"], "STOP")
    r.backup(lab.business, lab.release / "business-before.db")
    apply_additive_migration(lab.business)
    lab.run(["docker", "rename", "t24-crm", "retained-original"], "RENAME")
    candidate = lab.create("t24-crm", CANDIDATE, lab.original, SOURCE)
    lab.run(["docker", "start", candidate], "START")
    lab.nginx.write_bytes(lab.next_nginx)
    (lab.release / "nginx-before.conf").write_bytes(lab.orig_nginx)
    (lab.release / "activation-started.json").write_text(json.dumps({
        "prepared_sha256": lab.args.review_sha256, "source_sha": SOURCE, "old_id": r.OLD_ID,
        "candidate_image": CANDIDATE, "rollback_image": ROLLBACK}))
    with sqlite3.connect(lab.business) as connection:
        connection.execute("INSERT INTO payments VALUES (8, 123.45, 'new after release began')")
    r.recover(lab.release, lab.args, lab.manifest, {})
    assert lab.find("t24-crm")["Image"] == ROLLBACK and lab.find("t24-crm")["State"]["Running"]
    assert lab.nginx.read_bytes() == lab.orig_nginx
    with sqlite3.connect(lab.business) as connection:
        assert connection.execute("SELECT amount,note FROM payments WHERE id=8").fetchone() == (123.45, "new after release began")
    proof = json.loads((lab.release / "rollback.json").read_bytes())
    assert proof["stage"] == "ROLLED_BACK" and proof["database_restored"] is False


def test_recovery_does_not_overwrite_concurrent_nginx_edit_but_recovers_backend(lab):
    apply_additive_migration(lab.business)
    third_party = b"server { root /new-unrelated-reviewed-release; }\n"
    lab.nginx.write_bytes(third_party)
    with pytest.raises(RuntimeError, match="ROLLBACK_INCOMPLETE"):
        r.rollback(lab.release, lab.receipt, lab.manifest, {}, lab.orig_nginx, lab.next_nginx, "TimeoutError")
    assert lab.nginx.read_bytes() == third_party
    assert lab.find("t24-crm")["Image"] == ROLLBACK and lab.find("t24-crm")["State"]["Running"]
    proof = json.loads((lab.release / "rollback.json").read_bytes())
    assert proof["failures"] == ["NGINX_ROLLBACK_NGINX_DRIFT"]


@pytest.mark.parametrize("field,value,code", [
    ("payload_sha256", "f" * 64, "PREPARED_IDENTITY_DRIFT"),
    ("source_sha", "f" * 40, "PREPARED_SOURCE_DRIFT"),
    ("version", "f" * 12, "PREPARED_SOURCE_DRIFT"),
    ("candidate_image", "some-mutable-tag", "PREPARED_IMAGE_PINS_REQUIRED"),
])
def test_prepare_proof_is_bound_to_payload_source_and_immutable_images(lab, field, value, code):
    lab.receipt[field] = value
    (lab.release / "prepared.json").write_text(json.dumps(lab.receipt))
    lab.args.review_sha256 = r.H((lab.release / "prepared.json").read_bytes())
    with pytest.raises(RuntimeError, match=code):
        r.activate(lab.release, lab.args, lab.manifest, {})
    assert lab.events == [] and lab.find("t24-crm")["Id"] == r.OLD_ID


@pytest.mark.parametrize("drift,expected", [
    ("none", None), ("environment", "PRIVATE_ENV_CHANGED"), ("api", "PRIVATE_RUNTIME_CHANGED"),
    ("worker", "PRIVATE_RUNTIME_CHANGED"), ("identity", "PRIVATE_SCHEMA_CHANGED"), ("schema", "PRIVATE_SCHEMA_CHANGED"),
])
def test_private_runtime_identity_environment_and_schema_are_independent_guards(tmp_path, monkeypatch, drift, expected):
    env = tmp_path / "private.env"
    env.write_bytes(b"SYNTHETIC_PRIVATE_KEY=keep-identical\n")
    private = {"identity": {"device": 1, "inode": 42}, "schema_objects": {"private_mail": "original-schema"}}
    pins = {"environment_sha256": r.H(env.read_bytes()), "databases": {"private": copy.deepcopy(private)}, "roles": {}}
    for role in ("api", "worker"):
        pins["roles"][role] = {"id": "private-" + role, "image": "immutable-image", "attempt": "same-attempt", "source": "same-source", "runtime": {"role": role, "unchanged": True}}
    if drift == "environment":
        env.write_bytes(b"CHANGED=1")
    if drift == "identity":
        private["identity"]["inode"] = 43
    if drift == "schema":
        private["schema_objects"]["private_mail"] = "different-schema"
    base = SimpleNamespace(ENV=env, PRIVATE_DB="synthetic-private.db", BUSINESS="synthetic-company.db")
    prep = SimpleNamespace(release_snapshot=Mock(return_value={"private": private}))
    switch = SimpleNamespace(environment=lambda info: {"HASH_ONLY": "no-credentials"})
    def prove_role(*args):
        role = args[3]
        return {"role": role, "unchanged": role != drift}
    audit = SimpleNamespace(own_role=prove_role)
    monkeypatch.setattr(r, "tools", lambda: (None, audit, base, prep, switch))
    monkeypatch.setattr(r, "read", lambda path, expected=None: Path(path).read_bytes())
    monkeypatch.setattr(r, "inspect", lambda name: {"name": name})
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            r.private_boundary(pins)
    else:
        assert r.private_boundary(pins)[2] is base
    if drift == "environment":
        prep.release_snapshot.assert_not_called()


@pytest.mark.parametrize("existing_state", ["missing", "same", "different"])
def test_base_alias_is_local_exact_and_never_overwrites_another_image(tmp_path, monkeypatch, existing_state):
    manifest = {"source_sha": SOURCE}
    expected_tag = "t24-crm:customer-access-base-" + SOURCE[:12] + "-" + r.H(str(tmp_path).encode())[:12]
    images = {r.BASE_IMAGE: r.BASE_IMAGE}
    if existing_state != "missing":
        images[expected_tag] = r.BASE_IMAGE if existing_state == "same" else "sha256:" + "f" * 64
    commands = []
    def request(method, path, body=None):
        assert method == "GET" and path.startswith("/images/") and path.endswith("/json")
        name = r.urllib.parse.unquote(path[len("/images/"):-len("/json")])
        return (200, json.dumps({"Id": images[name]}).encode()) if name in images else (404, b'{}')
    def run(command, code, timeout=180):
        commands.append(command)
        if command[:3] == ["docker", "image", "tag"]:
            assert command[3] == r.BASE_IMAGE and command[4] == expected_tag
            assert command[4] not in images  # No replacement of a different tag.
            images[command[4]] = images[command[3]]
        elif command[:2] == ["docker", "build"]:
            assert "--network=none" in command and "--pull=false" in command
            assert images[expected_tag] == r.BASE_IMAGE
            filename = "Dockerfile.rollback" if "-f" in command else "Dockerfile"
            contents = (tmp_path / filename).read_text()
            assert contents.splitlines()[0] == "FROM " + expected_tag
            assert "FROM sha256:" not in contents
            images[command[command.index("-t") + 1]] = ROLLBACK if "-f" in command else CANDIDATE
        elif command[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": images[command[3]]}]).encode()
        else:
            raise AssertionError(command)
        return b""
    monkeypatch.setattr(r, "docker_request", request)
    monkeypatch.setattr(r, "run", run)
    if existing_state == "different":
        with pytest.raises(RuntimeError, match="BASE_TAG_ID_DRIFT"):
            r.build_images(tmp_path, manifest)
        assert commands == [] and not (tmp_path / "Dockerfile").exists()
        assert images[expected_tag] == "sha256:" + "f" * 64
    else:
        assert r.build_images(tmp_path, manifest) == (CANDIDATE, ROLLBACK)
        assert len([cmd for cmd in commands if cmd[:2] == ["docker", "build"]]) == 2
        assert len([cmd for cmd in commands if cmd[:3] == ["docker", "image", "tag"]]) == (1 if existing_state == "missing" else 0)
        assert (tmp_path / "Dockerfile.rollback").read_text().splitlines()[1] == "COPY backend/" + r.MIGRATION + " /app/backend/" + r.MIGRATION


def test_base_alias_change_during_candidate_build_blocks_the_release(tmp_path, monkeypatch):
    tag = "t24-crm:customer-access-base-" + SOURCE[:12] + "-" + r.H(str(tmp_path).encode())[:12]
    state = {"changed": False, "builds": 0}
    def image_id(name):
        if name == tag and state["changed"]:
            return "sha256:" + "f" * 64
        return r.BASE_IMAGE
    def run(command, code, timeout=180):
        assert command[:2] == ["docker", "build"]
        state["builds"] += 1
        state["changed"] = True
        return b""
    monkeypatch.setattr(r, "local_image_id", image_id)
    monkeypatch.setattr(r, "run", run)
    with pytest.raises(RuntimeError, match="BASE_TAG_ID_DRIFT"):
        r.build_images(tmp_path, {"source_sha": SOURCE})
    assert state["builds"] == 1
    assert not (tmp_path / "Dockerfile.rollback").exists()


def test_base_alias_rechecks_the_id_after_tag_creation(tmp_path, monkeypatch):
    state = {"tagged": False}
    def image_id(name):
        if name == r.BASE_IMAGE:
            return r.BASE_IMAGE
        return "sha256:" + "f" * 64 if state["tagged"] else None
    def run(command, code, timeout=180):
        assert command[:3] == ["docker", "image", "tag"]
        state["tagged"] = True
        return b""
    monkeypatch.setattr(r, "local_image_id", image_id)
    monkeypatch.setattr(r, "run", run)
    with pytest.raises(RuntimeError, match="BASE_TAG_ID_DRIFT"):
        r.build_images(tmp_path, {"source_sha": SOURCE})
    assert not (tmp_path / "Dockerfile").exists()


def install_single_load_trusted_helpers(lab, monkeypatch):
    """Model the retained loader that refuses a duplicate sys.modules identity."""
    counts = {"legacy_loads": 0, "retained_loads": 0, "personal_hash_checks": 0, "environment_reads": 0}
    private = {"identity": {"inode": 42}, "schema_objects": {"mail": "unchanged"}}
    env = lab.release / "synthetic-private.env"
    env.write_bytes(b"SYNTHETIC=private\n")
    helper = lab.release / "synthetic-helper.py"
    helper.write_bytes(b"LEGACY = 'synthetic'\ndef load_legacy(name):\n return _synthetic_load(name)\n")
    pins = {"environment_sha256": r.H(env.read_bytes()), "databases": {"private": private}, "roles": {}}
    for role in ("api", "worker"):
        pins["roles"][role] = {"id": "private-" + role, "image": "immutable", "attempt": "same", "source": "same", "runtime": {"role": role}}
    base = SimpleNamespace(ENV=env, PRIVATE_DB="synthetic-private.db", BUSINESS=lab.business,
        public_check=Mock(), file_map=lambda root: {})
    prep = SimpleNamespace(release_snapshot=Mock(return_value={"private": private}))
    switch = SimpleNamespace(environment=lambda info: {})
    def retained_tools(path):
        counts["retained_loads"] += 1
        if counts["retained_loads"] > 1:
            raise RuntimeError("RETAINED_TOOL_MODULE_ALREADY_LOADED")
        return base, None, prep, switch
    legacy = SimpleNamespace(retained_tools=retained_tools, own_role=Mock(side_effect=lambda *args: {"role": args[3]}))
    def load(name):
        assert name == "upgrade.py"
        counts["legacy_loads"] += 1
        return legacy
    compiled_module = ModuleType("_customer_access_personal_synthetic")
    compiled_module._synthetic_load = load
    monkeypatch.setattr(r.importlib.util, "module_from_spec", lambda spec: compiled_module)
    monkeypatch.setattr(r, "PERSONAL", helper)
    monkeypatch.setattr(r, "PERSONAL_SHA", r.H(helper.read_bytes()))
    original_read = r.read
    def read(path, expected=None):
        if Path(path) == helper:
            counts["personal_hash_checks"] += 1
        elif Path(path) == env:
            counts["environment_reads"] += 1
        return original_read(path, expected)
    monkeypatch.setattr(r, "read", read)
    original_inspect = r.inspect
    inspections = []
    def inspect(name):
        inspections.append(name)
        return {"Id": name} if name.startswith("t24-private-") else original_inspect(name)
    monkeypatch.setattr(r, "inspect", inspect)
    monkeypatch.setattr(r, "private_boundary", REAL_PRIVATE_BOUNDARY)
    return SimpleNamespace(counts=counts, pins=pins, env=env, helper=helper, prep=prep, legacy=legacy, inspections=inspections)


def assert_live_checks_and_one_load(helpers, expected_boundaries):
    assert helpers.counts == {"legacy_loads": 1, "retained_loads": 1,
        "personal_hash_checks": expected_boundaries, "environment_reads": expected_boundaries}
    assert helpers.prep.release_snapshot.call_count == expected_boundaries
    assert helpers.legacy.own_role.call_count == 2 * expected_boundaries
    for role in ("api", "worker"):
        assert helpers.inspections.count("t24-private-" + role) == expected_boundaries


def test_one_prepare_checks_head_and_tail_without_reloading_retained_modules(lab, monkeypatch):
    helpers = install_single_load_trusted_helpers(lab, monkeypatch)
    # Prepare's repeated live guards previously triggered the retained loader's
    # duplicate-module rejection. Exercise actual prepare through its final guard.
    (lab.release / "prepared.json").unlink()
    (lab.release / "original-container.json").unlink()
    lab.manifest["backend_before"] = {name: None if name == r.MIGRATION else "e" * 64 for name in r.BACKEND}
    monkeypatch.setattr(r, "extract", lambda *args: None)
    monkeypatch.setattr(r, "build_images", lambda *args: (CANDIDATE, ROLLBACK))
    def inventory(name, paths):
        if name == "t24-crm":
            return lab.manifest["backend_before"]
        if "candidate" in name:
            return lab.manifest["backend_after"]
        return {**lab.manifest["backend_before"], r.MIGRATION: lab.manifest["backend_after"][r.MIGRATION]}
    monkeypatch.setattr(r, "inventory_in_container", inventory)
    monkeypatch.setattr(r, "ready", lambda *args: None)
    def run(command, code, timeout=180):
        if code == "OFFLINE_MIGRATION_FAILED":
            apply_additive_migration(lab.release / "probe-data/crm_prod.db")
        else:
            assert code in {"OFFLINE_STARTUP_FAILED", "OFFLINE_PROBE_STOP_FAILED"}
        return b""
    monkeypatch.setattr(r, "run", run)
    boundary = r.current_boundary
    counter = {"calls": 0}
    def stop_after_tail(*args, **kwargs):
        value = boundary(*args, **kwargs)
        counter["calls"] += 1
        if counter["calls"] == 2:
            raise RuntimeError("SYNTHETIC_PREPARE_TAIL_VERIFIED")
        return value
    monkeypatch.setattr(r, "current_boundary", stop_after_tail)
    with pytest.raises(RuntimeError, match="SYNTHETIC_PREPARE_TAIL_VERIFIED"):
        r.prepare(lab.release, lab.args, lab.manifest, helpers.pins)
    assert_live_checks_and_one_load(helpers, 2)
    assert r.committed_revision() == r.OLD_REVISION  # Only the offline copy migrated.


@pytest.mark.parametrize("fail_candidate,expected_boundaries", [(False, 3), (True, 2)])
def test_activate_and_rollback_reuse_loader_but_recheck_private_state(lab, monkeypatch, fail_candidate, expected_boundaries):
    helpers = install_single_load_trusted_helpers(lab, monkeypatch)
    if fail_candidate:
        lab.faults.add("candidate_ready")
        with pytest.raises(RuntimeError, match="CANDIDATE_READINESS_TIMEOUT"):
            r.activate(lab.release, lab.args, lab.manifest, helpers.pins)
        assert json.loads((lab.release / "rollback.json").read_bytes())["stage"] == "ROLLED_BACK"
    else:
        r.activate(lab.release, lab.args, lab.manifest, helpers.pins)
        assert json.loads((lab.release / "deployed.json").read_bytes())["deployed"] is True
    assert_live_checks_and_one_load(helpers, expected_boundaries)


def test_cached_loader_still_rejects_private_env_and_helper_hash_drift(lab, monkeypatch):
    helpers = install_single_load_trusted_helpers(lab, monkeypatch)
    r.current_boundary(helpers.pins)
    helpers.env.write_bytes(b"SYNTHETIC=changed\n")
    with pytest.raises(RuntimeError, match="PRIVATE_ENV_CHANGED"):
        r.current_boundary(helpers.pins)
    assert helpers.counts["retained_loads"] == 1
    helpers.env.write_bytes(b"SYNTHETIC=private\n")
    helpers.helper.write_bytes(b"changed trusted helper")
    # lab.read verifies expected bytes; production read raises FILE_HASH_DRIFT.
    with pytest.raises(AssertionError):
        r.current_boundary(helpers.pins)
    assert helpers.counts["retained_loads"] == 1
    assert helpers.prep.release_snapshot.call_count == 1


@pytest.mark.parametrize("statement", [
    "UPDATE customer_access_grants SET access_level='none' WHERE id=1",
    "UPDATE customer_access_grants SET scopes='{\"materials\":\"none\"}' WHERE id=1",
    "UPDATE customer_access_grants SET finance_access='profit' WHERE id=1",
    "UPDATE customers SET private_notes='new owner-only information' WHERE id=45",
    "UPDATE customer_materials SET visibility='owner' WHERE id=1",
    "UPDATE employees SET role='finance' WHERE id=2",
    "INSERT INTO customer_access_audits(id) VALUES (1)",
    "INSERT INTO customer_record_audits(id) VALUES (1)",
])
def test_new_permission_or_private_content_blocks_old_code_and_static_rollback(lab, statement):
    lab.run(["docker", "stop", "t24-crm"], "STOP")
    apply_additive_migration(lab.business)
    lab.run(["docker", "rename", "t24-crm", "retained-original"], "RENAME")
    candidate=lab.create("t24-crm", CANDIDATE, lab.original, SOURCE)
    lab.run(["docker", "start", candidate], "START")
    lab.nginx.write_bytes(lab.next_nginx)
    with sqlite3.connect(lab.business) as connection:
        connection.execute(statement)
    containers=copy.deepcopy(lab.containers)
    events=len(lab.events)
    with pytest.raises(RuntimeError, match="ROLLBACK_AUTHORIZATION_GUARD_REJECTED"):
        r.rollback(lab.release,lab.receipt,lab.manifest,{},lab.orig_nginx,lab.next_nginx,"SYNTHETIC_FAILURE")
    assert lab.containers==containers and lab.nginx.read_bytes()==lab.next_nginx
    assert len(lab.events)==events
    proof=json.loads(next(lab.release.glob("rollback-blocked-*.json")).read_bytes())
    assert proof["reason_type"]=="ROLLBACK_AUTHORIZATION_STATE_CHANGED"
    assert proof["old_authorization_code_started"] is False and proof["database_restored"] is False


def test_permission_write_finishing_during_shutdown_restarts_candidate_and_keeps_new_static(lab,monkeypatch):
    lab.run(["docker", "stop", "t24-crm"], "STOP")
    apply_additive_migration(lab.business)
    lab.run(["docker", "rename", "t24-crm", "retained-original"], "RENAME")
    candidate=lab.create("t24-crm",CANDIDATE,lab.original,SOURCE)
    lab.run(["docker", "start",candidate],"START")
    lab.nginx.write_bytes(lab.next_nginx)
    def run(command,code,timeout=180):
        result=lab.run(command,code,timeout)
        if code=="CANDIDATE_GUARD_STOP_FAILED":
            with sqlite3.connect(lab.business) as connection:
                connection.execute("UPDATE customer_access_grants SET access_level='none' WHERE id=1")
        return result
    monkeypatch.setattr(r,"run",run)
    with pytest.raises(RuntimeError,match="ROLLBACK_AUTHORIZATION_GUARD_REJECTED"):
        r.rollback(lab.release,lab.receipt,lab.manifest,{},lab.orig_nginx,lab.next_nginx,"SYNTHETIC_FAILURE")
    assert lab.find("t24-crm")["Id"]==candidate and lab.find("t24-crm")["State"]["Running"]
    assert lab.nginx.read_bytes()==lab.next_nginx
    assert not any(value["Image"]==ROLLBACK for value in lab.containers.values())


def test_permission_guard_must_exist_before_older_authorization_code_can_start(lab):
    apply_additive_migration(lab.business)
    (lab.release/"authorization-guard.json").unlink()
    before=copy.deepcopy(lab.containers)
    with pytest.raises(RuntimeError,match="ROLLBACK_AUTHORIZATION_GUARD_REJECTED"):
        r.rollback(lab.release,lab.receipt,lab.manifest,{},lab.orig_nginx,lab.next_nginx,"SYNTHETIC_FAILURE")
    assert lab.containers==before


def test_permission_snapshot_is_stable_across_migration_but_ignores_unrelated_financial_writes(lab):
    before=r.authorization_snapshot(lab.business)
    apply_additive_migration(lab.business)
    assert before==r.authorization_snapshot(lab.business)
    with sqlite3.connect(lab.business) as connection:
        connection.execute("INSERT INTO payments VALUES (8,321.09,'ordinary financial write')")
    assert before==r.authorization_snapshot(lab.business)


def test_new_audit_table_schema_and_rows_are_verified_during_migration(lab):
    before=r.sql_snapshot(lab.business)
    apply_additive_migration(lab.business)
    r.original_rows_unchanged(before,r.sql_snapshot(lab.business,before))
    with sqlite3.connect(lab.business) as connection:
        connection.execute("INSERT INTO customer_record_audits(id) VALUES (1)")
    with pytest.raises(RuntimeError,match="NEW_AUDIT_TABLE_NOT_EMPTY_OR_SCHEMA_DRIFT"):
        r.original_rows_unchanged(before,r.sql_snapshot(lab.business,before))
