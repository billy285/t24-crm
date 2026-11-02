import copy,importlib.util,json,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
def load(name,file):
    s=importlib.util.spec_from_file_location(name,HERE/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
w=load('_test_worker_enable','worker_enable.py');c=load('_test_commands','make_commands.py');b=load('_test_package','build_payload.py')
class RuntimeFlagTests(unittest.TestCase):
    def setUp(self):
        self.info={'Config':{'Env':['OLD_FEATURE=true','OLD_CUTOFF=2026-10-30T19:42:04Z','OLD_DISABLED=false'],'Image':'same','Labels':{'scope':'existing'}},'HostConfig':{'NetworkMode':'bridge'},'Id':'a'*64}
    def test_projection_removes_only_one_new_entry_without_mutating_input(self):
        original=copy.deepcopy(self.info);original['Config']['Env'].append(w.KEY+'=true');projected=w.project(original);self.assertEqual(projected,self.info);self.assertEqual(original['Config']['Env'][-1],w.KEY+'=true')
    def test_false_or_missing_new_entry_rejected(self):
        for values in ([],[w.KEY+'=false'],[w.KEY+'=true',w.KEY+'=true'],[w.KEY+'=TRUE']):
            with self.subTest(values=values),self.assertRaises(RuntimeError):w.project({'Config':{'Env':values}})
    def test_only_one_entry_appended_and_old_order_unchanged(self):
        class M:
            @staticmethod
            def clone_config(image,current):return {**copy.deepcopy(current['Config']),'Image':image,'HostConfig':copy.deepcopy(current['HostConfig'])}
        value=w.candidate_config(M(),'same',self.info);self.assertEqual(value['Env'],[*self.info['Config']['Env'],w.KEY+'=true']);self.assertEqual(value['HostConfig'],self.info['HostConfig']);self.assertEqual(self.info['Config']['Env'],['OLD_FEATURE=true','OLD_CUTOFF=2026-10-30T19:42:04Z','OLD_DISABLED=false'])
    def test_existing_flag_even_false_requires_separate_review(self):
        self.info['Config']['Env'].append(w.KEY+'=false')
        with self.assertRaisesRegex(RuntimeError,'NEW_WORKER_FLAG_MUST_BE_ABSENT_BEFORE_ENABLE'):w.candidate_config(None,'same',self.info)
    def test_clone_environment_reordering_rejected(self):
        class M:
            @staticmethod
            def clone_config(image,current):return {'Env':list(reversed(current['Config']['Env']))}
        with self.assertRaisesRegex(RuntimeError,'ORIGINAL_ORDERED_ENVIRONMENT_REQUIRED'):w.candidate_config(M(),'same',self.info)
    def test_worker_helper_contains_no_policy_or_provider_write(self):
        text=(HERE/'worker_enable.py').read_text()
        for value in ('save_policy(','.generate(','INSERT INTO','UPDATE ','DELETE FROM','DROP TABLE','ALTER TABLE','write_text('):self.assertNotIn(value,text)
    def test_recovery_has_no_database_restore_or_policy_delete(self):
        import ast
        root=ast.parse((HERE/'worker_enable.py').read_text());method=next(n for n in ast.walk(root) if isinstance(n,ast.FunctionDef) and n.name=='recover_internal');body=ast.unparse(method)
        for value in ('backup(','.remove(','.unlink(','.restore(','DROP ','DELETE '):self.assertNotIn(value,body)
    def test_same_migration_backend_scope_in_package_and_release(self):self.assertEqual(b.BACKEND_SCOPE,c.r.BACKEND_SCOPE);self.assertEqual(len(b.SOURCE_SCOPE),23)

class EnvelopeTests(unittest.TestCase):
    def test_canonical_receipt_roundtrip(self):
        body=c.r.encoded({'stage':'SYNTHETIC','data':True});value=c.canonical_prepared(body);self.assertEqual(value['_canonical_sha256'],c.H(body))
    def test_transport_envelope_roundtrip(self):
        value={'stage':'SYNTHETIC','data':True};sha=c.H(c.r.encoded(value));body=json.dumps({**value,'receipt_sha256':sha}).encode();self.assertEqual(c.canonical_prepared(body)['_canonical_sha256'],sha)
    def test_incorrect_transport_hash_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'ENVELOPE_RECEIPT_HASH_MISMATCH'):c.canonical_prepared(json.dumps({'stage':'SYNTHETIC','receipt_sha256':'f'*64}).encode())
    def test_noncanonical_unwrapped_receipt_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'EXACT_CANONICAL_SERVER_RECEIPT_REQUIRED'):c.canonical_prepared(b'{"stage":"SYNTHETIC"}')
    def test_duplicate_and_nonfinite_receipt_rejected(self):
        for body in (b'{"a":1,"a":2}',b'{"a":NaN}'):
            with self.assertRaises(RuntimeError):c.canonical_prepared(body)
    def test_forged_internal_canonical_marker_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'CANONICAL_RECEIPT_OBJECT_REQUIRED'):c.canonical_prepared(c.r.encoded({'_canonical_sha256':'a'*64}))
if __name__=='__main__':unittest.main()
