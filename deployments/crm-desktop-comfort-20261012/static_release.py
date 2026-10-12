#!/usr/bin/env python3
"""Publish only frozen CRM desktop assets. Never mutate a database/container.

prepare validates the current authenticated receipt and extracts a new protected
static payload. activate requires its independently reviewed receipt hash, keeps
old hashed assets and CAS-replaces one Nginx root. Recovery restores only that
root; legitimate concurrent financial records are never compared or restored.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import sys
import tarfile

HOST = "iZj6c4cj7edgnhdimts4l7Z"
PERSONAL_RELEASE = Path("/opt/t24-crm/releases/personal-finance-1a9232dcc04a-20261012-retry2")
PERSONAL_HELPER_SHA = "a3d63f63a6c2b0483469c27a488f7c115848e63a603ad3f5fbdc92c16b382d16"
BASELINE_SOURCE = "9d10d98fff6779fd9e6bace22a761fa7b4c8b45f"
BASELINE_VERSION = "22b2d2ad92c2"
ALLOWED_SOURCE_FILES = frozenset("app/frontend/src/" + name for name in (
    "components/Layout.tsx", "pages/Dashboard.tsx", "pages/Customers.tsx",
    "pages/OperationsWorkbench.tsx", "components/crm-desktop-layout.css"))
HASH = re.compile(r"[a-f0-9]{64}")
SOURCE = re.compile(r"[a-f0-9]{40}")
VERSION = re.compile(r"[a-f0-9]{12}")
SUFFIXES = {".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".ico", ".txt", ".woff", ".woff2", ".ttf", ".webmanifest"}


class StaticError(RuntimeError):
    pass


def need(value, code):
    if not value:
        raise StaticError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def stamp(info):
    # Reading may update atime. Identity and every mutation stamp remain bound.
    return tuple(getattr(info, name) for name in ("st_dev", "st_ino", "st_uid", "st_gid",
        "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def protected(path, directory=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, "CANONICAL_PROTECTED_PATH_REQUIRED")
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
             "PROTECTED_ANCESTOR_REQUIRED")
    info = path.lstat()
    need(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
         "ROOT_PRIVATE_FILE_OR_DIRECTORY_REQUIRED")
    return info


def read(path, maximum=4 * 1024**2):
    before = protected(path)
    need(before.st_size <= maximum, "PROTECTED_SIZE_LIMIT")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        need(stamp(os.fstat(stream.fileno())) == stamp(before), "PROTECTED_FILE_IDENTITY_DRIFT")
        data = stream.read(maximum + 1)
    need(len(data) <= maximum and stamp(protected(path)) == stamp(before), "PROTECTED_FILE_CHANGED")
    return data


def fixed_json(path, expected):
    need(HASH.fullmatch(expected or ""), "INDEPENDENT_RECEIPT_HASH_REQUIRED")
    data = read(path)
    need(sha(data) == expected, "REVIEWED_RECEIPT_HASH_DRIFT")
    value = json.loads(data)
    need(isinstance(value, dict), "OBJECT_RECEIPT_REQUIRED")
    return value


def retained_tools():
    path = PERSONAL_RELEASE / "release.py"
    blob = read(path, 1024**2)
    need(sha(blob) == PERSONAL_HELPER_SHA, "ACCEPTED_PERSONAL_HELPER_HASH_DRIFT")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_loader("_crm_static_personal_primitives", loader=None)
    personal = importlib.util.module_from_spec(spec)
    personal.__file__ = str(path)
    exec(compile(blob, str(path), "exec"), personal.__dict__)
    need(personal.HOST == HOST and personal.RELEASE == PERSONAL_RELEASE,
         "EXACT_PERSONAL_PRIMITIVES_REQUIRED")
    upgrade = personal.load_legacy("upgrade.py")
    base, _nav, preparation, switch = upgrade.retained_tools(personal.LEGACY)
    return personal, upgrade, base, preparation, switch


def canonical_name(name, *, allow_hidden=False):
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    return name == path.as_posix() and not path.is_absolute() and ".." not in path.parts \
        and (allow_hidden or not any(part.startswith(".") for part in path.parts))


def hash_inventory(value, *, allow_hidden=False):
    return isinstance(value, dict) and bool(value) and all(isinstance(name, str) and canonical_name(name, allow_hidden=allow_hidden)
        and isinstance(fingerprint, str) and HASH.fullmatch(fingerprint) for name, fingerprint in value.items())


def checked_manifest(value, payload_sha):
    need(value.get("format_version") == 1 and value.get("stage") == "CRM_DESKTOP_COMFORT_STATIC_PAYLOAD_PREPARED"
         and SOURCE.fullmatch(value.get("source_sha", "")) and value["source_sha"] != BASELINE_SOURCE
         and value.get("baseline_source_sha") == BASELINE_SOURCE
         and value.get("baseline_frontend_version") == BASELINE_VERSION
         and VERSION.fullmatch(value.get("frontend_version", "")) and value["frontend_version"] != BASELINE_VERSION,
         "FROZEN_CRM_DESKTOP_SOURCE_REQUIRED")
    need(value.get("static_only") is True and all(value.get(key) is False for key in (
         "backend_changes", "credentials_included", "databases_modified", "services_modified", "environment_modified")),
         "PURE_STATIC_SCOPE_REQUIRED")
    changed = value.get("changed_source_files")
    need(hash_inventory(changed) and set(changed) == ALLOWED_SOURCE_FILES, "EXACT_FIVE_CRM_LAYOUT_SOURCE_FILES_REQUIRED")
    kept = value.get("preserved_source_inventories", {})
    # Metadata includes every tracked source file, including .gitignore. Such
    # names are never extracted; deployable static members stay hidden-free.
    need(set(kept) == {"backend", "private_frontend"} and all(hash_inventory(row, allow_hidden=True) for row in kept.values())
         and all(name.startswith("app/backend/") for name in kept["backend"])
         and all(name.startswith("app/frontend/src/") for name in kept["private_frontend"])
         and not any(set(row) & ALLOWED_SOURCE_FILES for row in kept.values()),
         "UNCHANGED_BACKEND_AND_PRIVATE_SOURCE_PROOF_REQUIRED")
    files = value.get("payload_files")
    need(hash_inventory(files) and 2 <= len(files) < 10000
         and {"index.html", "app-version.json"} <= set(files), "COMPLETE_STATIC_INVENTORY_REQUIRED")
    need(all(PurePosixPath(name).suffix in SUFFIXES and (not name.endswith(".html")
         or name in {"index.html", "offline.html"}) for name in files), "STATIC_FILE_SCOPE_REJECTED")
    need(HASH.fullmatch(payload_sha or "") and value.get("payload_sha256") == payload_sha,
         "INDEPENDENT_STATIC_PAYLOAD_HASH_REQUIRED")
    return value


def checked_preflight(value, personal):
    need(value.get("stage") == "CRM_DESKTOP_COMFORT_AUTHENTICATED_READONLY_PREFLIGHT"
         and value.get("host") == HOST and value.get("mutation_performed") is False
         and value.get("frontend_version") == BASELINE_VERSION,
         "FRESH_AUTHENTICATED_PREFLIGHT_REQUIRED")
    need(value.get("backend_source_sha") == personal.SOURCE and set(value.get("roles", {})) == {"crm", "api", "worker"}
         and set(value["databases"]["private"]["tables"]) == personal.TARGET_TABLES
         and len(value["databases"]["business"]["tables"]) == 83,
         "CURRENT_TWENTY_PRIVATE_EIGHTYTHREE_CRM_BASE_REQUIRED")
    need(HASH.fullmatch(value.get("nginx_sha256", "")) and HASH.fullmatch(value.get("environment_sha256", ""))
         and value.get("public_root") == "/var/www/t24-crm-public/personal-finance-1a9232dcc04a-20261012",
         "CURRENT_PERSONAL_STATIC_BASE_REQUIRED")
    for role in ("api", "worker"):
        row = value["roles"][role]
        need(HASH.fullmatch(row.get("id", "")) and re.fullmatch(r"sha256:[a-f0-9]{64}", row.get("image", ""))
             and row.get("source") == personal.SOURCE and re.fullmatch(r"[a-f0-9]{32}", row.get("attempt", ""))
             and row.get("runtime", {}).get("id") == row["id"], "EXACT_CURRENT_PRIVATE_ROLES_REQUIRED")
    receipt_pin = value.get("personal_release_receipt", {})
    need(receipt_pin.get("path") == str(PERSONAL_RELEASE / "upgrade-state.json")
         and HASH.fullmatch(receipt_pin.get("sha256", "")), "ACCEPTED_PERSONAL_RELEASE_RECEIPT_REQUIRED")
    receipt = fixed_json(Path(receipt_pin["path"]), receipt_pin["sha256"])
    need(receipt.get("phase") == "PERSONAL_FINANCE_DEPLOYED_VERIFIED" and receipt.get("deployed") is True
         and receipt.get("public_root") == value["public_root"] and receipt.get("new_nginx_sha256") == value["nginx_sha256"]
         and all(row["image"] == receipt.get("candidate_image") and row["attempt"] == receipt.get("attempt")
             and row["runtime"] == receipt["roles"][role]["runtime"]
             for role, row in value["roles"].items() if role != "crm"), "ACCEPTED_PERSONAL_RUNTIME_LINEAGE_DRIFT")
    return value


def stable_database(value):
    # release_snapshot includes scalar receipt metadata alongside the two DBs.
    # Only named database sections participate in the runtime/DDL comparison.
    need(isinstance(value, dict) and all(isinstance(value.get(name), dict) for name in ("business", "private")),
         "BUSINESS_AND_PRIVATE_DATABASE_SNAPSHOTS_REQUIRED")
    for name in ("business", "private"):
        row = value[name]
        need(isinstance(row.get("identity"), dict) and bool(row["identity"])
             and isinstance(row.get("schema_objects"), dict) and bool(row["schema_objects"])
             and isinstance(row.get("schema_sha256"), str) and HASH.fullmatch(row["schema_sha256"])
             and isinstance(row.get("tables"), dict) and bool(row["tables"])
             and all(isinstance(entry, dict) and isinstance(entry.get("columns_sha256"), str)
                 and HASH.fullmatch(entry["columns_sha256"]) for entry in row["tables"].values()),
             "VALID_DATABASE_IDENTITY_AND_DDL_PROOF_REQUIRED")
    return {name: {"identity": row["identity"], "schema_objects": row["schema_objects"],
        "schema_sha256": row["schema_sha256"], "table_columns": {
            table: entry["columns_sha256"] for table, entry in row["tables"].items()}}
        for name in ("business", "private") for row in (value[name],)}


def database_stats(base):
    result = {}
    for label, path in (("business", base.BUSINESS), ("private", base.PRIVATE_DB)):
        info = path.lstat()
        need(path.resolve() == path and stat.S_ISREG(info.st_mode) and info.st_uid == 0
             and info.st_nlink == 1 and not info.st_mode & 0o022, "LIVE_DATABASE_PATH_UNTRUSTED")
        result[label] = {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns}
    return result


def boundary(personal, upgrade, base, preparation, switch, pins):
    need(base.crm_check() == pins["roles"]["crm"] and sha(read(base.ENV)) == pins["environment_sha256"],
         "CRM_RUNTIME_OR_ORIGINAL_ENVIRONMENT_CHANGED")
    for field, path in (("private_database", base.PRIVATE_DB), ("business_database", base.BUSINESS),
                        ("nginx_path", base.NGINX), ("runtime_env_path", base.ENV)):
        need(str(path) == pins[field], "EXACT_REVIEWED_LIVE_PATHS_REQUIRED")
    role_pins = {"roles": {role: pins["roles"][role] for role in ("api", "worker")}}
    personal.old_roles(base, switch, upgrade, role_pins, running=True)
    snapshot = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(stable_database(snapshot) == stable_database(pins["databases"]), "LIVE_SCHEMA_OR_DATABASE_IDENTITY_DRIFT")
    return {"runtime": {"crm": base.crm_check(), "roles": pins["roles"],
        "environment_sha256": sha(read(base.ENV))}, "databases": stable_database(snapshot),
        "database_stats": database_stats(base)}


def stable_boundary(value):
    # The services remain live; owner/provider writes may legitimately update data.
    # We prove identical runtime, identity and DDL without claiming row immutability.
    stats = {key: {name: row[name] for name in ("device", "inode", "mode", "uid", "gid")}
        for key, row in value["database_stats"].items()}
    return {"runtime": value["runtime"], "databases": value["databases"], "database_identity_mode": stats}


def extract_payload(personal, base, release, manifest, archive):
    need(sha(archive) == manifest["payload_sha256"], "STATIC_PAYLOAD_HASH_DRIFT")
    root = release / "payload"
    need(not root.exists() and not root.is_symlink(), "FRESH_STATIC_PAYLOAD_REQUIRED")
    root.mkdir(mode=0o700)
    actual, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        for member in stream:
            need(member.isfile() and not member.pax_headers and member.name.startswith("payload/"),
                 "REGULAR_STATIC_MEMBER_REQUIRED")
            name = member.name.removeprefix("payload/")
            need(canonical_name(name) and name in manifest["payload_files"] and name not in actual
                 and 0 <= member.size <= 16 * 1024**2, "STATIC_ARCHIVE_SCOPE_REJECTED")
            total += member.size
            need(total <= 64 * 1024**2, "STATIC_ARCHIVE_TOTAL_SIZE_LIMIT")
            handle = stream.extractfile(member)
            need(handle is not None, "STATIC_MEMBER_STREAM_REQUIRED")
            data = handle.read(member.size + 1)
            need(len(data) == member.size and sha(data) == manifest["payload_files"][name], "STATIC_MEMBER_HASH_DRIFT")
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            personal.write_new(destination, data)
            actual[name] = sha(data)
    need(actual == manifest["payload_files"] == base.file_map(root), "COMPLETE_STATIC_PAYLOAD_REQUIRED")
    need(json.loads(read(root / "app-version.json", 4096)) == {"version": manifest["frontend_version"]},
         "FROZEN_STATIC_VERSION_REQUIRED")
    return root


def payload_check(base, release, manifest):
    root = release / "payload"
    protected(root, True)
    need(base.file_map(root) == manifest["payload_files"], "PREPARED_STATIC_BYTES_DRIFT")
    for name, expected in manifest["payload_files"].items():
        need(sha(read(root / name, 16 * 1024**2)) == expected, "PREPARED_STATIC_FILE_DRIFT")
    return root


@contextmanager
def release_lock(base):
    path = base.CONFIG / "private-finance-release.lock"
    before = protected(path)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        need(stamp(os.fstat(descriptor)) == stamp(before), "RELEASE_LOCK_IDENTITY_DRIFT")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(stamp(protected(path)) == stamp(before), "RELEASE_LOCK_REBOUND")
        yield
    finally:
        os.close(descriptor)


def public_root(release, manifest):
    name = "crm-desktop-comfort-" + manifest["source_sha"][:12] + "-20261012"
    need(release in {Path("/opt/t24-crm/releases") / name, Path("/opt/t24-crm/releases") / (name + "-retry2")},
         "EXACT_NEW_RELEASE_PATH_REQUIRED")
    return Path("/var/www/t24-crm-public") / release.name


def prepare(args, personal, upgrade, base, preparation, switch, manifest, pins):
    release = args.release
    target = public_root(release, manifest)
    need(not target.exists() and not target.is_symlink(), "FRESH_PUBLIC_ROOT_REQUIRED")
    original = base.read_nginx()
    need(sha(original) == pins["nginx_sha256"], "CURRENT_NGINX_BASE_DRIFT")
    before = boundary(personal, upgrade, base, preparation, switch, pins)
    old = Path(pins["public_root"])
    old_files = base.file_map(old)
    base.public_check(old_files, BASELINE_VERSION, old, verify_services=False)
    personal.authentication_probe(public=True)
    archive = read(release / "static-payload.tar.gz", 64 * 1024**2)
    extract_payload(personal, base, release, manifest, archive)
    after = boundary(personal, upgrade, base, preparation, switch, pins)
    need(stable_boundary(before) == stable_boundary(after) and base.read_nginx() == original
         and base.file_map(old) == old_files, "PREPARATION_BOUNDARY_DRIFT")
    receipt = {"format_version": 1, "stage": "CRM_DESKTOP_COMFORT_STATIC_PREPARED", "source_sha": manifest["source_sha"],
        "frontend_version": manifest["frontend_version"], "manifest_sha256": args.manifest_sha256,
        "payload_sha256": args.payload_sha256, "preflight_sha256": args.preflight_sha256,
        "personal_helper_sha256": PERSONAL_HELPER_SHA, "public_root": str(target), "old_public_root": str(old),
        "old_public_files": old_files, "old_nginx_sha256": sha(original), "boundary": before,
        "deployed": False, "database_mutation_performed": False, "services_modified": False,
        "environment_modified": False, "private_source_unchanged": True, "backend_source_unchanged": True}
    receipt_sha = personal.save(release / "prepared.json", receipt)
    return {"stage": receipt["stage"], "source_sha": manifest["source_sha"], "frontend_version": manifest["frontend_version"],
        "prepared_sha256": receipt_sha, "private_tables": 20, "business_tables": 83, "deployed": False}


def checked_prepared(value, args, manifest):
    need(value.get("stage") == "CRM_DESKTOP_COMFORT_STATIC_PREPARED" and value.get("format_version") == 1
         and value.get("source_sha") == manifest["source_sha"] and value.get("frontend_version") == manifest["frontend_version"]
         and value.get("manifest_sha256") == args.manifest_sha256 and value.get("payload_sha256") == args.payload_sha256
         and value.get("preflight_sha256") == args.preflight_sha256
         and value.get("personal_helper_sha256") == PERSONAL_HELPER_SHA
         and value.get("public_root") == str(public_root(args.release, manifest))
         and value.get("old_public_root") == "/var/www/t24-crm-public/personal-finance-1a9232dcc04a-20261012"
         and HASH.fullmatch(value.get("old_nginx_sha256", "")) and hash_inventory(value.get("old_public_files"))
         and all(value.get(key) is False for key in ("deployed", "database_mutation_performed", "services_modified", "environment_modified"))
         and value.get("private_source_unchanged") is True and value.get("backend_source_unchanged") is True,
         "EXACT_INDEPENDENT_PREPARED_RECEIPT_REQUIRED")
    return value


def rollback(base, original, changed, old, old_files):
    current = sha(base.read_nginx())
    need(current in {sha(original), sha(changed)}, "STATIC_ROLLBACK_CONCURRENT_NGINX_CHANGE")
    if current == sha(changed):
        base.atomic_nginx(original, {sha(changed)})
        base.run(["nginx", "-t"], "ROLLBACK_NGINX_TEST_FAILED")
        base.run(["systemctl", "reload", "nginx"], "ROLLBACK_NGINX_RELOAD_FAILED")
    need(base.read_nginx() == original and base.file_map(old) == old_files, "STATIC_ROLLBACK_BYTES_DRIFT")
    base.public_check(old_files, BASELINE_VERSION, old, verify_services=False)


def safe_error(error):
    accepted = isinstance(error, StaticError) or type(error).__name__ in {
        "ReleaseError", "UpgradeError", "SwitchError", "GuardError", "TransferError", "PrepareError"}
    return str(error) if accepted and re.fullmatch(r"[A-Z0-9_]{1,100}", str(error)) else "STATIC_RELEASE_REJECTED"


def activate(args, personal, upgrade, base, preparation, switch, manifest, pins):
    prepared = checked_prepared(fixed_json(args.release / "prepared.json", args.prepared_sha256), args, manifest)
    payload = payload_check(base, args.release, manifest)
    old, public = Path(prepared["old_public_root"]), Path(prepared["public_root"])
    old_files = prepared["old_public_files"]
    with release_lock(base):
        original = base.read_nginx()
        need(sha(original) == prepared["old_nginx_sha256"] == pins["nginx_sha256"], "ACTIVATION_NGINX_DRIFT")
        need(base.file_map(old) == old_files, "CURRENT_PUBLIC_BYTES_DRIFT")
        before = boundary(personal, upgrade, base, preparation, switch, pins)
        need(stable_boundary(before) == stable_boundary(prepared["boundary"]), "PREPARED_RUNTIME_SCHEMA_DRIFT")
        changed = personal.changed_nginx(original, old, public, sha(original))
        state = {**{key: prepared[key] for key in ("source_sha", "frontend_version", "manifest_sha256", "payload_sha256",
            "preflight_sha256", "personal_helper_sha256", "old_public_root", "public_root", "old_nginx_sha256")},
            "format_version": 1, "phase": "CRM_DESKTOP_COMFORT_STATIC_ACTIVATING", "prepared_sha256": args.prepared_sha256,
            "new_nginx_sha256": sha(changed), "deployed": False, "database_mutation_performed": False,
            "services_modified": False, "environment_modified": False, "databases_restored": False,
            "private_source_unchanged": True, "backend_source_unchanged": True,
            "business_tables_verified": 83, "private_tables_verified": 20}
        personal.write_new(args.release / "nginx-before.bin", original)
        personal.write_new(args.release / "nginx-after.bin", changed)
        personal.save(args.release / "runtime-schema-before.json", before)
        state_path = args.release / "static-state.json"
        personal.save(state_path, state)
        try:
            desired = personal.install_public(base, payload, old, public)
            current = boundary(personal, upgrade, base, preparation, switch, pins)
            need(stable_boundary(current) == stable_boundary(before) and base.file_map(old) == old_files,
                 "PRE_SWITCH_RUNTIME_SCHEMA_OR_OLD_ASSET_DRIFT")
            base.atomic_nginx(changed, {sha(original)})
            state["phase"] = "CRM_DESKTOP_COMFORT_STATIC_ROOT_CHANGED"
            personal.save(state_path, state, replace=True)
            base.run(["nginx", "-t"], "NGINX_TEST_FAILED")
            base.run(["systemctl", "reload", "nginx"], "NGINX_RELOAD_FAILED")
            base.public_check(desired, manifest["frontend_version"], public, verify_services=False)
            personal.authentication_probe(public=True)
            after = boundary(personal, upgrade, base, preparation, switch, pins)
            need(stable_boundary(before) == stable_boundary(after) and base.read_nginx() == changed
                 and base.file_map(public) == desired and base.file_map(old) == old_files, "FINAL_STATIC_BOUNDARY_DRIFT")
            personal.save(args.release / "public-manifest.json", desired)
            personal.save(args.release / "runtime-schema-after.json", after)
            state.update(phase="CRM_DESKTOP_COMFORT_STATIC_PUBLIC_VERIFIED", deployed=True,
                same_database_identity_and_schema=True, same_crm_and_private_runtime=True,
                previous_hashed_assets_preserved=True)
            receipt_sha = personal.save(state_path, state, replace=True)
        except BaseException as error:
            state.update(failure_code=safe_error(error), rollback_attempted=True, deployed=False)
            try:
                # Recovery never depends on row hashes or runtime checks that may
                # have changed legitimately during the live publication window.
                rollback(base, original, changed, old, old_files)
                state["phase"] = "CRM_DESKTOP_COMFORT_STATIC_ROLLED_BACK"
            except BaseException as recovery_error:
                state.update(phase="CRM_DESKTOP_COMFORT_STATIC_ROLLBACK_NEEDS_REVIEW", rollback_failure_code=safe_error(recovery_error))
            personal.save(state_path, state, replace=True)
            raise StaticError(state["failure_code"]) from None
        return {"phase": state["phase"], "source_sha": manifest["source_sha"], "frontend_version": manifest["frontend_version"],
            "receipt_sha256": receipt_sha, "public_root": str(public), "private_tables": 20, "business_tables": 83,
            "deployed": True, "database_mutation_performed": False, "services_modified": False, "environment_modified": False}


def main(args):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, "EXACT_AUTHENTICATED_SERVER_REQUIRED")
    need(args.release == Path(__file__).resolve().parent, "ACQUIRED_RELEASE_HELPER_PATH_REQUIRED")
    protected(args.release, True)
    manifest = checked_manifest(fixed_json(args.release / "static-manifest.json", args.manifest_sha256), args.payload_sha256)
    public_root(args.release, manifest)
    personal, upgrade, base, preparation, switch = retained_tools()
    pins = checked_preflight(fixed_json(args.preflight, args.preflight_sha256), personal)
    if args.phase == "prepare":
        return prepare(args, personal, upgrade, base, preparation, switch, manifest, pins)
    return activate(args, personal, upgrade, base, preparation, switch, manifest, pins)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise StaticError("ARGUMENTS_REJECTED")


if __name__ == "__main__":
    parser = SafeParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "activate"), required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--prepared-sha256")
    try:
        print(json.dumps(main(parser.parse_args()), sort_keys=True))
    except BaseException as error:
        print(json.dumps({"stage": "CRM_DESKTOP_COMFORT_STATIC_REJECTED", "error": safe_error(error),
            "services_modified": False, "database_mutation_performed": False, "environment_modified": False}, sort_keys=True))
        sys.exit(1)
