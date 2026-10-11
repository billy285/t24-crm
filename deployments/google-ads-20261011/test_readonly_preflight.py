"""Synthetic preflight scope tests; never read real credentials or databases."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PATH=Path(__file__).with_name('readonly_preflight.py')
spec=importlib.util.spec_from_file_location('ads_preflight',PATH);module=importlib.util.module_from_spec(spec)
with mock.patch('subprocess.run',side_effect=AssertionError('external import')),mock.patch('sqlite3.connect',side_effect=AssertionError('database import')):
    spec.loader.exec_module(module)


def environment():
    return {'PRIVATE_WORKSPACE_OWNER_IDS':'4','PRIVATE_WORKSPACE_PUBLIC_URL':'https://t24-crm.com',
            'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db','DATABASE_URL':'sqlite:///./data/crm_prod.db',
            'DATABASE_SCHEMA_MODE':'verify_only','ENFORCE_EMPLOYEE_STATUS':'true','ENFORCE_EMPLOYEE_SESSIONS':'true',
            'GOOGLE_WORKSPACE_CLIENT_ID':'synthetic-client','GOOGLE_WORKSPACE_CLIENT_SECRET':'synthetic-secret',
            'GOOGLE_ADS_DEVELOPER_TOKEN':'synthetic-developer','JWT_SECRET_KEY':'synthetic-jwt','PRIVATE_WORKSPACE_ENCRYPTION_KEY':'synthetic-key'}


class PreflightTest(unittest.TestCase):
    def test_direct_customer_scope_rejects_manager_or_conflicting_private_or_legacy_id(self):
        base=environment();self.assertTrue(module.direct_customer_scope(base)['direct_customer_only'])
        for key,value in [('GOOGLE_ADS_LOGIN_CUSTOMER_ID','1234567890'),(module.TARGET_KEY,'1234567890'),('GOOGLE_ADS_CUSTOMER_ID','1234567890')]:
            with self.subTest(key=key),self.assertRaises(module.SwitchError):module.direct_customer_scope(dict(base,**{key:value}))
        self.assertTrue(module.direct_customer_scope(dict(base,GOOGLE_ADS_CUSTOMER_ID='753-980-6760'))['direct_customer_only'])

    def test_missing_provider_configuration_reports_names_without_values(self):
        base=environment();base.pop('GOOGLE_WORKSPACE_CLIENT_ID')
        result=module.direct_customer_scope(base)
        self.assertEqual(result['missing_configuration_names'],['GOOGLE_WORKSPACE_CLIENT_ID'])
        self.assertNotIn('synthetic',json.dumps(result))

    def test_env_parser_rejects_duplicate_keys_and_target_injection(self):
        for data in (b'X=1\nX=2\n',b'X=1\r\n',b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=7539806760\nBAD',b'X=1\x00\n'):
            with self.subTest(data=data),self.assertRaises(module.SwitchError):module.parse_env(data)

    def test_script_command_and_sql_surface_has_no_mutations(self):
        source=PATH.read_text();tree=ast.parse(source)
        self.assertEqual(source.count("['docker', 'inspect', identity]"),1)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'execute','connect'} and node.args:
                first=node.args[0]
                if isinstance(first,ast.Constant) and isinstance(first.value,str):
                    self.assertTrue(first.value.startswith(('SELECT','PRAGMA','BEGIN')),first.value)
        for prohibited in ('os.O_WRONLY','os.O_RDWR','os.O_CREAT','write_text(','write_bytes(','os.replace(','docker\', \'stop','docker\', \'start'):
            self.assertNotIn(prohibited,source)

    def test_main_prints_only_safe_proofs_and_current_runtime(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name).resolve()
        public=root/'public';public.mkdir();(public/'app-version.json').write_text('{"version":"5434cc26636a"}')
        env=''.join(k+'='+v+'\n' for k,v in environment().items()).encode();nginx=str(public).encode()
        infos={}
        for role,identity in module.PRIVATE_IDS.items():
            infos['t24-private-'+role]={'Id':identity,'Image':module.PRIVATE_IMAGE,'Config':{'Env':['SYNTHETIC=only']},'HostConfig':{},
                'Mounts':[{'Source':'/opt/t24-crm/app/data','Destination':'/app/backend/data','RW':False,'Type':'bind'},
                          {'Source':'/opt/t24-crm/private-workspace/data','Destination':'/private-data','RW':True,'Type':'bind'}],
                'State':{'StartedAt':'current-start','Running':True,'Health':{'Status':'healthy'}},'RestartCount':0}
        private={role:{'configuration_sha256':module.config_hash(infos['t24-private-'+role]),'started_at':'current-start'} for role in module.PRIVATE_IDS}
        db={'device':64515,'inode':282885,'schema_sha256':'schema'}
        previous={'phase':'RESPONSIVE_STATIC_UPGRADE_VERIFIED','business_tables_verified':83,'backend_services_modified':False,'databases_restored':False,
                  'private_and_crm_runtime':{'private':private,'private_database':db},'new_nginx_sha256':module.sha(nginx)}
        proof=json.dumps(previous).encode();output=io.StringIO()
        with mock.patch.object(module.os,'geteuid',return_value=0),mock.patch.object(module.socket,'gethostname',return_value=module.HOST), \
             mock.patch.object(module,'PUBLIC',public),mock.patch.object(module,'STATIC_STATE_SHA',module.sha(proof)),mock.patch.object(module,'CURRENT_ENV_SHA',module.sha(env)), \
             mock.patch.object(module,'read_protected',side_effect=lambda p:env if p==module.ENV else proof),mock.patch.object(module,'crm_check',return_value={'id':module.CRM_ID}), \
             mock.patch.object(module,'inspect',side_effect=lambda n:infos[n]),mock.patch.object(module,'read_nginx',return_value=nginx), \
             mock.patch.object(module,'private_snapshot',return_value=db),mock.patch.object(module,'business_fingerprints',return_value={'tables':{},'schema_sha256':'schema'}),contextlib.redirect_stdout(output):
            module.main()
        result=json.loads(output.getvalue());self.assertFalse(result['mutation_performed']);self.assertEqual(result['business_tables_verified'],83)
        self.assertEqual(result['private']['t24-private-api']['id'],module.PRIVATE_IDS['api']);self.assertNotIn('synthetic-secret',output.getvalue())
        self.assertNotIn('synthetic-developer',output.getvalue());self.assertNotIn('synthetic-key',output.getvalue())


if __name__=='__main__':unittest.main()
