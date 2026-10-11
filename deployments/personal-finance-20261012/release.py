#!/usr/bin/env python3
"""Frozen private-only 11-to-20 release; never restore or delete live databases.

prepare runs with no production mounts or runtime credentials. activate freezes
only private writers, backs up SQLite, appends the reviewed private tables and
switches the private API/worker plus complete static assets. The CRM stays live.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from uuid import uuid4

SOURCE = "1a9232dcc04a6d09d0f4f60193c693bbb6243476"
BASE_SOURCE = "c1ae19b38fec8f62f044d4b0789f31662da12fbf"
HOST = "iZj6c4cj7edgnhdimts4l7Z"
BASE_IMAGE = "sha256:3edf765dac63430764b5f294a1ac0e0114763c3a59e5afa6790bf3dfc49f5734"
RELEASE = Path("/opt/t24-crm/releases/personal-finance-1a9232dcc04a-20261012")
LEGACY = Path("/opt/t24-crm/releases/stripe-report-c1ae19b38fec-20261012")
LEGACY_HASHES = {
    "prepare_candidate.py": "989dc1de81a0b3a39ad978c395bdfd7a3c31725a3e2ebee57a5713cfc8faa613",
    "upgrade.py": "919f0ecca1d33a46d882a816b70fccb1514144ba4ddc828c2921e5db1a4b5e5b",
}
HASH = re.compile(r"[a-f0-9]{64}")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
BASE_TABLES = frozenset({
    "private_connections", "private_items", "private_preferences", "private_sync_runs",
    "private_mail_translations", "private_translation_usage", "private_mail_briefs",
    "private_mail_brief_usage", "private_workspace_briefs", "private_bank_links", "private_stripe_reports",
})
NEW_TABLES = frozenset("private_pf_" + name for name in (
    "settings", "categories", "accounts", "debts", "plans", "goals", "entries", "audits", "receipts"))
TARGET_TABLES = BASE_TABLES | NEW_TABLES
RUNTIME = frozenset("backend/" + name for name in (
    "models/private_personal_finance.py", "schemas/private_personal_finance.py",
    "services/private_personal_finance.py", "routers/private_personal_finance.py",
    "services/private_workspace.py", "services/private_workspace_app.py"))
BACKEND_CHANGES = frozenset("app/" + name for name in RUNTIME) | {
    "app/backend/tests/test_private_personal_finance.py", "app/backend/tests/test_private_workspace_core.py"}
TEST_NAMES = (
    "conftest", "test_private_ads_health", "test_private_bank_auth", "test_private_bank_provider",
    "test_private_bank_service", "test_private_mail_brief", "test_private_mail_brief_service",
    "test_private_mail_content", "test_private_mail_relevance", "test_private_mail_translation",
    "test_private_mail_translation_service", "test_private_personal_finance", "test_private_python310_compat",
    "test_private_stripe_auth", "test_private_stripe_connection", "test_private_stripe_report_provider",
    "test_private_stripe_report_service", "test_private_workspace_app", "test_private_workspace_brief",
    "test_private_workspace_core", "test_private_workspace_providers", "test_private_workspace_worker",
)
PRIVATE_TESTS = frozenset("app/backend/tests/" + name + ".py" for name in TEST_NAMES)
ROLLBACK_IMPORT = b"\n# Recognize additive personal tables without exposing the new ledger API.\nimport models.private_personal_finance  # noqa: F401\n"
MINIMUM_TESTS = 1192


class ReleaseError(RuntimeError):
    pass


def need(value, code):
    if not value:
        raise ReleaseError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def safe_failure(error):
    reviewed = isinstance(error, ReleaseError) or type(error).__name__ in {
        "UpgradeError", "StaticError", "SwitchError", "PreparationError", "PrepareError", "GuardError", "TransferError"}
    code = str(error)
    if reviewed and re.fullmatch(r"[A-Z0-9_]{1,100}", code):
        return code
    return re.sub(r"[^A-Z0-9_]", "_", type(error).__name__.upper())[:100] or "UNCLASSIFIED_FAILURE"


def protected(path, *, directory=False):
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


def stamp(info):
    return tuple(getattr(info, field) for field in (
        "st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def read(path, maximum=4 * 1024**2):
    before = protected(path)
    need(before.st_size <= maximum, "PROTECTED_SIZE_LIMIT")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        need(stamp(os.fstat(stream.fileno())) == stamp(before), "PROTECTED_FILE_IDENTITY_DRIFT")
        data = stream.read(maximum + 1)
    need(len(data) <= maximum and stamp(protected(path)) == stamp(before), "PROTECTED_FILE_CHANGED")
    return data


def fixed_json(path, expected):
    need(HASH.fullmatch(expected or ""), "REVIEWED_HASH_REQUIRED")
    data = read(path)
    need(sha(data) == expected, "FIXED_JSON_HASH_DRIFT")
    value = json.loads(data)
    need(isinstance(value, dict), "OBJECT_RECEIPT_REQUIRED")
    return value


def write_new(path, data):
    path = Path(path)
    protected(path.parent, directory=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value, *, replace=False):
    data = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    if replace:
        previous = protected(path)
        temporary = Path(path).parent / ("." + Path(path).name + "-" + uuid4().hex)
        write_new(temporary, data)
        need(stamp(protected(path)) == stamp(previous), "RECEIPT_CHANGED_BEFORE_REPLACE")
        os.replace(temporary, path)
        descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        write_new(path, data)
    return sha(data)


def load_legacy(name):
    path = LEGACY / name
    need(name in LEGACY_HASHES and sha(read(path, 1024**2)) == LEGACY_HASHES[name], "RETAINED_PRIMITIVE_HASH_DRIFT")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("_personal_finance_" + name.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_manifest(manifest):
    need(manifest.get("format_version") == 1 and manifest.get("stage") == "PERSONAL_FINANCE_PAYLOAD_PREPARED"
         and manifest.get("source_sha") == SOURCE and manifest.get("baseline_private_source_sha") == BASE_SOURCE
         and manifest.get("base_private_image") == BASE_IMAGE, "FROZEN_PERSONAL_FINANCE_MANIFEST_REQUIRED")
    need(all(manifest.get(name) is False for name in (
        "runtime_dependency_changes", "credentials_included", "production_access", "deployed")),
        "NO_DEPENDENCY_CREDENTIAL_OR_PRODUCTION_PAYLOAD")
    need(set(manifest.get("backend_changes", [])) == BACKEND_CHANGES
         and set(manifest.get("private_tests", [])) == PRIVATE_TESTS
         and len(manifest["private_tests"]) == len(PRIVATE_TESTS), "EXACT_PRIVATE_SOURCE_AND_TEST_SCOPE_REQUIRED")
    need(type(manifest.get("backend_regression_tests_expected_minimum")) is int
         and manifest["backend_regression_tests_expected_minimum"] >= MINIMUM_TESTS
         and manifest.get("private_schema_table_count_before") == 11
         and manifest.get("private_schema_table_count_after") == 20, "ELEVEN_TO_TWENTY_AND_COMPLETE_TESTS_REQUIRED")
    hashes = manifest.get("source_file_sha256")
    inventory = manifest.get("payload_files")
    need(isinstance(hashes, dict) and set(hashes) == BACKEND_CHANGES | PRIVATE_TESTS
         and all(HASH.fullmatch(value or "") for value in hashes.values()), "COMPLETE_FROZEN_SOURCE_HASHES_REQUIRED")
    need(isinstance(inventory, dict) and 30 < len(inventory) < 10000
         and all(HASH.fullmatch(value or "") for value in inventory.values()), "BOUNDED_COMPLETE_PAYLOAD_REQUIRED")
    expected = {name.removeprefix("app/"): value for name, value in hashes.items()}
    static = {name: value for name, value in inventory.items() if name.startswith("frontend/dist/")}
    need({"frontend/dist/index.html", "frontend/dist/app-version.json"} <= set(static), "COMPLETE_STATIC_REQUIRED")
    suffixes = {".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".webp", ".gif",
                ".svg", ".ico", ".txt", ".woff", ".woff2", ".ttf", ".webmanifest"}
    for name in inventory:
        relative = PurePosixPath(name)
        need(name == relative.as_posix() and not relative.is_absolute() and ".." not in relative.parts
             and not any(part.startswith(".") for part in relative.parts), "CANONICAL_PAYLOAD_PATH_REQUIRED")
        if name in static:
            need(relative.suffix in suffixes and (relative.suffix != ".html"
                 or name in {"frontend/dist/index.html", "frontend/dist/offline.html"}), "STATIC_EXTENSION_REJECTED")
    need(inventory == {**expected, **static}, "UNREVIEWED_OR_MISSING_PAYLOAD_FILE")
    need(HASH.fullmatch(manifest.get("payload_sha256", "")) and
         re.fullmatch(r"[a-f0-9]{12}", manifest.get("frontend_version", "")), "FROZEN_ARTIFACT_VERSION_REQUIRED")
    need(isinstance(manifest.get("runtime_dependency_file_sha256"), dict)
         and manifest["runtime_dependency_file_sha256"], "UNCHANGED_DEPENDENCY_PROOF_REQUIRED")
    return manifest


def checked_preflight(value):
    need(value.get("stage") == "PERSONAL_FINANCE_AUTHENTICATED_READONLY_PREFLIGHT"
         and value.get("host") == HOST and value.get("backend_source_sha") == BASE_SOURCE
         and value.get("private_image") == BASE_IMAGE and value.get("mutation_performed") is False,
         "AUTHENTICATED_FRESH_PREFLIGHT_REQUIRED")
    need(set(value.get("roles", {})) == {"api", "worker"} and set(value["snapshot"]["private"]["tables"]) == BASE_TABLES
         and len(value["snapshot"]["business"]["tables"]) == 83, "EXACT_ELEVEN_PRIVATE_AND_83_CRM_BASE_REQUIRED")
    for name, record in value["roles"].items():
        need(HASH.fullmatch(record.get("id", "")) and record.get("image") == BASE_IMAGE
             and record.get("source") == BASE_SOURCE and re.fullmatch(r"[a-f0-9]{32}", record.get("attempt", ""))
             and record["runtime"]["id"] == record["id"] and record["runtime"]["image"] == BASE_IMAGE,
             "EXACT_ORIGINAL_PRIVATE_ROLES_REQUIRED")
    need(HASH.fullmatch(value.get("nginx_sha256", "")) and HASH.fullmatch(value.get("environment_sha256", ""))
         and re.fullmatch(r"[a-f0-9]{12}", value.get("frontend_version", "")), "PINNED_PUBLIC_ENVIRONMENT_REQUIRED")
    need(value.get("primitives") == {
        "prepare_candidate": {"path": str(LEGACY / "prepare_candidate.py"), "sha256": LEGACY_HASHES["prepare_candidate.py"]},
        "stripe_upgrade": {"path": str(LEGACY / "upgrade.py"), "sha256": LEGACY_HASHES["upgrade.py"]}},
        "EXACT_REVIEWED_PRIMITIVES_REQUIRED")
    return value


def compare_schema(before, after, target_objects, *, in_place=True, new_empty=True):
    old, new = before["private"], after["private"]
    need(set(old["tables"]) == BASE_TABLES and set(new["tables"]) == TARGET_TABLES, "EXACT_ELEVEN_TO_TWENTY_REQUIRED")
    need(before["business"] == after["business"], "CRM_DATABASE_CHANGED")
    need(new["schema_objects"] == target_objects and
         {name for name, row in target_objects.items() if row["type"] == "table"} == TARGET_TABLES,
         "REHEARSED_TARGET_DDL_REQUIRED")
    if in_place:
        need(old["identity"] == new["identity"], "LIVE_PRIVATE_DATABASE_REPLACED")
    else:
        need((old["identity"]["device"], old["identity"]["inode"]) !=
             (new["identity"]["device"], new["identity"]["inode"]), "DISTINCT_SYNTHETIC_CLONE_REQUIRED")
    need(all(old["tables"][name] == new["tables"][name] for name in BASE_TABLES), "ORIGINAL_PRIVATE_ROWS_OR_COLUMNS_CHANGED")
    need(old["schema_objects"] == {name: row for name, row in new["schema_objects"].items() if row["table"] in BASE_TABLES},
         "ORIGINAL_PRIVATE_INDEXES_OR_DDL_CHANGED")
    if new_empty:
        need(all(new["tables"][name]["rows"] == 0 for name in NEW_TABLES), "NEW_PERSONAL_TABLES_MUST_START_EMPTY")
    return {"stage": "PERSONAL_FINANCE_ELEVEN_TO_TWENTY_VERIFIED", "source_sha": SOURCE,
            "existing_private_tables_preserved": 11, "private_tables": 20, "crm_unchanged": True,
            "new_personal_tables_empty": new_empty, "same_live_inode": in_place,
            "before_sha256": digest(before), "after_sha256": digest(after), "schema_sha256": digest(target_objects)}


def checked_partial_schema(before, current, target):
    """Recovery may finish exact reviewed new DDL, never alter old table rows."""
    need(before["business"] == current["business"]
         and before["private"]["identity"] == current["private"]["identity"], "ROLLBACK_DATABASE_BOUNDARY_CHANGED")
    old, actual = before["private"], current["private"]
    need(BASE_TABLES <= set(actual["tables"]) <= TARGET_TABLES, "UNREVIEWED_PARTIAL_PRIVATE_TABLE")
    need(all(actual["tables"][name] == old["tables"][name] for name in BASE_TABLES), "ROLLBACK_ORIGINAL_ROWS_CHANGED")
    need(old["schema_objects"] == {name: row for name, row in actual["schema_objects"].items() if row["table"] in BASE_TABLES}
         and all(target.get(name) == row for name, row in actual["schema_objects"].items()),
         "UNREVIEWED_PARTIAL_PRIVATE_SCHEMA")


def target_schema(before, independent):
    additions = {name: row for name, row in independent.items() if row["table"] in NEW_TABLES}
    need({name for name, row in additions.items() if row["type"] == "table"} == NEW_TABLES
         and not set(additions) & set(before["private"]["schema_objects"]), "EXACT_NINE_NEW_TABLES_REQUIRED")
    return {**before["private"]["schema_objects"], **additions}


def rollback_service(original):
    need(b"import models.private_personal_finance" not in original and b"async def private_session_factory" in original,
         "ACTUAL_OLD_PRIVATE_SERVICE_REQUIRED")
    return original + ROLLBACK_IMPORT


def expected_backend(base, manifest, *, rollback_hashes=None):
    result = dict(base)
    additions = rollback_hashes or {
        name.removeprefix("backend/"): manifest["payload_files"][name] for name in RUNTIME}
    result.update(additions)
    return result


def recipe(base_tag, *, rollback=False):
    need(re.fullmatch(r"t24-private-personal-base:[a-f0-9]{12}-[a-f0-9]{12}", base_tag), "EXCLUSIVE_BASE_TAG_REQUIRED")
    names = ("rollback/models/private_personal_finance.py", "rollback/services/private_workspace.py") if rollback else sorted(RUNTIME)
    content = "FROM " + base_tag + "\n"
    for name in names:
        target = "backend/" + name.removeprefix("rollback/") if rollback else name
        content += "COPY " + name + " /app/" + target + "\n"
    label = "t24.private.rollback.schema-compatible" if rollback else "t24.private.source.sha"
    return (content + "LABEL " + label + '="' + ("eleven-to-twenty-personal" if rollback else SOURCE) + '"\n').encode()


def preparation_runner(prep, root):
    class Runner(prep.Runner):
        def isolated(self, stage, image, code, *, mounts=(), timeout=180):
            need(IMAGE.fullmatch(image or ""), "IMMUTABLE_ISOLATED_IMAGE_REQUIRED")
            name = "t24-personal-prepare-" + uuid4().hex
            command = ["docker", "run", "--rm", "--name", name, "--label", "t24.personal.prepare=" + name,
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--no-healthcheck", "--workdir", "/app/backend", "--pids-limit", "128", "--memory", "1g", "--cpus", "2",
                "--tmpfs", "/tmp:rw,nosuid,size=512m", "--tmpfs", "/app/backend/logs:rw,nosuid,noexec,size=16m"]
            for key, value in sorted(prep.SYNTHETIC_ENV.items()):
                command += ["--env", key + "=" + value]
            for source, destination, readonly in mounts:
                prep.protected(source, directory=True)
                need((source.is_relative_to(self.release) or source == prep.BASE_TEST_ROOT / "test-wheels")
                     and destination in {"/synthetic/private", "/synthetic/business", "/test-results", "/test-wheels", "/app/backend/tests"}
                     and (destination not in {"/app/backend/tests", "/test-wheels"} or readonly),
                     "ONLY_SYNTHETIC_OFFLINE_TEST_MOUNTS_ALLOWED")
                command += ["--mount", "type=bind,src=" + str(source) + ",dst=" + destination + (",readonly" if readonly else "")]
            command += ["--entrypoint", "python", image, "-c", code]
            try:
                return self.run(stage, command, timeout=timeout)
            finally:
                result = subprocess.run(["docker", "inspect", name], capture_output=True, timeout=30, check=False)
                if result.returncode == 0:
                    rows = json.loads(result.stdout)
                    need(len(rows) == 1 and rows[0]["Image"] == image
                         and rows[0]["Config"].get("Labels", {}).get("t24.personal.prepare") == name,
                         "OWN_PREPARATION_CLEANUP_ONLY")
                    removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False)
                    need(removed.returncode == 0, "PREPARATION_CONTAINER_CLEANUP_FAILED")
    return Runner(root)


LEDGER_REHEARSAL = """import asyncio,os
from datetime import date
from uuid import uuid4
os.environ['DATABASE_URL']='sqlite+aiosqlite:////synthetic/business/business.db'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////synthetic/private/migrated/workspace.db'
from services.private_workspace import private_session_factory,close_private_workspace_storage
from services import private_personal_finance as f
from schemas.private_personal_finance import BootstrapInput,AccountCreate,DebtCreate,GoalCreate,PlanCreate,PlanPay,EntryCreate
async def run():
 sessions=await private_session_factory()
 async with sessions() as db:
  state=await f.bootstrap(db,'4',BootstrapInput(client_request_id=uuid4()))
  await db.rollback()
  category=next(c for c in state['categories'] if c['kind']=='expense')
  account=await f.create_account(db,'4',AccountCreate(name='Synthetic account',kind='cash',opening_balance_minor=10000,client_request_id=uuid4()))
  await f.create_debt(db,'4',DebtCreate(name='Synthetic principal',direction='payable',principal_minor=2000,client_request_id=uuid4()))
  await f.create_goal(db,'4',GoalCreate(name='Synthetic goal',target_minor=10000,prepared_minor=1000,client_request_id=uuid4()))
  plan=await f.create_plan(db,'4',PlanCreate(name='Synthetic payment',category_id=category['id'],amount_minor=2000,due_date=date(2026,10,20),client_request_id=uuid4()))
  await f.create_entry(db,'4',EntryCreate(kind='expense',amount_minor=150,account_id=account['id'],category_id=category['id'],entry_date=date(2026,10,12),client_request_id=uuid4()))
  await f.pay_plan(db,'4',plan['id'],PlanPay(amount_minor=1900,account_id=account['id'],entry_date=date(2026,10,12),client_request_id=uuid4()))
  report=await f.report(db,'4',date(2026,10,1),date(2026,10,31))
  assert report['expense_minor']==2050 and report['income_minor']==0
 await close_private_workspace_storage()
asyncio.run(run());print('{"synthetic_personal_ledger_only":true}')
"""


def schema_rehearsal(prep, runner, image, rollback_image):
    root = runner.release / "synthetic"
    root.mkdir(mode=0o700)
    private, business = root / "private", root / "business"
    private.mkdir(mode=0o700); business.mkdir(mode=0o700)
    writable = [(private, "/synthetic/private", False), (business, "/synthetic/business", False)]
    private_only = [(private, "/synthetic/private", False), (business, "/synthetic/business", True)]
    fixture = prep.FIXTURE_BASE + "\n" + prep.SEED_REPORT_CACHE.replace(
        "/synthetic/private/migrated/workspace.db", "/synthetic/private/original.db")
    runner.isolated("schema-original-eleven", BASE_IMAGE, fixture, mounts=writable)
    original, business_file = private / "original.db", business / "business.db"
    before = prep.release_snapshot(original, business_file)
    need(set(before["private"]["tables"]) == BASE_TABLES
         and all(row["rows"] > 0 for row in before["private"]["tables"].values()), "POPULATED_ELEVEN_TABLE_BASE_REQUIRED")
    empty_code = prep.EMPTY_SCHEMA.replace("from models.private_workspace import PrivateWorkspaceBase",
        "from models.private_workspace import PrivateWorkspaceBase\nimport models.private_personal_finance")
    runner.isolated("schema-independent-empty-twenty", image, empty_code, mounts=private_only)
    empty = prep.database_snapshot(private / "empty.db", private=True)
    need(set(empty["tables"]) == TARGET_TABLES and all(row["rows"] == 0 for row in empty["tables"].values()),
         "INDEPENDENT_EMPTY_TWENTY_TABLE_SCHEMA_REQUIRED")
    migrated = private / "migrated"
    migrated.mkdir(mode=0o700)
    with sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(migrated / "workspace.db") as target:
        source.backup(target)
    (migrated / "workspace.db").chmod(0o600)
    runner.isolated("schema-eleven-to-twenty", image, prep.INIT_MIGRATION, mounts=private_only)
    after = prep.release_snapshot(migrated / "workspace.db", business_file)
    proof = compare_schema(before, after, empty["schema_objects"], in_place=False)
    runner.isolated("schema-personal-ledger-populated", image, LEDGER_REHEARSAL, mounts=private_only)
    populated = prep.release_snapshot(migrated / "workspace.db", business_file)
    compare_schema(before, populated, empty["schema_objects"], in_place=False, new_empty=False)
    need(all(populated["private"]["tables"][name]["rows"] > 0 for name in NEW_TABLES), "ALL_NINE_PERSONAL_TABLES_EXERCISED")
    runner.isolated("schema-compatible-old-api", rollback_image, prep.ROLLBACK_READ, mounts=private_only)
    need(prep.release_snapshot(migrated / "workspace.db", business_file) == populated, "ROLLBACK_CHANGED_EXISTING_LEDGER_OR_CREDENTIALS")
    # Simulate failure after new DDL on a separate clone, then rehearse a
    # schema-compatible rollback without restoring/deleting its database.
    interrupted = private / "interrupted"
    interrupted.mkdir(mode=0o700)
    with sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(interrupted / "workspace.db") as target:
        source.backup(target)
    (interrupted / "workspace.db").chmod(0o600)
    fault = prep.INIT_MIGRATION.replace("/migrated/", "/interrupted/").replace(
        "async def run():", """original_factory=__import__('services.private_workspace',fromlist=['create_async_engine']).create_async_engine
from sqlalchemy import event
import services.private_workspace as storage
def fault_factory(*args,**kwargs):
 engine=original_factory(*args,**kwargs)
 def fail(connection,cursor,statement,parameters,context,many):
  if 'CREATE TABLE private_pf_' in statement:raise RuntimeError('synthetic_ddl_interruption')
 event.listen(engine.sync_engine,'after_cursor_execute',fail)
 return engine
storage.create_async_engine=fault_factory
async def run():""").replace(
        "await private_session_factory();await close_private_workspace_storage()",
        "try:await private_session_factory()\n except Exception:pass\n await close_private_workspace_storage()")
    runner.isolated("schema-interrupted-new-ddl", image, fault, mounts=private_only)
    partial = prep.release_snapshot(interrupted / "workspace.db", business_file)
    # Source clone identity differs; compare to a logically same baseline with
    # only that clone's independently observed file identity.
    partial_before = json.loads(json.dumps(before))
    partial_before["private"]["identity"] = partial["private"]["identity"]
    checked_partial_schema(partial_before, partial, empty["schema_objects"])
    runner.isolated("schema-interrupted-compatible-rollback", rollback_image,
        prep.ROLLBACK_READ.replace("/migrated/", "/interrupted/"), mounts=private_only)
    recovered = prep.release_snapshot(interrupted / "workspace.db", business_file)
    compare_schema(partial_before, recovered, empty["schema_objects"], new_empty=True)
    save(runner.release / "synthetic-before.json", before)
    save(runner.release / "synthetic-after.json", after)
    save(runner.release / "synthetic-populated.json", populated)
    save(runner.release / "synthetic-recovered.json", recovered)
    return {**proof, "schema_objects": empty["schema_objects"], "populated_new_ledger_preserved": True,
            "compatible_old_api_started_and_owner_read": True, "encrypted_existing_credentials_decrypted": True,
            "interrupted_ddl_compatible_rollback_verified": True, "business_physically_readonly": True}


def prepare(release, manifest, archive, preflight, *, manifest_sha256, preflight_sha256):
    protected(release, directory=True)
    checked_manifest(manifest); checked_preflight(preflight)
    need(sha(archive) == manifest["payload_sha256"], "PAYLOAD_HASH_DRIFT")
    prep = load_legacy("prepare_candidate.py")
    root = release / "prepared-backend"
    need(not root.exists(), "NEW_PREPARATION_DIRECTORY_REQUIRED")
    root.mkdir(mode=0o700)
    context = root / "payload"
    prep.extract(archive, manifest, context)
    runner = preparation_runner(prep, root)
    base_inspection = prep.inspect_image(BASE_IMAGE)
    prep.checked_base_runtime(runner.scan("base-python-runtime", BASE_IMAGE, prep.SCAN_RUNTIME))
    base = runner.scan("base-backend", BASE_IMAGE, prep.SCAN_BACKEND)
    packages = runner.scan("base-packages", BASE_IMAGE, prep.SCAN_PACKAGES)
    static = runner.scan("base-bundled-static", BASE_IMAGE, prep.SCAN_STATIC)
    export = "import base64,pathlib;print(base64.b64encode(pathlib.Path('/app/backend/services/private_workspace.py').read_bytes()).decode())"
    old_service = base64.b64decode(runner.isolated("base-private-service-export", BASE_IMAGE, export).strip(), validate=True)
    need(sha(old_service) == base["services/private_workspace.py"], "ACTUAL_OLD_SERVICE_BYTE_DRIFT")
    rollback_bytes = rollback_service(old_service)
    rollback_root = context / "rollback"
    (rollback_root / "models").mkdir(mode=0o700, parents=True)
    (rollback_root / "services").mkdir(mode=0o700)
    model_bytes = (context / "backend/models/private_personal_finance.py").read_bytes()
    write_new(rollback_root / "models/private_personal_finance.py", model_bytes)
    write_new(rollback_root / "services/private_workspace.py", rollback_bytes)
    rollback_hashes = {"models/private_personal_finance.py": sha(model_bytes), "services/private_workspace.py": sha(rollback_bytes)}
    wheels = prep.BASE_TEST_ROOT / "test-wheels"
    wheel_manifest = json.loads(prep.frozen_file(prep.BASE_TEST_ROOT / "test-wheel-manifest.json", prep.BASE_WHEEL_MANIFEST_SHA, 1024**2))
    tools = prep.wheel_tools(wheels, wheel_manifest)
    base_tag = "t24-private-personal-base:" + SOURCE[:12] + "-" + uuid4().hex[:12]
    missing = subprocess.run(["docker", "image", "inspect", base_tag], capture_output=True, timeout=30, check=False)
    need(missing.returncode != 0, "EXCLUSIVE_BASE_TAG_REQUIRED")
    runner.run("pin-actual-base", ["docker", "tag", BASE_IMAGE, base_tag])
    need(runner.run("base-pin-before", ["docker", "image", "inspect", "-f", "{{.Id}}", base_tag]).decode().strip() == BASE_IMAGE,
         "BASE_PIN_DRIFT")
    images = {}
    for role in ("candidate", "rollback"):
        tag = "t24-private-personal-" + role + ":" + SOURCE[:12] + "-" + uuid4().hex[:12]
        need(subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=30, check=False).returncode != 0,
             "EXCLUSIVE_CANDIDATE_TAG_REQUIRED")
        recipe_path = root / ("Dockerfile." + role)
        write_new(recipe_path, recipe(base_tag, rollback=role == "rollback"))
        runner.run(role + "-build", ["docker", "build", "--pull=false", "--network=none", "--no-cache",
            "-f", str(recipe_path), "-t", tag, "."], timeout=600, cwd=context)
        image = runner.run(role + "-id", ["docker", "image", "inspect", "-f", "{{.Id}}", tag]).decode().strip()
        need(IMAGE.fullmatch(image or "") and image != BASE_IMAGE and image not in images.values(), "DISTINCT_PREPARED_IMAGE_REQUIRED")
        prep.verify_candidate_base(base_inspection, prep.inspect_image(image))
        expected = expected_backend(base, manifest, rollback_hashes=rollback_hashes if role == "rollback" else None)
        need(runner.scan(role + "-backend", image, prep.SCAN_BACKEND) == expected, "UNRELATED_BACKEND_BYTES_CHANGED")
        need(runner.scan(role + "-packages", image, prep.SCAN_PACKAGES) == packages
             and runner.scan(role + "-static", image, prep.SCAN_STATIC) == static, "UNRELATED_RUNTIME_OR_BUNDLED_STATIC_CHANGED")
        images[role] = image
    need(runner.run("base-pin-after", ["docker", "image", "inspect", "-f", "{{.Id}}", base_tag]).decode().strip() == BASE_IMAGE,
         "BASE_PIN_DRIFT")
    results = root / "test-results"
    results.mkdir(mode=0o700)
    code = prep.regression_code(tools, manifest["private_tests"])
    runner.isolated("all-private-regressions", images["candidate"], code,
        mounts=[(wheels, "/test-wheels", True), (results, "/test-results", False),
                (context / "backend/tests", "/app/backend/tests", True)], timeout=600)
    xml_path = results / "regressions.xml"
    info = xml_path.lstat()
    need(xml_path.resolve() == xml_path and stat.S_ISREG(info.st_mode) and info.st_uid == 0
         and info.st_nlink == 1 and not info.st_mode & 0o022 and 0 < info.st_size <= 8 * 1024**2,
         "REGULAR_PROTECTED_REGRESSION_EVIDENCE_REQUIRED")
    xml_path.chmod(0o600)
    xml = read(xml_path, 8 * 1024**2)
    minimum = manifest["backend_regression_tests_expected_minimum"]
    total = prep.test_report(xml, minimum)
    rehearsal = schema_rehearsal(prep, runner, images["candidate"], images["rollback"])
    receipt = {"format_version": 1, "stage": "PERSONAL_FINANCE_CANDIDATE_VERIFIED", "source_sha": SOURCE,
        "baseline_private_source_sha": BASE_SOURCE, "base_image_id": BASE_IMAGE, "image_id": images["candidate"],
        "rollback_image_id": images["rollback"], "rollback_model_registration_only": True,
        "all_other_backend_bytes_identical": True, "all_runtime_package_bytes_identical": True,
        "bundled_static_bytes_unchanged": True, "base_layers_verified": True, "base_pin_verified": True,
        "candidate_backend_sha256": digest(expected_backend(base, manifest)), "base_backend_sha256": digest(base),
        "rollback_backend_sha256": digest(expected_backend(base, manifest, rollback_hashes=rollback_hashes)),
        "runtime_packages": packages, "manifest_sha256": manifest_sha256, "preflight_sha256": preflight_sha256,
        "payload_sha256": manifest["payload_sha256"], "regressions": {"tests": total, "minimum": minimum,
            "python": "3.10.22", "network": "none", "all_private_tests": manifest["private_tests"],
            "xml_sha256": sha(xml), "wheel_manifest_sha256": prep.BASE_WHEEL_MANIFEST_SHA},
        "synthetic_schema": rehearsal, "production_environment_loaded": False, "production_database_access": False,
        "production_services_modified": False, "public_assets_published": False, "deployed": False}
    value = save(release / "candidate.json", receipt)
    return {"stage": receipt["stage"], "candidate_sha256": value, "image_id": images["candidate"],
            "rollback_image_id": images["rollback"], "tests": total, "deployed": False}


def checked_candidate(value, manifest, manifest_hash, preflight_hash):
    need(value.get("stage") == "PERSONAL_FINANCE_CANDIDATE_VERIFIED" and value.get("source_sha") == SOURCE
         and value.get("baseline_private_source_sha") == BASE_SOURCE and value.get("base_image_id") == BASE_IMAGE
         and value.get("manifest_sha256") == manifest_hash and value.get("preflight_sha256") == preflight_hash
         and value.get("payload_sha256") == manifest["payload_sha256"], "EXACT_REHEARSED_CANDIDATE_REQUIRED")
    need(all(value.get(name) is True for name in ("rollback_model_registration_only", "all_other_backend_bytes_identical",
        "all_runtime_package_bytes_identical", "bundled_static_bytes_unchanged", "base_layers_verified", "base_pin_verified")),
        "RETAINED_RUNTIME_BYTES_REQUIRED")
    need(all(value.get(name) is False for name in ("production_environment_loaded", "production_database_access",
        "production_services_modified", "public_assets_published", "deployed")), "ISOLATED_PREPARATION_REQUIRED")
    need(IMAGE.fullmatch(value.get("image_id", "")) and IMAGE.fullmatch(value.get("rollback_image_id", ""))
         and len({BASE_IMAGE, value["image_id"], value["rollback_image_id"]}) == 3, "DISTINCT_REVIEWED_IMAGES_REQUIRED")
    tests = value.get("regressions", {})
    need(type(tests.get("tests")) is int and tests["tests"] >= tests.get("minimum", 0) >= MINIMUM_TESTS
         and tests.get("minimum") == manifest["backend_regression_tests_expected_minimum"]
         and tests.get("python") == "3.10.22" and tests.get("network") == "none"
         and tests.get("all_private_tests") == manifest["private_tests"] and HASH.fullmatch(tests.get("xml_sha256", "")),
         "COMPLETE_DEPLOYED_PYTHON_PRIVATE_REGRESSIONS_REQUIRED")
    schema = value.get("synthetic_schema", {})
    need(schema.get("stage") == "PERSONAL_FINANCE_ELEVEN_TO_TWENTY_VERIFIED" and schema.get("source_sha") == SOURCE
         and schema.get("private_tables") == 20 and schema.get("existing_private_tables_preserved") == 11
         and all(schema.get(name) is True for name in ("crm_unchanged", "new_personal_tables_empty",
             "populated_new_ledger_preserved", "compatible_old_api_started_and_owner_read",
             "encrypted_existing_credentials_decrypted", "interrupted_ddl_compatible_rollback_verified",
             "business_physically_readonly")), "DATA_PRESERVING_COMPATIBLE_ROLLBACK_REQUIRED")
    need({name for name, row in schema.get("schema_objects", {}).items() if row.get("type") == "table"} == TARGET_TABLES,
         "EXACT_REHEARSED_TWENTY_TABLE_SCHEMA_REQUIRED")
    return value


def verify_prepared_files(base, release, manifest):
    root = release / "prepared-backend/payload"
    for name, expected in manifest["payload_files"].items():
        need(sha(read(root / name, 16 * 1024**2)) == expected, "PREPARED_PAYLOAD_BYTES_CHANGED")
    need(base.file_map(root / "frontend/dist") == {
        name.removeprefix("frontend/dist/"): value for name, value in manifest["payload_files"].items()
        if name.startswith("frontend/dist/")}, "COMPLETE_PREPARED_STATIC_BYTES_REQUIRED")
    need(json.loads(read(root / "frontend/dist/app-version.json", 4096)) == {"version": manifest["frontend_version"]},
         "FROZEN_FRONTEND_VERSION_DRIFT")
    return root / "frontend/dist"


def runtime_boundary(base, pins):
    need(base.crm_check() == pins["crm"] and sha(base.read_protected(base.ENV)) == pins["environment_sha256"],
         "CRM_RUNTIME_OR_ORIGINAL_ENVIRONMENT_CHANGED")
    need(str(base.PRIVATE_DB) == pins["private_database"] and str(base.BUSINESS) == pins["business_database"]
         and str(base.NGINX) == pins["nginx_path"] and str(base.ENV) == pins["runtime_env_path"],
         "EXACT_REVIEWED_LIVE_PATHS_REQUIRED")


def old_roles(base, switch, legacy, pins, *, running):
    values = {}
    for role, row in pins["roles"].items():
        info = base.inspect(row["id"])
        configured = switch.environment(info)
        proof = legacy.own_role(base, switch, row["id"], role, row["image"], row["attempt"], row["source"],
            configured, running)
        need(proof == row["runtime"], "ORIGINAL_PRIVATE_RUNTIME_DRIFT")
        values[role] = configured
    return values


def install_public(base, static, old_root, public):
    """The only publish change is a new root plus retained hashed asset files."""
    for parent in (Path("/var"), Path("/var/www"), public.parent, old_root):
        info = parent.lstat()
        need(parent.resolve() == parent and stat.S_ISDIR(info.st_mode) and info.st_uid == 0
             and not info.st_mode & 0o022 and info.st_mode & 0o005 == 0o005, "PUBLIC_ANCESTOR_UNTRUSTED")
    need(not public.exists() and not public.is_symlink(), "NEW_PUBLIC_DIRECTORY_REQUIRED")
    fresh, old = base.file_map(static), base.file_map(old_root)
    desired = dict(fresh)
    for name, value in old.items():
        if name.startswith("assets/"):
            need(name not in desired or desired[name] == value, "HASHED_ASSET_COLLISION")
            desired.setdefault(name, value)
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    for name in sorted(desired):
        source = static / name if name in fresh else old_root / name
        destination = public / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        base.write_new(destination, source.read_bytes())
        destination.chmod(0o644)
    for path in public.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
    need(base.file_map(public) == desired and base.file_map(old_root) == old, "PUBLIC_INSTALL_BYTE_DRIFT")
    return desired


def changed_nginx(original, old_root, public, expected):
    need(sha(original) == expected, "PINNED_NGINX_BASELINE_REQUIRED")
    old, new = str(old_root).encode(), str(public).encode()
    need(original.count(old) == 1 and new not in original and b"127.0.0.1:8000" in original
         and b"127.0.0.1:8001" in original, "EXACT_PUBLIC_ROOT_SWITCH_REQUIRED")
    changed = original.replace(old, new, 1)
    need(changed.replace(new, old, 1) == original, "PROXY_AND_HEADERS_MUST_BE_BYTE_IDENTICAL")
    return changed


def authentication_probe(*, public=False, personal=True):
    origin = "https://t24-crm.com" if public else "http://127.0.0.1:8001"
    path = "/api/v1/private-workspace/personal-finance/state" if personal else "/api/v1/private-workspace"
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    try:
        result = opener.open(origin + path, timeout=5)
    except urllib.error.HTTPError as error:
        result = error
    with result:
        need(len(result.read(65537)) <= 65536 and result.code == 401
             and "no-store" in {piece.strip().lower() for piece in result.headers.get("Cache-Control", "").split(",")},
             "PRIVATE_AUTH_OR_CACHE_BOUNDARY_FAILED")


def snapshot_unchanged(prep, base, before, target, *, exact_rows):
    current = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(current["business"] == before["business"] and len(current["business"]["tables"]) == 83
         and current["private"]["identity"] == before["private"]["identity"]
         and current["private"]["schema_objects"] == target, "PRIVATE_OR_CRM_BOUNDARY_CHANGED")
    if exact_rows:
        need(current["private"]["tables"] == before["private"]["tables"], "PRIVATE_ROWS_CHANGED_BEFORE_WORKER_START")
    return current


def rollback(base, switch, legacy, prep, release, pins, candidate, state, values, before, target, original, changed):
    runtime_boundary(base, pins)
    legacy.stop_owned(base, switch, state, values)
    for role, row in pins["roles"].items():
        info = base.inspect(row["id"])
        need(info["Image"] == BASE_IMAGE and base.config_hash(info) == row["runtime"]["configuration_sha256"],
             "RETAINED_PRIVATE_CONFIGURATION_CHANGED")
        if info["State"]["Running"]:
            switch.docker(["stop", "--time", "30", row["id"]], timeout=45)
    legacy.no_writers(base, switch)
    frozen = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    preserved_before = json.loads(json.dumps(before))
    # A live CRM or candidate API can legitimately commit during publication.
    # Rejecting publication is safe, but rollback must keep those current rows
    # and restore availability. Schema, inode and CRM runtime still stay pinned.
    need(before["business"]["identity"] == frozen["business"]["identity"]
         and before["business"]["schema_objects"] == frozen["business"]["schema_objects"],
         "ROLLBACK_CRM_SCHEMA_OR_IDENTITY_CHANGED")
    preserved_before["business"] = frozen["business"]
    for name in BASE_TABLES:
        preserved_before["private"]["tables"][name] = frozen["private"]["tables"][name]
    state["rollback_preserves_current_data"] = True
    checked_partial_schema(preserved_before, frozen, target)
    current_nginx = sha(base.read_nginx())
    need(current_nginx in {sha(original), sha(changed)}, "ROLLBACK_NGINX_CONCURRENT_CHANGE")
    if current_nginx == sha(changed):
        base.atomic_nginx(original, {sha(changed)})
        base.run(["nginx", "-t"], "ROLLBACK_NGINX_TEST_FAILED")
        base.run(["systemctl", "reload", "nginx"], "ROLLBACK_NGINX_RELOAD_FAILED")
    stable = switch.stable_records(base.PRIVATE_DB)
    authorization = legacy.stable_authorization(base)
    state["rollback_attempt"] = uuid4().hex
    state["rollback_roles"] = {}
    save(release / "upgrade-state.json", state, replace=True)
    legacy.start_role(base, switch, release, state, "api", candidate["rollback_image_id"], BASE_SOURCE,
        values["api"], rollback=True)
    recovered = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(recovered["business"]["identity"] == frozen["business"]["identity"]
         and recovered["business"]["schema_objects"] == frozen["business"]["schema_objects"]
         and set(recovered["business"]["tables"]) == set(frozen["business"]["tables"])
         and recovered["private"]["identity"] == frozen["private"]["identity"]
         and recovered["private"]["schema_objects"] == target
         and all(recovered["private"]["tables"][name] == row for name, row in frozen["private"]["tables"].items()),
         "COMPATIBLE_ROLLBACK_CHANGED_EXISTING_DATA")
    state["rollback_crm_data_changed_during_recovery"] = recovered["business"]["tables"] != frozen["business"]["tables"]
    need(legacy.stable_authorization(base) == authorization, "ROLLBACK_CREDENTIALS_OR_AUTHORIZATION_CHANGED")
    switch.preserved(stable, switch.stable_records(base.PRIVATE_DB))
    authentication_probe(personal=False)
    base.public_check(base.file_map(Path(pins["public_root"])), pins["frontend_version"], Path(pins["public_root"]))
    legacy.start_role(base, switch, release, state, "worker", candidate["rollback_image_id"], BASE_SOURCE,
        values["worker"], rollback=True)
    runtime_boundary(base, pins)
    legacy.no_writers(base, switch, [row["id"] for row in state["rollback_roles"].values()])
    state.update(phase="PERSONAL_FINANCE_COMPATIBLE_ROLLBACK_VERIFIED", deployed=False,
        databases_restored=False, personal_schema_retained=True)
    save(release / "upgrade-state.json", state, replace=True)
    return state


def activate(release, manifest, preflight, candidate, *, manifest_sha256, preflight_sha256, candidate_sha256):
    checked_manifest(manifest); checked_preflight(preflight)
    checked_candidate(candidate, manifest, manifest_sha256, preflight_sha256)
    legacy = load_legacy("upgrade.py")
    base, _nav, prep, switch = legacy.retained_tools(LEGACY)
    static = verify_prepared_files(base, release, manifest)
    # Recheck immutable images and their prepared dependency/base-layer proof.
    base_info = prep.inspect_image(BASE_IMAGE)
    for name in ("image_id", "rollback_image_id"):
        info = prep.inspect_image(candidate[name])
        prep.verify_candidate_base(base_info, info)
    need(prep.inspect_image(candidate["image_id"])["Config"].get("Labels", {}).get("t24.private.source.sha") == SOURCE
         and prep.inspect_image(candidate["rollback_image_id"])["Config"].get("Labels", {}).get(
            "t24.private.rollback.schema-compatible") == "eleven-to-twenty-personal", "REVIEWED_IMAGE_LABELS_REQUIRED")
    with legacy.release_lock(base):
        runtime_boundary(base, preflight)
        values = old_roles(base, switch, legacy, preflight, running=True)
        original = base.read_nginx()
        need(sha(original) == preflight["nginx_sha256"], "FRESH_NGINX_DRIFT")
        old_root = Path(preflight["public_root"])
        base.public_check(base.file_map(old_root), preflight["frontend_version"], old_root)
        legacy.no_writers(base, switch, [row["id"] for row in preflight["roles"].values()])
        observed = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
        need(observed["private"]["identity"] == preflight["snapshot"]["private"]["identity"]
             and observed["private"]["schema_objects"] == preflight["snapshot"]["private"]["schema_objects"]
             and set(observed["private"]["tables"]) == BASE_TABLES
             and observed["business"]["schema_objects"] == preflight["snapshot"]["business"]["schema_objects"]
             and len(observed["business"]["tables"]) == 83, "FRESH_STRUCTURAL_BASELINE_DRIFT")
        public = old_root.parent / ("personal-finance-" + SOURCE[:12] + "-20261012")
        changed = changed_nginx(original, old_root, public, preflight["nginx_sha256"])
        target = target_schema(observed, candidate["synthetic_schema"]["schema_objects"])
        need(not (release / "live-upgrade").exists() and not (release / "upgrade-state.json").exists(), "NEW_ACTIVATION_STATE_REQUIRED")
        (release / "live-upgrade").mkdir(mode=0o700)
        state = {"format_version": 1, "phase": "PERSONAL_FINANCE_ACTIVATION_PREPARED", "source_sha": SOURCE,
            "frontend_version": manifest["frontend_version"], "candidate_image": candidate["image_id"],
            "rollback_image": candidate["rollback_image_id"], "candidate_sha256": candidate_sha256,
            "manifest_sha256": manifest_sha256, "preflight_sha256": preflight_sha256,
            "attempt": uuid4().hex, "old_ids": {role: row["id"] for role, row in preflight["roles"].items()},
            "old_runtime": {role: row["runtime"] for role, row in preflight["roles"].items()},
            "original_nginx_sha256": sha(original), "new_nginx_sha256": sha(changed),
            "public_root": str(public), "roles": {}, "deployed": False, "databases_restored": False,
            "worker_started": False}
        save(release / "upgrade-state.json", state)
        base.write_new(release / "live-upgrade/nginx-before.conf", original)
        # Private writers may have refreshed/synced since the readonly preflight.
        # Freeze their current state after stopping, rather than restoring it.
        before = None
        try:
            old_roles(base, switch, legacy, preflight, running=True)
            for role in ("worker", "api"):
                state["stop_intent"] = role
                save(release / "upgrade-state.json", state, replace=True)
                switch.docker(["stop", "--time", "30", preflight["roles"][role]["id"]], timeout=45)
            legacy.no_writers(base, switch)
            runtime_boundary(base, preflight)
            before = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
            need(before["private"]["identity"] == observed["private"]["identity"]
                 and before["private"]["schema_objects"] == observed["private"]["schema_objects"]
                 and before["business"]["schema_objects"] == observed["business"]["schema_objects"],
                 "STRUCTURE_CHANGED_DURING_WRITER_FREEZE")
            save(release / "live-upgrade/schema-before.json", before)
            state["backup_sha256"] = legacy.backup_private(base, prep, before, release / "live-upgrade/original-private.db")
            state["phase"] = "PERSONAL_FINANCE_BACKUP_VERIFIED"
            save(release / "upgrade-state.json", state, replace=True)
            stable = switch.stable_records(base.PRIVATE_DB)
            authorization = legacy.stable_authorization(base)
            legacy.run_initializer(base, switch, candidate["image_id"], state["attempt"], state, release / "upgrade-state.json")
            legacy.no_writers(base, switch)
            after = prep.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
            proof = compare_schema(before, after, target)
            save(release / "live-upgrade/schema-after.json", after)
            save(release / "live-upgrade/schema-validation.json", proof)
            state.update(phase="PERSONAL_FINANCE_LIVE_SCHEMA_VERIFIED", existing_private_tables_preserved=11,
                private_tables_verified=20, business_tables_verified=83, same_private_inode=True,
                new_personal_tables_empty=True, schema_validation_sha256=digest(proof))
            save(release / "upgrade-state.json", state, replace=True)
            legacy.start_role(base, switch, release, state, "api", candidate["image_id"], SOURCE, values["api"])
            snapshot_unchanged(prep, base, after, target, exact_rows=True)
            need(legacy.stable_authorization(base) == authorization, "PRIVATE_AUTHORIZATION_CHANGED_BEFORE_WORKER")
            authentication_probe()
            published = install_public(base, static, old_root, public)
            need(sha(base.read_nginx()) == sha(original), "PUBLICATION_NGINX_CONCURRENT_CHANGE")
            runtime_boundary(base, preflight)
            base.atomic_nginx(changed, {sha(original)})
            base.run(["nginx", "-t"], "PERSONAL_FINANCE_NGINX_TEST_FAILED")
            base.run(["systemctl", "reload", "nginx"], "PERSONAL_FINANCE_NGINX_RELOAD_FAILED")
            state["phase"] = "PERSONAL_FINANCE_STATIC_SWITCHED"
            save(release / "upgrade-state.json", state, replace=True)
            base.public_check(published, manifest["frontend_version"], public)
            authentication_probe(public=True)
            snapshot_unchanged(prep, base, after, target, exact_rows=True)
            need(legacy.stable_authorization(base) == authorization, "PRIVATE_AUTHORIZATION_CHANGED_BEFORE_WORKER")
            switch.preserved(stable, switch.stable_records(base.PRIVATE_DB), allow_provider_changes=False)
            legacy.start_role(base, switch, release, state, "worker", candidate["image_id"], SOURCE, values["worker"])
            state["worker_started"] = True
            legacy.no_writers(base, switch, [row["id"] for row in state["roles"].values()])
            snapshot_unchanged(prep, base, after, target, exact_rows=False)
            runtime_boundary(base, preflight)
            state.update(phase="PERSONAL_FINANCE_DEPLOYED_VERIFIED", deployed=True,
                environment_unchanged=True, crm_not_restarted=True, authorization_preserved_until_worker_start=True)
            state_hash = save(release / "upgrade-state.json", state, replace=True)
            return {"stage": state["phase"], "state_sha256": state_hash, "frontend_version": manifest["frontend_version"],
                    "image_id": candidate["image_id"], "private_tables": 20, "crm_tables": 83,
                    "deployed": True, "owner_ui_verified": False}
        except BaseException as failure:
            state.update(failure_code=safe_failure(failure), failure_phase=state["phase"])
            save(release / "upgrade-state.json", state, replace=True)
            try:
                if before is not None and state.get("backup_sha256"):
                    rollback(base, switch, legacy, prep, release, preflight, candidate, state, values,
                        before, target, original, changed)
                else:
                    # No reviewed backup/DDL yet: recover only the pinned old
                    # stopped writers. Never let rollback initialize new DDL.
                    for role in ("api", "worker"):
                        row = preflight["roles"][role]
                        info = base.inspect(row["id"])
                        need(info["Image"] == BASE_IMAGE and base.config_hash(info) == row["runtime"]["configuration_sha256"],
                             "PRE_DDL_OLD_ROLE_IDENTITY_DRIFT")
                        if not info["State"]["Running"]:
                            switch.docker(["start", row["id"]])
                    runtime_boundary(base, preflight)
                    state.update(phase="PERSONAL_FINANCE_PRE_DDL_ORIGINAL_ROLES_RECOVERED", deployed=False)
                    save(release / "upgrade-state.json", state, replace=True)
            except BaseException as recovery_failure:
                state.update(phase="PERSONAL_FINANCE_ROLLBACK_REQUIRES_REVIEW", deployed=False,
                    rollback_failure_code=safe_failure(recovery_failure))
                save(release / "upgrade-state.json", state, replace=True)
                raise ReleaseError("PERSONAL_FINANCE_ROLLBACK_REQUIRES_REVIEW") from None
            raise ReleaseError("PERSONAL_FINANCE_ACTIVATION_FAILED_ROLLBACK_VERIFIED") from None


def main(args):
    os.umask(0o077)
    need(os.geteuid() == 0 and socket.gethostname() == HOST and args.release == RELEASE,
         "EXACT_AUTHENTICATED_SERVER_RELEASE_REQUIRED")
    protected(args.release, directory=True)
    need(args.manifest == args.release / "manifest.json" and args.payload == args.release / "payload.tar.gz",
         "EXACT_ACQUIRED_ARTIFACT_PATHS_REQUIRED")
    manifest = fixed_json(args.manifest, args.manifest_sha256)
    preflight = fixed_json(args.preflight, args.preflight_sha256)
    checked_manifest(manifest); checked_preflight(preflight)
    archive = read(args.payload, 64 * 1024**2)
    need(sha(archive) == manifest["payload_sha256"], "REVIEWED_PAYLOAD_HASH_DRIFT")
    if args.stage == "prepare":
        return prepare(args.release, manifest, archive, preflight,
            manifest_sha256=args.manifest_sha256, preflight_sha256=args.preflight_sha256)
    need(args.candidate == args.release / "candidate.json" and args.candidate_sha256,
         "INDEPENDENT_REVIEWED_CANDIDATE_REQUIRED")
    candidate = fixed_json(args.candidate, args.candidate_sha256)
    return activate(args.release, manifest, preflight, candidate, manifest_sha256=args.manifest_sha256,
        preflight_sha256=args.preflight_sha256, candidate_sha256=args.candidate_sha256)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "activate"])
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-sha256")
    try:
        print(json.dumps(main(parser.parse_args()), sort_keys=True))
    except BaseException as error:
        code = str(error) if isinstance(error, ReleaseError) and re.fullmatch(r"[A-Z0-9_]{1,100}", str(error)) else "PERSONAL_FINANCE_RELEASE_REJECTED"
        print(json.dumps({"stage": "PERSONAL_FINANCE_RELEASE_REJECTED", "code": code, "deployed": False}, sort_keys=True))
        raise SystemExit(1)
