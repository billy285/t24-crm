"""Real additive migration and the explicit pre-start/live-write frontier."""
import copy,hashlib,importlib.util,json,os,sqlite3,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
def load(name,file):
    s=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
r=load('_unified_release_test',HERE/'release.py');pf=load('_unified_preflight_test',HERE/'preflight.py')
def evidence(path):
    con=sqlite3.connect(path);out={}
    try:
        for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            sql=con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()[0];shape=[sql,con.execute('PRAGMA table_info("'+name+'")').fetchall(),con.execute('PRAGMA index_list("'+name+'")').fetchall()];rows=con.execute('SELECT * FROM "'+name+'"').fetchall();h=hashlib.sha256()
            for row in sorted(rows,key=repr):h.update(json.dumps(list(row)).encode())
            out[name]={'count':len(rows),'rows_sha256':h.hexdigest(),'shape_sha256':r.digest(shape)}
    finally:con.close()
    return out
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'crm_prod.db';con=sqlite3.connect(self.db);con.execute('PRAGMA journal_mode=WAL');con.execute('CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)');con.execute('INSERT INTO alembic_version VALUES(?)',(r.OLD_REVISION,));con.execute('CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT)');con.execute("INSERT INTO customers(name) VALUES('synthetic')");con.execute('CREATE TABLE media_monthly_automation_policies(id INTEGER PRIMARY KEY,last_checked_at TEXT)');con.executemany('INSERT INTO media_monthly_automation_policies VALUES(?,?)',[(1,'before'),(2,'before')])
        for i in range(162):con.execute('CREATE TABLE original_'+str(i)+'(id INTEGER PRIMARY KEY,value TEXT)');con.execute('INSERT INTO original_'+str(i)+" VALUES(1,'preserve')")
        con.commit();con.close();self.before=evidence(self.db);self.defs=pf.table_definitions(self.db)
    def tearDown(self):self.temp.cleanup()
    def migrate(self):
        script=r.migration_script().replace('/app/backend/data/crm_prod.db',str(self.db)).replace('/app/backend/'+r.MIGRATION,str(HERE.parents[1]/'app/backend'/r.MIGRATION));exec(compile(script,'<isolated-wal-clone-migration>','exec'),{})
    def test_actual165_to169_preserves_all_rows_definitions_and_sequences(self):
        self.assertEqual(len(self.before),165);con=sqlite3.connect(self.db);seq=con.execute('SELECT * FROM sqlite_sequence').fetchall();con.close();self.migrate();after=evidence(self.db);self.assertEqual(len(after),169);r.compare_rows(self.before,after,migrated=True);r.compare_definitions(self.defs,pf.table_definitions(self.db),migrated=True);con=sqlite3.connect(self.db);self.assertEqual(con.execute('SELECT * FROM sqlite_sequence').fetchall(),seq);con.close()
    def test_every_original_table_row_change_rejected_before_start(self):
        self.migrate();after=evidence(self.db)
        for name in self.before:
            changed=copy.deepcopy(after);changed[name]['rows_sha256']='f'*64
            with self.subTest(table=name),self.assertRaises(RuntimeError):r.compare_rows(self.before,changed,migrated=True)
    def test_new_tables_missing_extra_or_nonempty_rejected(self):
        self.migrate();after=evidence(self.db)
        for kind in ('missing','extra','nonempty'):
            v=copy.deepcopy(after)
            if kind=='missing':v.pop(next(iter(r.NEW_TABLES)))
            if kind=='extra':v['extra']=v['customers']
            if kind=='nonempty':v[next(iter(r.NEW_TABLES))]['count']=1
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):r.compare_rows(self.before,v,migrated=True)
    def test_original_table_schema_or_index_change_rejected(self):
        self.migrate();con=sqlite3.connect(self.db);con.execute('CREATE INDEX injected ON original_0(value)');con.commit();con.close()
        with self.assertRaises(RuntimeError):r.compare_definitions(self.defs,pf.table_definitions(self.db),migrated=True)
    def test_failed_ddl_rolls_back_without_restoring_database(self):
        con=sqlite3.connect(self.db);con.execute('CREATE TABLE media_automation_template_versions(id INTEGER)');con.commit();con.close();rows=evidence(self.db);defs=pf.table_definitions(self.db)
        with self.assertRaises(Exception):self.migrate()
        self.assertEqual(evidence(self.db),rows);self.assertEqual(pf.table_definitions(self.db),defs)
    def test_policy_heartbeat_before_start_is_still_a_protected_business_row(self):
        self.migrate();con=sqlite3.connect(self.db);con.execute("UPDATE media_monthly_automation_policies SET last_checked_at='advanced'");con.commit();con.close()
        with self.assertRaisesRegex(RuntimeError,'ORIGINAL165_BUSINESS_ROWS_CHANGED_BEFORE_START'):r.compare_rows(self.before,evidence(self.db),migrated=True)

class FrontierTests(unittest.TestCase):
    def fake(self,*,live=False,changed=False,bad_schema=False):
        original={'Id':'old','State':{'Running':False}};candidate={'Id':'new','State':{'Running':live},'RestartCount':0};calls=[]
        def immutable(**kwargs):
            calls.append(('immutable',kwargs))
            if bad_schema:raise RuntimeError('REVIEWED169_SCHEMA_CHANGED')
        def compare(*args,**kwargs):
            calls.append(('exact_rows',kwargs))
            if changed:raise RuntimeError('ORIGINAL165_BUSINESS_ROWS_CHANGED_BEFORE_START')
        obj=types.SimpleNamespace(immutable=immutable,identities=lambda r,old:(original,candidate),base=types.SimpleNamespace(c=types.SimpleNamespace(retained=types.SimpleNamespace(compare=lambda *x:None),source_boundary=lambda *x:None,helper=types.SimpleNamespace(validation_window=lambda x:calls.append(('window',True))))),m=types.SimpleNamespace(BUSINESS=Path('/synthetic/db'),inspect=lambda name:candidate),writer_census=lambda allowed=():calls.append(('writers',allowed)),census=types.SimpleNamespace(no_open_database_fds=lambda path:None),environment=lambda x:None,inventory={},baseline={'rows':'all165'},compare_before_start=compare)
        return obj,original,calls
    def test_before_candidate_start_all165_rows_are_exact(self):
        obj,old,calls=self.fake(changed=True)
        with self.assertRaisesRegex(RuntimeError,'ORIGINAL165_BUSINESS_ROWS_CHANGED_BEFORE_START'):r.Release.runtime_boundary(obj,{},old,migrated=True)
        self.assertTrue(any(v[0]=='exact_rows' for v in calls))
    def test_after_start_policy_heartbeat_is_not_a_false_positive(self):
        obj,old,calls=self.fake(live=True,changed=True);r.Release.runtime_boundary(obj,{},old,migrated=True,live=True);self.assertFalse(any(v[0]=='exact_rows' for v in calls));self.assertTrue(any(v[0]=='immutable' for v in calls))
    def test_after_start_schema_changes_remain_rejected(self):
        obj,old,_=self.fake(live=True,bad_schema=True)
        with self.assertRaisesRegex(RuntimeError,'REVIEWED169_SCHEMA_CHANGED'):r.Release.runtime_boundary(obj,{},old,migrated=True,live=True)
    def test_recovery_preserves_latest_independent_business_rows(self):
        obj,old,calls=self.fake(changed=True);r.Release.runtime_boundary(obj,{},old,migrated=True,recovery=True);self.assertFalse(any(v[0]=='exact_rows' for v in calls))
    def test_idle_unknown_writer_after_migration_rejected_before_candidate_start(self):
        obj,old,calls=self.fake()
        def reject(allowed=()):raise RuntimeError('UNKNOWN_RUNNING_DATABASE_WRITER')
        obj.writer_census=reject
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):r.Release.runtime_boundary(obj,{},old,migrated=True)
    def test_unknown_writer_after_candidate_start_is_still_rejected(self):
        obj,old,calls=self.fake(live=True)
        def reject(allowed=()):raise RuntimeError('UNKNOWN_RUNNING_DATABASE_WRITER')
        obj.writer_census=reject
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):r.Release.runtime_boundary(obj,{},old,migrated=True,live=True)

class EnvironmentAndCodeTests(unittest.TestCase):
    def test_existing_monthly_worker_true_is_preserved_without_mutating_info(self):
        rows=['OLD_WORKER=true',pf.KEY+'=true'];info={'Config':{'Env':rows[:]}};seen=[];ctx=types.SimpleNamespace(environment=lambda value:seen.append(value['Config']['Env'][:]));env,ordered=pf.environment(ctx,info);self.assertEqual(info['Config']['Env'],rows);self.assertEqual(seen,[['OLD_WORKER=true']]);self.assertEqual(env,pf.digest(sorted(rows)));self.assertEqual(ordered,pf.digest(rows))
    def test_missing_false_or_duplicate_monthly_worker_flag_rejected(self):
        for rows in ([],[pf.KEY+'=false'],[pf.KEY+'=true',pf.KEY+'=true']):
            with self.subTest(rows=rows),self.assertRaises(RuntimeError):pf.environment(None,{'Config':{'Env':rows}})
    def test_only_four_new_tables_and_five_named_indexes(self):self.assertEqual(len(r.NEW_TABLES),4);self.assertEqual(len(r.NEW_INDEXES),5)
    def test_no_worker_activation_or_second_constructor_flow(self):
        text=(HERE/'release.py').read_text();self.assertNotIn('Enable(',text);self.assertNotIn('T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=false',text);self.assertNotIn('T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=true',text);self.assertIn('adapter.offline_args(data,image)',text)
    def test_new_tool_does_not_call_mutated_legacy_sample(self):
        for name in ('release.py','preflight.py'):
            text=(HERE/name).read_text();self.assertNotIn('.pf.sample(',text);self.assertNotIn('ctx.sample(',text);self.assertNotIn('worker_enable.Enable',text)
    def test_no_database_restore_drop_or_production_delete_path(self):
        text=(HERE/'release.py').read_text()
        for token in ('DROP TABLE','DELETE FROM','downgrade(','.restore(','.unlink('):self.assertNotIn(token,text)
    def test_nginx_changes_only_exact_public_root(self):
        before=b'server { root /old; add_header Content-Security-Policy exact; }';after=r.next_nginx(before,Path('/old'),Path('/new'),r.H(before));self.assertEqual(after.replace(b'/new',b'/old'),before)
        with self.assertRaises(RuntimeError):r.next_nginx(before+b'changed',Path('/old'),Path('/new'),r.H(before))
    def test_unfrozen_tool_rejects_before_server_work(self):
        if r.SOURCE_SHA=='0'*40:
            with self.assertRaises(RuntimeError):r.pins_ready()
if __name__=='__main__':unittest.main()
