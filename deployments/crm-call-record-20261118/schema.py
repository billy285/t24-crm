"""Verify, rehearse and apply the additive sales communication record migration."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4


HOST_DATABASE = Path("/opt/t24-crm/app/data/crm_prod.db")
CONTAINER_DATA = "/app/backend/data"
OLD_REVISION = "n18f9a3c0452"
NEW_REVISION = "p18f9a3c0453"
MIGRATIONS = ((NEW_REVISION, OLD_REVISION, "p18f9a3c0453_sales_call_selections.py",
               "0750b8ed66698b38c29af1a660ae729529f5fccc0c6b68919a0d8401c137157f"),)
CALL_TABLE = "sales_call_activities"
NEW_COLUMN = "communication_record"
EXPECTED_SQL = "ALTER TABLE sales_call_activities ADD COLUMN communication_record JSON;"


def call_columns(database):
    return [tuple(row) for row in database.execute("PRAGMA table_xinfo(sales_call_activities)")]



def require(condition, error):
    if not condition:
        raise RuntimeError(error)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def docker(args, *, body=None, timeout=30):
    result = subprocess.run(["docker", *args], input=body, capture_output=True, timeout=timeout)
    require(result.returncode == 0 and len(result.stdout) <= 2_000_000, "CRM_SCHEMA_OFFLINE_DOCKER_CHECK_FAILED")
    return result.stdout


def database_for(original):
    """Verify the known production volume without exposing runtime configuration."""
    mount_entries = [entry for entry in original["Mounts"] if entry["Destination"] == CONTAINER_DATA]
    require(len(mount_entries) == 1, "CRM_DATABASE_MOUNT_REQUIRED")
    mount = mount_entries[0]
    require(mount["Type"] == "bind" and mount["RW"] and Path(mount["Source"]) == HOST_DATABASE.parent,
            "CRM_DATABASE_BIND_CHANGED")
    configuration = original["Config"]
    active_urls = [pair.partition("=")[2] for pair in configuration["Env"] if pair.startswith("DATABASE_URL=")]
    match = re.fullmatch(r"sqlite(?:\+aiosqlite)?:///([a-zA-Z0-9_./-]+)", active_urls[0]) if len(active_urls) == 1 else None
    require(match, "CRM_DATABASE_CONFIGURATION_CHANGED")
    value = Path(match[1])
    if not value.is_absolute():
        require(configuration["WorkingDir"] == "/app/backend", "CRM_DATABASE_RELATIVE_CONFIGURATION_CHANGED")
        value = Path(configuration["WorkingDir"]) / value
    require(value == Path(CONTAINER_DATA) / HOST_DATABASE.name, "CRM_DATABASE_CONFIGURATION_CHANGED")
    require(HOST_DATABASE.resolve(strict=True) == HOST_DATABASE and HOST_DATABASE.is_file(),
            "CRM_DATABASE_FILE_CHANGED")
    return HOST_DATABASE


def assert_writers(database, expected):
    running = docker(["ps", "--quiet", "--no-trunc"]).decode().split()
    writer_ids = set()
    if running:
        mounted = json.loads(docker(["inspect", *running], timeout=45))
        for entry in mounted:
            for mount in entry["Mounts"]:
                if mount["RW"] and database.is_relative_to(Path(mount["Source"]).resolve()):
                    writer_ids.add(entry["Id"])
    require(writer_ids == expected, "CRM_DATABASE_WRITER_SET_CHANGED")


def open_readonly(path):
    database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10, isolation_level=None)
    database.execute("PRAGMA query_only=ON")
    return database


def schema_items(database):
    return [tuple(row) for row in database.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    )]


def metadata(database):
    version = database.execute("SELECT version_num FROM alembic_version").fetchall()
    require(len(version) == 1 and version[0][0] in {OLD_REVISION, NEW_REVISION}, "UNREVIEWED_CRM_SCHEMA_REVISION")
    items = schema_items(database)
    tables = {item[1] for item in items if item[0] == "table"}
    require({"sales_leads", "merchant_pool", "app_settings"}.issubset(tables), "CRM_SCHEMA_BASE_TABLES_MISSING")
    require(CALL_TABLE in tables, "SALES_CALL_TABLE_MISSING")
    new = [column for column in call_columns(database) if column[1] == NEW_COLUMN]
    if version[0][0] == NEW_REVISION:
        require(len(new) == 1 and new[0][2:] == ("JSON", 0, None, 0, 0), "CRM_CALL_COLUMN_WRONG")
    else:
        require(not new, "CRM_SCHEMA_PARTIALLY_MIGRATED")
    return {
        "revision": version[0][0],
        "schema_sha256": digest(items),
        "table_count": len(tables),
        "database_pages_bytes": database.execute("PRAGMA page_count").fetchone()[0]
        * database.execute("PRAGMA page_size").fetchone()[0],
    }


def status(original, root):
    path = database_for(original)
    with closing(open_readonly(path)) as database:
        database.execute("BEGIN")
        return metadata(database)


def preflight(original, root):
    path = database_for(original)
    assert_writers(path, {original["Id"]})
    receipt = status(original, root)
    require(receipt["revision"] == OLD_REVISION, "CRM_SCHEMA_ALREADY_MIGRATED")
    required_capacity = receipt["database_pages_bytes"] * 3 + 64 * 1024 * 1024
    require(shutil.disk_usage(root).free >= required_capacity and shutil.disk_usage(path.parent).free >= required_capacity,
            "INSUFFICIENT_PRIVATE_BACKUP_SPACE")
    return receipt


def sync_private(path):
    with path.open("rb") as stream:
        require(os.fstat(stream.fileno()).st_mode & 0o777 == 0o600, "CRM_BACKUP_PERMISSION_MISMATCH")
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(source, target):
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    deadline = time.monotonic() + 65

    def enforce_deadline(_status, _remaining, _total):
        require(time.monotonic() < deadline, "CRM_PRIVATE_BACKUP_TIMED_OUT")

    try:
        with closing(open_readonly(source)) as old, closing(sqlite3.connect(target, timeout=10)) as copy:
            old.backup(copy, pages=128, progress=enforce_deadline, sleep=0.01)
        sync_private(target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def row_evidence(database, tables):
    """Prove all original rows survive without putting row contents in the receipt."""
    proofs = {}
    for name in sorted(tables):
        identifier = quote(name)
        columns = [quote(column[1]) for column in database.execute("PRAGMA table_info(" + identifier + ")")
                   if not (name == CALL_TABLE and column[1] == NEW_COLUMN)]
        require(columns, "CRM_ROW_PROOF_COLUMN_MISSING")
        order = ",".join(map(str, range(1, len(columns) + 1)))
        projection = ",".join(columns)
        count = 0
        hashed = hashlib.sha256()
        for row in database.execute(f"SELECT {projection} FROM {identifier} ORDER BY {order}"):
            encoded = json.dumps([{"blob": value.hex()} if isinstance(value, bytes) else value for value in row],
                                 ensure_ascii=True, separators=(",", ":")).encode()
            hashed.update(len(encoded).to_bytes(8, "big"))
            hashed.update(encoded)
            count += 1
        proofs[name] = (count, hashed.hexdigest())
    return digest(proofs)


def retained_tables(items):
    return {item[1] for item in items if item[0] == "table" and item[1] != "alembic_version"}


def verified_backup(target, expected_schema):
    with closing(open_readonly(target)) as copy:
        copy.execute("BEGIN")
        require(copy.execute("PRAGMA quick_check").fetchall() == [("ok",)], "CRM_BACKUP_INTEGRITY_FAILED")
        before = metadata(copy)
        require(before["revision"] == OLD_REVISION and before["schema_sha256"] == expected_schema,
                "CRM_BACKUP_SCHEMA_DIFFERS")
        return row_evidence(copy, retained_tables(schema_items(copy)))


OFFLINE_COMPILER = """
import hashlib, json, sqlite3
from io import StringIO
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations

buffer = StringIO()
with Operations.context(MigrationContext.configure(url="sqlite://", opts={"as_sql": True, "output_buffer": buffer})):
    for revision, predecessor, filename, digest in MIGRATIONS:
        path = Path("/app/backend/alembic/versions") / filename
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        migration = {"__name__": "reviewed_sales_migration", "__file__": str(path)}
        exec(compile(content, str(path), "exec"), migration)
        assert migration["revision"] == revision and migration["down_revision"] == predecessor
        migration["upgrade"]()
statements = []
chunk = ""
for piece in buffer.getvalue():
    chunk += piece
    if piece == ";" and sqlite3.complete_statement(chunk):
        statements.append(chunk.strip())
        chunk = ""
assert not chunk.strip()
print(json.dumps(statements))
"""


def isolated_python(image, script, *, snapshot=None):
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image), "IMMUTABLE_CRM_SCHEMA_IMAGE_REQUIRED")
    command = ["run", "--rm", "--interactive", "--network=none", "--read-only", "--cap-drop=ALL",
               "--security-opt=no-new-privileges", "--pids-limit=96", "--memory=512m", "--user=0:0"]
    if snapshot:
        command += ["--mount", f"type=bind,src={snapshot},dst=/validation/crm.sqlite3,readonly"]
    for key, value in {
        "APP_ENV": "test",
        "ENVIRONMENT": "test",
        "DATABASE_SCHEMA_MODE": "verify_only",
        "DATABASE_URL": "sqlite+aiosqlite:////validation/crm.sqlite3",
        "JWT_SECRET_KEY": "isolated-schema-verify-synthetic-do-not-use",
        "MASK_KEY": "isolated-schema-verify-synthetic-do-not-use",
        "OPENAI_API_KEY": "",
    }.items():
        command += ["-e", f"{key}={value}"]
    return docker([*command, "--entrypoint=python", image, "-I", "-B", "-"], body=script.encode(), timeout=120)


def validate_statements(statements):
    require(statements == [EXPECTED_SQL], "EXACT_ADDITIVE_CALL_COLUMN_REQUIRED")


def apply_atomic(path, statements, expected_before, *, expected_after=None, private_backup=None):
    """Preserve all old objects and records in a single write transaction."""
    validate_statements(statements)
    with closing(sqlite3.connect(path, isolation_level=None, timeout=20)) as database:
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("BEGIN IMMEDIATE")
        try:
            before = schema_items(database)
            require(metadata(database)["revision"] == OLD_REVISION and digest(before) == expected_before,
                    "CRM_SCHEMA_BASELINE_DRIFTED")
            tables = retained_tables(before)
            previous_columns = call_columns(database)
            if private_backup:
                backup(path, private_backup)
                expected_rows = verified_backup(private_backup, expected_before)
                require(row_evidence(database, tables) == expected_rows, "CRM_BACKUP_ROWS_DIFFER")
            else:
                expected_rows = row_evidence(database, tables)
            for statement in statements:
                database.execute(statement)
            after = schema_items(database)
            previous_call = [item for item in before if item[:2] == ("table", CALL_TABLE)]
            updated_call = [item for item in after if item[:2] == ("table", CALL_TABLE)]
            require(len(previous_call) == len(updated_call) == 1 and set(before) - set(previous_call)
                    == set(after) - set(updated_call), "EXISTING_CRM_OBJECTS_CHANGED")
            columns = call_columns(database)
            require(columns[:-1] == previous_columns and columns[-1][1:] == (NEW_COLUMN, "JSON", 0, None, 0, 0),
                    "UNREVIEWED_CALL_COLUMN_CHANGE")
            require(not expected_after or digest(after) == expected_after, "CRM_SCHEMA_DIFFERS_FROM_REHEARSAL")
            require(database.execute("SELECT 1 FROM sales_call_activities WHERE communication_record IS NOT NULL LIMIT 1")
                    .fetchone() is None, "INITIAL_CALL_COLUMN_MUST_BE_NULL")
            require(database.execute("UPDATE alembic_version SET version_num=? WHERE version_num=?",
                                     (NEW_REVISION, OLD_REVISION)).rowcount == 1, "CRM_SCHEMA_HEAD_UPDATE_FAILED")
            require(row_evidence(database, tables) == expected_rows, "CRM_MIGRATION_CHANGED_EXISTING_ROWS")
            require(database.execute("PRAGMA quick_check").fetchall() == [("ok",)], "CRM_SCHEMA_INTEGRITY_FAILED")
            got = metadata(database)
            database.commit()
            return {**got, "existing_rows_preserved": True, "existing_schema_preserved": True,
                    "private_backup_verified": private_backup is not None}
        except BaseException:
            database.rollback()
            raise


OFFLINE_VALIDATOR = """
import hashlib, json, sqlite3, sys
sys.path.insert(0, "/app/backend")
from core.database import Base
from services.database import _alembic_heads, _load_all_models
from services.schema_readiness import RUNTIME_REQUIRED_TABLE_COLUMNS

_load_all_models()
assert _alembic_heads() == {REVISION}
conn = sqlite3.connect("file:/validation/crm.sqlite3?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")
assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [(REVISION,)]
schema = [tuple(row) for row in conn.execute(
    "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
)]
assert hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest() == SCHEMA
expected = {table.name: {column.name for column in table.columns} for table in Base.metadata.tables.values()}
expected.update({name: set(columns) for name, columns in RUNTIME_REQUIRED_TABLE_COLUMNS.items()})
names = {row[1] for row in schema if row[0] == "table"}
assert expected.keys() <= names
for table, columns in expected.items():
    identifier = '"' + table.replace('"', '""') + '"'
    assert columns <= {row[1] for row in conn.execute("PRAGMA table_info(" + identifier + ")")}
print("crm_schema_verified")
"""


def prepare(original, root, candidate_image, fallback_image):
    before = preflight(original, root)
    compiler = f"MIGRATIONS = {MIGRATIONS!r}\n" + OFFLINE_COMPILER
    sql = json.loads(isolated_python(candidate_image, compiler))
    path = database_for(original)
    with tempfile.TemporaryDirectory(prefix="crm-schema-rehearsal-", dir=root) as temporary:
        clone = Path(temporary) / "crm.sqlite3"
        backup(path, clone)
        after = apply_atomic(clone, sql, before["schema_sha256"])
        with closing(sqlite3.connect(clone, timeout=10)) as db:
            require(db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0, "CRM_CLONE_CHECKPOINT_FAILED")
        validator = f"REVISION = {NEW_REVISION!r}\nSCHEMA = {after['schema_sha256']!r}\n" + OFFLINE_VALIDATOR
        for image in (candidate_image, fallback_image):
            require(isolated_python(image, validator, snapshot=clone).strip() == b"crm_schema_verified",
                    "CRM_IMAGE_SCHEMA_BOOTSTRAP_CHECK_FAILED")
    return {"before": before, "after": after, "statements": sql, "candidate_schema_verified": True,
            "fallback_schema_verified": True}


def migrate(original, root, proof):
    path = database_for(original)
    require(json.loads(docker(["inspect", "--format", "{{json .State.Running}}", original["Id"]])) is False,
            "CRM_ORIGINAL_RUNTIME_MUST_BE_STOPPED")
    assert_writers(path, set())
    require(proof["candidate_schema_verified"] and proof["fallback_schema_verified"], "CRM_MIGRATION_REHEARSAL_REQUIRED")
    require(proof["before"]["revision"] == OLD_REVISION and proof["after"]["revision"] == NEW_REVISION,
            "UNREVIEWED_CRM_MIGRATION_PROOF")
    # This private backup is sealed and verified before the live commit.
    permanent = root / f"crm-pre-migration-{uuid4().hex}.sqlite3"
    result = apply_atomic(path, proof["statements"], proof["before"]["schema_sha256"],
                          expected_after=proof["after"]["schema_sha256"], private_backup=permanent)
    return {**result, "backup_name": permanent.name}
