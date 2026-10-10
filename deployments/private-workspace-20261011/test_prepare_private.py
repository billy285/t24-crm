"""Offline release boundary checks; no Docker, network, or production paths."""
import importlib.util
import io
import json
import hashlib
import os
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('private_release_preparation', HERE/'prepare_private.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
SHA = 'a'*40
HASH = 'b'*64


class PreparationSafety(unittest.TestCase):
    def manifest(self):
        before = {'app/backend/services/payments.py':'c'*64, 'app/Dockerfile':'d'*64,
                  'app/frontend/package.json':'e'*64}
        after = {**before, **{name:'f'*64 for name in prep.BACKEND_ADDITIONS},
                 'app/backend/tests/test_private_workspace_app.py':HASH}
        changed = {name:{'before_sha256':before.get(name),'after_sha256':value}
                   for name,value in after.items() if before.get(name)!=value}
        value = {'source_sha':SHA,'archive_sha256':HASH,'frontend_version':'1'*12,
                 'source_file_sha256':after.copy(),'changed_file_sha256':changed,
                 'backend_runtime_added_files':sorted(prep.BACKEND_ADDITIONS),'local_verification_passed':True}
        return value,before,after

    def args(self):
        return SimpleNamespace(source_sha=SHA,archive_sha256=HASH)

    def test_exact_additions_are_accepted(self):
        value,before,after=self.manifest()
        self.assertEqual(prep.checked_manifest(value,self.args(),before,after),value['changed_file_sha256'])

    def test_changed_financial_source_rejected_even_when_manifest_agrees(self):
        value,before,after=self.manifest()
        after['app/backend/services/payments.py']='0'*64
        value['source_file_sha256']=after.copy()
        value['changed_file_sha256']['app/backend/services/payments.py']={'before_sha256':'c'*64,'after_sha256':'0'*64}
        with self.assertRaisesRegex(prep.PrepareError,'ALLOWLIST'):
            prep.checked_manifest(value,self.args(),before,after)

    def test_unreviewed_frontend_build_configuration_rejected(self):
        value,before,after=self.manifest()
        after['app/frontend/package.json']='0'*64
        value['source_file_sha256']=after.copy()
        value['changed_file_sha256']['app/frontend/package.json']={'before_sha256':'e'*64,'after_sha256':'0'*64}
        with self.assertRaisesRegex(prep.PrepareError,'ALLOWLIST'):
            prep.checked_manifest(value,self.args(),before,after)

    def test_complete_manifest_omission_rejected(self):
        value,before,after=self.manifest()
        value['source_file_sha256'].pop('app/Dockerfile')
        with self.assertRaisesRegex(prep.PrepareError,'FULL_SOURCE'):
            prep.checked_manifest(value,self.args(),before,after)

    def test_existing_runtime_replacement_cannot_be_called_new(self):
        value,before,after=self.manifest()
        name=next(iter(prep.BACKEND_ADDITIONS))
        before[name]=after[name]
        value['changed_file_sha256'].pop(name)
        with self.assertRaisesRegex(prep.PrepareError,'MUST_BE_NEW'):
            prep.checked_manifest(value,self.args(),before,after)

    def archive(self, path, name, kind=None):
        with tarfile.open(path,'w:gz') as out:
            item=tarfile.TarInfo('t24-crm-'+SHA+'/'+name)
            if kind:
                item.type=kind
                item.linkname='../../etc/shadow'
                out.addfile(item)
            else:
                item.size=1
                out.addfile(item,io.BytesIO(b'x'))

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.tar.gz';self.archive(path,'../../etc/passwd')
            with self.assertRaisesRegex(prep.PrepareError,'PATH_UNSAFE'):
                prep.archive_files(path,SHA)

    def test_archive_symlink_and_hardlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):
                path=Path(directory)/'source.tar.gz';self.archive(path,'app/backend/leak',kind)
                with self.assertRaisesRegex(prep.PrepareError,'SPECIAL_FILE'):
                    prep.archive_files(path,SHA)

    def test_static_export_refuses_credentials_or_databases(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'index.html').write_text('ok');(root/'app-version.json').write_text('{}')
            for name in ('secret.env','data.db','backend.py'):
                (root/name).write_text('bad')
                with self.assertRaisesRegex(prep.PrepareError,'NON_STATIC'):
                    prep.file_manifest(root)
                (root/name).unlink()

    def test_static_export_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'index.html').write_text('ok');(root/'app-version.json').write_text('{}')
            (root/'fake.js').symlink_to(root/'index.html')
            with self.assertRaisesRegex(prep.PrepareError,'SYMLINK'):
                prep.file_manifest(root)

    def test_missing_current_lazy_chunk_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir()
            (root/'index.html').write_text('<script src="/assets/index-test.js"></script>')
            (root/'assets/index-test.js').write_text('import("./PrivateWorkspace-missing.js")')
            with self.assertRaisesRegex(prep.PrepareError,'REFERENCED_CURRENT_ASSET_MISSING'):
                prep.current_graph(root,'1'*12)

    def test_historical_private_chunk_is_not_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir()
            (root/'index.html').write_text('<script src="/assets/index-test.js"></script>')
            (root/'assets/index-test.js').write_text('const version="'+('1'*12)+'";')
            (root/'assets/PrivateWorkspace-historical.js').write_text('old stale page')
            with self.assertRaisesRegex(prep.PrepareError,'CURRENT_PRIVATE_WORKSPACE_MODULE_REQUIRED'):
                prep.current_graph(root,'1'*12)


class ResumeSafety(PreparationSafety):
    def fixture(self, directory):
        value,before,after=self.manifest()
        root=Path(directory)
        release=root/'release';release.mkdir(mode=0o700)
        public=root/'public'
        originals={
            'prepare_private.py':b'original failed preparer fixture',
            'prepare_private_v2.py':b'reviewed fixed preparer fixture',
            'release-spec.json':prep.canonical_json_bytes(value),
            'source.tar.gz':b'exact source archive fixture',
            'source-files.json':prep.canonical_json_bytes(after),
            'reviewed-changes.json':prep.canonical_json_bytes(value['changed_file_sha256']),
            'crm-before-safe.json':prep.canonical_json_bytes({'container_id':'same-fixture-container'}),
            'expected-runtime-backend.json':prep.canonical_json_bytes({}),
            'base-pin.log':prep.FAILED_BASE_PIN_BYTES,
            'existing-tags.log':b't24-crm:local\n\n',
        }
        for filename in ('base-backend.log','base-dist.log','base-package-bytes.log','base-packages.log'):
            originals[filename]=b'{}\n\n'
        for filename,blob in originals.items():
            (release/filename).write_bytes(blob);(release/filename).chmod(0o600)
        (release/'source').mkdir(mode=0o700)
        args=SimpleNamespace(source_sha=SHA,
            archive_sha256=hashlib.sha256(originals['source.tar.gz']).hexdigest(),
            manifest_sha256=hashlib.sha256(originals['release-spec.json']).hexdigest())
        # checked_manifest verifies these identity fields in the fixture too.
        value['archive_sha256']=args.archive_sha256
        (release/'release-spec.json').write_bytes(prep.canonical_json_bytes(value))
        args.manifest_sha256=prep.sha(release/'release-spec.json')
        return release,public,args,value,before,after

    def resume(self,release,public,args,value,before,after):
        def read_archive(path,source_sha,target=None):
            return before if source_sha==prep.BASE_SOURCE else after
        with patch.object(prep,'private_file',side_effect=lambda path:path), \
             patch.object(prep,'ORIGINAL_FAILED_PREPARER_SHA',prep.sha(release/'prepare_private.py')), \
             patch.object(prep,'archive_files',side_effect=read_archive), \
             patch.object(prep,'source_tree_manifest',return_value=after):
            return prep.verify_resume_preconditions(release,public,args,value,Path('base-archive'),
                                                     {'container_id':'same-fixture-container'})

    def test_resume_exact_failure_and_original_hashes_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            restored,changes,inventory=self.resume(release,public,args,value,before,after)
            self.assertEqual(restored,after)
            self.assertEqual(changes,value['changed_file_sha256'])
            self.assertEqual(set(inventory),set(prep.RESUME_ORIGINAL_FILES))
            self.assertEqual((release/'base-pin.log').read_bytes(),prep.FAILED_BASE_PIN_BYTES)

    def test_resume_candidate_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            (release/'candidate.json').write_text('{}')
            with self.assertRaisesRegex(prep.PrepareError,'EXACT_BASE_PIN_FAILURE_FILESET'):
                self.resume(release,public,args,value,before,after)

    def test_resume_existing_public_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            public.mkdir()
            with self.assertRaisesRegex(prep.PrepareError,'PUBLIC_RELEASE_ALREADY_EXISTS'):
                self.resume(release,public,args,value,before,after)

    def test_resume_different_failed_tag_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            (release/'base-pin.log').write_bytes(b'\nother Docker error\n')
            with self.assertRaisesRegex(prep.PrepareError,'EXACT_BASE_PIN_FAILURE_REQUIRED'):
                self.resume(release,public,args,value,before,after)

    def test_resume_changed_original_source_proof_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            (release/'source-files.json').write_text('{}')
            with self.assertRaisesRegex(prep.PrepareError,'SOURCE_OR_CRM_PROOF_DRIFT'):
                self.resume(release,public,args,value,before,after)

    def test_resume_changed_crm_container_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            (release/'crm-before-safe.json').write_bytes(prep.canonical_json_bytes({'container_id':'different'}))
            with self.assertRaisesRegex(prep.PrepareError,'SOURCE_OR_CRM_PROOF_DRIFT'):
                self.resume(release,public,args,value,before,after)

    def test_resume_modified_scan_log_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            release,public,args,value,before,after=self.fixture(directory)
            (release/'base-backend.log').write_text('{}\nwarning\n')
            with self.assertRaises((prep.PrepareError,json.JSONDecodeError)):
                self.resume(release,public,args,value,before,after)

    def test_real_preparation_backend_loop_keeps_release_tag(self):
        # Execute prepare through the real backend additions loop, intercepting
        # only the first mutation. This failed against the original name shadow.
        class StopAtTag(RuntimeError):pass
        value,before,after=self.manifest()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();releases=root/'releases';releases.mkdir()
            release_name,expected_tag=prep.release_identity(SHA)
            release=releases/release_name;release.mkdir(mode=0o700)
            baseline=root/'baseline';baseline.mkdir()
            (baseline/'source.tar.gz').write_bytes(b'baseline')
            archive_blob=b'exact-source-fixture'
            args=SimpleNamespace(source_sha=SHA,archive_sha256=hashlib.sha256(archive_blob).hexdigest(),
                                 resume_base_pin_failure=False)
            value['archive_sha256']=args.archive_sha256
            (release/'release-spec.json').write_bytes(prep.canonical_json_bytes(value))
            args.manifest_sha256=prep.sha(release/'release-spec.json')
            response=io.BytesIO(archive_blob);response.status=200
            real_stat=Path.stat
            def root_stat(path,*args,**kwargs):
                record=list(real_stat(path,*args,**kwargs));record[4]=0
                return os.stat_result(record)
            observed=[]
            def fake_run(stage,command,*args,**kwargs):
                if stage=='existing-tags':return ''
                if stage=='base-pin':
                    observed.append(command)
                    raise StopAtTag()
                raise AssertionError('Unexpected Docker operation '+stage)
            def fake_scan(stage,*args):
                return {'sha256':'a'*64} if stage=='base-package-bytes' else {}
            with patch.object(prep.os,'geteuid',return_value=0), \
                 patch.object(prep.socket,'gethostname',return_value=prep.HOST), \
                 patch.object(prep,'RELEASES',releases),patch.object(prep,'PUBLIC_RELEASES',root/'public'), \
                 patch.object(prep,'BASE_RELEASE',baseline), \
                 patch.object(prep,'BASE_ARCHIVE_SHA',prep.sha(baseline/'source.tar.gz')), \
                 patch.object(prep,'trusted_parent'),patch.object(prep,'private_file',side_effect=lambda path:path), \
                 patch.object(prep,'crm_identity',return_value={'container_id':'same-fixture-container'}), \
                 patch.object(prep.urllib.request,'urlopen',return_value=response), \
                 patch.object(prep,'archive_files',side_effect=lambda path,sha,target=None: before if sha==prep.BASE_SOURCE else after), \
                 patch.object(prep,'image_scan',side_effect=fake_scan),patch.object(prep,'run',side_effect=fake_run), \
                 patch.object(Path,'stat',root_stat):
                with self.assertRaises(StopAtTag):
                    prep.prepare(args)
            self.assertEqual(observed,[['docker','tag',prep.BASE_IMAGE,expected_tag+'-base']])


if __name__=='__main__':
    unittest.main()
