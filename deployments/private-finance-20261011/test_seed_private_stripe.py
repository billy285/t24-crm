"""Synthetic seed fixtures, actual core/GET adapter, no Docker/server/network."""
from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
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

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app/backend'))
import seed_private_stripe as seed


class SeedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.root.chmod(0o700)

    def candidate_fixture(self):
        results = self.root / 'test-results'; results.mkdir(mode=0o700)
        xml = ('<testsuite tests="738" failures="0" errors="0" skipped="0">' + '<testcase />' * 738 + '</testsuite>').encode()
        (results / 'regressions.xml').write_bytes(xml); (results / 'regressions.xml').chmod(0o600)
        proof = {'base_image_id':seed.live.PRIVATE_IMAGE,'python':'3.10.22',
            'base_package_versions':seed.candidate.BASE_PACKAGE_VERSIONS,'retained_wheel_versions':seed.candidate.WHEEL_VERSIONS,
            'retained_wheel_manifest_sha256':seed.candidate.BASE_WHEEL_MANIFEST_SHA,'runtime_packages_modified':False,'network':'none'}
        blob = json.dumps(proof).encode(); path = self.root / 'candidate-test-tools.json'; path.write_bytes(blob); path.chmod(0o600)
        receipt = {'format_version':1,'stage':'PRIVATE_FINANCE_CANDIDATE_VERIFIED','source_sha':'a'*40,
            'base_image_id':seed.live.PRIVATE_IMAGE,'image_id':'sha256:'+'b'*64,
            'candidate_regressions':{'tests':738,'minimum':738,'network':'none','production_environment_loaded':False,
                'production_database_access':False,'xml_sha256':seed.sha(xml),'test_tools_proof_sha256':seed.sha(blob)},
            'synthetic_schema':{'stage':'SYNTHETIC_SCHEMA_AND_OLD_IMAGE_COMPATIBILITY_VERIFIED',
                'tables':sorted(seed.TARGET_TABLES),'base_image_id':seed.live.PRIVATE_IMAGE,'candidate_image_id':'sha256:'+'b'*64,
                'old_image_reads_upgraded_schema':True,'original_rows_columns_indexes_preserved':True,
                'new_tables_empty':True,'business_unchanged':True,'production_database_access':False}}
        receipt.update({name:True for name in ('base_pin_verified_before_and_after_build','base_layers_verified',
            'all_other_backend_bytes_identical','all_package_bytes_identical','complete_frontend_dist_bytes_verified','existing_hashed_static_assets_preserved')})
        receipt.update({name:False for name in ('production_services_modified','public_assets_published','production_databases_modified','deployed')})
        return receipt

    def test_candidate_requires_actual_xml_runtime_and_rollback_evidence(self):
        receipt = self.candidate_fixture()
        with mock.patch.object(seed.transfer,'read_protected',side_effect=lambda p,*unused:p.read_bytes()):
            self.assertEqual(seed.checked_candidate(receipt,source_sha='a'*40,release=self.root),receipt)
            for field in ('all_other_backend_bytes_identical','base_layers_verified'):
                wrong = deepcopy(receipt); wrong[field] = False
                with self.subTest(field=field), self.assertRaises(seed.SeedError):
                    seed.checked_candidate(wrong,source_sha='a'*40,release=self.root)
            wrong = deepcopy(receipt); wrong['candidate_regressions']['minimum']=737
            with self.assertRaises(seed.SeedError):seed.checked_candidate(wrong,source_sha='a'*40,release=self.root)
            wrong = deepcopy(receipt);wrong['synthetic_schema']['old_image_reads_upgraded_schema']=False
            with self.assertRaises(seed.SeedError):seed.checked_candidate(wrong,source_sha='a'*40,release=self.root)
            (self.root/'test-results'/'regressions.xml').write_bytes(b'<testsuite tests="738" skipped="1" />')
            with self.assertRaises(seed.SeedError):seed.checked_candidate(receipt,source_sha='a'*40,release=self.root)

    def test_seed_cannot_overwrite_credentials_lease_or_pending_oauth(self):
        self.assertEqual(seed.seedable({'row':None}),0)
        row = {'owner_id':'4','source_id':'stripe','status':'disconnected','generation':5}
        self.assertEqual(seed.seedable({'row':row}),5)
        for changes in ({'status':'connected'},{'encrypted_credentials':'synthetic-encrypted'},
                        {'sync_lease_until':'2026-10-11'},{'oauth_state_hash':'synthetic'}, {'owner_id':'5'}, {'generation':True}):
            with self.subTest(changes=changes),self.assertRaisesRegex(seed.SeedError,'EXISTING_STRIPE_CONNECTION_PRESERVED'):
                seed.seedable({'row':{**row,**changes}})

    def test_configuration_contains_only_private_identity_no_platform_or_ai_credentials(self):
        parsed = {'DATABASE_URL':'sqlite:///./data/crm_prod.db','DATABASE_SCHEMA_MODE':'verify_only',
            'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db','PRIVATE_WORKSPACE_OWNER_IDS':'4',
            'PRIVATE_WORKSPACE_ENCRYPTION_KEY':'synthetic-key','JWT_SECRET_KEY':'synthetic-jwt',
            'PRIVATE_WORKSPACE_GOOGLE_CLIENT_SECRET':'synthetic-other-platform','PRIVATE_MAIL_BRIEF_API_KEY':'synthetic-ai'}
        with mock.patch.object(seed.live,'parse_env',return_value=parsed):
            selected=seed.checked_configuration(b'fixture')
        self.assertNotIn('PRIVATE_WORKSPACE_GOOGLE_CLIENT_SECRET',selected)
        self.assertNotIn('PRIVATE_MAIL_BRIEF_API_KEY',selected)
        self.assertEqual(selected['PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID'],seed.transfer.ACCOUNT)
        self.assertEqual(selected['PRIVATE_WORKSPACE_PLAID_ENABLED'],'false')
        for field in ('STRIPE_SECRET_KEY','OPENAI_API_KEY','PRIVATE_WORKSPACE_STRIPE_KEY'):
            with mock.patch.object(seed.live,'parse_env',return_value={**parsed,field:'synthetic'}),self.assertRaises(seed.SeedError):
                seed.checked_configuration(b'fixture')

    def helper_fixture(self):
        image='sha256:'+'b'*64; identity='c'*64; attempt='d'*32
        info={'Id':identity,'Image':image,'Config':{'Labels':{seed.HELPER_LABEL:attempt},'Entrypoint':['python'],
            'Cmd':['-c',seed.helper_code()],'WorkingDir':'/app/backend','OpenStdin':True,'Env':['PATH=/usr/bin','PYTHONDONTWRITEBYTECODE=1']},
            'HostConfig':{'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],
            'NetworkMode':'bridge','RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'none'},'PortBindings':{},
            'PidsLimit':64,'Memory':256*1024**2,'NanoCpus':10**9,'Tmpfs':{'/tmp':'rw,nosuid,noexec,size=64m'},'IpcMode':'private'},
            'Mounts':[{'Type':'bind','Source':str(seed.BUSINESS_ROOT),'Destination':'/app/backend/data','RW':False},
                {'Type':'bind','Source':str(seed.PRIVATE_ROOT),'Destination':'/private-data','RW':True}]}
        return info,identity,attempt,image

    def test_helper_mount_privilege_program_and_secret_config_fail_closed(self):
        info,identity,attempt,image=self.helper_fixture()
        self.assertEqual(seed.checked_helper(info,identity,attempt,image),info)
        changes=[lambda v:v['Mounts'][0].update(RW=True),lambda v:v['HostConfig'].update(Privileged=True),
            lambda v:v['HostConfig']['LogConfig'].update(Type='json-file'),
            lambda v:v['Config']['Env'].append('PRIVATE_WORKSPACE_STRIPE_KEY=rk_live_SYNTHETICONLY'),
            lambda v:v['Config'].update(Cmd=['-c','unreviewed']),lambda v:v.update(Image=seed.live.PRIVATE_IMAGE)]
        for change in changes:
            value=deepcopy(info);change(value)
            with self.assertRaises(seed.SeedError):seed.checked_helper(value,identity,attempt,image)
        command=seed.create_command('synthetic',attempt,image)
        self.assertNotIn('--env-file',command);self.assertNotIn('--publish',command)
        self.assertNotIn('rk_live_',json.dumps(command));self.assertIn('--interactive',command)

    def test_running_private_writer_and_ancestor_bind_rejected(self):
        identity='a'*64
        old={'State':{'Running':False},'Mounts':[]}
        for source in (str(seed.PRIVATE_ROOT),str(seed.PRIVATE_ROOT.parent),str(seed.PRIVATE_ROOT/'nested')):
            current={'Mounts':[{'Type':'bind','Source':source,'RW':True}]}
            with mock.patch.object(seed,'docker',return_value=(identity+'\n').encode()),mock.patch.object(seed,'inspect_container',side_effect=lambda cid:current if cid==identity else old):
                with self.assertRaisesRegex(seed.SeedError,'ALL_PRIVATE_WRITERS_MUST_BE_STOPPED'):seed.no_private_writers()
        with mock.patch.object(seed,'docker',return_value=b''),mock.patch.object(seed,'inspect_container',return_value={'State':{'Running':True}}):
            with self.assertRaisesRegex(seed.SeedError,'OLD_PRIVATE_SERVICE_MUST_BE_STOPPED'):seed.no_private_writers()

    def test_safe_report_cannot_echo_key_or_claim_another_mode_or_generation(self):
        report={'stage':'PRIVATE_STRIPE_SEED_CONNECTED','owner_id':'4','mode':'live','six_get_probes_verified':True,
            'encrypted_db_credential_verified':True,'generation':1,'key_removed_from_process_environment':True}
        self.assertEqual(seed.checked_report(json.dumps(report).encode(),0),report)
        for change in ({'key':'rk_live_SYNTHETICONLY'},{'mode':'test'},{'generation':2},{'six_get_probes_verified':False}):
            with self.assertRaises(seed.SeedError):seed.checked_report(json.dumps({**report,**change}).encode(),0)

    def test_cli_never_echoes_unknown_key_argument_or_unexpected_exception(self):
        output=io.StringIO()
        with redirect_stdout(output):self.assertEqual(seed.cli(['--api-key','rk_live_SYNTHETICSECRET']),1)
        self.assertNotIn('SYNTHETICSECRET',output.getvalue())
        with mock.patch.object(seed.SafeParser,'parse_args',return_value=None),mock.patch.object(seed,'main',side_effect=ValueError('rk_live_SYNTHETICSECRET')),redirect_stdout(output):
            self.assertEqual(seed.cli([]),1)
        self.assertNotIn('SYNTHETICSECRET',output.getvalue())

    def test_explicit_root_server_execute_required_before_credential_access(self):
        with mock.patch.object(seed.transfer,'environment_guard') as guard:
            with self.assertRaisesRegex(seed.SeedError,'EXPLICIT_VERIFIED_ROOT_SERVER_REQUIRED'):
                seed.main(SimpleNamespace(execute=False))
            guard.assert_not_called()


    def test_one_use_claim_preserves_first_attempt_after_ambiguous_failure(self):
        with mock.patch.object(seed.transfer,'CONFIG',self.root),mock.patch.object(seed.transfer,'protected_directory',side_effect=lambda p:self.assertEqual(p.stat().st_mode & 0o777,0o700)):
            path=seed.claim_bootstrap('a'*64,'b'*64,'c'*40,'d'*32)
            original=path.read_bytes()
            with self.assertRaisesRegex(seed.SeedError,'SEALED_BOOTSTRAP_ALREADY_CLAIMED_REVIEW_REQUIRED'):
                seed.claim_bootstrap('a'*64,'e'*64,'c'*40,'f'*32)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertNotIn('api_key',original.decode())


class SchemaAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.root.chmod(0o700)
        self.private=self.root/'workspace.db';self.business=self.root/'business.db';self.backup=self.root/'original-backup.db'
        from sqlalchemy import create_engine
        from models.private_workspace import PrivateWorkspaceBase
        engine=create_engine('sqlite:///'+str(self.private))
        PrivateWorkspaceBase.metadata.create_all(engine,tables=[PrivateWorkspaceBase.metadata.tables[name] for name in seed.guard.BASE_TABLES]);engine.dispose()
        self.private.chmod(0o600)
        with sqlite3.connect(self.business) as db:
            for index in range(83):db.execute('CREATE TABLE fixture_'+str(index)+'(id INTEGER PRIMARY KEY,amount INTEGER)')
            db.execute('INSERT INTO fixture_0 VALUES(1,70000)')
        self.before=seed.guard.release_snapshot(self.private,self.business)
        with sqlite3.connect(self.private) as old,sqlite3.connect(self.backup) as copied:old.backup(copied)
        self.backup.chmod(0o600)
        empty=self.root/'empty.db';engine=create_engine('sqlite:///'+str(empty));PrivateWorkspaceBase.metadata.create_all(engine);engine.dispose();empty.chmod(0o600)
        objects=seed.guard.database_snapshot(empty,private=True)['schema_objects']
        self.manifest={'format_version':1,'stage':'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST','source_sha':'a'*40,
            'baseline_tables':sorted(seed.guard.BASE_TABLES),'target_tables':sorted(seed.TARGET_TABLES),
            'target_schema_objects':objects,'business_table_count':83,'business_schema_sha256':self.before['business']['schema_sha256']}
        engine=create_engine('sqlite:///'+str(self.private));PrivateWorkspaceBase.metadata.create_all(engine);engine.dispose()
        self.after=seed.guard.release_snapshot(self.private,self.business)
        self.validation=seed.guard.compare_snapshots(self.before,self.after,self.manifest,source_sha='a'*40,mode='in_place')
        self.receipt={'source_sha':'a'*40,'synthetic_schema':{'schema_objects':objects}}

    def check(self, **changes):
        values={'before':self.before,'after':self.after,'manifest':self.manifest,'validation':self.validation,'receipt':self.receipt}
        values.update(changes)
        with mock.patch.object(seed.live,'PRIVATE_DB',self.private),mock.patch.object(seed.live,'BUSINESS',self.business):
            return seed.checked_schema(**values)

    def test_actual_in_place_acceptance_requires_current_ten_table_83_customer_proof(self):
        self.assertEqual(self.check(),self.after)
        wrong=deepcopy(self.manifest);wrong['business_table_count']=1
        with self.assertRaisesRegex(seed.SeedError,'EXACT_PRODUCTION_TEN_TABLE_MANIFEST_REQUIRED'):self.check(manifest=wrong)
        wrong=deepcopy(self.validation);wrong['mode']='clone'
        with self.assertRaisesRegex(seed.SeedError,'ACTUAL_IN_PLACE_SCHEMA_ACCEPTANCE_REQUIRED'):self.check(validation=wrong)
        wrong=deepcopy(self.receipt);wrong['synthetic_schema']['schema_objects']={}
        with self.assertRaises(seed.SeedError):self.check(receipt=wrong)

    def test_post_acceptance_customer_write_and_added_private_write_both_block_seed(self):
        with sqlite3.connect(self.business) as db:db.execute('UPDATE fixture_0 SET amount=70001')
        with self.assertRaisesRegex(seed.SeedError,'MIGRATED_PRIVATE_OR_BUSINESS_SNAPSHOT_DRIFT'):self.check()
        with sqlite3.connect(self.business) as db:db.execute('UPDATE fixture_0 SET amount=70000')
        with sqlite3.connect(self.private) as db:
            db.execute("INSERT INTO private_bank_links(id,owner_id,connection_id,generation,state,expires_at,created_at,updated_at) VALUES('synthetic','4','synthetic',0,'pending','2026-10-11','2026-10-11','2026-10-11')")
        with self.assertRaisesRegex(seed.SeedError,'MIGRATED_PRIVATE_OR_BUSINESS_SNAPSHOT_DRIFT'):self.check()

    def test_backup_proof_requires_original_inventory_rows_and_distinct_file(self):
        with mock.patch.object(seed.live,'PRIVATE_DB',self.private),mock.patch.object(seed.live,'BUSINESS',self.business),\
             mock.patch.object(seed.transfer,'read_protected',side_effect=lambda p,*unused:p.read_bytes()):
            seed.checked_backup(self.backup,seed.sha(self.backup.read_bytes()),self.before)
            with self.assertRaisesRegex(seed.SeedError,'REVIEWED_ORIGINAL_BACKUP_HASH_REQUIRED'):
                seed.checked_backup(self.backup,'0'*64,self.before)
            with self.assertRaisesRegex(seed.SeedError,'BACKUP_CANNOT_ALIAS_LIVE_DB'):
                seed.checked_backup(self.private,seed.sha(self.private.read_bytes()),self.before)
            with sqlite3.connect(self.backup) as db:db.execute("INSERT INTO private_preferences(owner_id,preferences_json,updated_at) VALUES('4','{}','2026-10-11')")
            with self.assertRaisesRegex(seed.SeedError,'ORIGINAL_PRIVATE_BACKUP_PROOF_DRIFT'):
                seed.checked_backup(self.backup,seed.sha(self.backup.read_bytes()),self.before)


class ActualHelperTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.root.chmod(0o700)
        self.business=self.root/'business.db';self.private_root=self.root/'private';self.private_root.mkdir(mode=0o700)
        self.private=self.private_root/'workspace.db'
        with sqlite3.connect(self.business) as db:
            db.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY, role TEXT, status TEXT)')
            db.execute("INSERT INTO employees VALUES(4,'super_admin','active')")
            db.execute('CREATE TABLE finance_sentinel(id INTEGER,amount INTEGER)')
            db.execute('INSERT INTO finance_sentinel VALUES(1,70000)')
        from sqlalchemy import create_engine
        from models.private_workspace import PrivateWorkspaceBase
        engine=create_engine('sqlite:///'+str(self.private));PrivateWorkspaceBase.metadata.create_all(engine);engine.dispose()
        self.private.chmod(0o600)
        self.config={'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:///'+str(self.private),
            'DATABASE_URL':'sqlite:///'+str(self.business),'DATABASE_SCHEMA_MODE':'verify_only','PRIVATE_WORKSPACE_OWNER_IDS':'4',
            'PRIVATE_WORKSPACE_ENCRYPTION_KEY':'synthetic-private-seed-encryption-for-offline-tests-only',
            'JWT_SECRET_KEY':'synthetic-private-seed-jwt-for-offline-tests-only',
            'PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID':seed.transfer.ACCOUNT,'PRIVATE_WORKSPACE_STRIPE_MODE':'live',
            'PRIVATE_WORKSPACE_PLAID_ENABLED':'false','PRIVATE_MAIL_BRIEF_ENABLED':'false','PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT':'false'}
        before=seed.connection_state(self.private)
        # Generated fiction exercises the real restricted-key shape. It is
        # never obtained from Stripe and only reaches MockTransport.
        synthetic_key = '_'.join(('rk', 'live', 'SYNTHETICSEEDONLY' + '123456789'))
        self.packet={'configuration':self.config,'credentials':{'api_key':synthetic_key,
            'stripe_account_id':seed.transfer.ACCOUNT,'mode':'live'},'stripe_before_sha256':before['stripe_sha256'],
            'other_before_sha256':before['other_connections_sha256'],'generation_before':0}

    def run_helper(self, *, deny_resource=None, withdraw=False, owner_active=True):
        import httpx
        from services import private_workspace_providers as provider,private_workspace as core
        import asyncio
        asyncio.run(core.close_private_workspace_storage())
        original=provider.begin_connect;calls=[]
        async def handler(request):
            calls.append((request.method,request.url.path))
            if deny_resource==request.url.path:return httpx.Response(403,json={'error':'synthetic-denied'})
            if request.url.path=='/v1/account':return httpx.Response(200,json={'object':'account','id':seed.transfer.ACCOUNT})
            if request.url.path=='/v1/balance':return httpx.Response(200,json={'object':'balance','livemode':True,'available':[],'pending':[]})
            if withdraw and request.url.path=='/v1/payouts':
                with sqlite3.connect(self.business) as db:db.execute("UPDATE employees SET status='inactive' WHERE id=4")
            return httpx.Response(200,json={'object':'list','data':[],'has_more':False})
        async def mocked_begin(source,state):return await original(source,state,transport=httpx.MockTransport(handler))
        if not owner_active:
            with sqlite3.connect(self.business) as db:db.execute("UPDATE employees SET status='inactive' WHERE id=4")
        code=seed.helper_code().replace('/private-data/workspace.db',str(self.private))
        output=io.StringIO()
        with mock.patch.dict(os.environ,{},clear=True),mock.patch.object(sys,'stdin',io.StringIO(json.dumps(self.packet))),\
             mock.patch.object(provider,'begin_connect',side_effect=mocked_begin),redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_result:exec(compile(code,'<synthetic-seed-helper>','exec'),{})
        return exit_result.exception.code,json.loads(output.getvalue()),calls

    def test_actual_helper_six_gets_encrypts_without_customer_or_other_private_changes(self):
        business_before=self.business.read_bytes();schema=seed.guard.database_snapshot(self.private,private=True)
        code,report,calls=self.run_helper()
        self.assertEqual(code,0);self.assertEqual(report['stage'],'PRIVATE_STRIPE_SEED_CONNECTED')
        self.assertEqual(calls,[('GET','/v1/account'),('GET','/v1/balance'),('GET','/v1/charges'),('GET','/v1/refunds'),('GET','/v1/disputes'),('GET','/v1/payouts')])
        self.assertEqual(self.business.read_bytes(),business_before)
        saved=seed.connection_state(self.private)['row'];self.assertEqual(saved['status'],'connected')
        self.assertNotIn(self.packet['credentials']['api_key'],saved['encrypted_credentials'])
        after=seed.guard.database_snapshot(self.private,private=True)
        for name in seed.TARGET_TABLES-{'private_connections'}:self.assertEqual(schema['tables'][name],after['tables'][name])
        self.assertNotIn(self.packet['credentials']['api_key'],json.dumps(report))

    def test_actual_helper_revocation_during_last_get_cannot_commit_credentials(self):
        code,report,calls=self.run_helper(withdraw=True)
        self.assertEqual(code,1);self.assertEqual(len(calls),6)
        self.assertEqual(report['stage'],'PRIVATE_STRIPE_SEED_HELPER_REJECTED')
        self.assertIsNone(seed.connection_state(self.private)['row'])

    def test_actual_helper_missing_read_permission_never_connects(self):
        code,report,calls=self.run_helper(deny_resource='/v1/disputes')
        self.assertEqual(code,1);self.assertEqual(calls[-1],('GET','/v1/disputes'))
        self.assertIsNone(seed.connection_state(self.private)['row'])
        self.assertNotIn(self.packet['credentials']['api_key'],json.dumps(report))

    def test_actual_helper_inactive_owner_rejected_before_any_provider_call(self):
        code,report,calls=self.run_helper(owner_active=False)
        self.assertEqual(code,1);self.assertEqual(calls,[])
        self.assertIsNone(seed.connection_state(self.private)['row'])


if __name__=='__main__':
    unittest.main()
