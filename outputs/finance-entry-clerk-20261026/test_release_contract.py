import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('finance_entry_release_contract',Path(__file__).with_name('release_contract.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class BoundaryTests(unittest.TestCase):
 def rows(self):
  before={n:dict(columns=['id'],schema='unchanged',indexes=[],count=2,rows_sha256='old') for n in ['payments','expenses','deals','commissions','customer_access_grants','employees','stripe_auto_posting_jobs','app_settings']}
  before['alembic_version']=dict(columns=['version_num'],schema='unchanged',indexes=[],count=1,rows_sha256='old-rev',revision=c.OLD_REVISION)
  after=copy.deepcopy(before);after['alembic_version'].update(revision=c.NEW_REVISION,rows_sha256='new-rev')
  after.update({n:dict(columns=['id'],schema='new',indexes=[],count=0,rows_sha256='empty') for n in c.NEW_TABLES})
  return before,after
 def role(self):return dict(pages=['/finance-entry'],buttons=['finance_draft_create'],dataScope='self',sensitiveFields={'viewFinance':False})
 def test_only_additive_empty_drafts(self):
  b,a=self.rows();self.assertTrue(c.original_rows_transition(b,a))
 def test_each_legacy_business_table_mutation_rejected(self):
  for n in ['payments','expenses','deals','commissions','customer_access_grants','employees','stripe_auto_posting_jobs']:
   b,a=self.rows();a[n]['rows_sha256']='changed'
   with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
 def test_new_table_seed_rejected(self):
  b,a=self.rows();a['finance_entry_drafts']['count']=1
  with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
 def test_unknown_extra_or_missing_table_rejected(self):
  for change in ['extra','missing']:
   b,a=self.rows()
   if change=='extra':a['unexpected']={}
   else:del a['employees']
   with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
 def test_existing_schema_or_revision_change_rejected(self):
  for field in ['schema','columns','indexes']:
   b,a=self.rows();a['payments'][field]='changed'
   with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
  b,a=self.rows();a['alembic_version']['revision']='unknown'
  with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
 def test_finance_only_config_and_other_roles_preserved(self):
  b={'role_permissions':{'value':{'finance':{'old':1},'sales':{'pages':['/sales']}},'updated_at':'old'},'company_info':{'value':{'name':'same'}}};a=copy.deepcopy(b);a['role_permissions'].update(value={'finance':self.role(),'sales':{'pages':['/sales']}},updated_at='new')
  self.assertTrue(c.role_settings_transition(b,a,self.role()))
  a['role_permissions']['value']['sales']['pages']=[]
  with self.assertRaises(c.BoundaryRejected):c.role_settings_transition(b,a,self.role())
 def test_config_or_other_metadata_changes_rejected(self):
  for changed in ['company_info','role_permissions']:
   b={'role_permissions':{'value':{'finance':self.role()},'id':1},'company_info':{'value':{'name':'same'}}};a=copy.deepcopy(b)
   if changed=='company_info':a[changed]['value']['name']='different'
   else:a[changed]['id']=2
   with self.assertRaises(c.BoundaryRejected):c.role_settings_transition(b,a,self.role())
 def test_absent_role_settings_left_absent(self):self.assertTrue(c.role_settings_transition({}, {}, self.role()))
 def test_dangerous_finance_role_configs_rejected(self):
  for patch in [dict(dataScope='all'),dict(sensitiveFields={'viewFinance':True}),dict(buttons=['payment_create'])]:
   r={**self.role(),**patch};x={'role_permissions':{'value':{'finance':r}}}
   with self.assertRaises(c.BoundaryRejected):c.role_settings_transition(x,x,r)
 def test_settings_hash_exception_needs_separate_proof(self):
  b,a=self.rows();a['app_settings']['rows_sha256']='new'
  with self.assertRaises(c.BoundaryRejected):c.original_rows_transition(b,a)
  self.assertTrue(c.original_rows_transition(b,a,role_config_change_proved=True))
 def test_schema_trigger_or_old_table_index_rejected(self):
  b={('table','payments','payments'):'same'}
  for obj in [('trigger','surprise','payments'),('index','surprise','payments')]:
   with self.assertRaises(c.BoundaryRejected):c.schema_objects_transition(b,{**b,obj:'new'},{obj})
 def test_protected_original_handler_and_unknown_path_rejected(self):
  b={'app/backend/routers/payments.py':'old'};a={'app/backend/routers/payments.py':'new'}
  with self.assertRaises(c.BoundaryRejected):c.source_scope(b,a,{'routers/payments.py'},set())
  with self.assertRaises(c.BoundaryRejected):c.source_scope({}, {'app/backend/anything.py':'new'}, {'anything.py'},set())
 def test_offline_candidate_forbidden_side_effect_rejected(self):
  good={k:True for k in ['exact_source_inventory','original_rows_unchanged','new_tables_empty','private_runtime_unchanged','private_db_identity_schema_unchanged','environment_mount_networks_preserved','offline_network_none','offline_workers_disabled','offline_credentials_not_mounted','python310_verified','startup_no_original_row_writes']};good.update({k:False for k in ['provider_requests','ledger_posts','auto_posting_policy_changes','historical_pending_processed','accounts_created_or_modified']});self.assertTrue(c.candidate_proof(good))
  for k in ['provider_requests','ledger_posts','auto_posting_policy_changes','historical_pending_processed','accounts_created_or_modified']:
   with self.assertRaises(c.BoundaryRejected):c.candidate_proof({**good,k:True})

if __name__=='__main__':unittest.main()
