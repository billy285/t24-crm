"""Synthetic SQLite and Docker-boundary tests; no server, provider or credentials."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app/backend'))
import switch_completed as switch


class SwitchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.root.chmod(0o700)
        self.private_root = self.root/'private'; self.private_root.mkdir(mode=0o700)
        self.business_root = self.root/'business'; self.business_root.mkdir(mode=0o700)
        self.private = self.private_root/'workspace.db'; self.business = self.business_root/'crm.db'
        self.image = 'sha256:'+'b'*64; self.source = 'a'*40; self.attempt = 'c'*32
        self.identity = 'd'*64
        for attr,value in (('PRIVATE_DB',self.private),('BUSINESS',self.business)):
            p = mock.patch.object(switch.live,attr,value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(switch.transfer,'protected_directory',side_effect=self.local_protection)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(switch.transfer,'read_protected',side_effect=lambda path,*unused:path.read_bytes())
        p.start(); self.addCleanup(p.stop)

    @staticmethod
    def local_protection(path):
        if path.resolve() != path or not path.is_dir() or path.stat().st_mode & 0o077:
            raise switch.transfer.TransferError('TEST_PROTECTED_DIRECTORY_REQUIRED')

    def databases(self,*,new=False):
        from sqlalchemy import create_engine
        from models.private_workspace import PrivateWorkspaceBase
        engine = create_engine('sqlite:///'+str(self.private))
        if new: PrivateWorkspaceBase.metadata.create_all(engine)
        else:
            for name in sorted(switch.guard.BASE_TABLES):
                PrivateWorkspaceBase.metadata.tables[name].create(engine)
        engine.dispose(); self.private.chmod(0o600)
        with sqlite3.connect(self.business) as db:
            for index in range(83):
                db.execute('CREATE TABLE ledger_'+str(index)+' (id INTEGER PRIMARY KEY, amount INTEGER)')
                db.execute('INSERT INTO ledger_'+str(index)+' VALUES (1,70000)')
        self.business.chmod(0o600)

    def migrate(self):
        from sqlalchemy import create_engine
        from models.private_workspace import PrivateWorkspaceBase
        engine = create_engine('sqlite:///'+str(self.private)); PrivateWorkspaceBase.metadata.create_all(engine); engine.dispose()

    def actual_stripe(self,*,success=True):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.private_workspace import PrivateConnection,PrivateSyncRun
        now = datetime.now(timezone.utc)
        metadata = {'stripe_account_id':switch.transfer.ACCOUNT,'mode':'live','read_only_adapter':True,
            'payouts_are_income':False,'aggregated_totals':False,'coverage':'bounded_recent_records',
            'stripe_snapshot':{'account_id':switch.transfer.ACCOUNT,'mode':'live','id':'synthetic-snapshot','observed_at':now.isoformat()}}
        engine = create_engine('sqlite:///'+str(self.private))
        with Session(engine) as db:
            db.add(PrivateConnection(id='synthetic-stripe',owner_id='4',source_id='stripe',status='connected',
                encrypted_credentials='synthetic-encrypted-value-not-real',metadata_json=metadata,generation=1,last_sync=now))
            db.add(PrivateSyncRun(id='synthetic-run',owner_id='4',source_id='stripe',status='succeeded' if success else 'failed',
                started_at=now,completed_at=now))
            db.commit()
        engine.dispose()

    def runtime_values(self,role='api'):
        return {'DATABASE_URL':'sqlite:///./data/crm_prod.db','DATABASE_SCHEMA_MODE':'verify_only',
            'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db','PRIVATE_WORKSPACE_OWNER_IDS':'4',
            'PRIVATE_WORKSPACE_ENCRYPTION_KEY':'synthetic-private-encryption-key-32',
            'JWT_SECRET_KEY':'synthetic-employee-identity-key-long-32',
            'PRIVATE_WORKSPACE_PROCESS_ROLE':role,'PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID':switch.transfer.ACCOUNT,
            'PRIVATE_WORKSPACE_STRIPE_MODE':'live',**switch.DISABLED}

    def role_fixture(self,role='api',*,running=False):
        values = self.runtime_values(role)
        host = {'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],
            'RestartPolicy':{'Name':'unless-stopped'},'LogConfig':{'Config':{'max-size':'5m','max-file':'3'}},
            'Tmpfs':{'/tmp':'rw,nosuid,noexec,size=128m'},'NetworkMode':'bridge','IpcMode':'private',
            'PortBindings':{'8001/tcp':[{'HostIp':'127.0.0.1','HostPort':'8001'}]} if role == 'api' else {}}
        config = {'Labels':{'t24.private.source.sha':self.source,'t24.private.role':role,switch.ROLE_LABEL:self.attempt},
            'Env':[key+'='+value for key,value in values.items()]+['PATH=/usr/bin'],
            'Entrypoint':['uvicorn'] if role == 'api' else ['python'],
            'Cmd':switch.API_PROGRAM if role == 'api' else switch.WORKER_PROGRAM,
            'Healthcheck':{'Test':['CMD-SHELL','curl -fsS http://127.0.0.1:8001/ready || exit 1'],
                'Interval':15_000_000_000,'Timeout':5_000_000_000,'StartPeriod':15_000_000_000,'Retries':3} if role == 'api' else {'Test':['NONE']}}
        mounts = [{'Type':'bind','Source':str(self.business_root),'Destination':'/app/backend/data','RW':False},
            {'Type':'bind','Source':str(self.private_root),'Destination':'/private-data','RW':True}]
        return {'Id':self.identity,'Image':self.image,'Config':config,'HostConfig':host,'Mounts':mounts,
            'RestartCount':0,'State':{'Running':running,'StartedAt':'synthetic-start','Status':'running' if running else 'created'},
            'Name':'/t24-private-'+role},values

    def test_role_profiles_preserve_identity_disable_unavailable_integrations_and_never_include_stripe_key(self):
        raw = b'synthetic-original-file\n'
        original = self.runtime_values()
        for key in set(switch.DISABLED)|{'PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID','PRIVATE_WORKSPACE_STRIPE_MODE','PRIVATE_WORKSPACE_PROCESS_ROLE'}:
            original.pop(key,None)
        with mock.patch.object(switch.live,'ENV_SHA',switch.sha(raw)),mock.patch.object(switch.live,'parse_env',return_value=original):
            api = switch.role_configuration(raw,'api'); worker = switch.role_configuration(raw,'worker')
        self.assertEqual(api['JWT_SECRET_KEY'],original['JWT_SECRET_KEY'])
        self.assertEqual(api['PRIVATE_WORKSPACE_ENCRYPTION_KEY'],original['PRIVATE_WORKSPACE_ENCRYPTION_KEY'])
        self.assertEqual(api['PRIVATE_WORKSPACE_PROCESS_ROLE'],'api')
        self.assertEqual(worker['PRIVATE_WORKSPACE_PROCESS_ROLE'],'worker')
        self.assertEqual(api['PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD'],'5000000')
        self.assertTrue(all(api[key] == 'false' for key in switch.DISABLED))
        self.assertNotIn('PRIVATE_WORKSPACE_STRIPE_KEY',api)
        for bad in ('STRIPE_SECRET_KEY','OPENAI_API_KEY','PRIVATE_WORKSPACE_STRIPE_KEY','PRIVATE_WORKSPACE_PLAID_SECRET','PRIVATE_MAIL_BRIEF_OPENAI_API_KEY'):
            with self.subTest(bad=bad),mock.patch.object(switch.live,'ENV_SHA',switch.sha(raw)),mock.patch.object(switch.live,'parse_env',return_value={**original,bad:'synthetic'}):
                with self.assertRaises(switch.SwitchError): switch.role_configuration(raw,'api')

    def test_new_role_is_fail_closed_for_finance_write_mount_public_port_privileges_extra_secrets_and_wrong_identity(self):
        info,values = self.role_fixture()
        with mock.patch.object(switch,'inspect',return_value=info):
            self.assertEqual(switch.staged_check(self.identity,'api',self.image,self.attempt,self.source,values,running=False)['id'],self.identity)
        changes = [lambda v:v['Mounts'][0].update(RW=True),lambda v:v['Mounts'].append({'Type':'bind','Source':'/','Destination':'/host','RW':True}),
            lambda v:v['HostConfig'].update(Privileged=True),lambda v:v['HostConfig']['PortBindings']['8001/tcp'][0].update(HostIp='0.0.0.0'),
            lambda v:v['Config']['Env'].append('PRIVATE_WORKSPACE_STRIPE_KEY=synthetic'),
            lambda v:v['Config']['Env'].append('UNREVIEWED_SECRET=synthetic'),
            lambda v:v['Config']['Labels'].update({'t24.private.source.sha':'e'*40}),
            lambda v:v['HostConfig'].update(NetworkMode='host'),lambda v:v.update(Id=switch.live.CRM_ID)]
        for change in changes:
            wrong = deepcopy(info); change(wrong)
            with self.subTest(change=changes.index(change)),mock.patch.object(switch,'inspect',return_value=wrong),self.assertRaises(switch.SwitchError):
                switch.staged_check(self.identity,'api',self.image,self.attempt,self.source,values,running=False)

    def test_commands_only_allow_reviewed_programs_mounts_role_and_loopback(self):
        profile = self.root/'api-runtime.env'
        api = switch.create_command('t24-private-finance-stage-api-'+self.attempt,'api',self.image,self.attempt,self.source,profile)
        worker = switch.create_command('t24-private-finance-stage-worker-'+self.attempt,'worker',self.image,self.attempt,self.source,profile)
        self.assertIn('127.0.0.1:8001:8001',api); self.assertNotIn('--publish',worker)
        self.assertIn('type=bind,src='+str(self.business_root)+',dst=/app/backend/data,readonly',api)
        self.assertEqual(api[-len(switch.API_PROGRAM):],switch.API_PROGRAM)
        self.assertEqual(worker[-len(switch.WORKER_PROGRAM):],switch.WORKER_PROGRAM)
        self.assertNotIn('--privileged',api)
        with self.assertRaises(switch.SwitchError): switch.create_command('arbitrary','api',self.image,self.attempt,self.source,profile)

    def test_rollback_can_verify_and_stop_its_own_crash_loop_without_weakening_identity_or_mount_guards(self):
        info,values = self.role_fixture(); info['RestartCount'] = 3; info['State']['Restarting'] = True
        with mock.patch.object(switch,'inspect',return_value=info):
            with self.assertRaisesRegex(switch.SwitchError,'NEW_PRIVATE_UNSTABLE_RUNTIME'):
                switch.staged_check(self.identity,'api',self.image,self.attempt,self.source,values)
            switch.staged_check(self.identity,'api',self.image,self.attempt,self.source,values,require_stable=False)
            info['Mounts'][0]['RW'] = True
            with self.assertRaisesRegex(switch.SwitchError,'ONLY_PRIVATE_DATABASE_WRITABLE_MOUNT_REQUIRED'):
                switch.staged_check(self.identity,'api',self.image,self.attempt,self.source,values,require_stable=False)

    def test_actual_additive_migration_preserves_original_inode_data_and_customer_tables(self):
        self.databases()
        before = switch.guard.release_snapshot(self.private,self.business)
        original_inode = self.private.stat().st_ino
        backup = self.root/'original-private.db'
        backup_hash = switch.backup_private(backup,before)
        self.assertEqual(backup_hash,switch.sha(backup.read_bytes()))
        self.migrate()
        after = switch.guard.release_snapshot(self.private,self.business)
        manifest = {'format_version':1,'stage':'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST','source_sha':self.source,
            'baseline_tables':sorted(switch.guard.BASE_TABLES),'target_tables':sorted(switch.candidate.TARGET_TABLES),
            'target_schema_objects':after['private']['schema_objects'],'business_table_count':83,
            'business_schema_sha256':before['business']['schema_sha256']}
        proof = switch.guard.compare_snapshots(before,after,manifest,source_sha=self.source,mode='in_place')
        self.assertTrue(proof['original_rows_columns_indexes_preserved']); self.assertTrue(proof['business_unchanged'])
        self.assertEqual(self.private.stat().st_ino,original_inode)
        self.assertEqual(set(switch.guard.database_snapshot(backup,private=True)['tables']),switch.guard.BASE_TABLES)
        switch.disabled_data(after)
        with sqlite3.connect(self.business) as db: db.execute('UPDATE ledger_0 SET amount=1')
        changed = switch.guard.release_snapshot(self.private,self.business)
        with self.assertRaisesRegex(switch.SwitchError,'ALL_CUSTOMER_TABLE_FINGERPRINTS'):
            switch.schema_and_business_unchanged(changed,after)

    def test_backup_cannot_be_live_alias_or_preserve_wrong_data(self):
        self.databases(); before = switch.guard.release_snapshot(self.private,self.business)
        with self.assertRaises(FileExistsError): switch.backup_private(self.private,before)
        wrong = deepcopy(before); wrong['private']['data_sha256'] = 'f'*64
        with self.assertRaisesRegex(switch.SwitchError,'EXACT_ORIGINAL_PRIVATE_BACKUP'):
            switch.backup_private(self.root/'rejected-backup.db',wrong)
        self.assertTrue(self.private.exists())

    def test_initializer_is_networkless_and_has_no_identity_or_platform_credentials(self):
        command = switch.initializer_command('t24-private-finance-initialize-'+self.attempt,self.image,self.attempt)
        self.assertEqual(command[command.index('--network')+1],'none')
        self.assertEqual(command[command.index('--log-driver')+1],'none')
        self.assertNotIn('--env-file',command)
        self.assertNotIn('--publish',command)
        self.assertNotIn('JWT_SECRET_KEY',switch.INIT_CODE)
        self.assertNotIn('PRIVATE_WORKSPACE_ENCRYPTION_KEY',switch.INIT_CODE)
        self.assertIn('private_session_factory',switch.INIT_CODE)

    def test_first_sync_requires_actual_success_identity_and_snapshot_not_seed_only(self):
        self.databases(new=True)
        with self.assertRaisesRegex(switch.SwitchError,'FIRST_REAL_STRIPE_SYNC_REQUIRED'):
            switch.checked_first_sync({})
        self.actual_stripe()
        proof = switch.checked_first_sync({})
        self.assertTrue(proof['first_real_stripe_sync_verified']); self.assertFalse(proof['payouts_are_income'])
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_sync_runs SET status='failed'")
        with self.assertRaisesRegex(switch.SwitchError,'PERSISTED_FIRST_STRIPE_SYNC_SUCCESS_REQUIRED'):
            switch.checked_first_sync({})
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_sync_runs SET status='succeeded'")
            db.execute("UPDATE private_connections SET metadata_json=?",(json.dumps({'stripe_account_id':'acct_WRONG','mode':'live'}),))
        with self.assertRaisesRegex(switch.SwitchError,'REAL_STRIPE_SNAPSHOT_IDENTITY'):
            switch.checked_first_sync({})

    def test_seed_receipt_cannot_substitute_account_or_frozen_snapshot(self):
        self.databases(new=True); self.actual_stripe()
        current = switch.guard.release_snapshot(self.private,self.business)
        args = SimpleNamespace(candidate_sha256='c'*64,source_sha=self.source)
        state = {'candidate_image':self.image,'schema_validation_sha256':'a'*64,'backup_sha256':'b'*64}
        value = {'stage':'PRIVATE_STRIPE_SEED_VERIFIED_NOT_DEPLOYED','format_version':1,
            'candidate_sha256':args.candidate_sha256,'source_sha':self.source,'image_id':self.image,
            'schema_acceptance_sha256':'a'*64,'backup_sha256':'b'*64,'six_get_probes_verified':True,
            'encrypted_db_credential_verified':True,'runtime_env_changed':False,'customer_data_changed':False,
            'other_private_connections_changed':False,'private_rows_changed_only_stripe_connection':True,
            'deployed':False,'after_snapshot_sha256':switch.guard.digest(current),'before_snapshot_sha256':'f'*64,'generation':1}
        switch.checked_seed(value,args,state,current)
        for field,wrong in (('after_snapshot_sha256','f'*64),('candidate_sha256','f'*64),('deployed',True),('six_get_probes_verified',False)):
            with self.subTest(field=field),self.assertRaises(switch.SwitchError):
                switch.checked_seed({**value,field:wrong},args,state,current)

    def test_bank_and_ai_tables_cannot_be_nonempty_even_if_environment_flags_are_off(self):
        self.databases(new=True)
        current = switch.guard.release_snapshot(self.private,self.business); switch.disabled_data(current)
        wrong = deepcopy(current); wrong['private']['tables']['private_bank_links']['rows'] = 1
        with self.assertRaisesRegex(switch.SwitchError,'BANK_OR_AI_TABLES_MUST_REMAIN_EMPTY'): switch.disabled_data(wrong)
        wrong = deepcopy(current); wrong['private']['tables']['private_mail_briefs']['rows'] = 1
        with self.assertRaises(switch.SwitchError): switch.disabled_data(wrong)

    def test_stable_original_records_reject_notes_preferences_and_identity_drift_but_allow_provider_append(self):
        before = {'items':{'a':'hash-a'},'preferences':{'4':'prefhash'},'connections':{'c':'identityhash'}}
        after = deepcopy(before); after['items']['new'] = 'provider-hash'; switch.preserved(before,after)
        for field in ('items','preferences','connections'):
            wrong = deepcopy(after); wrong[field][next(iter(before[field]))] = 'changed'
            with self.subTest(field=field),self.assertRaisesRegex(switch.SwitchError,'PRIVATE_NOTES_ACTIONS'):
                switch.preserved(before,wrong)

    def test_unknown_writers_mounting_ancestor_descendant_or_exact_private_directory_are_rejected(self):
        exact,ancestor,descendant = self.private_root,self.root,self.private_root/'subdir'
        for path in (exact,ancestor,descendant):
            info = {'Mounts':[{'Type':'bind','RW':True,'Source':str(path)}],'State':{'Running':False}}
            with (self.subTest(path=path),mock.patch.object(switch,'docker',return_value=(self.identity+'\n').encode()),
                  mock.patch.object(switch,'inspect',return_value=info)):
                with self.assertRaisesRegex(switch.SwitchError,'UNEXPECTED_PRIVATE_DATABASE_WRITER'): switch.no_writers()
                switch.no_writers([self.identity])
        with self.assertRaisesRegex(switch.SwitchError,'OLD_OR_BUSINESS_WRITER_CANNOT_BE_ALLOWED'):
            switch.no_writers([switch.live.CRM_ID])

    def test_rollback_rejects_unknown_ddl_and_private_file_replacement_but_retains_seeded_data(self):
        self.databases(); before = switch.guard.release_snapshot(self.private,self.business)
        self.migrate(); self.actual_stripe()
        current = switch.guard.release_snapshot(self.private,self.business)
        receipt = {'synthetic_schema':{'schema_objects':current['private']['schema_objects']}}
        switch.rollback_schema_preserved(before,current,receipt,allow_private_sync=True)
        # The rollback validator does not remove new encrypted Stripe data.
        self.assertTrue(switch.seed.connection_state(self.private)['row']['encrypted_credentials'])
        wrong = deepcopy(current); wrong['private']['identity']['inode'] += 1
        with self.assertRaisesRegex(switch.SwitchError,'ROLLBACK_DATABASE_IDENTITY'):
            switch.rollback_schema_preserved(before,wrong,receipt)
        wrong = deepcopy(current); wrong['private']['schema_objects']['unreviewed'] = {'type':'table','table':'private_unreviewed','sql_sha256':'f'*64}
        with self.assertRaisesRegex(switch.SwitchError,'ROLLBACK_UNKNOWN_PRIVATE_DDL'):
            switch.rollback_schema_preserved(before,wrong,receipt)

    def test_schema_failure_rollback_refuses_deleted_preferences_or_changed_original_credentials(self):
        self.databases()
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.private_workspace import PrivateConnection,PrivatePreferences
        engine = create_engine('sqlite:///'+str(self.private))
        with Session(engine) as db:
            db.add(PrivateConnection(id='synthetic-gmail',owner_id='4',source_id='gmail',status='connected',
                encrypted_credentials='synthetic-original-encrypted',generation=1,
                metadata_json={'account_label':'owner@example.test','scope':'synthetic-readonly','read_only_adapter':True}))
            db.add(PrivatePreferences(owner_id='4',preferences_json={'synthetic':'keep'})); db.commit()
        engine.dispose()
        before = switch.guard.release_snapshot(self.private,self.business)
        self.migrate(); current = switch.guard.release_snapshot(self.private,self.business)
        receipt = {'synthetic_schema':{'schema_objects':current['private']['schema_objects']}}
        switch.rollback_schema_preserved(before,current,receipt)
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_connections SET encrypted_credentials='synthetic-changed'")
        with self.assertRaisesRegex(switch.SwitchError,'ROLLBACK_ORIGINAL_PRIVATE_ROWS_CHANGED_BEFORE_CONNECTORS'):
            switch.rollback_schema_preserved(before,switch.guard.release_snapshot(self.private,self.business),receipt)
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET encrypted_credentials='synthetic-original-encrypted'")
            db.execute('DELETE FROM private_preferences')
        with self.assertRaisesRegex(switch.SwitchError,'ROLLBACK_ORIGINAL_PRIVATE_ROWS_CHANGED_BEFORE_CONNECTORS'):
            switch.rollback_schema_preserved(before,switch.guard.release_snapshot(self.private,self.business),receipt)

    def test_non_stripe_rows_are_frozen_until_worker_and_identity_scope_remain_fixed_after_provider_refresh(self):
        self.databases(new=True)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.private_workspace import PrivateConnection
        engine = create_engine('sqlite:///'+str(self.private))
        with Session(engine) as db:
            db.add(PrivateConnection(id='synthetic-gmail',owner_id='4',source_id='gmail',status='connected',
                encrypted_credentials='synthetic-original-encrypted',generation=1,
                metadata_json={'account_label':'owner@example.test','scope':'synthetic-readonly','read_only_adapter':True})); db.commit()
        engine.dispose()
        before = switch.stable_records(self.private)
        with sqlite3.connect(self.private) as db: db.execute("UPDATE private_connections SET encrypted_credentials='synthetic-refresh-token'")
        after = switch.stable_records(self.private)
        with self.assertRaisesRegex(switch.SwitchError,'NON_STRIPE_ROWS_CHANGED_BEFORE_WORKER_START'):
            switch.preserved(before,after,allow_provider_changes=False)
        switch.preserved(before,after,allow_provider_changes=True)
        with sqlite3.connect(self.private) as db:
            db.execute("UPDATE private_connections SET metadata_json=?",(json.dumps({'account_label':'wrong@example.test','scope':'synthetic-readonly','read_only_adapter':True}),))
        with self.assertRaisesRegex(switch.SwitchError,'NON_STRIPE_CONNECTION_IDENTITY_OR_SCOPE_CHANGED'):
            switch.preserved(before,switch.stable_records(self.private),allow_provider_changes=True)

    def test_api_wait_requires_readiness_health_and_auth_no_store(self):
        info,_ = self.role_fixture(running=True); info['State']['Health'] = {'Status':'healthy'}
        responses = [(200,{},b'{"ready":true}'),(401,{'cache-control':'no-store'},b'{}'),(401,{'cache-control':'no-store'},b'{}')]
        with mock.patch.object(switch,'inspect',return_value=info),mock.patch.object(switch,'local_request',side_effect=responses): switch.wait_api(self.identity)
        responses[1] = (200,{'cache-control':'no-store'},b'{}')
        with mock.patch.object(switch,'inspect',return_value=info),mock.patch.object(switch,'local_request',side_effect=responses),self.assertRaisesRegex(switch.SwitchError,'PRIVATE_AUTHENTICATION'):
            switch.wait_api(self.identity)
        with self.assertRaisesRegex(switch.SwitchError,'FIXED_LOCAL_API_ONLY'): switch.local_request('/untrusted')

    def test_cli_rejects_unreviewed_input_without_echoing_secrets_or_running_docker(self):
        out = io.StringIO()
        with redirect_stdout(out),mock.patch.object(switch,'docker') as docker:
            result = switch.cli(['schema','--secret','synthetic-not-real-private-secret'])
        self.assertEqual(result,1); self.assertNotIn('synthetic-not-real-private-secret',out.getvalue())
        self.assertIn('ARGUMENTS_REJECTED',out.getvalue()); docker.assert_not_called()

    def test_activation_starts_only_api_and_records_worker_stopped_until_first_sync(self):
        self.databases(new=True); self.actual_stripe()
        release = self.root/'candidate'; release.mkdir(mode=0o700)
        completed = release/'completed-release'; completed.mkdir(mode=0o700)
        args = SimpleNamespace(candidate=release/'candidate.json',candidate_sha256='a'*64,source_sha=self.source,
            schema_state=completed/'schema-state.json',schema_state_sha256='b'*64,
            stripe_seed=release/'stripe-seed-receipt.json',stripe_seed_sha256='c'*64)
        snapshot = switch.guard.release_snapshot(self.private,self.business)
        state = {'candidate_image':self.image,'attempt':self.attempt,'candidate_sha256':args.candidate_sha256,
            'source_sha':self.source,'old_ids':switch.live.PRIVATE_IDS,'schema_validation_sha256':'d'*64,
            'backup_sha256':'e'*64,'bank_enabled':False,'ai_enabled':False,'baseline':'synthetic-baseline',
            'baseline_sha256':'f'*64,'schema_before_sha256':'f'*64,'public_assets_published':False}
        events = []
        def create(role,progress,values,profile,journal):
            events.append(('create',role)); progress['new_ids'][role] = self.identity if role == 'api' else 'e'*64
            return progress['new_ids'][role]
        def launch(role,*unused): events.append(('start',role))
        with (mock.patch.object(switch,'checked_candidate',return_value={'image_id':self.image}),
              mock.patch.object(switch,'checked_schema_state',return_value=(state,snapshot,snapshot,{})),
              mock.patch.object(switch,'fixed_json',return_value={}),
              mock.patch.object(switch,'no_writers'),mock.patch.object(switch,'runtime_guard',return_value={}),
              mock.patch.object(switch,'checked_seed'),
              mock.patch.object(switch,'role_configuration',side_effect=lambda unused,role:self.runtime_values(role)),
              mock.patch.object(switch,'create_role',side_effect=create),mock.patch.object(switch,'launch_role',side_effect=launch),
              mock.patch.object(switch,'wait_api'),mock.patch.object(switch,'staged_check',return_value={'id':self.identity}),
              mock.patch.object(switch.transfer,'ENV',self.root/'runtime.env'),redirect_stdout(io.StringIO())):
            switch.transfer.ENV.write_bytes(b'synthetic')
            switch.activate(args)
        self.assertEqual(events,[('create','api'),('create','worker'),('start','api')])
        accepted = json.loads((completed/'api-state.json').read_bytes())
        self.assertEqual(accepted['phase'],'PRIVATE_COMPLETED_RELEASE_API_READY')
        self.assertFalse(accepted['worker_started']); self.assertFalse(accepted['deployed'])
        self.assertFalse(accepted['public_assets_published'])

    def test_finish_rejects_missing_first_sync_before_any_worker_start(self):
        self.databases(new=True)
        release = self.root/'candidate'; release.mkdir(mode=0o700)
        completed = release/'completed-release'; completed.mkdir(mode=0o700)
        original = self.root/'runtime.env'; original.write_bytes(b'synthetic')
        profiles = {role:self.runtime_values(role) for role in ('api','worker')}
        for role,values in profiles.items(): (completed/(role+'-runtime.env')).write_bytes(switch.profile_bytes(values))
        snapshot = switch.guard.release_snapshot(self.private,self.business)
        state = {'candidate_image':self.image,'attempt':self.attempt,'source_sha':self.source,
            'new_ids':{'api':self.identity,'worker':'e'*64},'new_private':{'api':{'id':self.identity}},
            'role_environment_sha256':{role:switch.sha(switch.profile_bytes(values)) for role,values in profiles.items()},
            'stable_before':switch.stable_records(self.private)}
        args = SimpleNamespace(candidate=release/'candidate.json',candidate_sha256='a'*64,source_sha=self.source,
            api_state=completed/'api-state.json',api_state_sha256='b'*64)
        with (mock.patch.object(switch,'checked_candidate',return_value={'image_id':self.image}),
              mock.patch.object(switch,'checked_api_state',return_value=(state,snapshot,{})),
              mock.patch.object(switch,'runtime_guard',return_value={}),mock.patch.object(switch,'wait_api'),
              mock.patch.object(switch,'no_writers'),mock.patch.object(switch,'staged_check',return_value={'id':self.identity}),
              mock.patch.object(switch,'role_configuration',side_effect=lambda unused,role:profiles[role]),
              mock.patch.object(switch.transfer,'ENV',original),mock.patch.object(switch,'launch_role') as launch):
            with self.assertRaisesRegex(switch.SwitchError,'FIRST_REAL_STRIPE_SYNC_REQUIRED'): switch.finish(args)
            launch.assert_not_called()
        self.assertFalse((completed/'finish-progress.json').exists())

    def test_timeout_during_new_create_retains_exact_attempt_for_explicit_rollback(self):
        completed = self.root/'completed-release'; completed.mkdir(mode=0o700)
        journal = completed/'activate-progress.json'
        progress = {'attempt':self.attempt,'candidate_image':self.image,'source_sha':self.source,'new_ids':{},'stage_names':{}}
        switch.save(journal,progress)
        with mock.patch.object(switch,'inspect',return_value=None),mock.patch.object(switch,'docker',side_effect=switch.SwitchError('DOCKER_OUTCOME_REQUIRES_OPERATOR_REVIEW')):
            with self.assertRaises(switch.SwitchError):
                switch.create_role('api',progress,self.runtime_values(),completed/'api-runtime.env',journal)
        evidence = json.loads(journal.read_bytes())
        self.assertEqual(evidence['stage_names'],{'api':'t24-private-finance-stage-api-'+self.attempt})
        self.assertEqual(evidence['new_ids'],{})

    def test_explicit_rollback_of_partial_freeze_restarts_exact_old_roles_and_never_restores_database(self):
        self.databases()
        release = self.root/'candidate'; release.mkdir(mode=0o700)
        completed = release/'completed-release'; completed.mkdir(mode=0o700)
        state = {'candidate_image':self.image,'attempt':self.attempt,'candidate_sha256':'a'*64,
            'source_sha':self.source,'old_ids':switch.live.PRIVATE_IDS,'baseline':'synthetic-baseline','baseline_sha256':'b'*64}
        args = SimpleNamespace(candidate=release/'candidate.json',candidate_sha256='a'*64,source_sha=self.source,
            state=completed/'schema-progress.json',state_sha256='c'*64)
        before = switch.guard.release_snapshot(self.private,self.business)
        events = []
        running = {'api':True,'worker':False}
        def old(role,baseline,*,running=None):
            return {'Id':switch.live.PRIVATE_IDS[role],'State':{'Running':globals_running[role]},'Name':'/t24-private-'+role}
        globals_running = running
        def call(command,**unused):
            events.append(command)
            if command[0] in {'stop','start'}:
                role = next(key for key,value in switch.live.PRIVATE_IDS.items() if value == command[-1])
                globals_running[role] = command[0] == 'start'
            return b''
        baseline = {'business':{'synthetic':'business'},'private_database':{'synthetic':'private'}}
        with (mock.patch.object(switch,'checked_candidate',return_value={'image_id':self.image}),
              mock.patch.object(switch,'fixed_json',side_effect=[state,baseline]),mock.patch.object(switch,'runtime_guard'),
              mock.patch.object(switch.live,'PRIVATE_DEVICE_INODE',(self.private.stat().st_dev,self.private.stat().st_ino)),
              mock.patch.object(switch.live,'prior_receipts',return_value=({},{})),
              mock.patch.object(switch.live,'database_snapshots',return_value=(baseline['business'],baseline['private_database'])),
              mock.patch.object(switch,'role_configuration',side_effect=lambda unused,role:self.runtime_values(role)),
              mock.patch.object(switch.transfer,'ENV',self.private),mock.patch.object(switch,'old_check',side_effect=old),
              mock.patch.object(switch,'no_writers'),mock.patch.object(switch,'wait_api'),
              mock.patch.object(switch,'docker',side_effect=call),redirect_stdout(io.StringIO())):
            switch.rollback(args)
        self.assertEqual(events,[['stop','--time','30',switch.live.PRIVATE_IDS['api']],
            ['start',switch.live.PRIVATE_IDS['api']],['start',switch.live.PRIVATE_IDS['worker']]])
        self.assertEqual(before,switch.guard.release_snapshot(self.private,self.business))
        self.assertTrue(all(command[0] not in {'rm','cp','restore'} for command in events))
        evidence = json.loads(next(completed.glob('rollback-*.json')).read_bytes())
        self.assertFalse(evidence['databases_restored']); self.assertFalse(evidence['new_stripe_features_available'])


if __name__ == '__main__': unittest.main()
