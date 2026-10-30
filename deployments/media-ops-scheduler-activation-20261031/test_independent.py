"""Independent scheduler guard checks: synthetic memory/SQLite only, no Docker."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scheduler_independent_core", HERE / "core.py")
c = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c
SPEC.loader.exec_module(c)

ORIGINAL = "a" * 64
CANDIDATE = "b" * 64
PLAN = "c" * 64
ATTEMPT = "11111111-1111-4111-8111-111111111111"
CUTOFF = "2026-10-31T02:02:00Z"


def container():
    return {
        "Id": ORIGINAL, "Image": "sha256:" + "d" * 64, "Name": "/t24-crm",
        "Config": {
            "Env": ["PRESERVED=value=with=equals", "T24_GBP_SCHEDULER_ENABLED=false"],
            "Image": "original-tag", "Hostname": "old-host", "Cmd": ["serve"],
        },
        "HostConfig": {"OomKillDisable": False, "AutoRemove": False, "NetworkMode": "host", "Privileged": False},
        "Mounts": [{"Type": "bind", "Source": "/synthetic/data", "Destination": "/app/backend/data", "RW": True}],
        "NetworkSettings": {"Networks": {}},
        "State": {"Running": True, "Status": "running", "StartedAt": "2026-10-31T01:00:00Z"},
        "RestartCount": 0,
    }


def runtime(info):
    """Capture the same configuration dimensions without importing server helpers."""
    return {
        "id": info["Id"], "image": info["Image"], "started": info["State"]["StartedAt"],
        "restart": info["RestartCount"],
        "config": c.digest({key: info[key] for key in ("Config", "HostConfig", "Mounts", "NetworkSettings")}),
    }


def enabled_candidate(original=None):
    original = original or container()
    candidate = copy.deepcopy(original)
    candidate["Id"] = CANDIDATE
    candidate["Config"]["Env"] = ["PRESERVED=value=with=equals", "T24_GBP_SCHEDULER_ENABLED=true", "T24_GBP_SCHEDULER_ACTIVATION_FROM=" + CUTOFF]
    candidate["Config"]["Hostname"] = "new-host"
    candidate["Config"]["Image"] = original["Image"]
    return candidate


@pytest.mark.parametrize("left,right", [(None, None), (False, False), (None, False), (False, None)])
def test_only_exact_none_false_oom_defaults_are_comparison_equivalent(left, right):
    original = container(); candidate = enabled_candidate(original)
    original["HostConfig"]["OomKillDisable"] = left
    candidate["HostConfig"]["OomKillDisable"] = right
    before = copy.deepcopy((original, candidate))
    c.compare(candidate, original, runtime, CUTOFF)
    assert (original, candidate) == before


@pytest.mark.parametrize("bad", [True, 0, 1, "false", [], {}])
@pytest.mark.parametrize("side", ["original", "candidate"])
def test_oom_true_integer_or_coercible_values_never_pass(bad, side):
    original = container(); candidate = enabled_candidate(original)
    (original if side == "original" else candidate)["HostConfig"]["OomKillDisable"] = bad
    with pytest.raises(c.GuardError, match="EXACT_OOM_DEFAULT_REQUIRED"):
        c.compare(candidate, original, runtime, CUTOFF)


@pytest.mark.parametrize("side", ["original", "candidate"])
def test_missing_oom_key_is_rejected(side):
    original = container(); candidate = enabled_candidate(original)
    del (original if side == "original" else candidate)["HostConfig"]["OomKillDisable"]
    with pytest.raises(c.GuardError, match="EXACT_OOM_DEFAULT_REQUIRED"):
        c.compare(candidate, original, runtime, CUTOFF)


@pytest.mark.parametrize("change", ["command", "privilege", "mount", "network", "other_environment"])
def test_two_scheduler_values_do_not_hide_unrelated_configuration_change(change):
    original = container(); candidate = enabled_candidate(original)
    if change == "command": candidate["Config"]["Cmd"] = ["different"]
    if change == "privilege": candidate["HostConfig"]["Privileged"] = True
    if change == "mount": candidate["Mounts"][0]["RW"] = False
    if change == "network": candidate["NetworkSettings"]["Networks"]["unexpected"] = {}
    if change == "other_environment": candidate["Config"]["Env"].append("NEW_OTHER_KEY=changed")
    with pytest.raises(c.GuardError, match="OTHER_RUNTIME_CONFIGURATION_DRIFT|ONLY_TWO_SCHEDULER_VALUES_ALLOWED|ATTACHED_NETWORK_SET_DRIFT"):
        c.compare(candidate, original, runtime, CUTOFF)


def test_clone_preserves_original_and_only_edits_scheduler_environment_values():
    original = container(); before = copy.deepcopy(original)
    result = c.clone(original, CUTOFF, {})
    assert original == before
    assert result["Image"] == original["Image"]
    assert result["HostConfig"] == original["HostConfig"]
    assert result["Env"] == ["PRESERVED=value=with=equals", "T24_GBP_SCHEDULER_ENABLED=true", "T24_GBP_SCHEDULER_ACTIVATION_FROM=" + CUTOFF]
    result["HostConfig"]["Privileged"] = True
    assert original == before


@pytest.mark.parametrize("ipam", [{"IPv4Address": "192.0.2.25"}, {"IPv6Address": "2001:db8::25"}, {"LinkLocalIPs": ["169.254.1.25"]}])
def test_clone_rejects_explicit_network_configuration_legacy_clone_would_drop(ipam):
    original = container()
    original["HostConfig"]["NetworkMode"] = "synthetic-app-network"
    original["NetworkSettings"]["Networks"] = {"synthetic-app-network": {"Aliases": ["t24-crm"], "IPAMConfig": ipam}}
    legacy_clone_networks = {"synthetic-app-network": {"Aliases": ["t24-crm"]}}
    with pytest.raises(c.GuardError):
        c.clone(original, CUTOFF, legacy_clone_networks)


@pytest.mark.parametrize("value", ["2026-10-31T02:02:00+00:00", "2026-10-31T02:02:00", "2026-10-31T02:02:00.000Z", "2026-10-31 02:02:00Z", "2026-10-31T02:02:00z", None])
def test_cutoff_is_exact_fixed_utc_seconds(value):
    with pytest.raises(c.GuardError, match="FIXED_UTC_CUTOFF_REQUIRED"):
        c.cutoff(value)


@pytest.mark.parametrize("confirmed", [False, None, 0, 1, "true"])
def test_activation_confirmation_must_be_boolean_true_before_any_action(confirmed):
    workflow = object.__new__(c.Workflow)
    workflow.read_plan = lambda _: pytest.fail("read plan before explicit confirmation")
    with pytest.raises(c.GuardError, match="EXPLICIT_SCHEDULER_CONFIRMATION_REQUIRED"):
        workflow.activate(PLAN, confirmed)


@pytest.mark.parametrize("field,value", [
    ("stage", "MEDIA_OPS_MANAGEMENT_PREPARED"),
    ("stage", "MEDIA_OPS_MANAGEMENT_FORWARD_RECOVERY_REQUIRED"),
    ("deployed", False), ("deployed", 1),
    ("source_sha", "0" * 40), ("frontend_version", "0" * 12),
    ("schema_revision", "old-revision"),
    ("scheduler_disabled", False), ("existing_google_environment_preserved", False),
])
def test_constructor_requires_actual_verified_deployment_receipt_and_all_pins(monkeypatch, field, value):
    receipt = {
        "stage": "MEDIA_OPS_MANAGEMENT_DEPLOYED_VERIFIED", "deployed": True,
        "source_sha": c.SOURCE, "frontend_version": c.FRONTEND, "schema_revision": c.REVISION,
        "scheduler_disabled": True, "existing_google_environment_preserved": True,
    }
    receipt[field] = value
    monkeypatch.setattr(c, "load", lambda *_: SimpleNamespace())
    monkeypatch.setattr(c, "read", lambda *_: c.encoded(receipt))
    with pytest.raises(c.GuardError, match="EXACT_DEPLOYED_RELEASE_REQUIRED"):
        c.Workflow(ATTEMPT, c.DEPLOYED_SHA, 1)


def test_wrong_deployed_receipt_hash_is_rejected_before_loading_server_helpers(monkeypatch):
    monkeypatch.setattr(c, "load", lambda *_: pytest.fail("loaded server helper for wrong receipt"))
    with pytest.raises(c.GuardError, match="EXACT_RECEIPT_AND_OWNER_REQUIRED"):
        c.Workflow(ATTEMPT, "e" * 64, 1)


@pytest.mark.parametrize("field,value", [("id", "0" * 64), ("image", "sha256:" + "0" * 64)])
def test_exact_actual_deployed_container_and_image_pins_are_required(monkeypatch, field, value):
    receipt = {
        "stage": "MEDIA_OPS_MANAGEMENT_DEPLOYED_VERIFIED", "deployed": True,
        "source_sha": c.SOURCE, "frontend_version": c.FRONTEND, "schema_revision": c.REVISION,
        "scheduler_disabled": True, "existing_google_environment_preserved": True,
        "crm": {"id": c.ORIGINAL_ID, "image": c.IMAGE},
    }
    receipt["crm"][field] = value
    monkeypatch.setattr(c, "load", lambda *_: SimpleNamespace())
    monkeypatch.setattr(c, "read", lambda *_: c.encoded(receipt))
    with pytest.raises(c.GuardError, match="EXACT_DEPLOYED_CONTAINER_IMAGE_REQUIRED"):
        c.Workflow(ATTEMPT, c.DEPLOYED_SHA, 1)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public_mode", "wrong_hash", "oversize"])
def test_protected_read_rejects_unsafe_artifact_or_changed_bytes(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(c, "directory", lambda _: None)
    monkeypatch.setattr(c, "FILE_OWNER", os.getuid())
    source = tmp_path / "synthetic.json"; source.write_bytes(b"SYNTHETIC_ARTIFACT"); source.chmod(0o600)
    path = source; expected = None; maximum = 1024
    if kind == "symlink":
        path = tmp_path / "linked.json"; path.symlink_to(source)
    if kind == "hardlink": os.link(source, tmp_path / "second-link.json")
    if kind == "public_mode": source.chmod(0o644)
    if kind == "wrong_hash": expected = "0" * 64
    if kind == "oversize": maximum = 2
    with pytest.raises(c.GuardError): c.read(path, expected, maximum)
    assert source.read_bytes() == b"SYNTHETIC_ARTIFACT"


def test_artifact_writer_is_exclusive_and_does_not_follow_links(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "directory", lambda _: None)
    monkeypatch.setattr(c, "FILE_OWNER", os.getuid())
    path = tmp_path / "record.json"
    sha = c.write(path, {"synthetic": "only"})
    original = path.read_bytes()
    assert sha == c.H(original) and path.stat().st_mode & 0o777 == 0o600
    assert c.read(path, sha) == original
    with pytest.raises(FileExistsError): c.write(path, {"changed": True})
    linked = tmp_path / "linked.json"; linked.symlink_to(path)
    with pytest.raises(FileExistsError): c.write(linked, {"changed": True})
    assert path.read_bytes() == original


def synthetic_db(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE alembic_version(version_num TEXT);
            CREATE TABLE google_business_schedules(id INTEGER);
            CREATE TABLE employees(id INTEGER,role TEXT,status TEXT);
            CREATE TABLE google_business_connections(id INTEGER,owner_id INTEGER,active INTEGER,needs_reconnect INTEGER,token_encrypted TEXT);
        """)
        con.execute("INSERT INTO alembic_version VALUES(?)", (c.REVISION,))
        con.execute("INSERT INTO employees VALUES(1,'super_admin','active')")
        con.execute("INSERT INTO google_business_connections VALUES(1,1,1,0,'SYNTHETIC_ENCRYPTED_TOKEN')")


def test_oauth_queue_read_is_read_only_and_owner_bound(tmp_path):
    path = tmp_path / "synthetic.db"; synthetic_db(path)
    before = path.read_bytes()
    assert c.oauth_and_queue(SimpleNamespace(BUSINESS=path), 1)["active_owner_google_connections"] == 1
    assert path.read_bytes() == before
    with sqlite3.connect(path) as con:
        con.execute("UPDATE google_business_connections SET owner_id=2")
    with pytest.raises(c.GuardError, match="EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED"):
        c.oauth_and_queue(SimpleNamespace(BUSINESS=path), 1)


@pytest.mark.parametrize("mutation,code", [
    ("INSERT INTO google_business_schedules VALUES(9)", "FIRST_ENABLE_REQUIRES_EMPTY_QUEUE"),
    ("UPDATE employees SET role='manager'", "ACTIVE_OWNER_REQUIRED"),
    ("UPDATE employees SET status='inactive'", "ACTIVE_OWNER_REQUIRED"),
    ("UPDATE google_business_connections SET active=0", "EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED"),
    ("UPDATE google_business_connections SET needs_reconnect=1", "EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED"),
    ("UPDATE google_business_connections SET token_encrypted=''", "EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED"),
    ("UPDATE google_business_connections SET token_encrypted=NULL", "EXISTING_OWNER_GOOGLE_CONNECTION_REQUIRED"),
])
def test_queue_or_owner_connection_drift_is_rejected(tmp_path, mutation, code):
    path = tmp_path / "synthetic.db"; synthetic_db(path)
    with sqlite3.connect(path) as con: con.execute(mutation)
    with pytest.raises(c.GuardError, match=code):
        c.oauth_and_queue(SimpleNamespace(BUSINESS=path), 1)


class DockerMemory:
    """Model exact identities and commands without an external process/socket."""
    runtime = staticmethod(runtime)

    def __init__(self, original):
        self.items = {ORIGINAL: copy.deepcopy(original)}; self.commands = []

    def retained(self): return self
    def clone_networks(self, _): return {}
    def inspect(self, name):
        found = self.inspect_optional(name)
        if found is None: raise c.GuardError("SYNTHETIC_CONTAINER_MISSING")
        return found
    def inspect_optional(self, name):
        for identity, item in self.items.items():
            if name == identity or item["Name"] == "/" + name: return copy.deepcopy(item)
        return None
    def docker_request(self, method, path, config):
        assert method == "POST" and path.startswith("/containers/create?name=")
        candidate = enabled_candidate(self.items[ORIGINAL])
        candidate["Name"] = "/" + path.split("=", 1)[1]
        candidate["Config"] = {key: copy.deepcopy(value) for key, value in config.items() if key not in {"HostConfig", "NetworkingConfig"}}
        candidate["State"] = {"Running": False, "Status": "created", "StartedAt": "0001-01-01T00:00:00Z"}
        self.items[CANDIDATE] = candidate
        return 201, json.dumps({"Id": CANDIDATE}).encode()
    def run(self, args, _code, *_timeout):
        self.commands.append(args)
        if args[1] == "stop": self.items[args[-1]]["State"].update(Running=False, Status="exited")
        if args[1] == "rename": self.items[args[2]]["Name"] = "/" + args[3]
        if args[1] == "start": self.items[args[2]]["State"].update(Running=True, Status="running", StartedAt="2026-10-31T02:00:01Z")
        if args[1] == "exec": return b"SCHEDULER_CONFIG_NO_NETWORK_VERIFIED"
        return b""
    def ready(self, _): pass
    def verify_secret_mount(self, _): pass


def test_expired_during_final_fresh_check_never_starts_executor(tmp_path, monkeypatch):
    original = container(); memory = DockerMemory(original)
    clock = [datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(c, "now", lambda: clock[0])
    monkeypatch.setattr(c, "write", lambda path, value: c.digest(value))
    workflow = object.__new__(c.Workflow)
    workflow.attempt = ATTEMPT; workflow.path = tmp_path; workflow.owner = 1
    workflow.m = memory; workflow.receipt_sha = "e" * 64
    workflow.original_name = "synthetic-original-off"; workflow.candidate_name = "synthetic-candidate-on"
    facts = {"queue": "empty"}; rows = {"unchanged": True}
    plan = {"facts": facts, "rows": rows, "crm": memory.runtime(original)}
    workflow.read_plan = lambda _: plan
    workflow.initial = lambda: (copy.deepcopy(original), copy.deepcopy(facts), copy.deepcopy(rows))
    reads = [0]
    def boundary(**_):
        reads[0] += 1
        if reads[0] == 3: clock[0] += timedelta(seconds=121)
        return copy.deepcopy(facts)
    workflow.boundary = boundary; workflow.rows = lambda: copy.deepcopy(rows)
    workflow.source = lambda _: None; workflow.rollback = lambda _: None
    with pytest.raises(c.GuardError): workflow.activate(PLAN, True)
    assert not any(command[:2] == ["docker", "start"] and command[2] == CANDIDATE for command in memory.commands)


def test_rollback_contains_known_running_candidate_before_protection_drift_rejection(tmp_path, monkeypatch):
    original = container(); memory = DockerMemory(original)
    memory.items[ORIGINAL]["Name"] = "/synthetic-original-off"
    memory.items[ORIGINAL]["State"].update(Running=False, Status="exited")
    memory.items[CANDIDATE] = enabled_candidate(original)
    workflow = object.__new__(c.Workflow)
    workflow.path = tmp_path; workflow.m = memory; workflow.attempt = ATTEMPT
    workflow.original_name = "synthetic-original-off"; workflow.candidate_name = "synthetic-candidate-on"
    workflow.read_plan = lambda _: {"crm": runtime(original), "facts": {"metadata": "original", "oauth": "empty"}}
    workflow.boundary = lambda **_: {"metadata": "drifted"}
    workflow.source = lambda _: None
    state = {"stage": "SCHEDULER_SWITCH_INTENT", "source_sha": c.SOURCE, "attempt": ATTEMPT, "original_sha256": c.H(c.encoded(original)), "activation_from": CUTOFF, "original_id": ORIGINAL, "candidate_id": CANDIDATE, "candidate_name": workflow.candidate_name, "image": original["Image"], "plan_sha256": PLAN, "tool_sha256": c.tool_hash()}
    def read(path, *_args, **_kwargs):
        return c.encoded(original if path.name == "original-container.json" else state)
    monkeypatch.setattr(c, "read", read)
    with pytest.raises(c.GuardError, match="ROLLBACK_PROTECTION_DRIFT"):
        workflow.rollback(PLAN)
    assert memory.inspect(CANDIDATE)["State"]["Running"] is False
    assert not any(command[:2] == ["docker", "start"] for command in memory.commands)


def test_rollback_saved_original_is_bound_to_reviewed_plan_before_restart(tmp_path, monkeypatch):
    reviewed = container(); saved = copy.deepcopy(reviewed)
    saved["HostConfig"]["Privileged"] = True
    memory = DockerMemory(saved)
    memory.items[ORIGINAL]["Name"] = "/synthetic-original-off"
    memory.items[ORIGINAL]["State"].update(Running=False, Status="exited")
    memory.items[CANDIDATE] = enabled_candidate(reviewed)
    workflow = object.__new__(c.Workflow)
    workflow.path = tmp_path; workflow.m = memory; workflow.attempt = ATTEMPT
    workflow.original_name = "synthetic-original-off"; workflow.candidate_name = "synthetic-candidate-on"
    facts = {"metadata": "unchanged"}
    workflow.read_plan = lambda _: {"crm": runtime(reviewed), "facts": facts}
    workflow.boundary = lambda **_: copy.deepcopy(facts)
    workflow.source = lambda _: None
    state = {"stage": "SCHEDULER_SWITCH_INTENT", "source_sha": c.SOURCE, "attempt": ATTEMPT, "original_sha256": c.H(c.encoded(saved)), "original_id": ORIGINAL, "candidate_id": CANDIDATE, "candidate_name": workflow.candidate_name, "image": reviewed["Image"], "plan_sha256": PLAN, "activation_from": CUTOFF, "tool_sha256": c.tool_hash()}
    monkeypatch.setattr(c, "read", lambda path, *_args, **_kwargs: c.encoded(saved if path.name == "original-container.json" else state))
    monkeypatch.setattr(c, "write", lambda path, value: c.digest(value))
    with pytest.raises(c.GuardError): workflow.rollback(PLAN)
    assert memory.inspect(CANDIDATE)["State"]["Running"] is False
    assert not any(command[:2] == ["docker", "start"] for command in memory.commands)


def test_global_activation_lock_rejects_second_dispatch_before_workflow_construction(tmp_path, monkeypatch):
    root = tmp_path / "locks"; constructions = []
    monkeypatch.setattr(c, "ROOT", root)
    monkeypatch.setattr(c, "guard", lambda: None)
    monkeypatch.setattr(c, "mkdir", lambda path: path.mkdir(exist_ok=True, mode=0o700))
    monkeypatch.setattr(c, "read", lambda *_args, **_kwargs: b"")
    class SyntheticWorkflow:
        def __init__(self, *args): constructions.append(args)
        def plan(self):
            with pytest.raises(BlockingIOError):
                c.dispatch("plan", ATTEMPT, "e" * 64, 1)
            return {"lock": "exclusive"}
    monkeypatch.setattr(c, "Workflow", SyntheticWorkflow)
    assert c.dispatch("plan", ATTEMPT, "e" * 64, 1) == {"lock": "exclusive"}
    assert len(constructions) == 1


@pytest.mark.parametrize("drift", ["stopped", "renamed"])
def test_final_receipt_rejects_candidate_losing_live_primary_role(tmp_path, monkeypatch, drift):
    original = container(); memory = DockerMemory(original)
    monkeypatch.setattr(c, "now", lambda: datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(c, "write", lambda path, value: c.digest(value))
    workflow = object.__new__(c.Workflow)
    workflow.attempt = ATTEMPT; workflow.path = tmp_path; workflow.owner = 1
    workflow.m = memory; workflow.receipt_sha = "e" * 64
    workflow.original_name = "synthetic-original-off"; workflow.candidate_name = "synthetic-candidate-on"
    facts = {"queue": "empty"}; rows = {"unchanged": True}
    plan = {"facts": facts, "rows": rows, "crm": memory.runtime(original)}
    workflow.read_plan = lambda _: plan
    workflow.initial = lambda: (copy.deepcopy(original), copy.deepcopy(facts), copy.deepcopy(rows))
    workflow.boundary = lambda **_: copy.deepcopy(facts)
    workflow.rows = lambda: copy.deepcopy(rows)
    workflow.source = lambda _: None; workflow.rollback = lambda _: None
    run = memory.run
    def after_probe(args, code, *timeout):
        output = run(args, code, *timeout)
        if args[:2] == ["docker", "exec"]:
            if drift == "stopped": memory.items[CANDIDATE]["State"].update(Running=False, Status="exited")
            if drift == "renamed": memory.items[CANDIDATE]["Name"] = "/" + workflow.candidate_name
        return output
    memory.run = after_probe
    with pytest.raises(c.GuardError): workflow.activate(PLAN, True)
