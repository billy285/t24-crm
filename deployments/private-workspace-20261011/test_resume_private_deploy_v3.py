"""Read-only worker gate and preserved-evidence tests; no production operations."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('resume_v3',Path(__file__).parent/'resume_private_deploy_v3.py')
resume=importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


class PublicWorkerGate(unittest.TestCase):
    def test_requires_actual_single_unprivileged_worker_identity(self):
        runner=mock.Mock(return_value='0 nginx: master process nginx\n33 nginx: worker process\n33 nginx: worker process\n')
        with mock.patch.object(resume.pwd,'getpwuid',return_value=SimpleNamespace(pw_name='www-data')):
            self.assertEqual(resume.nginx_worker_user(runner),('www-data',33))
        self.assertEqual(runner.call_args.args[1],['ps','-C','nginx','-o','uid=,args='])

    def test_rejects_root_multiple_or_missing_worker_identities(self):
        for value in ('0 nginx: worker process\n','33 nginx: worker process\n34 nginx: worker process\n','0 nginx: master process\n'):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError,'EXACT_UNPRIVILEGED'):
                resume.nginx_worker_user(mock.Mock(return_value=value))

    def test_inventory_preserves_old_scripts_and_previous_failure_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for filename in ('resume_private_deploy.py','resume_private_deploy_v2.py','resume_private_deploy_v3.py','candidate.json'):
                (root/filename).write_text(filename)
            previous=root/'resume-attempt-old';previous.mkdir()
            (previous/'failure.json').write_text('original')
            current=root/'resume-attempt-new';current.mkdir()
            (current/'current.json').write_text('new')
            with mock.patch.object(resume,'RELEASE',root):
                result=resume.original_inventory(current)
            self.assertIn('resume_private_deploy.py',result)
            self.assertIn('resume_private_deploy_v2.py',result)
            self.assertIn('resume-attempt-old/failure.json',result)
            self.assertNotIn('resume_private_deploy_v3.py',result)
            self.assertNotIn('resume-attempt-new/current.json',result)

    def test_refuses_public_ancestor_symlink_without_changing_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            real=Path(directory)/'real';real.mkdir(mode=0o700)
            linked=Path(directory)/'link';linked.symlink_to(real)
            before=real.stat().st_mode
            with self.assertRaisesRegex(RuntimeError,'PUBLIC_ANCESTOR'):
                resume.trusted_public_directory(linked)
            self.assertEqual(real.stat().st_mode,before)


if __name__=='__main__':
    unittest.main()
