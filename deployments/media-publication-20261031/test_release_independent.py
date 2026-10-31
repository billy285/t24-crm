"""Independent release faults; fake Docker and temporary SQLite only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("publication_independent_fixture", HERE / "test_release.py")
author = importlib.util.module_from_spec(spec); spec.loader.exec_module(author)
r = author.r
publisher = author.publisher
OLD, NEW, IMAGE = author.OLD, author.NEW, author.IMAGE


def no_original_restart(w):
    assert not any(call[:3] == ["docker", "start", OLD] for call in w.m.calls)
    assert not any(call[:2] in (["docker", "rm"], ["docker", "run"]) for call in w.m.calls)


def test_committed_migration_with_lost_process_result_recovers_forward(publisher):
    w = publisher; migrate = w.run_migration
    def commit_then_lost(*args, **kwargs):
        migrate(*args, **kwargs)
        raise RuntimeError("MIGRATION_RESULT_LOST_AFTER_COMMIT")
    w.run_migration = commit_then_lost
    w.settle_migration = lambda *args, **kwargs: {"Image": IMAGE, "State": {"Running": False, "ExitCode": 1}}
    with pytest.raises(RuntimeError, match="MIGRATION_RESULT_LOST_AFTER_COMMIT"): w.activate()
    assert w.m.head == r.NEW_REVISION and w.m.inspect("t24-crm")["Id"] == NEW
    assert w.m.inspect(OLD)["State"]["Running"] is False
    assert w.m.inspect(NEW)["Config"]["Env"] == author.original()["Config"]["Env"]
    no_original_restart(w)


def test_independent_rows_after_partial_switch_are_preserved_by_forward_recovery(publisher):
    w = publisher; injected = [False]
    def independent_write(args, code):
        if args[0] == "curl" and not injected[0]:
            injected[0] = True
            w.m.rows["finance_canary"].update(count=2, rows_sha256="INDEPENDENT-NEW-ROW")
            w.m.rows[r.NEW_TABLE].update(count=1, rows_sha256="INDEPENDENT-NEW-SPEC")
    w.m.fault = independent_write
    with pytest.raises(RuntimeError, match="ORIGINAL_BUSINESS_ROWS_CHANGED"): w.activate()
    assert w.m.inspect("t24-crm")["Id"] == NEW and w.m.inspect(NEW)["State"]["Running"]
    assert w.m.rows["finance_canary"]["count"] == 2 and w.m.rows[r.NEW_TABLE]["count"] == 1
    no_original_restart(w)


def test_production_baseline_journal_failure_occurs_before_migration_and_resumes_old(publisher):
    w = publisher; write = w.m.write; migrate = []
    def fail(path, value):
        if path.name == "production-baseline-identity.json": raise OSError("SYNTHETIC_FULL_DISK")
        return write(path, value)
    w.m.write = fail; w.run_migration = lambda *args, **kwargs: migrate.append("unexpected")
    with pytest.raises(OSError, match="SYNTHETIC_FULL_DISK"): w.activate()
    assert migrate == [] and w.m.head == r.OLD_REVISION
    assert w.m.inspect("t24-crm")["Id"] == OLD and w.m.inspect(OLD)["State"]["Running"]
    assert not w.m.inspect(NEW)["State"]["Running"]


def test_final_receipt_write_failure_keeps_known_new_application_and_on_worker(publisher):
    w = publisher; write = w.m.write
    def fail(path, value):
        if path.name == "deployed.json": raise OSError("SYNTHETIC_FINAL_RECEIPT_FAILED")
        return write(path, value)
    w.m.write = fail
    with pytest.raises(OSError, match="SYNTHETIC_FINAL_RECEIPT_FAILED"): w.activate()
    assert w.m.head == r.NEW_REVISION and w.m.inspect("t24-crm")["Id"] == NEW
    assert w.m.inspect(NEW)["State"]["Running"] and not w.m.inspect(OLD)["State"]["Running"]
    w.pf.google_environment(w.m.inspect(NEW))
    no_original_restart(w)


def test_unsettled_migration_does_not_resume_old_or_guess_a_new_worker(publisher):
    w = publisher
    def unknown(*args, **kwargs): raise RuntimeError("KNOWN_MIGRATION_STILL_RUNNING")
    w.run_migration = unknown; w.settle_migration = unknown
    with pytest.raises(RuntimeError, match="KNOWN_MIGRATION_STILL_RUNNING"): w.activate()
    assert not w.m.inspect(OLD)["State"]["Running"] and not w.m.inspect(NEW)["State"]["Running"]
    no_original_restart(w)


def test_unknown_primary_is_not_stopped_or_renamed_during_failed_switch(publisher):
    w = publisher; unknown_id = "9" * 64; created = w.m.docker_request
    def collision(*args, **kwargs):
        result = created(*args, **kwargs)
        unknown = copy.deepcopy(author.original()); unknown.update(Id=unknown_id, Name="/t24-crm")
        w.m.items[OLD]["Name"] = "/" + w.old_name
        w.m.items[unknown_id] = unknown
        return result
    w.m.docker_request = collision
    with pytest.raises(RuntimeError, match="UNKNOWN_PRIMARY_CONTAINER"): w.activate()
    assert w.m.items[unknown_id]["State"]["Running"]
    assert not any(unknown_id in call for call in w.m.calls)


def metadata(values, **updates):
    return {"pragma_sha256": "a" * 64, "sequence_exists": True,
        "sequence_values": values, "sequence_sha256": r.digest(sorted(values.items())), **updates}


def test_counter_progress_is_accepted_only_forward_and_never_mutated():
    before, after = metadata({"existing": 1}), metadata({"existing": 2})
    snapshot = copy.deepcopy((before, after)); r.sequence_boundary(before, after, forward=True)
    assert (before, after) == snapshot
    with pytest.raises(RuntimeError): r.sequence_boundary(before, after)


@pytest.mark.parametrize("values", [{"existing": 0}, {}, {"existing": 2, "new": 1},
    {"existing": True}, {"existing": 1.0}, {"existing": -1}, {"existing": "2"}])
def test_forward_counter_regression_key_drift_and_wrong_types_rejected(values):
    with pytest.raises(RuntimeError): r.sequence_boundary(metadata({"existing": 1}), metadata(values), forward=True)


@pytest.mark.parametrize("change", ["pragma", "existence", "hash", "bool_value"])
def test_recovery_does_not_waive_metadata_integrity_or_pragma(change):
    before = metadata({"existing": 1}); after = metadata({"existing": 2})
    if change == "pragma": after["pragma_sha256"] = "b" * 64
    elif change == "existence": after.update(sequence_exists=False, sequence_values={}, sequence_sha256=r.digest([]))
    elif change == "hash": after["sequence_sha256"] = "0" * 64
    else: after.update(sequence_values={"existing": False}, sequence_sha256=r.digest([("existing", False)]))
    with pytest.raises(RuntimeError): r.sequence_boundary(before, after, recovery=True)


def test_recovery_keeps_current_independent_counter_without_restoring_old_value():
    before = metadata({"existing": 3}); after = metadata({"existing": 100, "newly_used_old_table": 1})
    snapshot = copy.deepcopy(after); r.sequence_boundary(before, after, recovery=True)
    assert after == snapshot


def test_reused_migration_primitive_is_persistent_and_rechecks_exact_command():
    # Verify the actual retained implementation being called rather than a
    # second imitation of a successful process. These source contracts are
    # bound by the preflight's existing immutable helper hashes.
    path = HERE.parent / "media-ops-management-20261031/release.py"
    spec = importlib.util.spec_from_file_location("publication_independent_retained_migration", path)
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    code = base.Release.run_migration.__code__
    assert "MIGRATION_CONTAINER_CREATE_FAILED" in code.co_consts
    assert "MIGRATION_WAIT_INCOMPLETE" in code.co_consts
    assert "--rm" in code.co_consts and "create" in code.co_consts
    source = path.read_text()
    section = source.split("    def run_migration", 1)[1].split("    def migrate", 1)[0]
    assert section.index("m.write(path,") < section.index("m.run(['docker','start',identity]")
    assert "known['Image'] == image" in section
    assert "info['Config'].get('Cmd') == ['python','-B','-c',migration_script()]" in source


def actual_migration_seam(w, tmp_path, monkeypatch, fail_directory):
    """Run the real retained create/identity/settle/start/wait implementation."""
    path = HERE.parent / "media-ops-management-20261031/release.py"
    spec = importlib.util.spec_from_file_location("publication_independent_migration_fsync", path)
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    base.OLD_REVISION, base.NEW_REVISION, base.MIGRATION = r.OLD_REVISION, r.NEW_REVISION, r.MIGRATION
    base.migration_script = r.migration_script; w.base = base; w.source = "f" * 40
    data = tmp_path / "production-data"; data.mkdir(); (data / "crm_prod.db").write_bytes(b"SYNTHETIC-INODE-ONLY")
    w.m.BUSINESS = data / "crm_prod.db"
    w.migration_identity = lambda data: base.Release.migration_identity(w, data)
    w.settle_migration = lambda data, required=False: base.Release.settle_migration(w, data, required=required)
    events = []; real_fsync = os.fsync
    def fsync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        events.append("directory-fsync" if directory else "file-fsync")
        if directory and fail_directory: raise OSError("SYNTHETIC_DIRECTORY_FSYNC_FAILED")
        return real_fsync(fd)
    monkeypatch.setattr(r.os, "fsync", fsync)
    def write(path, value):
        body = value if isinstance(value, bytes) else r.encoded(value)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        events.append("identity-file-complete")
        return r.H(body)
    w.m.write = write; original_write = w.m.write
    identity = "6" * 64
    def run(args, code, *timeout):
        if args[:2] == ["docker", "create"]:
            events.append("create")
            assert "--rm" not in args and "--network=none" in args and "--read-only" in args
            values = [args[i+1] for i, arg in enumerate(args) if arg == "-e"]
            assert "T24_GBP_SCHEDULER_ENABLED=false" in values and "T24_GBP_SCHEDULER_ACTIVATION_FROM=" in values
            name = args[args.index("--name") + 1]
            w.m.items[identity] = {"Id": identity, "Image": IMAGE, "Name": "/" + name,
                "Config": {"Env": values, "Cmd": ["python", "-B", "-c", r.migration_script()]},
                "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True},
                "Mounts": [{"Type": "bind", "Source": str(data), "Destination": "/app/backend/data", "RW": True},
                    {"Type": "bind", "Source": str(w.args.release / "probe-logs"), "Destination": "/app/backend/logs", "RW": True},
                    {"Type": "tmpfs", "Destination": "/tmp"}],
                "State": {"Running": False, "Status": "created", "ExitCode": 0}}
            return identity.encode()
        if args[:3] == ["docker", "start", identity]:
            events.append("start"); w.m.items[identity]["State"].update(Running=True, Status="running"); return b""
        if args[:3] == ["docker", "wait", identity]:
            events.append("wait"); w.m.items[identity]["State"].update(Running=False, Status="exited"); return b"0"
        pytest.fail("Unexpected migration command " + repr(args[:2]))
    w.m.run = run
    return data, events, identity, original_write


def test_actual_retained_migration_fsyncs_identity_directory_before_start(publisher, tmp_path, monkeypatch):
    w = publisher; data, events, identity, original_write = actual_migration_seam(w, tmp_path, monkeypatch, False)
    r.Release.run_migration(w, data, IMAGE)
    assert events.index("create") < events.index("file-fsync") < events.index("directory-fsync") < events.index("start") < events.index("wait")
    assert not w.m.items[identity]["State"]["Running"] and w.m.write is original_write
    marker = json.loads((w.args.release / "migration-production-container.json").read_bytes())
    assert marker["id"] == identity and marker["image"] == IMAGE


def test_migration_identity_directory_fsync_failure_never_starts_process(publisher, tmp_path, monkeypatch):
    w = publisher; data, events, identity, original_write = actual_migration_seam(w, tmp_path, monkeypatch, True)
    with pytest.raises(OSError, match="SYNTHETIC_DIRECTORY_FSYNC_FAILED"):
        r.Release.run_migration(w, data, IMAGE)
    assert "create" in events and "file-fsync" in events and "directory-fsync" in events
    assert "start" not in events and "wait" not in events
    assert w.m.items[identity]["State"]["Status"] == "created" and not w.m.items[identity]["State"]["Running"]
    assert w.m.write is original_write
