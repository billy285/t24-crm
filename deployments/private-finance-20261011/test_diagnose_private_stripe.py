"""Actual provider/core readonly diagnosis with synthetic DB and MockTransport."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app/backend'))
import diagnose_private_stripe as diagnostic


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.root.chmod(0o700)
        self.private=self.root/'workspace.db';self.business=self.root/'business.db'
        with sqlite3.connect(self.business) as db:
            db.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY,role TEXT,status TEXT)')
            db.execute("INSERT INTO employees VALUES(4,'super_admin','active')")
            db.execute('CREATE TABLE finance_sentinel(id INTEGER,amount INTEGER)');db.execute('INSERT INTO finance_sentinel VALUES(1,70000)')
        from sqlalchemy import create_engine
        from models.private_workspace import PrivateWorkspaceBase
        engine=create_engine('sqlite:///'+str(self.private));PrivateWorkspaceBase.metadata.create_all(engine);engine.dispose()
        self.private.chmod(0o600)
        key='_'.join(('rk','live','FICTIONREADONLYDIAG123456789'))
        self.packet={'configuration':{'PRIVATE_WORKSPACE_OWNER_IDS':'4','PRIVATE_WORKSPACE_STRIPE_MODE':'live',
            'PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID':diagnostic.transfer.ACCOUNT,
            'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:///'+str(self.private),
            'DATABASE_URL':'sqlite:///'+str(self.business),'DATABASE_SCHEMA_MODE':'verify_only',
            'PRIVATE_WORKSPACE_ENCRYPTION_KEY':'synthetic-diagnosis-encryption-no-real-secrets',
            'JWT_SECRET_KEY':'synthetic-diagnosis-owner-jwt-no-real-secrets'},
            'credentials':{'api_key':key,'stripe_account_id':diagnostic.transfer.ACCOUNT,'mode':'live'}}

    def run_helper(self,*,deny=None,invalid_charge=False,malicious_error=False):
        import httpx
        from services import private_workspace_providers as provider
        original=provider.begin_connect;calls=[]
        async def handler(request):
            calls.append((request.method,request.url.path))
            if malicious_error:raise ValueError('SECRET SHOULD NEVER LEAVE THE HELPER '+self.packet['credentials']['api_key'])
            if request.url.path==deny:return httpx.Response(403,json={'error':'fiction-denied'})
            if request.url.path=='/v1/account':return httpx.Response(200,json={'object':'account','id':diagnostic.transfer.ACCOUNT})
            if request.url.path=='/v1/balance':return httpx.Response(200,json={'object':'balance','livemode':True,'available':[],'pending':[]})
            if invalid_charge and request.url.path=='/v1/charges':
                return httpx.Response(200,json={'object':'list','has_more':False,'data':[{'id':'ch_FICTION','livemode':True,'amount':None}]})
            return httpx.Response(200,json={'object':'list','has_more':False,'data':[]})
        async def mocked(source,state):return await original(source,state,transport=httpx.MockTransport(handler))
        code=diagnostic.helper_code().replace('file:/private-data/workspace.db?mode=ro','file:'+str(self.private)+'?mode=ro')
        output=io.StringIO();before_private=self.private.read_bytes();before_business=self.business.read_bytes()
        with (mock.patch.dict(os.environ,{},clear=True),mock.patch.object(sys,'stdin',io.StringIO(json.dumps(self.packet))),
              mock.patch.object(provider,'begin_connect',side_effect=mocked),redirect_stdout(output)):
            exec(compile(code,'<synthetic-readonly-diagnosis>','exec'),{})
            self.assertNotIn('PRIVATE_WORKSPACE_STRIPE_KEY',os.environ)
        self.assertEqual(self.private.read_bytes(),before_private);self.assertEqual(self.business.read_bytes(),before_business)
        self.assertNotIn(self.packet['credentials']['api_key'],output.getvalue())
        self.assertNotIn('SECRET SHOULD NEVER',output.getvalue())
        return diagnostic.checked_report(output.getvalue().encode()),calls

    def test_real_provider_six_gets_validate_without_any_private_connection_or_database_write(self):
        report,calls=self.run_helper()
        self.assertTrue(report['success']);self.assertFalse(report['connected']);self.assertFalse(report['database_writes'])
        self.assertEqual(calls,[('GET','/v1/'+name) for name in ('account','balance','charges','refunds','disputes','payouts')])
        with sqlite3.connect(self.private) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM private_connections').fetchone()[0],0)

    def test_endpoint_permission_failure_reports_fixed_stage_and_machine_code(self):
        report,calls=self.run_helper(deny='/v1/disputes')
        self.assertEqual(report['last_stage'],'disputes');self.assertEqual(report['error_code'],'access_denied')
        self.assertEqual(report['error_class'],'ProviderError');self.assertFalse(report['success'])

    def test_invalid_realistic_object_shape_reports_parser_stage_without_object_values(self):
        report,calls=self.run_helper(invalid_charge=True)
        self.assertEqual(report['last_stage'],'charges');self.assertEqual(report['error_code'],'invalid_response')
        self.assertNotIn('ch_FICTION',json.dumps(report));self.assertEqual(len(calls),3)

    def test_owner_denied_before_provider_and_existing_unreadable_ciphertext_before_probe(self):
        with sqlite3.connect(self.business) as db:db.execute("UPDATE employees SET status='inactive'")
        report,calls=self.run_helper();self.assertEqual(report['last_stage'],'owner');self.assertEqual(calls,[])
        with sqlite3.connect(self.business) as db:db.execute("UPDATE employees SET status='active'")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.private_workspace import PrivateConnection
        engine=create_engine('sqlite:///'+str(self.private))
        with Session(engine) as db:
            db.add(PrivateConnection(id='synthetic-gmail',owner_id='4',source_id='gmail',status='connected',encrypted_credentials='fiction-unreadable'))
            db.commit()
        engine.dispose()
        report,calls=self.run_helper();self.assertEqual(report['last_stage'],'existing_credentials')
        self.assertEqual(report['error_code'],'existing_credential_unreadable');self.assertEqual(calls,[])

    def test_arbitrary_exception_details_are_never_emitted(self):
        report,calls=self.run_helper(malicious_error=True)
        self.assertEqual(report['error_class'],'ValueError');self.assertEqual(report['error_code'],'unclassified')
        self.assertFalse(report['success']);self.assertEqual(report['last_stage'],'account')

    def test_both_mounts_are_readonly_and_program_contains_no_factory_or_connect_or_claim_mutation(self):
        command=diagnostic.create_command('t24-private-stripe-diagnosis-'+'a'*32,'sha256:'+'b'*64,'a'*32)
        mount_values=[command[index+1] for index,value in enumerate(command) if value=='--mount']
        self.assertEqual(len(mount_values),2);self.assertTrue(all(value.endswith(',readonly') for value in mount_values))
        self.assertNotIn('--env-file',command);self.assertNotIn('--publish',command)
        self.assertIn('--log-driver',command);self.assertIn('none',command)
        code=diagnostic.helper_code()
        for forbidden in ('private_session_factory','connect_source','claim_bootstrap','commit(','INSERT','UPDATE','DELETE'):
            self.assertNotIn(forbidden,code)

    def test_reports_reject_unexpected_keys_raw_errors_and_non_get_stages(self):
        report,_=self.run_helper()
        for changes in ({'raw_error':'fiction-secret'},{'database_writes':True},{'probes':['POST']},{'success':1}):
            with self.subTest(changes=changes),self.assertRaises(diagnostic.DiagnosisError):
                diagnostic.checked_report(json.dumps({**report,**changes}).encode())

    def test_failed_seed_proof_refuses_token_refresh_or_any_stripe_row(self):
        snapshot={'private':{'data_sha256':'fiction-accepted'},'business':{'tables':{}}}
        diagnostic.checked_failed_outcome(snapshot,deepcopy(snapshot),{'row':None})
        refreshed=deepcopy(snapshot);refreshed['private']['data_sha256']='fiction-token-refreshed'
        for current,row in ((refreshed,None),(snapshot,{}),(snapshot,{'status':'error'})):
            with self.subTest(current=current,row=row),self.assertRaises(diagnostic.DiagnosisError):
                diagnostic.checked_failed_outcome(current,snapshot,{'row':row})

    def test_container_name_image_and_attempt_cannot_be_operator_program_arguments(self):
        valid=('t24-private-stripe-diagnosis-'+'a'*32,'sha256:'+'b'*64,'a'*32)
        for index,bad in ((0,'t24-private-api'),(1,'arbitrary:latest'),(2,'b'*32)):
            values=list(valid);values[index]=bad
            with self.subTest(index=index),self.assertRaises(diagnostic.DiagnosisError):
                diagnostic.create_command(*values)

    def test_resume_diagnosis_binds_original_claim_without_relabelling_old_candidate_source(self):
        args=SimpleNamespace(source_sha='a'*40,candidate_sha256='b'*64,bootstrap_sha256='c'*64,failed_claim_sha256='d'*64)
        claim={'stage':'STRIPE_SEED_ONE_USE_CLAIMED','source_sha':'e'*40,'candidate_sha256':'f'*64,
            'bootstrap_sha256':args.bootstrap_sha256,'attempt':'1'*32}
        state={'resume_lineage':{'original_source_sha':claim['source_sha'],'original_candidate_sha256':claim['candidate_sha256'],
            'original_claim_sha256':args.failed_claim_sha256,'bootstrap_sha256':args.bootstrap_sha256}}
        diagnostic.checked_failed_claim(claim,args,state)
        for changes in ({'source_sha':args.source_sha},{'candidate_sha256':args.candidate_sha256},{'attempt':'invalid'}):
            with self.subTest(changes=changes),self.assertRaises(diagnostic.DiagnosisError):
                diagnostic.checked_failed_claim({**claim,**changes},args,state)


if __name__=='__main__':unittest.main()
