import copy,importlib.util,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_readonly_postflight_test',HERE/'postflight.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PostflightTests(unittest.TestCase):
    def test_media_hash_differences_reported_without_automatic_failure(self):
        before={name:{'count':1,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for name in p.MEDIA_TABLES};after=copy.deepcopy(before);after['media_operation_tasks'].update(count=2,rows_sha256='c'*64);result=p.compare_media(before,after);self.assertEqual(result['media_operation_tasks']['current_count'],2);self.assertFalse(result['media_operation_tasks']['rows_hash_match']);self.assertTrue(result['media_monthly_runs']['rows_hash_match'])
    def test_missing_expected_old_media_table_rejected(self):
        before={name:{'count':0,'rows_sha256':'a','shape_sha256':'b'} for name in p.MEDIA_TABLES};after=dict(before);after.pop('media_monthly_runs')
        with self.assertRaises(RuntimeError):p.compare_media(before,after)
    def test_two_active_policy_heartbeats_are_read_only_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.db';con=sqlite3.connect(path);con.execute('CREATE TABLE media_monthly_automation_policies(id INTEGER,enabled INTEGER,platform TEXT,last_checked_at TEXT)');con.execute('CREATE TABLE media_monthly_automation_occurrences(id INTEGER)');stamp=datetime.now(timezone.utc).isoformat();con.executemany('INSERT INTO media_monthly_automation_policies VALUES(?,?,?,?)',[(1,1,'facebook',stamp),(2,1,'instagram',stamp)]);con.commit();before=con.execute('SELECT * FROM media_monthly_automation_policies').fetchall();con.close();result=p.heartbeat(path);self.assertEqual(result['enabled_policy_count'],2);self.assertEqual(result['enabled_policies_seen_within_180_seconds'],2);self.assertEqual(result['occurrence_count'],0);con=sqlite3.connect(path);self.assertEqual(con.execute('SELECT * FROM media_monthly_automation_policies').fetchall(),before);con.close()
if __name__=='__main__':unittest.main()
