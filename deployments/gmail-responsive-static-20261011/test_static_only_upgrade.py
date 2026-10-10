"""Local synthetic release guard tests, without credentials or production I/O."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PATH=Path(__file__).with_name('static_only_upgrade.py')
spec=importlib.util.spec_from_file_location('static_patch',PATH);patch=importlib.util.module_from_spec(spec)
with mock.patch('subprocess.run',side_effect=AssertionError('external import')), \
     mock.patch('sqlite3.connect',side_effect=AssertionError('database import')):
    spec.loader.exec_module(patch)


class StaticGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()

    def archive(self,entries):
        target=self.root/'static-payload.tar.gz'
        with tarfile.open(target,'w:gz') as stream:
            for name,blob,kind in entries:
                item=tarfile.TarInfo(name);item.type=kind;item.size=len(blob)
                if kind!=tarfile.REGTYPE:item.linkname='../../escaped'
                stream.addfile(item,io.BytesIO(blob) if kind==tarfile.REGTYPE else None)

    def valid(self):
        return {'index.html':b'<script src="/assets/app.js"></script>',
                'app-version.json':json.dumps({'version':patch.VERSION}).encode(),'assets/app.js':b'const ready=true;'}

    def extract(self,files):
        with mock.patch.object(patch,'RELEASE',self.root):
            return patch.extract_static({'payload_files':{k:patch.sha(v) for k,v in files.items()}})

    def test_regular_static_payload_hashes_and_exact_version(self):
        files=self.valid();self.archive([('payload/'+n,b,tarfile.REGTYPE) for n,b in files.items()])
        self.assertEqual(patch.file_map(self.extract(files)),{n:patch.sha(b) for n,b in files.items()})

    def test_production_verified_archive_bytes_branch_ignores_reopened_path(self):
        files=self.valid();self.archive([('payload/'+n,b,tarfile.REGTYPE) for n,b in files.items()])
        verified=(self.root/'static-payload.tar.gz').read_bytes()
        manifest={'source_sha':patch.SOURCE,'frontend_version':patch.VERSION,'static_only':True,'backend_changes':False,
                  'credentials_included':False,'payload_files':{n:patch.sha(b) for n,b in files.items()},'payload_sha256':patch.sha(verified)}
        blob=json.dumps(manifest).encode();(self.root/'static-payload.tar.gz').write_bytes(b'changed after verification')
        with mock.patch.object(patch,'RELEASE',self.root),mock.patch.object(patch,'read_protected',side_effect=lambda path,*a:blob if path.name=='static-manifest.json' else verified):
            checked,carrier=patch.manifest_check(patch.sha(blob))
            actual=patch.extract_static(checked,carrier)
        self.assertEqual(patch.file_map(actual),manifest['payload_files'])

    def test_tar_traversal_links_duplicates_backend_and_wrong_hash_fail(self):
        for name,kind,expected in [('payload/../escape.js',tarfile.REGTYPE,'STATIC_PAYLOAD_PATH_INVALID'),
                                   ('payload/assets/link.js',tarfile.SYMTYPE,'REGULAR_STATIC_FILES_ONLY'),
                                   ('payload/assets/link.js',tarfile.LNKTYPE,'REGULAR_STATIC_FILES_ONLY'),
                                   ('payload/.env',tarfile.REGTYPE,'STATIC_PAYLOAD_PATH_INVALID')]:
            with self.subTest(name=name,kind=kind):
                if (self.root/'payload').exists(): import shutil;shutil.rmtree(self.root/'payload')
                self.archive([(name,b'bad',kind)])
                with self.assertRaisesRegex(patch.SwitchError,expected):self.extract(self.valid())
        import shutil
        shutil.rmtree(self.root/'payload');files=self.valid();self.archive([('payload/index.html',files['index.html'],tarfile.REGTYPE)]*2)
        with self.assertRaisesRegex(patch.SwitchError,'STATIC_ALLOWLIST_DRIFT'):self.extract(files)
        shutil.rmtree(self.root/'payload');files['backend.py']=b'pass';self.archive([('payload/'+n,b,tarfile.REGTYPE) for n,b in files.items()])
        with self.assertRaisesRegex(patch.SwitchError,'NON_STATIC_FILE'):self.extract(files)
        shutil.rmtree(self.root/'payload');files=self.valid();self.archive([('payload/index.html',b'wrong',tarfile.REGTYPE)])
        with self.assertRaisesRegex(patch.SwitchError,'STATIC_FILE_HASH_DRIFT'):self.extract(files)

    def test_umask_does_not_make_new_public_root_private(self):
        previous=os.umask(0o077)
        try: patch.create_public_root(self.root/'public')
        finally: os.umask(previous)
        self.assertEqual(stat.S_IMODE((self.root/'public').stat().st_mode),0o755)
        with self.assertRaisesRegex(patch.SwitchError,'FRESH_PUBLIC_ROOT_REQUIRED'):patch.create_public_root(self.root/'public')

    def test_old_hashed_assets_preserved_and_worker_reads_actual_bytes(self):
        old=self.root/'old';new=self.root/'public';payload=self.root/'source'
        for p in (old/'assets',payload/'assets'):p.mkdir(parents=True)
        (old/'assets/old.js').write_text('old');(old/'index.html').write_text('old index')
        for name,blob in self.valid().items():
            p=payload/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
        def run(command,*args):return json.dumps(patch.file_map(new)).encode()
        previous=os.umask(0o077)
        try:
            with mock.patch.object(patch,'PUBLIC',new),mock.patch.object(patch,'OLD_PUBLIC',old),mock.patch.object(patch,'RELEASE',self.root), \
                 mock.patch.object(patch,'public_ancestors'),mock.patch.object(patch.subprocess,'check_output',return_value='1001 nginx: worker process\n'), \
                 mock.patch.object(patch.pwd,'getpwuid',return_value=SimpleNamespace(pw_name='www-data')),mock.patch.object(patch,'run',side_effect=run):
                result=patch.install_public(payload)
        finally:os.umask(previous)
        self.assertIn('assets/old.js',result);self.assertEqual((new/'index.html').read_bytes(),self.valid()['index.html'])
        self.assertEqual(stat.S_IMODE(new.stat().st_mode),0o755)
        self.assertEqual(stat.S_IMODE((new/'assets').stat().st_mode),0o755)
        self.assertEqual(stat.S_IMODE((new/'assets/app.js').stat().st_mode),0o644)

    def test_nginx_changes_only_exact_current_root(self):
        before=(str(patch.OLD_PUBLIC)+'\nproxy_pass http://127.0.0.1:8000;\nproxy_pass http://127.0.0.1:8001;\n'+'\n'.join(patch.HEADERS)).encode()
        after=patch.nginx_bytes(before,patch.sha(before))
        self.assertEqual(after.replace(str(patch.PUBLIC).encode(),str(patch.OLD_PUBLIC).encode(),1),before)
        with self.assertRaisesRegex(patch.SwitchError,'NGINX_BASELINE_DRIFT'):patch.nginx_bytes(before,'a'*64)
        with self.assertRaisesRegex(patch.SwitchError,'EXACT_ROOT_REPLACEMENT_REQUIRED'):patch.nginx_bytes(before+str(patch.OLD_PUBLIC).encode(),patch.sha(before+str(patch.OLD_PUBLIC).encode()))

    def test_command_allowlist_forbids_all_container_and_database_mutations(self):
        with mock.patch.object(patch.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'ok')) as execute:
            for command in (['docker','restart',patch.CRM_ID],['docker','stop',patch.PRIVATE_IDS['worker']],['sqlite3',str(patch.BUSINESS),'DELETE FROM payments']):
                with self.assertRaisesRegex(patch.SwitchError,'COMMAND_SCOPE_REJECTED'):patch.run(command,'FAIL')
            execute.assert_not_called()
            patch.run(['nginx','-t'],'FAIL');patch.run(['systemctl','reload','nginx'],'FAIL')
        tree=ast.parse(PATH.read_text())
        commands=[n for n in ast.walk(tree) if isinstance(n,ast.Constant) and n.value=='docker']
        self.assertEqual(len(commands),1) # The sole Docker command is read-only inspect.
        self.assertIn("['docker', 'inspect', identity]",PATH.read_text())

    def test_private_guard_ignores_worker_provider_refresh_but_keeps_connection_identity(self):
        private=self.root/'workspace.db';business=self.root/'crm.db';business.touch()
        import sqlite3
        with sqlite3.connect(private) as db:
            db.execute('CREATE TABLE private_connections(id TEXT,owner_id TEXT,source_id TEXT,status TEXT,generation INT,metadata_json TEXT,encrypted_credentials TEXT)')
            db.execute('INSERT INTO private_connections VALUES(?,?,?,?,?,?,?)',('id','4','gmail','connected',7,json.dumps({'scope':'https://www.googleapis.com/auth/gmail.readonly','connection_mode':'oauth','account_label':'synthetic@example.test'}),'ciphertext'))
        def guard():
            with mock.patch.object(patch,'PRIVATE_DB',private),mock.patch.object(patch,'BUSINESS',business),mock.patch.object(patch,'secure',return_value=SimpleNamespace(st_dev=64515,st_ino=282885)):
                return patch.private_guard()
        before=guard()
        with sqlite3.connect(private) as db:db.execute('UPDATE private_connections SET encrypted_credentials=?',('rotated',))
        self.assertEqual(guard(),before)
        with sqlite3.connect(private) as db:db.execute('UPDATE private_connections SET generation=8')
        self.assertNotEqual(guard(),before)
        self.assertNotIn('synthetic@example.test',json.dumps(before));self.assertNotIn('ciphertext',json.dumps(before))

    def test_rollback_restores_only_nginx_root_without_health_dependency(self):
        original=b'old';changed=b'new';current=[changed];commands=[]
        def atomic(blob,hashes):self.assertEqual(hashes,{patch.sha(changed)});current[0]=blob
        old=self.root/'old';old.mkdir();(old/'app-version.json').write_text('{"version":"old-version"}')
        with mock.patch.object(patch,'OLD_PUBLIC',old),mock.patch.object(patch,'public_check') as verify, \
             mock.patch.object(patch,'runtime_check') as check,mock.patch.object(patch,'read_nginx',side_effect=lambda:current[0]), \
             mock.patch.object(patch,'atomic_nginx',side_effect=atomic),mock.patch.object(patch,'run',side_effect=lambda c,*a:commands.append(c)):
            patch.rollback_static(original,changed,{'pinned':'prior'})
        check.assert_called_once_with({'pinned':'prior'},healthy=False)
        self.assertEqual(commands,[['nginx','-t'],['systemctl','reload','nginx']]);self.assertEqual(current[0],original)
        self.assertEqual(verify.call_args.args[1:3],('old-version',old));self.assertEqual(verify.call_args.kwargs,{'verify_services':False})

    def test_rollback_rejects_concurrent_nginx_change(self):
        with mock.patch.object(patch,'runtime_check'),mock.patch.object(patch,'read_nginx',return_value=b'foreign'),mock.patch.object(patch,'atomic_nginx') as mutate:
            with self.assertRaisesRegex(patch.SwitchError,'STATIC_ROLLBACK_CONCURRENT_CHANGE'):patch.rollback_static(b'old',b'new',{})
        mutate.assert_not_called()

    def test_manifest_must_pin_static_scope_payload_hash_and_version(self):
        payload=b'synthetic archive'
        valid={'source_sha':patch.SOURCE,'frontend_version':patch.VERSION,'static_only':True,'backend_changes':False,
               'credentials_included':False,'payload_files':{'index.html':'a'*64},'payload_sha256':patch.sha(payload)}
        def check(value,expected=None):
            blob=json.dumps(value).encode()
            with mock.patch.object(patch,'read_protected',side_effect=lambda path,*a:blob if path.name=='static-manifest.json' else payload):
                return patch.manifest_check(expected or patch.sha(blob))
        self.assertEqual(check(valid),(valid,payload))
        for field,value in [('source_sha','a'*40),('frontend_version','b'*12),('static_only',False),('backend_changes',True),('credentials_included',True)]:
            changed=dict(valid);changed[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(patch.SwitchError,'STATIC_MANIFEST_SCOPE_DRIFT'):check(changed)
        with self.assertRaisesRegex(patch.SwitchError,'STATIC_MANIFEST_HASH_DRIFT'):check(valid,'f'*64)
        changed=dict(valid,payload_sha256='f'*64)
        with self.assertRaisesRegex(patch.SwitchError,'STATIC_ARCHIVE_HASH_DRIFT'):check(changed)

    def test_current_private_image_ids_started_config_and_env_are_pinned(self):
        from copy import deepcopy
        info={role:{'Id':identity,'Image':patch.PRIVATE_IMAGE,'Config':{'Env':['SYNTHETIC=value']},'HostConfig':{},'Mounts':[],
                    'State':{'StartedAt':'known-start','Running':True,'Health':{'Status':'healthy'}},'RestartCount':0}
              for role,identity in patch.PRIVATE_IDS.items()}
        guard={'device':64515,'inode':282885,'schema_sha256':'schema','connection_identity_sha256':'identity'}
        previous={'new_private':{role:{'configuration_sha256':patch.config_hash(value),'started_at':'known-start','restart_count':0} for role,value in info.items()},
                  'private_database':{k:guard[k] for k in ('device','inode','schema_sha256')}}
        def check(observed,environment=b'synthetic-env',healthy=True):
            with mock.patch.object(patch,'crm_check',return_value={'id':patch.CRM_ID}),mock.patch.object(patch,'CURRENT_ENV_SHA',patch.sha(b'synthetic-env')), \
                 mock.patch.object(patch,'read_protected',return_value=environment),mock.patch.object(patch,'private_guard',return_value=guard), \
                 mock.patch.object(patch,'inspect',side_effect=lambda name:observed[name.removeprefix('t24-private-')]):
                return patch.runtime_check(previous,healthy=healthy)
        self.assertEqual(check(info)['private_database'],guard)
        for mutate in (lambda x:x.update(Id='f'*64),lambda x:x.update(Image='sha256:'+'f'*64),
                       lambda x:x['State'].update(StartedAt='different'),lambda x:x['Config'].update(Env=['changed']),
                       lambda x:x.update(RestartCount=1)):
            changed=deepcopy(info);mutate(changed['api'])
            with self.subTest(mutate=mutate),self.assertRaisesRegex(patch.SwitchError,'PRIVATE_RUNTIME_CONFIGURATION_DRIFT'):check(changed)
        with self.assertRaisesRegex(patch.SwitchError,'ENVIRONMENT_HASH_DRIFT'):check(info,b'changed-env')
        changed=deepcopy(info);changed['api']['State']['Health']['Status']='unhealthy'
        with self.assertRaisesRegex(patch.SwitchError,'PRIVATE_API_HEALTH_DRIFT'):check(changed)
        check(changed,healthy=False) # Rollback may proceed despite unrelated transient health.

    def test_static_http_rollback_verification_does_not_depend_on_backend_health(self):
        root=self.root/'http';(root/'assets').mkdir(parents=True)
        index=b'<script src="/assets/app.js"></script>';asset=b'const app=true;'
        (root/'index.html').write_bytes(index);(root/'assets/app.js').write_bytes(asset)
        manifest={'index.html':patch.sha(index),'assets/app.js':patch.sha(asset)};urls=[]
        headers={name.lower():value for name,value in patch.HEADERS.items()};headers['cache-control']='no-store'
        def request(url,*args):
            urls.append(url)
            if '/app-version.json?' in url:return 200,headers,b'{"version":"old-version"}'
            if url.endswith('/assets/app.js'):return 200,headers,asset
            if '/?gmail_upgrade=' in url:return 200,headers,index
            raise AssertionError('Unexpected backend HTTP during static rollback')
        with mock.patch.object(patch,'request',side_effect=request):patch.public_check(manifest,'old-version',root,verify_services=False)
        self.assertEqual(len(urls),3)


class BuilderTest(unittest.TestCase):
    def setUp(self):
        path=PATH.with_name('build_static_payload.py');spec=importlib.util.spec_from_file_location('static_builder',path)
        self.builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.builder)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.repo=self.root/'repo';dist=self.repo/'app/frontend/dist';dist.mkdir(parents=True)
        css=self.repo/'app/frontend/src/pages/private-workspace.css';css.parent.mkdir(parents=True);css.write_bytes(b'.synthetic{max-width:100%}')
        (dist/'index.html').write_text('<script src="/assets/app.js"></script>');(dist/'app-version.json').write_text(json.dumps({'version':self.builder.VERSION}))
        (dist/'assets').mkdir();(dist/'assets/app.js').write_text('const app=true;')
        self.css=css;self.dist=dist

    def invoke(self,output,dirty=False):
        def git(command,**kwargs):
            if command[1]=='rev-parse':return self.builder.SOURCE+'\n'
            if command[1]=='status':return ' M app/frontend/src/file.ts' if dirty else ''
            if command[1]=='show':return self.css.read_bytes()
            raise AssertionError('Unexpected command')
        with mock.patch.object(self.builder.subprocess,'check_output',side_effect=git),contextlib.redirect_stdout(io.StringIO()):
            self.builder.main(SimpleNamespace(repo=self.repo,output=output))

    def test_builder_is_deterministic_static_only_and_protected(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir();self.invoke(a);self.invoke(b)
        self.assertEqual((a/'static-payload.tar.gz').read_bytes(),(b/'static-payload.tar.gz').read_bytes())
        manifest=json.loads((a/'static-manifest.json').read_text());self.assertIs(manifest['static_only'],True)
        self.assertIs(manifest['backend_changes'],False);self.assertIs(manifest['credentials_included'],False)
        self.assertEqual(stat.S_IMODE((a/'static-payload.tar.gz').stat().st_mode),0o600)
        with tarfile.open(a/'static-payload.tar.gz') as stream:
            self.assertEqual({m.name for m in stream},{'payload/index.html','payload/app-version.json','payload/assets/app.js'})

    def test_builder_rejects_dirty_frontend_and_nonstatic_payload(self):
        output=self.root/'out';output.mkdir()
        with self.assertRaisesRegex(RuntimeError,'TRACKED_FRONTEND_CHANGES_REJECTED'):self.invoke(output,dirty=True)
        (self.dist/'private_credentials.py').write_text('synthetic only')
        with self.assertRaisesRegex(RuntimeError,'NON_STATIC_FILE'):self.invoke(output)
        self.assertFalse((output/'static-payload.tar.gz').exists())

if __name__=='__main__':unittest.main()
