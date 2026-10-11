"""Synthetic SQLite and isolated runtime guards; no production/provider access."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parent))
import seeded_repair as repair
import test_switch_completed as fixtures


class SeededRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SwitchTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.databases(new=True);self.fixture.actual_stripe(success=False)
        self.root=self.fixture.root;self.private=self.fixture.private;self.business=self.fixture.business
        self.source=self.fixture.source;self.image=self.fixture.image;self.attempt=self.fixture.attempt
        self.identity=self.fixture.identity
        self.snapshot=repair.guard.release_snapshot(self.private,self.business)
        self.stripe=repair.stripe_fingerprint(1)

    def stripe_update(self,sql,value):
        with sqlite3.connect(self.private) as db:db.execute(sql,(value,))

    def helper_fixture(self,*,sync=False):
        name='t24-private-seeded-'+('sync' if sync else 'fetch')+'-'+self.attempt
        return {'Id':self.identity,'Image':self.image,'Name':'/'+name,
            'Config':{'Labels':{repair.LABEL+('.sync' if sync else ''):self.attempt},
                'Entrypoint':['python'],'Cmd':['-c',repair.sync_code() if sync else repair.helper_code()],
                'WorkingDir':'/app/backend','OpenStdin':True,'Env':['PATH=/usr/bin','PYTHONDONTWRITEBYTECODE=1']},
            'HostConfig':{'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],
                'NetworkMode':'bridge','RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'none'},
                'PortBindings':{},'Binds':None,'Privileged':False,'CapAdd':None,'Devices':None,'DeviceRequests':None,
                'PidMode':'','UTSMode':'','IpcMode':'private','PidsLimit':64,'Memory':256*1024**2,
                'NanoCpus':10**9,'Tmpfs':{'/tmp':'rw,nosuid,noexec,size=64m'}},
            'Mounts':[{'Type':'bind','Source':str(self.business.parent),'Destination':'/app/backend/data','RW':False},
                {'Type':'bind','Source':str(self.private.parent),'Destination':'/private-data','RW':sync}],
            'State':{'Running':False}}

    def success_report(self):
        return {'stage':'PRIVATE_SEEDED_FULL_FETCH_VALIDATED','success':True,
            'calls':['account','balance','charges','charges','refunds','disputes','payouts','payouts'],
            'resource_counts':{'charges':100,'refunds':1,'disputes':2,'payouts':85},
            'database_writes':False,'connected':False,'seed_attempted':False}

    def test_existing_authorization_requires_same_owner_generation_account_mode_status_and_no_lease(self):
        original=repair.seed.connection_state(self.private)['row']
        for column,value in (('owner_id','5'),('generation',2),('status','disconnected'),
                             ('encrypted_credentials',None),('sync_lease_until','2026-10-12 00:00:00')):
            with self.subTest(column=column):
                self.stripe_update('UPDATE private_connections SET '+column+'=? WHERE source_id=\'stripe\'',value)
                with self.assertRaises(repair.RepairError):repair.stripe_fingerprint(1)
                self.stripe_update('UPDATE private_connections SET '+column+'=? WHERE source_id=\'stripe\'',original[column])
        metadata=json.loads(original['metadata_json']);metadata['stripe_account_id']='acct_different'
        self.stripe_update("UPDATE private_connections SET metadata_json=? WHERE source_id='stripe'",json.dumps(metadata))
        with self.assertRaisesRegex(repair.RepairError,'ACCOUNT_OR_MODE'):repair.stripe_fingerprint(1)

    def test_original_stripe_ciphertext_is_frozen_even_when_failed_sync_error_changes(self):
        self.stripe_update("UPDATE private_connections SET error=? WHERE source_id='stripe'",'synthetic safe setup failure')
        self.assertEqual(repair.stripe_fingerprint(1),self.stripe)
        self.stripe_update("UPDATE private_connections SET encrypted_credentials=? WHERE source_id='stripe'",'other-ciphertext')
        self.assertNotEqual(repair.stripe_fingerprint(1),self.stripe)

    def test_bootstrap_verification_is_memory_only_and_never_returns_plaintext_or_exception_content(self):
        credentials={'api_key':'synthetic-secret-value','stripe_account_id':repair.transfer.ACCOUNT,'mode':'live'}
        crypto=mock.Mock();crypto.fernet.return_value=json.dumps(credentials).encode()
        before=(self.private.read_bytes(),self.business.read_bytes());output=io.StringIO()
        with mock.patch.object(repair.transfer,'environment_guard',return_value='synthetic-private-key'),\
             mock.patch.object(repair.transfer,'Crypto',return_value=crypto),\
             mock.patch.object(repair.transfer,'get_bootstrap',return_value={'credentials':credentials}),redirect_stdout(output):
            result=repair.stripe_fingerprint(1,verify_bootstrap=True)
            self.assertNotIn('synthetic-secret-value',json.dumps(result));self.assertEqual(output.getvalue(),'')
            crypto.fernet.side_effect=RuntimeError('synthetic-secret-value')
            with self.assertRaisesRegex(repair.RepairError,'^EXISTING_STRIPE_CREDENTIAL_VERIFICATION_REJECTED$'):
                repair.stripe_fingerprint(1,verify_bootstrap=True)
        self.assertEqual((self.private.read_bytes(),self.business.read_bytes()),before)

    def test_customer_finance_same_inode_ddl_local_notes_and_non_stripe_rows_are_protected(self):
        state={'stable_before':repair.switch.stable_records(self.private)};stripe={'generation':1}
        self.assertEqual(repair.existing_data(self.snapshot,state,self.snapshot,stripe),self.stripe)
        with sqlite3.connect(self.business) as db:db.execute('UPDATE ledger_0 SET amount=1')
        current=repair.guard.release_snapshot(self.private,self.business)
        with self.assertRaises(repair.switch.SwitchError):repair.existing_data(current,state,self.snapshot,stripe)

    def test_all_six_new_bank_ai_tables_must_stay_empty(self):
        with sqlite3.connect(self.private) as db:
            db.execute("INSERT INTO private_translation_usage(owner_id,month,characters,updated_at) VALUES('4','2026-10',0,'2026-10-11')")
        with self.assertRaisesRegex(repair.switch.SwitchError,'BANK_OR_AI'):
            repair.existing_data(repair.guard.release_snapshot(self.private,self.business),
                {'stable_before':repair.switch.stable_records(self.private)},self.snapshot,{'generation':1})

    def test_both_original_claims_and_bootstrap_remain_exact_no_retry_or_alias(self):
        config=self.root/'config';config.mkdir(mode=0o700);claims=config/'stripe-seed-claims';claims.mkdir(mode=0o700)
        bootstrap=config/'stripe-bootstrap.json';bootstrap.write_bytes(b'synthetic-sealed-blob')
        bootstrap_hash=repair.switch.sha(bootstrap.read_bytes())
        old=claims/(bootstrap_hash+'.json');old.write_bytes(b'old-claim')
        retry=claims/(bootstrap_hash+'.reviewed-retry.json');retry.write_bytes(b'reviewed-claim')
        value={'bootstrap_sha256':bootstrap_hash,'original_claim':str(old),
            'original_claim_sha256':repair.switch.sha(old.read_bytes()),'reviewed_retry_claim':str(retry),
            'reviewed_retry_claim_sha256':repair.switch.sha(retry.read_bytes())}
        with mock.patch.object(repair.transfer,'CONFIG',config),mock.patch.object(repair.transfer,'BOOTSTRAP',bootstrap):
            repair.claims_unchanged(value)
            with self.assertRaises(repair.RepairError):repair.claims_unchanged({**value,'reviewed_retry_claim':str(old)})
            retry.write_bytes(b'changed')
            with self.assertRaisesRegex(repair.RepairError,'CLAIM_CHANGED'):repair.claims_unchanged(value)
        self.assertEqual(old.read_bytes(),b'old-claim')

    def test_readonly_fetch_checks_exact_program_and_both_db_mounts_before_network(self):
        info=self.helper_fixture();repair.fetch_helper(info,self.identity,self.image,self.attempt)
        changes=[lambda x:x['Mounts'][0].update(RW=True),lambda x:x['Mounts'][1].update(RW=True),
            lambda x:x['HostConfig'].update(Privileged=True),lambda x:x['HostConfig'].update(PortBindings={'8001/tcp':[]}),
            lambda x:x['Config'].update(Cmd=['-c','arbitrary program']),lambda x:x['Config']['Env'].append('PRIVATE_WORKSPACE_STRIPE_KEY=synthetic')]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                altered=deepcopy(info);change(altered)
                with self.assertRaises((repair.RepairError,repair.diagnosis.DiagnosisError)):
                    repair.fetch_helper(altered,self.identity,self.image,self.attempt)

    def test_normal_sync_only_writes_private_db_with_original_sandbox_and_fixed_core_sync(self):
        info=self.helper_fixture(sync=True);repair.sync_helper(info,self.identity,self.image,self.attempt)
        for index in (0,1):
            altered=deepcopy(info);altered['Mounts'][index]['RW']=not altered['Mounts'][index]['RW']
            with self.assertRaises(repair.RepairError):repair.sync_helper(altered,self.identity,self.image,self.attempt)
        code=repair.sync_code();compile(code,'synthetic-normal-sync','exec')
        self.assertIn("core.sync_source(db,'4','stripe'",code)
        self.assertNotIn('connect_source',code);self.assertNotIn('private_session_factory',code)
        self.assertNotIn('create_all',code);self.assertNotIn('init_private',code)
        command=repair.sync_command('t24-private-seeded-sync-'+self.attempt,self.image,self.attempt)
        self.assertIn('--log-driver',command);self.assertIn('none',command);self.assertIn('--read-only',command)
        self.assertNotIn('PRIVATE_WORKSPACE_STRIPE_KEY',str(command));self.assertNotIn('synthetic-secret',str(command))

    def test_full_fetch_requires_all_resources_bounded_pagination_and_no_connect_or_writes(self):
        report=self.success_report();self.assertEqual(repair.fetch_report(json.dumps(report).encode()),report)
        changes=[{'calls':['account','balance','charges']},{'calls':['account','balance','refunds','charges','disputes','payouts']},
            {'calls':['account','balance','charges','charges','charges','refunds','disputes','payouts']},
            {'resource_counts':{**report['resource_counts'],'charges':101}},{'database_writes':True},{'connected':True},
            {'seed_attempted':True},{'credentials':'synthetic-secret'}]
        for values in changes:
            with self.subTest(values=list(values)):
                with self.assertRaises(repair.RepairError):repair.fetch_report(json.dumps({**report,**values}).encode())
        code=repair.helper_code();compile(code,'synthetic-readonly-fetch','exec')
        self.assertIn("method!='GET'",code);self.assertIn("provider.fetch_source('stripe'",code)
        self.assertNotIn('begin_connect',code);self.assertNotIn('connect_source',code);self.assertNotIn('.commit(',code)

    def test_candidate_baseline_is_exact_even_after_legitimate_sync_or_api_restart(self):
        value={'stage':repair.STAGE,'format_version':1,'mutation_performed':False,'snapshot':self.snapshot,
            'ancestor_api_runtime':{'started_at':'synthetic-start'}}
        repair.compare_baseline(deepcopy(value),value)
        for changed in ({**value,'snapshot':{}},{**value,'ancestor_api_runtime':{'started_at':'later'}}):
            with self.assertRaisesRegex(repair.RepairError,'FROZEN_SEEDED_REPAIR_BASELINE_DRIFT'):repair.compare_baseline(changed,value)

    def test_lineage_cannot_be_combined_with_absent_stripe_resume_or_legacy_candidate(self):
        with self.assertRaisesRegex(repair.RepairError,'COMPLETE_SEEDED_REPAIR_LINEAGE'):
            repair.checked_lineage({'resume_lineage':{},'seeded_repair_lineage':{}})
        with self.assertRaises(repair.RepairError):repair.checked_lineage({})

    def test_complete_fetch_receipt_cannot_be_substituted_from_another_candidate_or_snapshot(self):
        candidate_path=self.root/'candidate.json';validation=self.root/'seeded-repair'/('validation-'+self.attempt+'.json')
        args=SimpleNamespace(candidate=candidate_path,source_sha=self.source,candidate_sha256='a'*64,validation=validation)
        receipt={'image_id':self.image,'baseline_sha256':'b'*64,'seeded_repair_lineage':{'synthetic':'lineage'}}
        baseline={'snapshot':self.snapshot,'stripe_authorization':self.stripe}
        report={**self.success_report(),'format_version':1,'source_sha':self.source,'candidate_sha256':'a'*64,
            'image_id':self.image,'baseline_sha256':'b'*64,'seeded_repair_lineage_sha256':repair.guard.digest(receipt['seeded_repair_lineage']),
            'snapshot_sha256':repair.guard.digest(self.snapshot),'stripe_authorization':self.stripe,
            'original_claims_preserved':True,'production_services_changed':False,'deployed':False}
        repair.checked_validation(report,args,receipt,baseline)
        for column,value in (('candidate_sha256','c'*64),('snapshot_sha256','c'*64),('seed_attempted',True),
                             ('stripe_authorization',{**self.stripe,'generation':2}),('image_id','sha256:'+'c'*64)):
            with self.subTest(column=column):
                with self.assertRaises(repair.RepairError):repair.checked_validation({**report,column:value},args,receipt,baseline)

    def test_sync_audit_fingerprint_is_readonly_and_preserves_failed_attempts(self):
        before=self.private.read_bytes();values=repair.sync_audits()
        self.assertEqual(len(values),1);self.assertEqual(next(iter(values.values()))['status'],'failed')
        self.assertEqual(self.private.read_bytes(),before)
        self.assertNotIn('synthetic-run',json.dumps(values))

    def test_finish_never_starts_worker_without_actual_persisted_success(self):
        args=SimpleNamespace(candidate=self.root/'candidate.json',state=self.root/'seeded-repair'/'api-state.json',
            state_sha256='a'*64,source_sha=self.source,candidate_sha256='b'*64)
        state={'phase':'PRIVATE_SEEDED_REPAIR_API_READY','api_started':True,'worker_started':False,
            'new_ids':{'api':'a'*64,'worker':'b'*64},'new_private':{'api':{'proof':'api'}},'attempt':self.attempt,
            'role_environment_sha256':{'api':'x','worker':'x'},'stable_before':repair.switch.stable_records(self.private)}
        baseline={'stripe_authorization':self.stripe};receipt={'image_id':self.image}
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=({},self.snapshot,{},None,baseline)),\
             mock.patch.object(repair,'checked_repair_state',return_value=state),\
             mock.patch.object(repair,'repair_root',return_value=self.root),\
             mock.patch.object(repair,'claims_unchanged'),mock.patch.object(repair.switch,'runtime_guard'),\
             mock.patch.object(repair.transfer,'read_protected',return_value=b'bytes'),\
             mock.patch.object(repair.switch,'role_configuration',return_value={}),mock.patch.object(repair.switch,'profile_bytes',return_value=b'bytes'),\
             mock.patch.object(repair.switch,'sha',return_value='x'),mock.patch.object(repair.switch,'staged_check',return_value={'proof':'api'}),\
             mock.patch.object(repair.switch,'wait_api'),mock.patch.object(repair.switch,'no_writers'),\
             mock.patch.object(repair.switch,'docker') as docker:
            with self.assertRaisesRegex(repair.switch.SwitchError,'PERSISTED_FIRST_STRIPE_SYNC_SUCCESS'):
                repair.finish(args)
            docker.assert_not_called()

    def test_cli_failures_never_echo_credentials_or_mutate_without_execute(self):
        output=io.StringIO()
        with redirect_stdout(output),mock.patch.object(repair.switch,'docker') as docker:
            result=repair.cli(['activate','--source-sha','synthetic-secret','--candidate','/tmp/no',
                '--candidate-sha256','synthetic-secret','--validation','/tmp/no','--validation-sha256','synthetic-secret'])
        self.assertEqual(result,1);self.assertNotIn('synthetic-secret',output.getvalue());docker.assert_not_called()

    def phase_fixture(self):
        release=self.root/'candidate';release.mkdir(mode=0o700)
        stage=release/'seeded-repair';stage.mkdir(mode=0o700)
        environment=self.root/'runtime.env';environment.write_bytes(b'synthetic-env')
        self.env_patch=mock.patch.object(repair.transfer,'ENV',environment);self.env_patch.start();self.addCleanup(self.env_patch.stop)
        baseline={'stage':repair.STAGE,'format_version':1,'mutation_performed':False,'snapshot':self.snapshot,'stripe_authorization':self.stripe,
            'stable_records':repair.switch.stable_records(self.private),
            'ancestor_api_state':'/synthetic/api-state.json','ancestor_api_state_sha256':'e'*64}
        lineage={'new_baseline':str(release/'repair-baseline.json'),'new_baseline_sha256':'b'*64}
        receipt={'image_id':self.image,'baseline_sha256':'b'*64,'seeded_repair_lineage':lineage}
        ancestor={'new_ids':{'api':'f'*64,'worker':'0'*64},'attempt':'1'*32,'candidate_image':'sha256:'+'f'*64,
            'source_sha':'e'*40}
        args=SimpleNamespace(candidate=release/'candidate.json',candidate_sha256='a'*64,source_sha=self.source,
            validation=stage/('validation-'+self.attempt+'.json'),validation_sha256='c'*64)
        return stage,baseline,receipt,ancestor,args

    def test_activation_freezes_ancestor_api_and_starts_only_new_api_without_seed_or_migration(self):
        stage,baseline,receipt,ancestor,args=self.phase_fixture();events=[]
        def create(role,progress,*unused):
            progress['new_ids'][role]='2'*64 if role=='api' else '3'*64
            progress['stage_names'][role]='synthetic-stage-'+role
            events.append(['create',role]);return progress['new_ids'][role]
        def inspect(identity,**unused):
            return {'Name':'/t24-private-api'} if identity==ancestor['new_ids']['api'] else None
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=(ancestor,self.snapshot,{},None,baseline)),\
             mock.patch.object(repair,'checked_validation'),mock.patch.object(repair,'fixed',return_value={}),\
             mock.patch.object(repair,'preflight',return_value=baseline),mock.patch.object(repair,'ancestor_runtime'),\
             mock.patch.object(repair,'claims_unchanged'),mock.patch.object(repair.switch,'role_configuration',return_value={}),\
             mock.patch.object(repair.switch,'create_role',side_effect=create),mock.patch.object(repair.switch,'inspect',side_effect=inspect),\
             mock.patch.object(repair.switch,'docker',side_effect=lambda command,**unused:events.append(command) or b''),\
             mock.patch.object(repair.switch,'wait_api'),mock.patch.object(repair.switch,'staged_check',return_value={'id':'2'*64}),\
             mock.patch.object(repair.switch,'no_writers'),mock.patch.object(repair.switch,'runtime_guard'),redirect_stdout(io.StringIO()):
            repair.activate(args)
        self.assertEqual(events[0],['stop','--time','30',ancestor['new_ids']['api']])
        self.assertEqual([event for event in events if event[0]=='start'],[['start','2'*64]])
        self.assertEqual([event for event in events if event[0]=='create'],[['create','api'],['create','worker']])
        value=json.loads((stage/'api-state.json').read_bytes())
        self.assertEqual(value['phase'],'PRIVATE_SEEDED_REPAIR_API_READY');self.assertFalse(value['worker_started'])
        self.assertFalse(value['initializer_rerun']);self.assertFalse(value['credential_seed_attempted'])
        self.assertFalse(value['deployed']);self.assertEqual(repair.guard.release_snapshot(self.private,self.business),self.snapshot)

    def test_rollback_restores_only_ancestor_api_and_keeps_stripe_credential_and_ten_table_inode(self):
        stage,baseline,receipt,ancestor,args=self.phase_fixture()
        args.state=stage/'api-state.json';args.state_sha256='d'*64
        state={'attempt':self.attempt,'api_started':True,'new_ids':{'api':'2'*64,'worker':'3'*64},'stage_names':{}}
        info={ancestor['new_ids']['api']:{'Name':'/retained-ancestor','State':{'Running':False}},
            '2'*64:{'Name':'/t24-private-api','State':{'Running':True}},
            '3'*64:{'Name':'/synthetic-new-worker','State':{'Running':False}},
            repair.live.PRIVATE_IDS['worker']:{'Name':'/t24-private-worker','State':{'Running':False}}}
        events=[]
        def inspect(identity,**unused):return info.get(identity)
        def docker(command,**unused):
            events.append(command)
            if command[0] in {'stop','start'}:info[command[-1]]['State']['Running']=command[0]=='start'
            elif command[0]=='rename':info[command[1]]['Name']='/'+command[2]
            return b''
        before=(self.private.stat().st_ino,self.private.read_bytes(),self.business.read_bytes())
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=(ancestor,self.snapshot,{},None,baseline)),\
             mock.patch.object(repair,'checked_repair_state',return_value=state),mock.patch.object(repair,'claims_unchanged'),\
             mock.patch.object(repair,'ancestor_runtime'),mock.patch.object(repair.switch,'runtime_guard'),\
             mock.patch.object(repair.switch,'role_configuration',return_value={}),mock.patch.object(repair.switch,'staged_check',return_value={}),\
             mock.patch.object(repair.switch,'inspect',side_effect=inspect),mock.patch.object(repair.switch,'docker',side_effect=docker),\
             mock.patch.object(repair.switch,'wait_api'),mock.patch.object(repair.switch,'no_writers'),redirect_stdout(io.StringIO()):
            repair.rollback(args)
        self.assertEqual([event for event in events if event[0]=='start'],[['start',ancestor['new_ids']['api']]])
        self.assertFalse(info[repair.live.PRIVATE_IDS['worker']]['State']['Running'])
        self.assertEqual((self.private.stat().st_ino,self.private.read_bytes(),self.business.read_bytes()),before)
        self.assertEqual(repair.stripe_fingerprint(1),self.stripe)
        accepted=json.loads((stage/('rollback-'+self.attempt+'.json')).read_bytes())
        self.assertFalse(accepted['databases_restored']);self.assertTrue(accepted['stripe_credentials_preserved'])
        self.assertTrue(all(event[0] not in {'rm','restore','cp','init','seed'} for event in events))

    def test_sync_failure_keeps_worker_off_and_records_exclusive_attempt_without_automatic_retry(self):
        stage,baseline,receipt,ancestor,args=self.phase_fixture();args.state=stage/'api-state.json';args.state_sha256='d'*64
        state={'phase':'PRIVATE_SEEDED_REPAIR_API_READY','api_started':True,'worker_started':False,'attempt':self.attempt,
            'new_ids':{'api':'2'*64,'worker':'3'*64},'new_private':{'api':{'proof':'api'}}}
        helper=self.helper_fixture(sync=True)
        report={'stage':'PRIVATE_SEEDED_NORMAL_SYNC_REJECTED','success':False,'seed_attempted':False,'connected':False}
        events=[]
        def diagnose(command,**unused):
            if command[0]=='create':return self.identity.encode()
            if command[0]=='start':return json.dumps(report).encode()
            events.append(command);return b''
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=(ancestor,self.snapshot,{},None,baseline)),\
             mock.patch.object(repair,'checked_repair_state',return_value=state),mock.patch.object(repair,'claims_unchanged'),\
             mock.patch.object(repair.switch,'runtime_guard'),mock.patch.object(repair.switch,'role_configuration',return_value={}),\
             mock.patch.object(repair.switch,'staged_check',return_value={'proof':'api'}),mock.patch.object(repair.switch,'no_writers'),\
             mock.patch.object(repair.switch,'docker',side_effect=lambda command,**unused:events.append(command) or b''),\
             mock.patch.object(repair.diagnosis,'docker',side_effect=diagnose),mock.patch.object(repair.diagnosis,'inspect',return_value=helper),\
             mock.patch.object(repair,'sync_helper',return_value=helper):
            with self.assertRaisesRegex(repair.RepairError,'NORMAL_SYNC_FAILED_REQUIRES_EXPLICIT_REVIEW'):repair.normal_sync(args)
            with self.assertRaises(FileExistsError):repair.normal_sync(args)
        self.assertTrue((stage/'sync-progress.json').exists());self.assertFalse((stage/'sync-state.json').exists())
        self.assertEqual([event for event in events if event[0]=='start'],[])
        self.assertEqual([event for event in events if event[0]=='stop'],[['stop','--time','30','2'*64]])

    def test_normal_sync_adds_one_real_success_audit_preserves_old_failure_and_updates_api_start_proof(self):
        from datetime import datetime,timezone
        stage,baseline,receipt,ancestor,args=self.phase_fixture();args.state=stage/'api-state.json';args.state_sha256='d'*64
        state={'phase':'PRIVATE_SEEDED_REPAIR_API_READY','api_started':True,'worker_started':False,'attempt':self.attempt,
            'new_ids':{'api':'2'*64,'worker':'3'*64},'new_private':{'api':{'proof':'api'}}}
        helper=self.helper_fixture(sync=True);events=[];newproof={'proof':'new-api-start'}
        def diagnose(command,**unused):
            if command[0]=='create':return self.identity.encode()
            if command[0]=='start':
                now=datetime.now(timezone.utc).isoformat()
                with sqlite3.connect(self.private) as db:
                    db.execute("UPDATE private_connections SET error=NULL,last_sync=? WHERE source_id='stripe'",(now,))
                    db.execute("INSERT INTO private_sync_runs(id,owner_id,source_id,status,started_at,completed_at,created_count,updated_count) VALUES('new-normal-run','4','stripe','succeeded',?,?,0,0)",(now,now))
                return json.dumps({'stage':'PRIVATE_SEEDED_NORMAL_SYNC_SUCCEEDED','success':True,
                    'counts':{'created':0,'updated':0},'seed_attempted':False,'connected':False}).encode()
            events.append(command);return b''
        original_audits=repair.sync_audits();business=self.business.read_bytes();inode=self.private.stat().st_ino
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=(ancestor,self.snapshot,{},None,baseline)),\
             mock.patch.object(repair,'checked_repair_state',return_value=state),mock.patch.object(repair,'claims_unchanged'),\
             mock.patch.object(repair.switch,'runtime_guard'),mock.patch.object(repair.switch,'role_configuration',return_value={}),\
             mock.patch.object(repair.switch,'staged_check',side_effect=[{'proof':'api'},{}, {},newproof]),\
             mock.patch.object(repair.switch,'no_writers'),mock.patch.object(repair.switch,'wait_api'),\
             mock.patch.object(repair.switch,'docker',side_effect=lambda command,**unused:events.append(command) or b''),\
             mock.patch.object(repair.diagnosis,'docker',side_effect=diagnose),mock.patch.object(repair.diagnosis,'inspect',return_value=helper),\
             mock.patch.object(repair,'sync_helper',return_value=helper),redirect_stdout(io.StringIO()):
            repair.normal_sync(args)
        accepted=json.loads((stage/'sync-state.json').read_bytes())
        self.assertTrue(accepted['normal_sync_verified']);self.assertFalse(accepted['worker_started'])
        self.assertEqual(accepted['new_private']['api'],newproof)
        self.assertEqual([event for event in events if event[0]=='start'],[['start','2'*64]])
        current_audits=repair.sync_audits()
        self.assertTrue(all(current_audits.get(k)==v for k,v in original_audits.items()));self.assertEqual(len(current_audits),2)
        self.assertEqual(self.private.stat().st_ino,inode);self.assertEqual(self.business.read_bytes(),business)
        self.assertEqual(repair.stripe_fingerprint(1),self.stripe)

    def test_finish_starts_only_new_worker_after_actual_sync_and_pins_final_credential_lineage(self):
        stage,baseline,receipt,ancestor,args=self.phase_fixture();args.state=stage/'sync-state.json';args.state_sha256='d'*64
        with sqlite3.connect(self.private) as db:db.execute("UPDATE private_sync_runs SET status='succeeded' WHERE source_id='stripe'")
        profiles={role:{} for role in ('api','worker')}
        for role in profiles:(stage/(role+'-runtime.env')).write_bytes(repair.switch.profile_bytes(profiles[role]))
        state={'phase':'PRIVATE_SEEDED_REPAIR_API_READY','api_started':True,'worker_started':False,'attempt':self.attempt,
            'new_ids':{'api':'2'*64,'worker':'3'*64},'new_private':{'api':{'proof':'api'}},
            'role_environment_sha256':{role:repair.switch.sha(repair.switch.profile_bytes(profiles[role])) for role in profiles},
            'stable_before':baseline['stable_records']}
        events=[]
        def staged(identity,role,*unused,**kw):return {'proof':role}
        with mock.patch.object(repair,'checked_candidate',return_value=receipt),\
             mock.patch.object(repair,'checked_lineage',return_value=(ancestor,self.snapshot,{'crm':{}},None,baseline)),\
             mock.patch.object(repair,'checked_repair_state',return_value=state),mock.patch.object(repair,'claims_unchanged'),\
             mock.patch.object(repair.switch,'runtime_guard'),mock.patch.object(repair.switch,'role_configuration',return_value={}),\
             mock.patch.object(repair.switch,'staged_check',side_effect=staged),mock.patch.object(repair.switch,'wait_api'),\
             mock.patch.object(repair.switch,'old_check',return_value={'Name':'/t24-private-worker'}),\
             mock.patch.object(repair.switch,'inspect',return_value=None),mock.patch.object(repair.switch,'no_writers'),\
             mock.patch.object(repair.switch,'docker',side_effect=lambda command,**unused:events.append(command) or b''),\
             mock.patch.object(repair.time,'sleep'),redirect_stdout(io.StringIO()):
            repair.finish(args)
        value=json.loads((stage/'switch-state.json').read_bytes())
        self.assertEqual([event for event in events if event[0]=='start'],[['start','3'*64]])
        self.assertEqual(value['phase'],'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED');self.assertTrue(value['deployed'])
        self.assertFalse(value['public_assets_published']);self.assertTrue(value['original_claims_preserved'])
        self.assertEqual(value['stripe_authorization'] if 'stripe_authorization' in value else self.stripe,self.stripe)


if __name__=='__main__':unittest.main()
