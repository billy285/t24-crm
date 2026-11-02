"""Focused destructive-path guards and real SQLite additive migration proofs."""
import copy,hashlib,importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_test_automation_release',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
spec=importlib.util.spec_from_file_location('_test_automation_preflight',HERE/'preflight.py');pf=importlib.util.module_from_spec(spec);spec.loader.exec_module(pf)

def evidence(path):
    con=sqlite3.connect(path);value={}
    try:
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            shape=[con.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(name,)).fetchone()[0],con.execute('PRAGMA table_info("'+name+'")').fetchall(),con.execute('PRAGMA index_list("'+name+'")').fetchall()]
            rows=con.execute('SELECT * FROM "'+name+'"').fetchall();h=hashlib.sha256()
            for row in sorted(rows,key=repr):h.update(json.dumps(list(row)).encode())
            value[name]={'count':len(rows),'rows_sha256':h.hexdigest(),'shape_sha256':r.digest(shape)}
    finally:con.close()
    return value

class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'crm_prod.db';con=sqlite3.connect(self.db)
        con.execute('CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)');con.execute('INSERT INTO alembic_version VALUES(?)',(r.OLD_REVISION,))
        con.execute('CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT)');con.execute("INSERT INTO customers(name) VALUES('synthetic')")
        con.execute('CREATE TABLE media_monthly_runs(id INTEGER PRIMARY KEY)')
        for i in range(159):con.execute('CREATE TABLE original_'+str(i)+'(id INTEGER PRIMARY KEY,value TEXT)');con.execute('INSERT INTO original_'+str(i)+" VALUES(1,'preserve')")
        con.commit();con.close();self.before=evidence(self.db);self.defs=pf.table_definitions(self.db)
    def tearDown(self):self.temp.cleanup()
    def migrate(self):
        script=r.migration_script().replace('/app/backend/data/crm_prod.db',str(self.db)).replace('/app/backend/'+r.MIGRATION,str(HERE.parents[1]/'app/backend'/r.MIGRATION))
        exec(compile(script,'<isolated-synthetic-migration>','exec'),{})
    def test_actual_migration_preserves_all162_rows_and_objects(self):
        self.assertEqual(len(self.before),162);self.migrate();after=evidence(self.db);self.assertEqual(len(after),165);r.compare_rows(self.before,after,migrated=True);r.compare_definitions(self.defs,pf.table_definitions(self.db),migrated=True)
    def test_missing_or_extra_or_nonempty_table_rejected(self):
        self.migrate();after=evidence(self.db)
        for mutate in ('missing','extra','nonempty'):
            v=copy.deepcopy(after)
            if mutate=='missing':v.pop(next(iter(r.NEW_TABLES)))
            if mutate=='extra':v['other_table']=v['customers']
            if mutate=='nonempty':v[next(iter(r.NEW_TABLES))]['count']=1
            with self.assertRaises(RuntimeError):r.compare_rows(self.before,v,migrated=True)
    def test_original_row_mutation_rejected(self):
        self.migrate();con=sqlite3.connect(self.db);con.execute("UPDATE original_100 SET value='wrong'");con.commit();con.close()
        with self.assertRaisesRegex(RuntimeError,'ORIGINAL_BUSINESS_ROWS_CHANGED'):r.compare_rows(self.before,evidence(self.db),migrated=True)
    def test_original_schema_mutation_rejected(self):
        self.migrate();con=sqlite3.connect(self.db);con.execute('CREATE INDEX injected_index ON original_100(value)');con.commit();con.close()
        with self.assertRaisesRegex(RuntimeError,'ONLY_EXACT_THREE_TABLES_AND_INDEXES_ALLOWED'):r.compare_definitions(self.defs,pf.table_definitions(self.db),migrated=True)
    def test_wrong_head_rejected(self):
        self.migrate();con=sqlite3.connect(self.db);con.execute("UPDATE alembic_version SET version_num='unknown'");con.commit();con.close()
        with self.assertRaisesRegex(RuntimeError,'EXACT_NEW_HEAD_ROW_REQUIRED'):r.compare_rows(self.before,evidence(self.db),migrated=True)
    def test_failed_ddl_transaction_rolls_back_without_database_restore(self):
        con=sqlite3.connect(self.db);con.execute('CREATE TABLE media_monthly_automation_occurrences(id INTEGER)');con.commit();con.close();before=evidence(self.db);defs=pf.table_definitions(self.db)
        with self.assertRaises(Exception):self.migrate()
        self.assertEqual(evidence(self.db),before);self.assertEqual(pf.table_definitions(self.db),defs)
    def test_recovery_preserves_independent_rows_and_new_policy_rows(self):
        self.migrate();after=evidence(self.db);after['customers']['rows_sha256']='f'*64;after['customers']['count']=2;after[next(iter(r.NEW_TABLES))]['count']=1
        r.compare_rows(self.before,after,migrated=True,rows=False,empty=False)
    def test_recovery_still_rejects_original_shape_change(self):
        self.migrate();after=evidence(self.db);after['customers']['shape_sha256']='f'*64
        with self.assertRaises(RuntimeError):r.compare_rows(self.before,after,migrated=True,rows=False,empty=False)

class SourceGuards(unittest.TestCase):
    def test_nginx_exact_root_only(self):
        original=b'server { root /old; add_header Content-Security-Policy existing; }';new=r.next_nginx(original,Path('/old'),Path('/new'),r.H(original));self.assertEqual(new.replace(b'/new',b'/old'),original)
        for body in (original+b'x',original+original):
            with self.assertRaises(RuntimeError):r.next_nginx(body,Path('/old'),Path('/new'),r.H(original))
    def test_default_unfrozen_cannot_execute(self):
        if r.SOURCE_SHA=='0'*40:
            with self.assertRaisesRegex(RuntimeError,'FINAL_APPLICATION_PINS_REQUIRED'):r.pins_ready()
    def test_no_database_restore_or_schema_downgrade_paths(self):
        import ast
        tree=ast.parse((HERE/'release.py').read_text());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr in {'restore','downgrade','unlink','remove','replace'} and any('BUSINESS' in ast.unparse(a) for a in n.args) for n in calls))
        recover=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='recover_internal');text=ast.unparse(recover)
        self.assertNotIn('backup(',text);self.assertNotIn('DROP TABLE',text);self.assertNotIn('DELETE FROM',text)
    def test_existing_flags_and_new_default_off(self):
        text=(HERE/'release.py').read_text();self.assertIn("'T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=false'",text);self.assertNotIn('T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=true',text);self.assertNotIn('T24_META_OPS_EXECUTION_ENABLED=true',text)
    def test_capture_has_no_sql_writes(self):
        text=(HERE/'preflight.py').read_text()
        for keyword in ('INSERT INTO','UPDATE ','DELETE FROM','CREATE TABLE','ALTER TABLE','DROP TABLE'):self.assertNotIn(keyword,text)
    def test_prepared_guard_rejects_unfrozen_before_mutation(self):
        if r.SOURCE_SHA=='0'*40:
            with self.assertRaises(RuntimeError):r.validate_prepared({},'a'*64,'b'*64,'c'*64)

if __name__=='__main__':unittest.main()
