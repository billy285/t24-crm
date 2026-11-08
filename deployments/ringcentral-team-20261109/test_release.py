import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('r',Path(__file__).with_name('release.py'));r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class ReleaseTests(unittest.TestCase):
 def test_schema_json_roundtrip_and_unrelated_schema(self):
  with tempfile.TemporaryDirectory() as raw:
   path=Path(raw)/'db.sqlite';c=sqlite3.connect(path);c.executescript('CREATE TABLE employees(id INTEGER PRIMARY KEY,name TEXT);CREATE TABLE ringcentral_call_records(id INTEGER PRIMARY KEY,ringcentral_account_id TEXT,ringcentral_extension_id TEXT,ringcentral_call_id TEXT);CREATE TABLE ringcentral_connections(id INTEGER PRIMARY KEY,ringcentral_account_id TEXT,ringcentral_extension_id TEXT);');c.close()
   before=r.schema(path);self.assertEqual(before,json.loads(json.dumps(before)))
   c=sqlite3.connect(path);c.executescript('CREATE UNIQUE INDEX uq_ringcentral_connection_provider_identity ON ringcentral_connections(ringcentral_account_id,ringcentral_extension_id);CREATE UNIQUE INDEX uq_ringcentral_call_provider_identity ON ringcentral_call_records(ringcentral_account_id,ringcentral_extension_id,ringcentral_call_id);CREATE INDEX ix_ringcentral_call_records_ringcentral_call_id ON ringcentral_call_records(ringcentral_call_id);');c.close();after=r.schema(path)
   r.validate_schema(before,after)
   c=sqlite3.connect(path);c.execute('CREATE INDEX accidental_employee_change ON employees(name)');c.close()
   with self.assertRaisesRegex(RuntimeError,'UNRELATED_SCHEMA_CHANGED'):r.validate_schema(before,r.schema(path))
 def test_row_snapshot_checks_all_values_and_no_credentials_output(self):
  with tempfile.TemporaryDirectory() as raw:
   path=Path(raw)/'db.sqlite';c=sqlite3.connect(path);c.executescript("CREATE TABLE alembic_version(version_num TEXT);INSERT INTO alembic_version VALUES('old');CREATE TABLE ringcentral_connections(id INTEGER PRIMARY KEY,secret TEXT);INSERT INTO ringcentral_connections VALUES(1,'PRIVATE_TOKEN');");c.close()
   before=r.snapshot(path);self.assertNotIn('PRIVATE_TOKEN',json.dumps(before));c=sqlite3.connect(path);c.execute("UPDATE alembic_version SET version_num='new'");c.commit();c.close();self.assertEqual(before,r.snapshot(path))
   c=sqlite3.connect(path);c.execute("UPDATE ringcentral_connections SET secret='OTHER_PRIVATE_TOKEN'");c.commit();c.close();self.assertNotEqual(before,r.snapshot(path))
 def recover_case(self,rev,migration=False):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name);(root/'activation-started.json').write_text('{}');(root/'prepared.json').write_text(json.dumps({'candidate_image':'candidate-image','fallback_image':'fallback-image'}));(root/'nginx-before.conf').write_bytes(b'OLD_NGINX')
  if migration:(root/'migration-production.json').write_text(json.dumps({'id':'migration'}))
  baseline={'runtime':{'id':'old','config':'config-hash'}}
  old={'Id':'old','Image':'old-image','Name':'/t24-crm','State':{'Running':False}}
  calls=[];settled=[not migration]
  def inspect(name):
   if name=='migration':return {'Id':name,'State':{'Running':not settled[0]}}
   return old
  def run(args,*unused,**kw):
   calls.append(args)
   if args[:2]==['docker','wait']:settled[0]=True
   return b''
  def revision(path):
   self.assertTrue(settled[0],'revision was read before settling migration')
   return rev
  def create(name,image,original):
   self.assertIn(['docker','rename','old','t24-crm-before-ringcentral-'+r.SOURCE[:12]],calls)
   calls.append(['CREATE',name,image]);return 'fallback'
  obj=object.__new__(r.Release);obj.root=root;obj.baseline=lambda:baseline;obj.expected=lambda fallback=False:{'identity':'hash'};obj.swap_nginx=lambda value:calls.append(['NGINX',value])
  with patch.object(r,'inspect',inspect),patch.object(r,'optional',lambda name:old),patch.object(r,'runtime',lambda info:{'config':'config-hash'}),patch.object(r,'run',run),patch.object(r,'revision',revision),patch.object(r,'create',create),patch.object(r,'ready',lambda name:None),patch.object(r,'configuration_equal',lambda a,b:None),patch.object(r,'inventory',lambda name:{'identity':'hash'}):result=obj.recover()
  self.assertFalse(result['database_restored']);self.assertFalse(result['database_downgraded']);return calls,result
 def test_recover_new_schema_before_original_rename(self):
  calls,result=self.recover_case(r.NEW);self.assertTrue(result['forward_compatible_fallback']);self.assertTrue(any(call[0]=='CREATE' for call in calls))
 def test_recover_waits_then_uses_committed_revision(self):
  calls,result=self.recover_case(r.NEW,True);self.assertTrue(result['forward_compatible_fallback']);self.assertEqual(calls[0],['docker','wait','migration'])
 def test_recover_old_schema_restarts_original_without_db_restore(self):
  calls,result=self.recover_case(r.OLD);self.assertFalse(result['forward_compatible_fallback']);self.assertIn(['docker','start','old'],calls);self.assertFalse(any(call[0]=='CREATE' for call in calls))

if __name__=='__main__':unittest.main()
