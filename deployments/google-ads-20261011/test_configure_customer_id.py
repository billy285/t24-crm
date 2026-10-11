"""Synthetic offline configuration tests. Never read production environment."""
import ast
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('ads_config',Path(__file__).with_name('configure_customer_id.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def environment(extra=''):
    return ("PRIVATE_WORKSPACE_OWNER_IDS=4\nPRIVATE_WORKSPACE_PUBLIC_URL=https://t24-crm.com\n"
            "PRIVATE_WORKSPACE_DATABASE_URL=sqlite+aiosqlite:////private-data/workspace.db\nDATABASE_URL=sqlite:///./data/crm_prod.db\n"
            "DATABASE_SCHEMA_MODE=verify_only\nENFORCE_EMPLOYEE_STATUS=true\nENFORCE_EMPLOYEE_SESSIONS=true\n"
            "JWT_SECRET_KEY=synthetic-not-a-secret-0123456789\nPRIVATE_WORKSPACE_ENCRYPTION_KEY=synthetic-key-0123456789\n"
            "GOOGLE_WORKSPACE_CLIENT_ID=synthetic-client\nGOOGLE_WORKSPACE_CLIENT_SECRET=synthetic-secret\n"
            "PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT=owner@example.test\n"+extra).encode()

class TransitionTest(unittest.TestCase):
    def test_append_preserves_every_existing_byte(self):
        before=environment();after,count=module.new_environment(before)
        self.assertEqual(count,1)
        self.assertEqual(after,before+b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=7539806760\n')

    def test_only_blank_target_line_replaced_without_reordering(self):
        before=environment('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=  \nANOTHER_PLATFORM=unchanged\n')
        after,count=module.new_environment(before)
        self.assertEqual(count,1);self.assertEqual(after,before.replace(b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=  \n',b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=7539806760\n'))

    def test_same_target_is_true_noop(self):
        before=environment('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=753-980-6760\n')
        self.assertEqual(module.new_environment(before),(before,0))

    def test_conflicting_direct_scope_rejected(self):
        for extra in ['PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=1111111111\n','GOOGLE_ADS_CUSTOMER_ID=1111111111\n','GOOGLE_ADS_LOGIN_CUSTOMER_ID=7539806760\n']:
            with self.subTest(extra=extra),self.assertRaises(module.SwitchError):module.new_environment(environment(extra))

    def test_duplicate_injection_or_missing_boundary_rejected(self):
        for malformed in [environment('JWT_SECRET_KEY=duplicate\n'),environment()+b'bad row\n',environment().replace(b'\n',b'\r\n'),environment().rstrip(b'\n'),environment().replace(b'PRIVATE_WORKSPACE_OWNER_IDS=4',b'PRIVATE_WORKSPACE_OWNER_IDS=5')]:
            with self.subTest(),self.assertRaises(module.SwitchError):module.new_environment(malformed)

    def test_source_contains_no_service_database_or_network_boundary(self):
        tree=ast.parse(Path(module.__file__).read_text())
        self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(a.name.split('.')[0] in {'subprocess','sqlite3','urllib','requests'} for a in n.names) for n in ast.walk(tree)))

class AtomicMainTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.parent=Path(self.temporary.name).resolve()/'private-workspace';self.parent.mkdir(mode=0o700)
        self.config=self.parent/'config';self.config.mkdir(mode=0o700)
        self.env=self.config/'runtime.env';self.before=environment();self.env.write_bytes(self.before);self.env.chmod(0o600)
        self.pin=module.sha(self.before);self.args=SimpleNamespace(execute=True,expected_env_sha256=self.pin)
        self.original_umask=os.umask(0o077);self.addCleanup(os.umask,self.original_umask)
        def secure(path,directory=False,mode=None):
            info=path.lstat()
            module.need(path.resolve()==path and not path.is_symlink(),'PATH_ALIAS_REJECTED')
            module.need((path.is_dir() if directory else path.is_file() and info.st_nlink==1) and (mode is None or info.st_mode & 0o777 == mode),'PROTECTED_TYPE_REQUIRED')
            return info
        for patch in [mock.patch.object(module,'CONFIG',self.config),mock.patch.object(module,'ENV',self.env),
                      mock.patch.object(module,'BEFORE_ENV_SHA',self.pin),mock.patch.object(module.os,'geteuid',return_value=0),
                      mock.patch.object(module.socket,'gethostname',return_value=module.HOST),mock.patch.object(module,'secure',side_effect=secure)]:
            patch.start();self.addCleanup(patch.stop)

    def test_real_local_atomic_replace_and_protected_receipts(self):
        old_inode=self.env.stat().st_ino;stdout=io.StringIO()
        with redirect_stdout(stdout):module.main(self.args)
        self.assertNotEqual(self.env.stat().st_ino,old_inode)
        self.assertEqual(self.env.read_bytes(),module.new_environment(self.before)[0]);self.assertEqual(self.env.stat().st_mode & 0o777,0o600)
        result=json.loads(stdout.getvalue());receipt=self.config/result['receipt_basename']
        proof=json.loads(receipt.read_bytes());backup=self.config/proof['backup_basename']
        self.assertEqual(backup.read_bytes(),self.before);self.assertEqual(backup.stat().st_mode & 0o777,0o600);self.assertEqual(receipt.stat().st_mode & 0o777,0o600)
        self.assertEqual(result['changed_keys'],[module.TARGET_KEY]);self.assertEqual(result['receipt_sha256'],module.sha(receipt.read_bytes()))
        self.assertFalse(proof['services_modified']);self.assertFalse(proof['databases_modified'])
        for secret in ['synthetic-not-a-secret','synthetic-key','synthetic-client','synthetic-secret','owner@example.test','7539806760']:
            self.assertNotIn(secret,stdout.getvalue());self.assertNotIn(secret,receipt.read_text())

    def test_wrong_current_hash_refused_without_environment_mutation(self):
        self.env.write_bytes(environment('ANOTHER_PLATFORM=concurrent\n'));before=self.env.read_bytes()
        with self.assertRaisesRegex(module.SwitchError,'ENVIRONMENT_BASELINE_DRIFT'):module.main(self.args)
        self.assertEqual(self.env.read_bytes(),before);self.assertFalse(list(self.config.glob('runtime.env.before-*')))

    def test_wrong_argument_hash_refused_before_lock_or_backup(self):
        self.args.expected_env_sha256='f'*64
        with self.assertRaisesRegex(module.SwitchError,'PINNED_ORIGINAL_ENV_HASH_REQUIRED'):module.main(self.args)
        self.assertEqual(list(self.config.iterdir()),[self.env])

    def test_symlink_or_hardlinked_environment_refused(self):
        another=self.config/'aliased.env';os.link(self.env,another)
        with self.assertRaisesRegex(module.SwitchError,'PROTECTED_TYPE_REQUIRED'):module.main(self.args)
        another.unlink();self.env.unlink();self.env.symlink_to(another)
        with self.assertRaisesRegex(module.SwitchError,'PATH_ALIAS_REJECTED'):module.main(self.args)

if __name__=='__main__':unittest.main()
