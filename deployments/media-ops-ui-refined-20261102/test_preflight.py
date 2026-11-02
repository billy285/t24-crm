import copy,importlib.util,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('navigation_capture_test',HERE/'preflight.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class CaptureBoundary(unittest.TestCase):
    def test_exact_current_pins(self):
        self.assertEqual(p.SOURCE,'68fa8589101f4a3075141c910ec51fd86b9ec9ed');self.assertEqual(p.RUNTIME['id'],'6f826ade371a37fbf405c2e90ee405abb4e7d5ad5c9344139cb65a46596e5757');self.assertEqual(p.HEAD,'i54af678a914')
    def test_equal_samples(self):p.stable({'runtime':1,'schema':2},{'runtime':1,'schema':2})
    def test_each_immutable_drift_rejected(self):
        row={'runtime':1,'schema':2,'env':3,'private':4,'nginx':5,'source':6}
        for key in row:
            changed=copy.deepcopy(row);changed[key]+=1
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,'IMMUTABLE_STATIC_BOUNDARIES_CHANGED'):p.stable(row,changed)
    def test_capture_does_not_read_or_hash_business_rows(self):
        source=(HERE/'preflight.py').read_text();self.assertNotIn('ctx.rows(',source);self.assertNotIn("['rows']",source);self.assertNotIn('live_sequence_boundary',source);self.assertIn("'business_rows_read_or_frozen':False",source)
    def test_no_legacy_mutated_sample_or_worker_constructor(self):
        source=(HERE/'preflight.py').read_text();self.assertNotIn('.sample()',source);self.assertNotIn('Enable(',source);self.assertNotIn('m.public_root=',source)
    def test_capture_reuses_only_previous_static_readonly_boundary(self):
        source=(HERE/'preflight.py').read_text();self.assertIn('previous.boundary(updated=True)',source);self.assertNotIn('.immutable(',source);self.assertIn("'backend_source_sha':BACKEND_SOURCE",source)
    def test_no_cloud_mutation_commands(self):
        source=(HERE/'preflight.py').read_text()
        for text in ('docker stop','docker start','docker restart','UPDATE ','INSERT ','DELETE ','DROP TABLE','migration_script','reload_nginx'):
            self.assertNotIn(text,source)
if __name__=='__main__':unittest.main()
