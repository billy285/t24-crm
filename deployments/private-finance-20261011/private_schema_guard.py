#!/usr/bin/env python3
"""Read-only private release snapshots and explicit additive-schema validation.

This program never executes DDL, writes either database, starts containers,
reads environment credentials, or publishes files. Receipts contain hashes,
counts, schema metadata and file identity only, never record values or SQL text.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat


BASE_TABLES = frozenset({
    'private_connections', 'private_items', 'private_preferences', 'private_sync_runs',
})
HASH = re.compile(r'[a-f0-9]{64}')
PRIVATE_NAME = re.compile(r'private_[a-z][a-z0-9_]{0,79}')


class GuardError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise GuardError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _file_identity(path, *, protected):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_ABSOLUTE_PATH_REQUIRED')
    for ancestor in (path, *path.parents):
        need(not stat.S_ISLNK(ancestor.lstat().st_mode), 'PATH_SYMLINK_REJECTED')
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'REGULAR_SINGLE_LINK_FILE_REQUIRED')
    if protected:
        need(info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o077,
             'PRIVATE_FILE_OWNER_OR_MODE_REJECTED')
        parent = path.parent.stat()
        need(parent.st_uid == os.geteuid() and not stat.S_IMODE(parent.st_mode) & 0o077,
             'PRIVATE_DIRECTORY_OWNER_OR_MODE_REJECTED')
    return {'device': info.st_dev, 'inode': info.st_ino,
            'path_sha256': digest(str(path)), 'uid': info.st_uid,
            'mode': stat.S_IMODE(info.st_mode)}


def _rows_digest(db, table, columns):
    # Stable order with duplicate records is sufficient: identical rows have
    # identical bytes. No record value leaves this process or enters a receipt.
    order = ','.join(_quote(column[1]) for column in columns)
    stream = db.execute('SELECT * FROM ' + _quote(table) + ' ORDER BY ' + order)
    h = hashlib.sha256()
    count = 0
    for row in stream:
        encoded = json.dumps(list(row), ensure_ascii=False, separators=(',', ':'),
                             default=lambda value: {'bytes_hex': bytes(value).hex()}).encode()
        h.update(len(encoded).to_bytes(8, 'big'))
        h.update(encoded)
        count += 1
    return {'rows': count, 'rows_sha256': h.hexdigest()}


def database_snapshot(path, *, private, owner_id='4'):
    identity = _file_identity(path, protected=private)
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'DATABASE_INTEGRITY_FAILED')
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        names = sorted(row[1] for row in schema if row[0] == 'table')
        need(names, 'EMPTY_DATABASE_REJECTED')
        if private:
            need(all(PRIVATE_NAME.fullmatch(name) for name in names), 'MIXED_PRIVATE_SCHEMA_REJECTED')
        else:
            need(not any(name.startswith('private_') for name in names), 'PRIVATE_TABLE_IN_BUSINESS_REJECTED')
        objects = {}
        for kind, name, table, sql in schema:
            need(kind in {'table', 'index'}, 'TRIGGER_OR_VIEW_REQUIRES_SEPARATE_REVIEW')
            objects[name] = {'type': kind, 'table': table, 'sql_sha256': digest(sql)}
        tables = {}
        for table in names:
            columns = db.execute('PRAGMA table_info(' + _quote(table) + ')').fetchall()
            need(columns, 'TABLE_WITHOUT_COLUMNS_REJECTED')
            if private:
                need('owner_id' in {column[1] for column in columns}, 'PRIVATE_OWNER_COLUMN_REQUIRED')
                need(db.execute('SELECT 1 FROM ' + _quote(table) +
                                ' WHERE owner_id IS NULL OR owner_id <> ? LIMIT 1', (owner_id,)).fetchone() is None,
                     'PRIVATE_OWNER_SCOPE_DRIFT')
            tables[table] = {'columns_sha256': digest(columns), **_rows_digest(db, table, columns)}
    need(_file_identity(path, protected=private) == identity, 'DATABASE_FILE_IDENTITY_CHANGED')
    return {'identity': identity, 'tables': tables, 'schema_objects': objects,
            'schema_sha256': digest(objects), 'data_sha256': digest(tables)}


def release_snapshot(private_path, business_path, *, owner_id='4'):
    need(not os.path.samefile(private_path, business_path), 'PRIVATE_BUSINESS_DATABASE_ALIAS_REJECTED')
    private = database_snapshot(private_path, private=True, owner_id=owner_id)
    business = database_snapshot(business_path, private=False)
    return {'format_version': 1, 'stage': 'PRIVATE_READONLY_SCHEMA_SNAPSHOT',
            'mutation_performed': False, 'owner_id': owner_id,
            'private': private, 'business': business}


def checked_manifest(manifest, *, source_sha):
    need(manifest.get('format_version') == 1 and manifest.get('stage') == 'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST',
         'FROZEN_MANIFEST_REQUIRED')
    need(re.fullmatch(r'[a-f0-9]{40}', source_sha or '') and manifest.get('source_sha') == source_sha,
         'EXACT_CANDIDATE_SOURCE_REQUIRED')
    baseline = manifest.get('baseline_tables')
    target = manifest.get('target_tables')
    need(isinstance(baseline, list) and len(baseline) == len(set(baseline)) and set(baseline) == BASE_TABLES,
         'THIS_GUARD_REQUIRES_REVIEWED_FOUR_TABLE_BASELINE')
    need(isinstance(target, list) and len(target) == len(set(target)) and 4 < len(target) <= 20
         and BASE_TABLES < set(target) and all(PRIVATE_NAME.fullmatch(name) for name in target),
         'EXPLICIT_PRIVATE_TARGET_TABLES_REQUIRED')
    objects = manifest.get('target_schema_objects')
    need(isinstance(objects, dict) and objects and
         {name for name, value in objects.items() if isinstance(value, dict) and value.get('type') == 'table'} == set(target),
         'EXACT_TARGET_SCHEMA_OBJECTS_REQUIRED')
    for name, value in objects.items():
        need(isinstance(name, str) and isinstance(value, dict) and
             set(value) == {'type', 'table', 'sql_sha256'} and value['type'] in {'table', 'index'}
             and value['table'] in target and isinstance(value['sql_sha256'], str)
             and HASH.fullmatch(value['sql_sha256']), 'INVALID_TARGET_SCHEMA_OBJECT')
    need(isinstance(manifest.get('business_table_count'), int) and manifest['business_table_count'] > 0
         and isinstance(manifest.get('business_schema_sha256'), str)
         and HASH.fullmatch(manifest['business_schema_sha256']), 'BUSINESS_SCHEMA_PIN_REQUIRED')
    return set(target)


def compare_snapshots(before, after, manifest, *, source_sha, mode):
    target = checked_manifest(manifest, source_sha=source_sha)
    for snapshot in (before, after):
        need(snapshot.get('format_version') == 1 and snapshot.get('stage') == 'PRIVATE_READONLY_SCHEMA_SNAPSHOT'
             and snapshot.get('mutation_performed') is False and snapshot.get('owner_id') == '4',
             'VALID_OWNER_READONLY_SNAPSHOT_REQUIRED')
        need(snapshot['business']['schema_sha256'] == manifest['business_schema_sha256']
             and len(snapshot['business']['tables']) == manifest['business_table_count'],
             'BUSINESS_SCHEMA_OR_TABLE_COUNT_DRIFT')
    old, new = before['private'], after['private']
    need(set(old['tables']) == BASE_TABLES, 'BASELINE_PRIVATE_INVENTORY_DRIFT')
    need(set(new['tables']) == target, 'TARGET_PRIVATE_INVENTORY_DRIFT')
    need(new['schema_objects'] == manifest['target_schema_objects'], 'TARGET_DDL_OR_INDEX_DRIFT')
    need(mode in {'clone', 'in_place'}, 'EXPLICIT_VALIDATION_MODE_REQUIRED')
    if mode == 'in_place':
        need(old['identity'] == new['identity'], 'PRIVATE_DATABASE_FILE_REPLACED')
    else:
        need((old['identity']['device'], old['identity']['inode']) !=
             (new['identity']['device'], new['identity']['inode']), 'CLONE_MUST_HAVE_DISTINCT_IDENTITY')
    for name in BASE_TABLES:
        need(old['tables'][name] == new['tables'][name], 'ORIGINAL_PRIVATE_COLUMNS_OR_ROWS_CHANGED')
    original_objects = {name: value for name, value in old['schema_objects'].items() if value['table'] in BASE_TABLES}
    preserved_objects = {name: value for name, value in new['schema_objects'].items() if value['table'] in BASE_TABLES}
    need(original_objects == preserved_objects, 'ORIGINAL_PRIVATE_DDL_OR_INDEX_CHANGED')
    need(all(new['tables'][name]['rows'] == 0 for name in target - BASE_TABLES),
         'NEW_PRIVATE_TABLES_MUST_BE_EMPTY_BEFORE_CONNECTORS_START')
    need(before['business'] == after['business'], 'BUSINESS_FILE_SCHEMA_OR_DATA_CHANGED')
    return {'stage': 'PRIVATE_ADDITIVE_SCHEMA_VALIDATED', 'format_version': 1,
            'source_sha': source_sha, 'mode': mode, 'owner_id': '4',
            'original_tables_preserved': sorted(BASE_TABLES), 'target_tables': sorted(target),
            'original_rows_columns_indexes_preserved': True, 'new_tables_empty': True,
            'business_unchanged': True, 'databases_written_by_validator': False,
            'before_sha256': digest(before), 'after_sha256': digest(after),
            'manifest_sha256': digest(manifest)}


def _read_json(path, expected_sha256):
    path = Path(path)
    identity = _file_identity(path, protected=True)
    need(path.stat().st_size <= 4 * 1024**2,
         'BOUNDED_REGULAR_JSON_REQUIRED')
    raw = path.read_bytes()
    need(HASH.fullmatch(expected_sha256 or '') and hashlib.sha256(raw).hexdigest() == expected_sha256,
         'FROZEN_JSON_BYTES_CHANGED')
    need(_file_identity(path, protected=True) == identity, 'JSON_FILE_IDENTITY_CHANGED')
    return json.loads(raw)


def _write_receipt(path, value):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path and not path.is_symlink(),
         'CANONICAL_RECEIPT_PATH_REQUIRED')
    parent = path.parent.stat()
    need(parent.st_uid == os.geteuid() and not stat.S_IMODE(parent.st_mode) & 0o077,
         'PROTECTED_RECEIPT_DIRECTORY_REQUIRED')
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main(args):
    if args.command == 'snapshot':
        value = release_snapshot(args.private_db, args.business_db)
    else:
        manifest = _read_json(args.manifest, args.manifest_sha256)
        value = compare_snapshots(_read_json(args.before, args.before_sha256),
                                  _read_json(args.after, args.after_sha256), manifest,
                                  source_sha=args.source_sha, mode=args.mode)
    _write_receipt(args.output, value)
    print(json.dumps({'stage': value['stage'], 'receipt_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'mutation_performed': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    snapshot = commands.add_parser('snapshot')
    snapshot.add_argument('--private-db', type=Path, required=True)
    snapshot.add_argument('--business-db', type=Path, required=True)
    snapshot.add_argument('--output', type=Path, required=True)
    validate = commands.add_parser('validate')
    validate.add_argument('--before', type=Path, required=True)
    validate.add_argument('--before-sha256', required=True)
    validate.add_argument('--after', type=Path, required=True)
    validate.add_argument('--after-sha256', required=True)
    validate.add_argument('--manifest', type=Path, required=True)
    validate.add_argument('--manifest-sha256', required=True)
    validate.add_argument('--source-sha', required=True)
    validate.add_argument('--mode', choices=('clone', 'in_place'), required=True)
    validate.add_argument('--output', type=Path, required=True)
    try:
        main(parser.parse_args())
    except Exception as exc:
        # sqlite errors, malformed data and OS exceptions can include paths or
        # record values; only fixed GuardError codes leave the process.
        print(json.dumps({'stage': 'PRIVATE_SCHEMA_VALIDATION_REJECTED',
                          'code': str(exc) if isinstance(exc, GuardError) else type(exc).__name__,
                          'mutation_performed': False}, sort_keys=True))
        raise SystemExit(1)
