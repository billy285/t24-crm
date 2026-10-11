"""Offline real-SQL, generated-code and output-boundary tests; no live account."""
import ast
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('query_smoke',Path(__file__).with_name('live_query_smoke.py'))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def batch(now=None):
    now=now or datetime.now(timezone.utc)
    today=now.astimezone(smoke.ZoneInfo('America/Los_Angeles')).date()
    snapshot={'id':'ce931e4a-3c40-4a0c-966f-6db5b60cbacb','observed_at':now.isoformat(),
              'account_timezone':'America/Los_Angeles','inventory_count':1,'record_limit':100,
              'inventory_complete':True,'metrics_complete':True}
    periods={key:{'start':(today-smoke.timedelta(days=start)).isoformat(),'end':(today-smoke.timedelta(days=end)).isoformat()}
             for key,start,end in (('yesterday',1,1),('last_7_days',7,1),('previous_7_days',14,8),('last_30_days',30,1))}
    health={'version':1,'snapshot_id':snapshot['id'],'observed_at':snapshot['observed_at'],
            'account_timezone':snapshot['account_timezone'],'local_date':today.isoformat(),'bucket':'healthy',
            'currency':'USD','coverage':{'inventory_complete':True,'metrics_complete':True},'periods':periods,
            'metrics':{key:{'impressions':4,'clicks':1,'cost_micros':1000000,'conversions':0.0} for key in periods}}
    return {'items':[{'external_id':smoke.TARGET+':123:last_30_days','kind':'campaign','title':'PRIVATE-CAMPAIGN-NEVER-OUTPUT',
                      'currency':'usd','evidence':{'customer_id':smoke.TARGET,'campaign_id':'123','accounting_effect':'none',
                                                 'period':'LAST_30_DAYS','ads_snapshot_id':snapshot['id'],'ads_health':health}}],
            'balances':[],'metadata':{'ads_customer_id':smoke.TARGET,'api_version':'v25','record_limit':100,
                                    'aggregated_totals':False,'ads_snapshot':snapshot}}


class LiveQueryTest(unittest.TestCase):
    def test_complete_current_contract_outputs_only_counts(self):
        value=batch();report=smoke.validate_batch(value)
        self.assertEqual(report['campaign_count'],1);self.assertEqual(report['bucket_counts']['healthy'],1)
        text=json.dumps(report);self.assertNotIn('PRIVATE-CAMPAIGN',text);self.assertNotIn('cost_micros',text)
        self.assertEqual(smoke.safe_report(json.dumps(report).encode(),True),report)

    def test_partial_inventory_does_not_hide_proven_platform_problem(self):
        value=batch();value['metadata']['ads_snapshot']['inventory_complete']=False
        value['items'][0]['evidence']['ads_health']['coverage']['inventory_complete']=False
        value['items'][0]['evidence']['ads_health']['bucket']='problem'
        self.assertEqual(smoke.validate_batch(value)['bucket_counts']['problem'],1)

    def test_incomplete_metrics_require_nulls_but_platform_problem_can_remain(self):
        value=batch();value['metadata']['ads_snapshot']['metrics_complete']=False
        health=value['items'][0]['evidence']['ads_health'];health['coverage']['metrics_complete']=False
        health['metrics']={key:None for key in health['metrics']};health['bucket']='problem'
        self.assertEqual(smoke.validate_batch(value)['bucket_counts']['problem'],1)
        health['metrics']['yesterday']={'impressions':0}
        with self.assertRaises(ValueError):smoke.validate_batch(value)

    def test_account_snapshot_date_money_and_old_snapshot_rejected(self):
        now=datetime(2026,10,11,7,30,tzinfo=timezone.utc)
        mutations=[lambda x:x['metadata'].update(ads_customer_id='bad'),
                   lambda x:x['items'][0]['evidence'].update(ads_snapshot_id='bad'),
                   lambda x:x['items'][0]['evidence']['ads_health']['periods']['yesterday'].update(end='2026-10-11'),
                   lambda x:x['items'][0].update(amount_minor=0),
                   lambda x:x['items'][0]['evidence'].update(accounting_effect='income'),
                   lambda x:x['items'][0]['evidence']['ads_health']['metrics']['yesterday'].update(cost_micros=float('nan'))]
        for mutate in mutations:
            value=batch(now);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):smoke.validate_batch(value,now)
        with self.assertRaises(ValueError):smoke.validate_batch(batch(now-smoke.timedelta(minutes=6)),now)

    def test_duplicate_campaign_and_unknown_health_bucket_rejected(self):
        value=batch();value['items'].append(copy.deepcopy(value['items'][0]));value['metadata']['ads_snapshot']['inventory_count']=2
        with self.assertRaises(ValueError):smoke.validate_batch(value)
        value=batch();value['items'][0]['evidence']['ads_health']['bucket']='effect_is_profitable'
        with self.assertRaises(ValueError):smoke.validate_batch(value)

    def test_raw_failure_and_unapproved_extra_success_field_cannot_escape(self):
        for value in [{'stage':'ADS_HEALTH_LIVE_QUERY_FAILED','provider_error_code':'ya29.SECRET'},
                      {'stage':'ADS_HEALTH_LIVE_QUERY_FAILED','provider_error_code':'access_denied','body':'SECRET'}]:
            with self.assertRaises(ValueError):smoke.safe_report(json.dumps(value).encode(),False)
        value=smoke.validate_batch(batch());value['credentials']='SECRET'
        with self.assertRaises(ValueError):smoke.safe_report(json.dumps(value).encode(),True)
        self.assertEqual(smoke.safe_report(b'{"stage":"ADS_HEALTH_LIVE_QUERY_FAILED","provider_error_code":"upstream_timeout"}',False)['provider_error_code'],'upstream_timeout')

    def generated_query(self,failure=False):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'workspace.db'
            metadata={'ads_customer_id':smoke.TARGET,'scope':'https://www.googleapis.com/auth/adwords',
                      'connection_mode':'oauth','read_only_adapter':True}
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE private_connections(owner_id TEXT,source_id TEXT,status TEXT,metadata_json TEXT,encrypted_credentials TEXT)')
                db.execute('INSERT INTO private_connections VALUES(?,?,?,?,?)',('4','google_ads','connected',json.dumps(metadata),'SYNTHETIC-CIPHER'))
            before=path.read_bytes();queries=[];original=sqlite3.connect;calls=[]
            def connect(database,**kwargs):
                self.assertEqual(database,'file:/private-data/workspace.db?mode=ro');self.assertTrue(kwargs['uri'])
                db=original(path.as_uri()+'?mode=ro',uri=True);db.set_trace_callback(queries.append);return db
            provider=ModuleType('services.private_workspace_providers');provider.ADS_VERSION='v25'
            async def fetch(source,credentials,actualmetadata):
                calls.append(source);self.assertEqual(credentials,{'refresh_token':'SYNTHETIC-SECRET'})
                self.assertEqual(actualmetadata,metadata)
                print('UNEXPECTED-PRIVATE-LOG-MUST-BE-DISCARDED')
                if failure:
                    error=RuntimeError('SECRET-PROVIDER-BODY');error.code='access_denied';raise error
                value=batch();value['credentials']={'access_token':'SYNTHETIC-ROTATED-SECRET'};return value
            provider.fetch_source=fetch;services=ModuleType('services');services.private_workspace_providers=provider
            cipher=SimpleNamespace(decrypt=lambda x:b'{"refresh_token":"SYNTHETIC-SECRET"}')
            output=io.StringIO();environment={'PRIVATE_WORKSPACE_OWNER_IDS':'4','PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID':smoke.TARGET,
                                             'PRIVATE_WORKSPACE_ENCRYPTION_KEY':'SYNTHETIC-NOT-A-REAL-KEY-1234567890'}
            with mock.patch.dict('sys.modules',{'services':services,'services.private_workspace_providers':provider}),\
                 mock.patch.dict(smoke.os.environ,environment,clear=True),mock.patch('sqlite3.connect',side_effect=connect),\
                 mock.patch('cryptography.fernet.Fernet',return_value=cipher),redirect_stdout(output):
                with self.assertRaises(SystemExit) as exited:exec(compile(smoke.query_code(),'<reviewed-query>','exec'),{})
            self.assertEqual(exited.exception.code,1 if failure else 0)
            self.assertEqual(calls,['google_ads']);self.assertEqual(before,path.read_bytes())
            self.assertTrue(all(q.lstrip().upper().startswith(('PRAGMA ','BEGIN','SELECT ','COMMIT')) for q in queries))
            self.assertNotIn('SECRET',output.getvalue());self.assertNotIn('UNEXPECTED-PRIVATE-LOG',output.getvalue())
            return smoke.safe_report(output.getvalue().encode(),not failure)

    def test_exact_generated_production_query_real_sql_no_persistence_and_refresh_discard(self):
        self.assertFalse(self.generated_query()['refreshed_credentials_saved'])

    def test_exact_generated_failure_discards_raw_provider_body(self):
        self.assertEqual(self.generated_query(True)['provider_error_code'],'access_denied')

    def test_container_command_has_only_readonly_database_binds_and_no_service_commands(self):
        command=smoke.create_command('synthetic-query','attempt','sha256:'+'a'*64)
        self.assertEqual(command[:2],['docker','create']);self.assertIn('--read-only',command)
        mounts=[command[i+1] for i,x in enumerate(command) if x=='--mount']
        self.assertEqual(len(mounts),2);self.assertTrue(all(x.endswith(',readonly') for x in mounts))
        self.assertNotIn('--publish',command);self.assertNotIn('--privileged',command)
        self.assertEqual(command[command.index('--log-driver')+1],'none')
        source=Path(smoke.__file__).read_text();tree=ast.parse(source)
        self.assertNotIn('sync_source',source);self.assertNotIn('services.private_workspace_worker',source)
        self.assertNotIn('services.private_workspace_app',source)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='main']
        self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
