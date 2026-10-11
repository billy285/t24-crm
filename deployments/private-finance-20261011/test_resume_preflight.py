"""Actual synthetic SQLite boundaries; mocked runtime, no platforms or secrets."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app/backend'))
import candidate_prepare as candidate
import resume_preflight as resume
import seed_private_stripe as seed
import switch_completed as switch


class ResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.root.chmod(0o700)
        self.releases = self.root / 'releases'; self.releases.mkdir(mode=0o700)
        self.old_source = 'a' * 40; self.new_source = 'b' * 40
        self.old_release = self.releases / ('private-finance-' + self.old_source[:12] + '-20261011-candidate')
        self.old_release.mkdir(mode=0o700); self.completed = self.old_release / 'completed-release'; self.completed.mkdir(mode=0o700)
        self.data = self.root / 'data'; self.data.mkdir(mode=0o700)
        self.private = self.data / 'workspace.db'; self.business = self.data / 'business.db'
        self.config = self.root / 'config'; self.config.mkdir(mode=0o700)
        for obj, name, value in ((resume, 'RELEASES', self.releases), (resume.live, 'PRIVATE_DB', self.private),
            (resume.live, 'BUSINESS', self.business), (resume.transfer, 'CONFIG', self.config),
            (resume.transfer, 'BOOTSTRAP', self.config / 'stripe-bootstrap.json')):
            patch = mock.patch.object(obj, name, value); patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(resume.transfer, 'protected_directory', side_effect=self.protect)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(resume.transfer, 'read_protected', side_effect=self.read_protected)
        patch.start(); self.addCleanup(patch.stop)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.private_workspace import PrivateConnection, PrivateItem, PrivatePreferences, PrivateSyncRun, PrivateWorkspaceBase
        engine = create_engine('sqlite:///' + str(self.private))
        PrivateWorkspaceBase.metadata.create_all(engine, tables=[PrivateWorkspaceBase.metadata.tables[name] for name in resume.guard.BASE_TABLES])
        with Session(engine) as db:
            for source in ('gmail', 'google_ads', 'manual'):
                db.add(PrivateConnection(id=source, owner_id='4', source_id=source, status='connected',
                    encrypted_credentials='synthetic-encrypted-' + source,
                    metadata_json={'account_label': 'fixture@example.com', 'scope': 'readonly', 'read_only_adapter': True,
                        'fetched_messages': 1} if source == 'gmail' else {'scope': 'readonly'}))
            db.add(PrivateItem(id='mail-old', owner_id='4', source_id='gmail', external_id='old', kind='email',
                title='Synthetic', status='unread', local_title='Personal note', action_status='done'))
            db.add(PrivatePreferences(owner_id='4', preferences_json={'sync_interval_seconds': 900}))
            db.add(PrivateSyncRun(id='run-old', owner_id='4', source_id='gmail', status='succeeded',
                completed_at=datetime.now(timezone.utc)))
            db.commit()
        engine.dispose(); self.private.chmod(0o600)
        with sqlite3.connect(self.business) as db:
            db.execute('CREATE TABLE employees (id INTEGER,role TEXT,status TEXT)')
            db.execute("INSERT INTO employees VALUES (4,'super_admin','active')")
            db.execute('CREATE TABLE alembic_version (version_num TEXT)')
            db.execute("INSERT INTO alembic_version VALUES ('ab6d8e2f0411')")
            for index in range(81): db.execute('CREATE TABLE ledger_' + str(index) + ' (amount INTEGER)')
        self.business.chmod(0o600)
        self.before = resume.guard.release_snapshot(self.private, self.business)
        self.backup = self.completed / 'original-private.db'
        with sqlite3.connect(self.private) as source, sqlite3.connect(self.backup) as target: source.backup(target)
        self.backup.chmod(0o600)
        engine = create_engine('sqlite:///' + str(self.private)); PrivateWorkspaceBase.metadata.create_all(engine); engine.dispose()
        self.after = resume.guard.release_snapshot(self.private, self.business)
        self.manifest = {'format_version': 1, 'stage': 'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST', 'source_sha': self.old_source,
            'baseline_tables': sorted(resume.guard.BASE_TABLES), 'target_tables': sorted(candidate.TARGET_TABLES),
            'target_schema_objects': self.after['private']['schema_objects'], 'business_table_count': 83,
            'business_schema_sha256': self.before['business']['schema_sha256']}
        self.validation = resume.guard.compare_snapshots(self.before, self.after, self.manifest, source_sha=self.old_source, mode='in_place')
        baseline = {'format_version': 1, 'stage': 'PRIVATE_FINANCE_LIVE_READONLY_BASELINE', 'mutation_performed': False}
        baseline_path = self.old_release / 'baseline.json'; baseline_sha = self.save(baseline_path, baseline)
        self.state = {'format_version': 1, 'phase': 'PRIVATE_COMPLETED_SCHEMA_VERIFIED_WRITERS_STOPPED',
            'source_sha': self.old_source, 'candidate': str(self.old_release / 'candidate.json'), 'candidate_sha256': 'c' * 64,
            'candidate_image': 'sha256:' + 'd' * 64, 'baseline': str(baseline_path), 'baseline_sha256': baseline_sha,
            'attempt': 'e' * 32, 'old_ids': resume.live.PRIVATE_IDS, 'bank_enabled': False, 'ai_enabled': False,
            'worker_started': False, 'services_switched': False, 'deployed': False,
            'backup': str(self.backup), 'backup_sha256': resume.live.sha(self.backup.read_bytes())}
        for name, value in (('schema_before', self.before), ('schema_after', self.after),
            ('schema_manifest', self.manifest), ('schema_validation', self.validation)):
            path = self.completed / (name.replace('_', '-') + '.json')
            self.state[name] = str(path); self.state[name + '_sha256'] = self.save(path, value)
        self.state_path = self.completed / 'schema-state.json'; self.state_sha = self.save(self.state_path, self.state)
        self.rollback_path = self.completed / ('rollback-' + 'f' * 32 + '.json')
        self.rollback = {'format_version': 1, 'phase': 'PRIVATE_COMPLETED_RELEASE_ROLLED_BACK_OLD_SERVICES',
            'source_sha': self.old_source, 'attempt': self.state['attempt'], 'old_ids': resume.live.PRIVATE_IDS,
            'customer_tables_verified': 83, **{name: False for name in ('bank_enabled', 'ai_enabled', 'databases_restored',
            'private_database_replaced', 'public_assets_published', 'deployed')}}
        self.rollback_sha = self.save(self.rollback_path, self.rollback)
        self.old_candidate = {'source_sha': self.old_source, 'image_id': self.state['candidate_image'],
            'baseline_sha256': baseline_sha, 'synthetic_schema': {'schema_objects': self.after['private']['schema_objects']}}
        self.save(self.old_release / 'candidate.json', self.old_candidate)
        self.state['candidate_sha256'] = resume.live.sha((self.old_release / 'candidate.json').read_bytes())
        self.state_sha = self.save(self.state_path, self.state)
        bootstrap = resume.transfer.BOOTSTRAP; bootstrap.write_bytes(b'synthetic-sealed-ciphertext'); bootstrap.chmod(0o600)
        claims = self.config / 'stripe-seed-claims'; claims.mkdir(mode=0o700)
        bootstrap_sha = resume.live.sha(bootstrap.read_bytes())
        self.claim_path = claims / (bootstrap_sha + '.json')
        self.save(self.claim_path, {'stage': 'STRIPE_SEED_ONE_USE_CLAIMED', 'attempt': '1' * 32,
            'candidate_sha256': self.state['candidate_sha256'], 'bootstrap_sha256': bootstrap_sha, 'source_sha': self.old_source})

    @staticmethod
    def protect(path):
        if path.resolve() != path or not path.is_dir() or path.stat().st_mode & 0o077:
            raise resume.ResumeError('TEST_PROTECTED_DIRECTORY_REQUIRED')

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value, sort_keys=True)); path.chmod(0o600)
        return resume.live.sha(path.read_bytes())

    @staticmethod
    def read_protected(path, maximum=4 * 1024**2):
        if path.resolve() != path or path.is_symlink() or path.stat().st_mode & 0o777 != 0o600 or path.stat().st_nlink != 1:
            raise resume.ResumeError('TEST_PROTECTED_FILE_REQUIRED')
        blob = path.read_bytes()
        if len(blob) > maximum: raise resume.ResumeError('TEST_BOUNDED_FILE_REQUIRED')
        return blob

    def baseline(self):
        return {'format_version': 1, 'stage': resume.STAGE, 'mutation_performed': False,
            'accepted_snapshot': self.after, 'original_stable_reference': resume.stable_records(self.backup)}

    def frozen(self):
        return resume.checked_frozen_snapshot(self.baseline(), resume.guard.release_snapshot(self.private, self.business))

    def test_accepted_ten_schema_and_original_backup_are_checked_without_database_writes(self):
        before = (self.private.read_bytes(), self.business.read_bytes(), self.backup.read_bytes())
        self.assertEqual(self.frozen(), self.after)
        self.assertEqual((self.private.read_bytes(), self.business.read_bytes(), self.backup.read_bytes()), before)

    def test_gmail_count_and_provider_rows_refresh_with_same_identity_credentials_and_notes(self):
        with sqlite3.connect(self.private) as db:
            metadata = json.loads(db.execute("SELECT metadata_json FROM private_connections WHERE id='gmail'").fetchone()[0])
            metadata.update(fetched_messages=22, partial=True)
            db.execute("UPDATE private_connections SET metadata_json=?,last_sync='2026-10-11 13:28:00' WHERE id='gmail'", (json.dumps(metadata),))
            db.execute("UPDATE private_items SET title='Updated provider title',status='read' WHERE id='mail-old'")
        current = self.frozen(); self.assertNotEqual(current, self.after)

    def test_account_scope_status_generation_and_ciphertext_changes_are_not_provider_refresh(self):
        for column, value in [('encrypted_credentials', 'changed-ciphertext'), ('generation', 2), ('status', 'disconnected'),
            ('metadata_json', json.dumps({'account_label': 'different@example.com', 'scope': 'readonly', 'read_only_adapter': True}))]:
            with self.subTest(column=column), sqlite3.connect(self.private) as db:
                original = db.execute('SELECT ' + column + " FROM private_connections WHERE id='gmail'").fetchone()[0]
                db.execute('UPDATE private_connections SET ' + column + "=? WHERE id='gmail'", (value,)); db.commit()
                with self.assertRaisesRegex(resume.ResumeError, 'RESUME_ACCOUNT_SCOPE_OR_ENCRYPTED_CREDENTIAL_CHANGED'): self.frozen()
                db.execute('UPDATE private_connections SET ' + column + "=? WHERE id='gmail'", (original,))

    def test_fetched_messages_is_volatile_only_for_gmail(self):
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET metadata_json=? WHERE id='google_ads'", (json.dumps({'scope': 'readonly', 'fetched_messages': 3}),))
        with self.assertRaisesRegex(resume.ResumeError, 'RESUME_ACCOUNT_SCOPE_OR_ENCRYPTED_CREDENTIAL_CHANGED'): self.frozen()

    def test_personal_notes_preferences_and_original_items_cannot_change_or_disappear(self):
        for statement in ("UPDATE private_items SET local_title='Changed' WHERE id='mail-old'",
            "UPDATE private_items SET action_status='open' WHERE id='mail-old'", "DELETE FROM private_items WHERE id='mail-old'",
            "UPDATE private_preferences SET preferences_json='{}'"):
            with self.subTest(statement=statement), sqlite3.connect(self.private) as db:
                db.execute('SAVEPOINT damage'); db.execute(statement)
                # A separate readonly connection sees only committed changes.
                db.commit()
                with self.assertRaises(resume.ResumeError): self.frozen()
                # Restore only synthetic fixture from its backup by recreating.
                with sqlite3.connect(self.backup) as source: source.backup(db)
            from sqlalchemy import create_engine
            from models.private_workspace import PrivateWorkspaceBase
            engine = create_engine('sqlite:///' + str(self.private)); PrivateWorkspaceBase.metadata.create_all(engine); engine.dispose()

    def test_stripe_commit_bank_row_and_customer_write_are_rejected(self):
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET source_id='stripe' WHERE id='manual'")
        with self.assertRaisesRegex(resume.ResumeError, 'RESUME_MUST_HAVE_NO_COMMITTED_STRIPE_CONNECTION'): self.frozen()
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_connections SET source_id='manual' WHERE id='manual'")
        with sqlite3.connect(self.business) as db: db.execute('INSERT INTO ledger_0 VALUES (10)')
        with self.assertRaisesRegex(resume.ResumeError, 'RESUME_ALL_CUSTOMER_TABLE_FINGERPRINTS_CHANGED'): self.frozen()

    def test_new_schema_rows_and_unknown_ddl_are_rejected(self):
        with sqlite3.connect(self.private) as db: db.execute('CREATE TABLE private_unreviewed (owner_id TEXT)')
        with self.assertRaisesRegex(resume.ResumeError, 'RESUME_ACCEPTED_INODE_OR_TEN_TABLE_SCHEMA_CHANGED'): self.frozen()

    def test_existing_manual_rows_and_sync_audits_cannot_be_changed(self):
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_sync_runs SET status='failed' WHERE id='run-old'")
        with self.assertRaisesRegex(resume.ResumeError, 'RESUME_UNRELATED_OR_ORIGINAL_SYNC_AUDIT_CHANGED'): self.frozen()

    def test_original_migration_and_exact_rollback_proof_are_required(self):
        with mock.patch.object(seed, 'checked_candidate', return_value=self.old_candidate):
            result = resume.original_proof(self.state_path, self.state_sha, self.rollback_path, self.rollback_sha)
            self.assertEqual(result[1:3], (self.before, self.after))
            wrong = {**self.rollback, 'databases_restored': True}; digest = self.save(self.rollback_path, wrong)
            with self.assertRaisesRegex(resume.ResumeError, 'EXACT_OLD_SERVICES_RESTORED_WITHOUT_DATABASE_RESTORE_REQUIRED'):
                resume.original_proof(self.state_path, self.state_sha, self.rollback_path, digest)

    def test_original_claim_kept_and_success_receipt_forbids_no_commit_claim(self):
        original = self.claim_path.read_bytes(); value = resume.checked_claim(self.state)
        self.assertEqual(value['original_claim_sha256'], resume.live.sha(original))
        self.assertEqual(self.claim_path.read_bytes(), original)
        self.save(self.old_release / 'stripe-seed-receipt.json', {'success': True})
        with self.assertRaisesRegex(resume.ResumeError, 'ORIGINAL_SUCCESSFUL_STRIPE_SEED_MUST_NOT_EXIST'): resume.checked_claim(self.state)

    def test_candidate_fresh_path_keeps_original_four_table_preflight(self):
        args = SimpleNamespace()
        with mock.patch.object(candidate.live, 'preflight', return_value={'stage': 'old'}) as old, \
            mock.patch.object(candidate.live, 'compare_baseline') as compare, mock.patch.object(candidate.resume, 'preflight') as new:
            self.assertFalse(candidate.checked_running_baseline(args, {'stage': 'old'}))
            old.assert_called_once(); compare.assert_called_once(); new.assert_not_called()

    def test_candidate_resume_requires_all_four_explicit_flags_and_uses_new_proof(self):
        args = SimpleNamespace(resume_schema_state=self.state_path, resume_schema_state_sha256=self.state_sha,
            rollback_state=self.rollback_path, rollback_state_sha256=self.rollback_sha)
        with mock.patch.object(candidate.live, 'preflight') as old, mock.patch.object(candidate.resume, 'preflight', return_value=self.baseline()) as new:
            self.assertTrue(candidate.checked_running_baseline(args, self.baseline())); old.assert_not_called(); new.assert_called_once()
        args.rollback_state_sha256 = None
        with self.assertRaisesRegex(candidate.PrepareError, 'EXPLICIT_RESUME_SCHEMA_AND_ROLLBACK_FILES_AND_HASHES_REQUIRED_TOGETHER'):
            candidate.resume_requested(args)

    def test_comparison_allows_only_independently_verified_provider_snapshot_hash(self):
        current = {**self.baseline(), 'observed_snapshot_sha256': 'a' * 64, 'exact_accepted_schema_after': False}
        saved = {**current, 'observed_snapshot_sha256': 'b' * 64, 'exact_accepted_schema_after': True}
        resume.compare_baseline(current, saved)
        with self.assertRaisesRegex(resume.ResumeError, 'FROZEN_RESUME_BASELINE_DRIFT'):
            resume.compare_baseline({**current, 'private': {'started_at': 'changed'}}, saved)

    def test_root_host_is_checked_before_evidence_or_database_access_and_errors_do_not_echo_keys(self):
        with mock.patch.object(resume.os, 'geteuid', return_value=501), mock.patch.object(resume, 'original_proof') as proof:
            with self.assertRaisesRegex(resume.ResumeError, 'VERIFIED_ROOT_RESUME_SERVER_REQUIRED'):
                resume.preflight(schema_state=self.state_path, schema_state_sha256=self.state_sha,
                    rollback_state=self.rollback_path, rollback_state_sha256=self.rollback_sha)
            proof.assert_not_called()
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(resume.cli(['--key', 'rk_live_SYNTHETICSECRET']), 1)
        self.assertNotIn('SYNTHETICSECRET', output.getvalue())

    def complete_baseline(self):
        with mock.patch.object(seed, 'checked_candidate', return_value=self.old_candidate), \
             mock.patch.object(resume, 'root_guard'), \
             mock.patch.object(switch, 'runtime_guard', return_value={}), \
             mock.patch.object(resume, '_restored_runtime', return_value=({'api': {'started_at': 'fresh'}}, {})):
            return resume.preflight(schema_state=self.state_path, schema_state_sha256=self.state_sha,
                rollback_state=self.rollback_path, rollback_state_sha256=self.rollback_sha)

    def resume_receipt(self):
        baseline = self.complete_baseline()
        new_release = self.releases / ('private-finance-' + self.new_source[:12] + '-20261011-candidate')
        new_release.mkdir(mode=0o700)
        baseline_sha = self.save(new_release / 'resume-baseline.json', baseline)
        args = SimpleNamespace(release=new_release, baseline_sha256=baseline_sha)
        return {'source_sha': self.new_source, 'baseline_sha256': baseline_sha,
            'resume_lineage': resume.candidate_lineage(args, baseline),
            'synthetic_schema': {'schema_objects': self.after['private']['schema_objects']}}

    def test_complete_readonly_preflight_binds_claim_rollback_backup_and_new_runtime_without_writes(self):
        before = self.private.read_bytes(), self.business.read_bytes(), self.claim_path.read_bytes()
        baseline = self.complete_baseline()
        self.assertEqual(baseline['stage'], resume.STAGE)
        self.assertTrue(baseline['fresh_no_successful_seed_verified'])
        self.assertTrue(baseline['exact_accepted_schema_after'])
        self.assertEqual(baseline['rollback_state_sha256'], self.rollback_sha)
        self.assertEqual((self.private.read_bytes(), self.business.read_bytes(), self.claim_path.read_bytes()), before)
        output = json.dumps(baseline)
        self.assertNotIn('synthetic-encrypted-', output); self.assertNotIn('fixture@example.com', output)
        self.assertNotIn('Personal note', output)

    def test_historical_candidate_lineage_after_seed_does_not_require_current_stripe_absence(self):
        receipt = self.resume_receipt()
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_connections SET source_id='stripe' WHERE id='manual'")
        with mock.patch.object(seed, 'checked_candidate', return_value=self.old_candidate):
            state, before, after, old_baseline, new_baseline = resume.checked_lineage(receipt)
        self.assertEqual(state['candidate_sha256'], self.state['candidate_sha256'])
        self.assertEqual(after, self.after); self.assertEqual(new_baseline['stage'], resume.STAGE)

    def test_historical_lineage_rejects_missing_fields_schema_binding_claim_drift_or_new_path_alias(self):
        receipt = self.resume_receipt()
        with mock.patch.object(seed, 'checked_candidate', return_value=self.old_candidate):
            wrong = deepcopy(receipt); wrong['resume_lineage'].pop('original_claim_sha256')
            with self.assertRaisesRegex(resume.ResumeError, 'EXPLICIT_COMPLETE_RESUME_LINEAGE_REQUIRED'): resume.checked_lineage(wrong)
            wrong = deepcopy(receipt); wrong['synthetic_schema']['schema_objects'] = {}
            with self.assertRaisesRegex(resume.ResumeError, 'RESUME_ORIGINAL_PROOF_LINEAGE_DRIFT'): resume.checked_lineage(wrong)
            wrong = deepcopy(receipt); wrong['resume_lineage']['original_claim_sha256'] = '0' * 64
            with self.assertRaisesRegex(resume.ResumeError, 'ORIGINAL_ACCEPTED_SCHEMA_AND_RESUME_BASELINE_BINDING_REQUIRED'):
                resume.checked_lineage(wrong)

    def test_candidate_resume_cannot_prepare_with_old_test_minimum(self):
        args = SimpleNamespace(test_wheel_manifest_sha256=candidate.BASE_WHEEL_MANIFEST_SHA,
            freeze=Path('synthetic'), freeze_sha256='a' * 64, manifest=Path('synthetic'), manifest_sha256='b' * 64,
            payload=Path('synthetic'), payload_sha256='c' * 64, baseline=Path('synthetic'), baseline_sha256='d' * 64)
        with mock.patch.object(candidate, 'frozen_file', return_value=b'{}'), \
             mock.patch.object(candidate.builder, 'freeze', return_value={'backend_regression_tests_minimum': 806}), \
             mock.patch.object(candidate, 'checked_payload'), mock.patch.object(candidate, 'checked_running_baseline', return_value=True):
            # The payload's reviewed frozen hash is also independently pinned.
            with mock.patch.object(candidate.json, 'loads', return_value={'frozen_manifest_sha256': args.freeze_sha256}):
                with self.assertRaisesRegex(candidate.PrepareError, 'RESUME_REQUIRES_ALL_807_PRIVATE_REGRESSIONS'):
                    candidate.main(args)


if __name__ == '__main__': unittest.main()
