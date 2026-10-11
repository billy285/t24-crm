"""Real SQLite schema migration proofs using actual private SQLAlchemy models.

All writes are confined to TemporaryDirectory fixtures. Never production data.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from sqlalchemy import create_engine

import private_schema_guard as guard


SOURCE = 'a' * 40
NINE_TABLES = guard.BASE_TABLES | frozenset({
    'private_mail_translations', 'private_translation_usage', 'private_mail_briefs',
    'private_mail_brief_usage', 'private_workspace_briefs',
})
MODEL_PATH = Path(__file__).resolve().parents[2] / 'app/backend/models/private_workspace.py'
spec = importlib.util.spec_from_file_location('private_release_fixture_models', MODEL_PATH)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


class SchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.private = self.root / 'private.db'
        self.business = self.root / 'business.db'
        engine = create_engine('sqlite:///' + str(self.private))
        models.PrivateWorkspaceBase.metadata.create_all(
            engine, tables=[models.PrivateWorkspaceBase.metadata.tables[name] for name in guard.BASE_TABLES])
        engine.dispose()
        with sqlite3.connect(self.private) as db:
            # A synthetic stored credential is never returned by the guard.
            db.execute("INSERT INTO private_connections (id,owner_id,source_id,status,metadata_json,generation,encrypted_credentials,created_at,updated_at)"
                       " VALUES ('source','4','gmail','connected','{}',1,'SYNTHETIC_CREDENTIAL_MUST_NOT_LEAK','2026-10-11','2026-10-11')")
            db.execute("INSERT INTO private_preferences (owner_id,preferences_json,updated_at) VALUES ('4','{}','2026-10-11')")
        with sqlite3.connect(self.business) as db:
            db.execute('CREATE TABLE finance_sentinel (id INTEGER PRIMARY KEY, amount INTEGER NOT NULL)')
            db.execute('INSERT INTO finance_sentinel VALUES (1,70000)')
        self.private.chmod(0o600)
        self.business.chmod(0o600)
        self.before = guard.release_snapshot(self.private, self.business)
        engine = create_engine('sqlite:///' + str(self.private))
        models.PrivateWorkspaceBase.metadata.create_all(
            engine, tables=[models.PrivateWorkspaceBase.metadata.tables[name] for name in NINE_TABLES])
        engine.dispose()
        self.after = guard.release_snapshot(self.private, self.business)
        self.manifest = {
            'format_version': 1, 'stage': 'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST', 'source_sha': SOURCE,
            'baseline_tables': sorted(guard.BASE_TABLES), 'target_tables': sorted(NINE_TABLES),
            'target_schema_objects': self.after['private']['schema_objects'],
            'business_table_count': 1, 'business_schema_sha256': self.before['business']['schema_sha256'],
        }

    def validate(self, before=None, after=None, manifest=None, mode='in_place'):
        return guard.compare_snapshots(before or self.before, after or self.after,
                                       manifest or self.manifest, source_sha=SOURCE, mode=mode)

    def test_actual_four_to_nine_preserves_data_columns_indexes_and_finance(self):
        self.assertEqual(set(self.before['private']['tables']), guard.BASE_TABLES)
        self.assertEqual(set(self.after['private']['tables']), NINE_TABLES)
        result = self.validate()
        self.assertTrue(result['business_unchanged'])
        self.assertTrue(result['original_rows_columns_indexes_preserved'])

    def test_actual_bank_link_tenth_table_requires_exact_new_manifest(self):
        engine = create_engine('sqlite:///' + str(self.private))
        models.PrivateBankLink.__table__.create(engine)
        engine.dispose()
        after = guard.release_snapshot(self.private, self.business)
        with self.assertRaisesRegex(guard.GuardError, 'TARGET_PRIVATE_INVENTORY_DRIFT'):
            self.validate(after=after)
        manifest = copy.deepcopy(self.manifest)
        manifest['target_tables'] = sorted(NINE_TABLES | {'private_bank_links'})
        manifest['target_schema_objects'] = after['private']['schema_objects']
        result = self.validate(after=after, manifest=manifest)
        self.assertEqual(set(result['target_tables']), NINE_TABLES | {'private_bank_links'})
        self.assertTrue(result['original_rows_columns_indexes_preserved'])
        self.assertTrue(result['business_unchanged'])

    def test_receipts_never_include_credentials_or_finance_values(self):
        encoded = json.dumps([self.before, self.after, self.validate()])
        self.assertNotIn('SYNTHETIC_CREDENTIAL_MUST_NOT_LEAK', encoded)
        self.assertNotIn('70000', encoded)
        self.assertNotIn('INSERT INTO', encoded)

    def test_original_row_change_is_rejected(self):
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET encrypted_credentials='different' WHERE id='source'")
        with self.assertRaisesRegex(guard.GuardError, 'ORIGINAL_PRIVATE_COLUMNS_OR_ROWS_CHANGED'):
            self.validate(after=guard.release_snapshot(self.private, self.business))

    def test_original_column_and_index_changes_are_rejected_even_if_manifest_copied(self):
        for statement in [
            'ALTER TABLE private_connections ADD COLUMN unexpected TEXT',
            'CREATE INDEX unexpected_index ON private_connections(status)',
        ]:
            with self.subTest(statement=statement):
                temporary = self.root / ('copy-' + str(len(statement)) + '.db')
                shutil.copyfile(self.private, temporary)
                temporary.chmod(0o600)
                with sqlite3.connect(temporary) as db:
                    db.execute(statement)
                after = guard.release_snapshot(temporary, self.business)
                manifest = copy.deepcopy(self.manifest)
                manifest['target_schema_objects'] = after['private']['schema_objects']
                with self.assertRaisesRegex(guard.GuardError, 'ORIGINAL_PRIVATE_'):
                    self.validate(after=after, manifest=manifest, mode='clone')

    def test_finance_change_is_rejected(self):
        with sqlite3.connect(self.business) as db:
            db.execute('UPDATE finance_sentinel SET amount=0')
        with self.assertRaisesRegex(guard.GuardError, 'BUSINESS_FILE_SCHEMA_OR_DATA_CHANGED'):
            self.validate(after=guard.release_snapshot(self.private, self.business))

    def test_private_business_alias_and_wrong_owner_are_rejected(self):
        with self.assertRaisesRegex(guard.GuardError, 'PRIVATE_BUSINESS_DATABASE_ALIAS_REJECTED'):
            guard.release_snapshot(self.private, self.private)
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET owner_id='5'")
        with self.assertRaisesRegex(guard.GuardError, 'PRIVATE_OWNER_SCOPE_DRIFT'):
            guard.release_snapshot(self.private, self.business)

    def test_database_replacement_requires_explicit_clone_mode(self):
        clone = self.root / 'clone.db'
        shutil.copyfile(self.private, clone)
        clone.chmod(0o600)
        after = guard.release_snapshot(clone, self.business)
        with self.assertRaisesRegex(guard.GuardError, 'PRIVATE_DATABASE_FILE_REPLACED'):
            self.validate(after=after)
        self.assertEqual(self.validate(after=after, mode='clone')['mode'], 'clone')

    def test_mixed_business_table_and_symlink_and_exposed_modes_fail_closed(self):
        link = self.root / 'alias.db'
        link.symlink_to(self.private)
        with self.assertRaises(guard.GuardError):
            guard.release_snapshot(link, self.business)
        self.private.chmod(0o644)
        with self.assertRaisesRegex(guard.GuardError, 'PRIVATE_FILE_OWNER_OR_MODE_REJECTED'):
            guard.release_snapshot(self.private, self.business)
        self.private.chmod(0o600)
        with sqlite3.connect(self.private) as db:
            db.execute('CREATE TABLE business_payment (id TEXT)')
        with self.assertRaisesRegex(guard.GuardError, 'MIXED_PRIVATE_SCHEMA_REJECTED'):
            guard.release_snapshot(self.private, self.business)

    def test_unlisted_tenth_table_rejected_and_explicit_frozen_inventory_can_accept_it(self):
        with sqlite3.connect(self.private) as db:
            db.execute('CREATE TABLE private_bank_accounts (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)')
        after = guard.release_snapshot(self.private, self.business)
        with self.assertRaisesRegex(guard.GuardError, 'TARGET_PRIVATE_INVENTORY_DRIFT'):
            self.validate(after=after)
        manifest = copy.deepcopy(self.manifest)
        manifest['target_tables'].append('private_bank_accounts')
        manifest['target_schema_objects'] = after['private']['schema_objects']
        self.assertEqual(len(self.validate(after=after, manifest=manifest)['target_tables']), 10)

    def test_new_table_rows_before_acceptance_are_rejected(self):
        with sqlite3.connect(self.private) as db:
            db.execute("INSERT INTO private_translation_usage (owner_id,month,characters,updated_at) VALUES ('4','2026-10',1,'2026-10-11')")
        with self.assertRaisesRegex(guard.GuardError, 'NEW_PRIVATE_TABLES_MUST_BE_EMPTY'):
            self.validate(after=guard.release_snapshot(self.private, self.business))

    def test_readonly_snapshot_does_not_change_database_bytes_and_receipt_is_exclusive(self):
        before = self.private.read_bytes(), self.business.read_bytes()
        guard.release_snapshot(self.private, self.business)
        self.assertEqual(before, (self.private.read_bytes(), self.business.read_bytes()))
        output = self.root / 'receipt.json'
        guard._write_receipt(output, self.validate())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            guard._write_receipt(output, self.validate())

    def test_unfrozen_or_stale_source_and_non_four_baseline_rejected(self):
        for field, value in [('stage', 'PREPARATION_ONLY'), ('source_sha', 'b' * 40),
                             ('baseline_tables', sorted(NINE_TABLES))]:
            manifest = copy.deepcopy(self.manifest)
            manifest[field] = value
            with self.subTest(field=field), self.assertRaises(guard.GuardError):
                self.validate(manifest=manifest)

    def test_actual_cli_snapshot_and_pinned_validation_emit_only_controlled_receipts(self):
        script = Path(guard.__file__).resolve()
        before, after, manifest, result = [self.root / name for name in ('before.json', 'after.json', 'manifest.json', 'result.json')]
        guard._write_receipt(before, self.before)
        guard._write_receipt(manifest, self.manifest)
        response = subprocess.run([sys.executable, str(script), 'snapshot', '--private-db', str(self.private),
                                   '--business-db', str(self.business), '--output', str(after)], capture_output=True, text=True)
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        command = [sys.executable, str(script), 'validate', '--source-sha', SOURCE, '--mode', 'in_place', '--output', str(result)]
        for name, path in [('before', before), ('after', after), ('manifest', manifest)]:
            command.extend(['--' + name, str(path), '--' + name + '-sha256', hashlib.sha256(path.read_bytes()).hexdigest()])
        response = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        self.assertEqual(json.loads(response.stdout)['stage'], 'PRIVATE_ADDITIVE_SCHEMA_VALIDATED')
        self.assertTrue(json.loads(result.read_bytes())['business_unchanged'])
        self.assertNotIn('SYNTHETIC_CREDENTIAL_MUST_NOT_LEAK', response.stdout + response.stderr)

    def test_frozen_json_hash_and_public_receipt_directory_are_rejected(self):
        manifest = self.root / 'manifest.json'
        guard._write_receipt(manifest, self.manifest)
        with self.assertRaisesRegex(guard.GuardError, 'FROZEN_JSON_BYTES_CHANGED'):
            guard._read_json(manifest, '0' * 64)
        public = self.root / 'public'
        public.mkdir(mode=0o755)
        with self.assertRaisesRegex(guard.GuardError, 'PROTECTED_RECEIPT_DIRECTORY_REQUIRED'):
            guard._write_receipt(public / 'receipt.json', self.validate())


if __name__ == '__main__':
    unittest.main()
