"""Focused local-only acceptance SQL and output checks."""
import ast
from contextlib import redirect_stdout
import importlib.util
import io,json,sqlite3,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
spec=importlib.util.spec_from_file_location('post_audit',Path(__file__).with_name('readonly_preflight.py'))
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
class AuditTest(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.path=Path(t.name).resolve()/'workspace.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE private_connections(id TEXT,owner_id TEXT,source_id TEXT,status TEXT,generation INTEGER,metadata_json TEXT,encrypted_credentials TEXT,last_sync TEXT,error TEXT);
            CREATE TABLE private_items(id TEXT,owner_id TEXT,source_id TEXT,kind TEXT,external_id TEXT,evidence TEXT, local_title TEXT,local_summary TEXT,action_status TEXT,snoozed_until TEXT,created_at TEXT);
            CREATE TABLE private_preferences(owner_id TEXT,preferences_json TEXT);
            CREATE TABLE private_sync_runs(id TEXT,owner_id TEXT,source_id TEXT,status TEXT,created_count INTEGER,updated_count INTEGER,error TEXT,started_at TEXT);''')
            for source,metadata in [('gmail',{'account_label':'owner@example.test','scope':'https://www.googleapis.com/auth/gmail.readonly','connection_mode':'oauth'}),('google_ads',{'account_label':'synthetic-advertiser','scope':'https://www.googleapis.com/auth/adwords','connection_mode':'oauth','ads_customer_id':audit.TARGET_CUSTOMER,'read_only_adapter':True})]:
                db.execute('INSERT INTO private_connections VALUES(?,?,?,?,?,?,?,?,?)',(source+'-id','4',source,'connected',2,json.dumps(metadata),'SYNTHETIC-CIPHER-NEVER-SELECTED','2026-10-11',None))
            for i in range(68):db.execute('INSERT INTO private_items VALUES(?,?,?,?,?,?,?,?,?,?,?)',(str(i),'4','google_ads','campaign',audit.TARGET_CUSTOMER+':'+str(i)+':last_30_days',json.dumps({'customer_id':audit.TARGET_CUSTOMER,'period':'LAST_30_DAYS','accounting_effect':'none'}),None,None,'open',None,'2026-10-11'))
            db.execute('INSERT INTO private_sync_runs VALUES(?,?,?,?,?,?,?,?)',('sync','4','google_ads','succeeded',68,0,None,'2026-10-11'))
            schema=list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))
        self.baseline={'private_database':{'schema_sha256':audit.digest(schema),'connections':[{'id':'gmail-id','owner_id':'4','source_id':'gmail','generation':2,'account_identity_sha256':audit.digest('owner@example.test'),'scope_sha256':audit.digest('https://www.googleapis.com/auth/gmail.readonly')}]}}
    def check(self):
        with mock.patch.object(audit,'secure',return_value=SimpleNamespace(st_dev=64515,st_ino=282885)),mock.patch.object(audit.os.path,'samefile',return_value=False):return audit.private_snapshot(self.baseline,self.path)
    def test_real_sql_accepts_owner_target_scope_and_68_and_changes_nothing(self):
        before=self.path.read_bytes();result=self.check();self.assertEqual(result['ads_items_count'],68);self.assertEqual(before,self.path.read_bytes())
        text=json.dumps(result);self.assertNotIn('owner@example.test',text);self.assertNotIn('SYNTHETIC-CIPHER',text);self.assertNotIn('synthetic-advertiser',text)
    def test_ads_wrong_owner_scope_target_credentials_or_accounting_effect_rejected(self):
        for mutation in ["UPDATE private_connections SET owner_id='5' WHERE source_id='google_ads'","UPDATE private_connections SET metadata_json=json_set(metadata_json,'$.ads_customer_id','wrong') WHERE source_id='google_ads'","UPDATE private_connections SET metadata_json=json_set(metadata_json,'$.scope','wrong') WHERE source_id='google_ads'","UPDATE private_connections SET encrypted_credentials=NULL WHERE source_id='google_ads'","UPDATE private_items SET evidence=json_set(evidence,'$.accounting_effect','crm') WHERE id='1'"]:
            with self.subTest(mutation=mutation),sqlite3.connect(self.path) as db:
                db.execute('BEGIN');db.execute(mutation);db.commit()
                with self.assertRaises(audit.SwitchError):self.check()
                # Recreate each independent synthetic fixture.
            self.setUp()
    def test_gmail_identity_or_generation_change_rejected(self):
        with sqlite3.connect(self.path) as db:db.execute("UPDATE private_connections SET generation=3 WHERE source_id='gmail'")
        with self.assertRaisesRegex(audit.SwitchError,'GMAIL_CONNECTION_IDENTITY_DRIFT'):self.check()
    def test_fewer_records_or_failed_sync_rejected(self):
        with sqlite3.connect(self.path) as db:db.execute("UPDATE private_items SET owner_id='5' WHERE id='1'")
        with self.assertRaisesRegex(audit.SwitchError,'ADS_ITEM_SCOPE_DRIFT'):self.check()
    def test_audit_command_and_sql_surface_are_readonly_and_credentials_not_selected(self):
        source=Path(audit.__file__).read_text();tree=ast.parse(source)
        commands=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess']
        self.assertEqual(len(commands),1);self.assertEqual(ast.literal_eval(commands[0].args[0].elts[0]),'docker');self.assertEqual(ast.literal_eval(commands[0].args[0].elts[1]),'inspect')
        queries=[ast.literal_eval(n.args[0]) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='execute' and n.args and isinstance(n.args[0],ast.Constant)]
        self.assertTrue(all(q.lstrip().upper().startswith(('SELECT ','PRAGMA ','BEGIN')) for q in queries));self.assertIn('mode=ro',source);self.assertIn('PRAGMA query_only=ON',source)
        self.assertNotIn('metadata_json,encrypted_credentials FROM',source);self.assertNotIn('SELECT encrypted_credentials',source)
if __name__=='__main__':unittest.main()
