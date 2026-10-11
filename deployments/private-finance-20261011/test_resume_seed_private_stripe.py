"""Exclusive recovery claims and actual normal encrypt/first-sync path, offline."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app/backend'))
import resume_seed_private_stripe as resumed
import test_seed_private_stripe as existing_seed_tests


class ResumeSeedTests(unittest.TestCase):
    def setUp(self):
        existing_seed_tests.ActualHelperTests.setUp(self)
        self.release=self.root/'candidate';self.release.mkdir(mode=0o700)
        self.completed=self.release/'completed-release';self.completed.mkdir(mode=0o700)
        self.claims=self.root/'stripe-seed-claims';self.claims.mkdir(mode=0o700)
        self.bootstrap='a'*64;self.candidate_sha='b'*64;self.schema_hash='c'*64
        self.original={'stage':'STRIPE_SEED_ONE_USE_CLAIMED','bootstrap_sha256':self.bootstrap,
            'candidate_sha256':'d'*64,'source_sha':'e'*40,'attempt':'f'*32}
        original_path=self.claims/(self.bootstrap+'.json')
        original_path.write_bytes(resumed.transfer.encoded(self.original));original_path.chmod(0o600)
        self.original_hash=resumed.sha(original_path.read_bytes())
        self.state={'candidate_image':'sha256:'+'1'*64,'schema_after_sha256':'2'*64,
            'frozen_seed_before_sha256':'3'*64,'accepted_schema_state_sha256':self.schema_hash,
            'resume_lineage':{'original_claim_sha256':self.original_hash,'bootstrap_sha256':self.bootstrap,
                'original_candidate_sha256':self.original['candidate_sha256'],'original_source_sha':self.original['source_sha']}}
        diagnosis_path=self.completed/('stripe-diagnosis-'+'4'*32+'.json')
        self.args=SimpleNamespace(source_sha='5'*40,candidate_sha256=self.candidate_sha,candidate=self.release/'candidate.json',
            bootstrap_sha256=self.bootstrap,schema_state_sha256=self.schema_hash,
            readonly_diagnosis=diagnosis_path,readonly_diagnosis_sha256='6'*64)
        for name,value in (('CONFIG',self.root),):
            patch=mock.patch.object(resumed.transfer,name,value);patch.start();self.addCleanup(patch.stop)
        patch=mock.patch.object(resumed.transfer,'protected_directory',side_effect=lambda p:None);patch.start();self.addCleanup(patch.stop)
        patch=mock.patch.object(resumed.transfer,'read_protected',side_effect=lambda p,*unused:p.read_bytes());patch.start();self.addCleanup(patch.stop)

    def diagnosis_value(self):
        return {'format_version':1,'stage':'PRIVATE_STRIPE_READONLY_DIAGNOSIS_COMPLETE','last_stage':'complete',
            'probes':list(resumed.diagnosis.PROBES),'source_sha':self.args.source_sha,'candidate_sha256':self.candidate_sha,
            'image_id':self.state['candidate_image'],'schema_state_sha256':self.schema_hash,
            'schema_after_sha256':self.state['schema_after_sha256'],'bootstrap_sha256':self.bootstrap,
            'failed_claim_sha256':self.original_hash,'failed_seed_attempt':self.original['attempt'],
            'resume_lineage_sha256':resumed.guard.digest(self.state['resume_lineage']),
            'before_snapshot_sha256':self.state['frozen_seed_before_sha256'],
            'after_snapshot_sha256':self.state['frozen_seed_before_sha256'],
            **{key:True for key in ('success','stripe_connection_absent','exact_accepted_schema_after')},
            **{key:False for key in ('database_writes','connected','credential_seed_attempted','one_use_claim_changed',
                'production_services_changed','deployed')}}

    def test_original_claim_is_retained_and_exactly_one_reviewed_retry_can_be_claimed(self):
        old,_=resumed.claim_paths(self.bootstrap);before=old.read_bytes()
        retry,hash_value=resumed.claim_retry(self.args,self.state,self.original,'7'*32)
        self.assertEqual(old.read_bytes(),before);retry_before=retry.read_bytes()
        self.assertEqual(resumed.sha(retry_before),hash_value)
        self.assertEqual(json.loads(retry_before)['original_claim_sha256'],self.original_hash)
        with self.assertRaisesRegex(resumed.ResumeSeedError,'ALREADY_CLAIMED_NO_AUTOMATIC_RETRY'):
            resumed.claim_retry(self.args,self.state,self.original,'8'*32)
        self.assertEqual(old.read_bytes(),before);self.assertEqual(retry.read_bytes(),retry_before)

    def test_original_claim_cannot_be_relabelled_as_new_candidate_or_other_account_bootstrap(self):
        resumed.checked_original_claim(self.original,self.state,self.bootstrap)
        for changes in ({'source_sha':self.args.source_sha},{'candidate_sha256':self.candidate_sha},
                        {'bootstrap_sha256':'8'*64},{'stage':'success'}):
            with self.subTest(changes=changes),self.assertRaises(resumed.ResumeSeedError):
                resumed.checked_original_claim({**self.original,**changes},self.state,self.bootstrap)

    def test_retry_requires_actual_complete_readonly_diagnosis_on_same_frozen_candidate(self):
        value=self.diagnosis_value();resumed.checked_diagnosis(value,self.args,self.state)
        for changes in ({'success':False},{'probes':list(resumed.diagnosis.PROBES)[:-1]},
                        {'candidate_sha256':'8'*64},{'schema_state_sha256':'8'*64},
                        {'after_snapshot_sha256':'8'*64},{'credential_seed_attempted':True}):
            with self.subTest(changes=changes),self.assertRaises(resumed.ResumeSeedError):
                resumed.checked_diagnosis({**value,**changes},self.args,self.state)

    def test_persisted_retry_seed_receipt_is_bound_to_immutable_original_claim_and_diagnosis(self):
        self.args.readonly_diagnosis.write_bytes(resumed.transfer.encoded(self.diagnosis_value()))
        self.args.readonly_diagnosis.chmod(0o600)
        self.args.readonly_diagnosis_sha256=resumed.sha(self.args.readonly_diagnosis.read_bytes())
        retry,retry_hash=resumed.claim_retry(self.args,self.state,self.original,'7'*32)
        value={'resume_lineage_sha256':resumed.guard.digest(self.state['resume_lineage']),
            'schema_state_sha256':self.schema_hash,'original_claim_sha256':self.original_hash,
            'retry_claim':str(retry),'retry_claim_sha256':retry_hash,
            'readonly_diagnosis':str(self.args.readonly_diagnosis),
            'readonly_diagnosis_sha256':self.args.readonly_diagnosis_sha256}
        resumed.checked_seed_lineage(value,self.args,self.state)
        for changes in ({'schema_state_sha256':'8'*64},{'original_claim_sha256':'8'*64},
                        {'retry_claim':str(self.claims/'unreviewed.json')},{'readonly_diagnosis_sha256':'8'*64}):
            with self.subTest(changes=changes),self.assertRaises((resumed.ResumeSeedError,resumed.seed.SeedError)):
                resumed.checked_seed_lineage({**value,**changes},self.args,self.state)

    def test_actual_normal_helper_accepts_official_refund_encrypts_then_syncs_from_encrypted_credential(self):
        import httpx
        from services import private_workspace as core,private_workspace_providers as provider
        calls=[];business_before=self.business.read_bytes();asyncio.run(core.close_private_workspace_storage())
        refund={'object':'refund','id':'re_FICTIONOFFLINE','amount':2500,'currency':'usd',
            'charge':'ch_FICTIONOFFLINE','status':'succeeded','created':1791712000}
        async def transport(request):
            calls.append((request.method,request.url.path))
            if request.url.path=='/v1/account':return httpx.Response(200,json={'object':'account','id':resumed.transfer.ACCOUNT})
            if request.url.path=='/v1/balance':return httpx.Response(200,json={'object':'balance','livemode':True,'available':[],'pending':[]})
            return httpx.Response(200,json={'object':'list','has_more':False,'data':[refund] if request.url.path=='/v1/refunds' else []})
        original_begin=provider.begin_connect;original_fetch=provider.fetch_source
        async def begin(source,state):return await original_begin(source,state,transport=httpx.MockTransport(transport))
        async def fetch(source,credentials,metadata):return await original_fetch(source,credentials,metadata,transport=httpx.MockTransport(transport))
        code=resumed.seed.helper_code().replace('/private-data/workspace.db',str(self.private))
        output=io.StringIO()
        with (mock.patch.dict(os.environ,{},clear=True),mock.patch.object(sys,'stdin',io.StringIO(json.dumps(self.packet))),
              mock.patch.object(provider,'begin_connect',side_effect=begin),redirect_stdout(output)):
            with self.assertRaises(SystemExit) as exit_result:exec(compile(code,'<offline-reviewed-retry>','exec'),{})
        self.assertEqual(exit_result.exception.code,0);self.assertNotIn(self.packet['credentials']['api_key'],output.getvalue())
        saved=resumed.seed.connection_state(self.private)['row']
        self.assertEqual(saved['status'],'connected');self.assertNotIn(self.packet['credentials']['api_key'],saved['encrypted_credentials'])
        async def sync():
            sessions=await core.private_session_factory()
            async with sessions() as db:return await core.sync_source(db,'4','stripe',owner_validator=lambda:async_true())
        async def async_true():return True
        with mock.patch.dict(os.environ,self.config,clear=True),mock.patch.object(provider,'fetch_source',side_effect=fetch):
            result=asyncio.run(sync());asyncio.run(core.close_private_workspace_storage())
            self.assertNotIn('PRIVATE_WORKSPACE_STRIPE_KEY',os.environ)
        self.assertEqual(result['source']['status'],'connected');self.assertEqual(result['counts']['created'],1)
        self.assertEqual(calls,[('GET','/v1/'+name) for name in resumed.diagnosis.PROBES]*2)
        self.assertEqual(self.business.read_bytes(),business_before)
        final=resumed.seed.connection_state(self.private)['row'];self.assertTrue(final['last_sync'])
        self.assertEqual(json.loads(final['metadata_json'])['coverage'],'bounded_recent_records')
        with sqlite3.connect(self.private) as db:
            self.assertEqual(db.execute("SELECT status FROM private_sync_runs WHERE source_id='stripe'").fetchall(),[('succeeded',)])

    def test_retry_cli_rejects_unreviewed_input_without_echoing_values(self):
        output=io.StringIO()
        with redirect_stdout(output),mock.patch.object(resumed.seed,'docker') as docker:
            self.assertEqual(resumed.cli(['--secret','fiction-not-to-echo']),1)
        self.assertNotIn('fiction-not-to-echo',output.getvalue());docker.assert_not_called()


if __name__=='__main__':unittest.main()
