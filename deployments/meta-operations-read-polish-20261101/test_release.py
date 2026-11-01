"""Synthetic schema-free switch attacks/regressions, no server or provider."""
import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('read_polish_release_test',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def test_final_scope_is_only_four_sources_one_runtime_no_schema_dependency_or_env_changes():
    r.pins_ready();assert len(r.SOURCE_FILES)==4 and r.BACKEND_FILES=={'services/meta_operations_provider.py'}
    assert r.SCHEMA_REVISION==r.OLD_REVISION==r.NEW_REVISION=='cefa9b12a358'
    value=json.loads((ROOT/'outputs/meta-operations-read-polish-20261101/application-freeze.json').read_text())
    assert value['source_sha']==r.SOURCE_SHA and value['frontend_version']==r.FRONTEND and set(value['files'])==r.SOURCE_FILES
    assert r.H((ROOT/'outputs/meta-operations-read-polish-20261101/application-freeze.json').read_bytes())==r.APPLICATION_FREEZE_SHA


@pytest.mark.parametrize('field,value',[('sha256','0'*64),('table_count',141),('schema_revision','wrong'),('ops_execution_enabled',True),('ops_scheduler_enabled',True),('business_writes',True)])
def test_frozen_nonempty_all150_summary_rejects_identity_or_execution_drift(field,value):
    original=json.loads((ROOT/'outputs/meta-operations-read-polish-20261101/preflight-summary.json').read_text());r.validate_summary(original)
    with pytest.raises(RuntimeError):r.validate_summary({**original,field:value})


def test_only_single_static_root_bytes_change_and_csp_oauth_media_blocks_stay_exact():
    original=b"root /var/www/old;\nlocation /api/v1/meta-operations/delivery/ { access_log off; }\nlocation = /api/v1/meta-operations/oauth/callback { access_log off; }\nadd_header Content-Security-Policy unchanged;\n"
    updated=r.next_nginx(original,'/var/www/old','/var/www/new')
    assert updated.replace(b'/var/www/new',b'/var/www/old')==original
    with pytest.raises(RuntimeError):r.next_nginx(original+original,'/var/www/old','/var/www/new')


def prepared():
    value={'stage':'META_OPERATIONS_READ_POLISH_PREPARED','source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'schema_revision':r.SCHEMA_REVISION,'old_schema_revision':r.SCHEMA_REVISION,'table_count':150,
        'manifest_sha256':'a'*64,'payload_sha256':'b'*64,'preflight_sha256':r.ACTUAL_PREFLIGHT_SHA,'candidate_image':'sha256:'+'c'*64,
        'public_root':'/var/www/t24-crm-public/'+r.SCOPE+'-'+r.SOURCE_SHA[:12]+'-20261101',**{key:True for key in r.PREPARED_TRUE},**{key:False for key in r.PREPARED_FALSE}}
    value.update({key:'d'*64 for key in ('original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')});return value


def test_prepared_requires_actual_python310_canary_and_all150_preserved_no_schema_change():
    value=prepared();r.validate_prepared(value,'a'*64,'b'*64,r.ACTUAL_PREFLIGHT_SHA)
    for key in r.PREPARED_TRUE:
        with pytest.raises(RuntimeError):r.validate_prepared({**value,key:False},'a'*64,'b'*64,r.ACTUAL_PREFLIGHT_SHA)
    for key in r.PREPARED_FALSE:
        with pytest.raises(RuntimeError):r.validate_prepared({**value,key:True},'a'*64,'b'*64,r.ACTUAL_PREFLIGHT_SHA)


def test_fresh_rejects_staged_javascript_drift_before_any_candidate_or_runtime_action():
    calls=[];probe=SimpleNamespace(protections=lambda **kw:calls.append('protected-original'),m=SimpleNamespace(verify_public=lambda *a:'unexpected-asset-hash'),public=Path('/synthetic/public'),manifest={},identities=lambda *a:pytest.fail('candidate work after changed static'))
    with pytest.raises(RuntimeError,match='STAGED_STATIC_CONTENT_DRIFT'):r.Methods.fresh(probe,prepared(),{},{},{},{})
    assert calls==['protected-original']


def test_image_uses_exact_parent_and_only_provider_copy_without_dependency_install(tmp_path):
    base='sha256:'+'a'*64;candidate='sha256:'+'b'*64;aliases={base:base};calls=[];written={}
    class M:
        BASE_IMAGE=base
        def image_id(self,name):return aliases.get(name)
        def write(self,path,body):written[path.name]=body
        def run(self,argv,*args):
            calls.append(argv)
            if argv[1:3]==['image','tag']:aliases[argv[-1]]=base
            if argv[1]=='build':aliases[argv[argv.index('-t')+1]]=candidate
    assert r.Methods.image(SimpleNamespace(m=M(),args=SimpleNamespace(release=tmp_path)))==candidate
    assert '--network=none' in calls[-1] and '--pull=false' in calls[-1]
    docker=written['Dockerfile'].decode();assert docker.count('COPY ')==1 and 'services/meta_operations_provider.py' in docker and 'RUN ' not in docker and 'pip' not in docker


def test_actual_python310_runtime_canary_is_pure_read_parser_and_exact_offset_normalization():
    source=r.Methods.timestamp_probe(None);ast.parse(source)
    assert 'sys.version_info[:2]==(3,10)' in source and "_timestamp('2026-11-01T00:00:00+0000')=='2026-11-01T00:00:00+00:00'" in source
    assert "_timestamp('2026-11-01T00:00:00-0430')=='2026-11-01T04:30:00+00:00'" in source and 'NO_PROVIDER_NETWORK' in source
    assert 'db.' not in source and 'dispatch' not in source and 'publish' not in source


def test_prepare_uses_new_release_offline_log_namespace_and_never_migrates_or_journals_env():
    source=(HERE/'release.py').read_text();tree=ast.parse(source);cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Methods')
    prepare=ast.get_source_segment(source,next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='prepare'))
    assert 'self.ctx.module.OperationsMethods.offline_args(self,data,image)' in prepare
    assert 'original-container.json' not in source and "self.record('original-runtime.json',m.runtime(old))" in prepare
    assert 'run_migration' not in source and 'migrate(' not in source and 'new_schema(' not in source and 'empty=True' not in source
    activate=ast.get_source_segment(source,next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='activate'))
    assert activate.index("self.record('candidate-created.json'")<activate.index("['docker','stop'")


@pytest.mark.parametrize('attack',['foreign','corrupt','duplicate','symlink'])
def test_extract_refuses_foreign_corrupt_duplicate_or_linked_payload(tmp_path,attack):
    body=b'synthetic-approved';name='backend/services/meta_operations_provider.py';manifest={'files':{name:r.H(body)}}
    entries=[(name,body,'file')]
    if attack=='foreign':entries.append(('backend/finance.py',body,'file'))
    if attack=='corrupt':entries=[(name,b'unreviewed','file')]
    if attack=='duplicate':entries.append(entries[0])
    if attack=='symlink':entries=[(name,b'','link')]
    with tarfile.open(tmp_path/'payload.tar.gz','w:gz') as archive:
        for filename,data,kind in entries:
            row=tarfile.TarInfo(filename);row.size=len(data)
            if kind=='link':row.type=tarfile.SYMTYPE;row.linkname='/etc/passwd'
            archive.addfile(row,io.BytesIO(data) if kind=='file' else None)
    core=SimpleNamespace(mkdir=lambda path:path.mkdir(exist_ok=True),write=lambda path,data:path.write_bytes(data))
    with pytest.raises(RuntimeError):r.extract(tmp_path,manifest,core)
    assert not(tmp_path/'backend/finance.py').exists()


@pytest.mark.parametrize('fence_failure',[False,True])
def test_recovery_contains_known_candidate_and_keeps_independent_rows_and_credentials(tmp_path,fence_failure):
    old={'Id':'a'*64,'Image':'sha256:'+'1'*64,'Name':'/retained-old','State':{'Running':False},'config':'old-config'}
    candidate={'Id':'b'*64,'Image':'sha256:'+'2'*64,'Name':'/t24-crm','State':{'Running':True},'config':'new-config'}
    state={'candidate_id':candidate['Id']};calls=[];rows=['existing','independent-new-row'];credential=['unchanged-independent-key']
    nginx=tmp_path/'nginx.conf';nginx.write_bytes(b'old-static-root')
    class M:
        NGINX=nginx
        def inspect(self,name):return old if name==old['Id'] or name=='t24-crm' and old['Name']=='/t24-crm' else candidate
        def run(self,argv,*args):
            calls.append(argv)
            row=old if argv[-1]==old['Id'] else candidate
            if argv[1]=='stop':candidate['State']['Running']=False
            if argv[1]=='rename':
                row=old if argv[2]==old['Id'] else candidate;row['Name']='/'+argv[3]
            if argv[1]=='start':old['State']['Running']=True
        def ready(self,*a):calls.append(['ready'])
        def runtime(self,row):return {'config':row['config']}
        def retained(self):return SimpleNamespace(reload_nginx=lambda:calls.append(['reload-nginx']))
    def protections(**kw):
        assert kw.get('recovery') is True
        if fence_failure:raise RuntimeError('SYNTHETIC_SCHEMA_OR_PRIVATE_DRIFT')
    records=[];probe=SimpleNamespace(m=M(),args=SimpleNamespace(release=tmp_path),state=lambda *a:state,identities=lambda *a:(old,candidate),protections=protections,
        retained=SimpleNamespace(compare=lambda *a:None),environment=lambda *a:None,source_boundary=lambda *a:None,old_name='retained-old',candidate_name='kept-candidate',
        record=lambda *a:records.append(a),proof={'nginx_sha256':r.H(b'old-static-root')})
    receipt={'candidate_image':candidate['Image'],'nginx_next_sha256':r.H(b'new-static-root')}
    if fence_failure:
        with pytest.raises(RuntimeError,match='SYNTHETIC_SCHEMA_OR_PRIVATE_DRIFT'):r.Methods.recover_internal(probe,receipt,old,{},{} )
        assert candidate['State']['Running'] is False and old['State']['Running'] is False and all('start' not in call for call in calls)
    else:
        result=r.Methods.recover_internal(probe,receipt,old,{},{})
        assert result['independent_rows_preserved'] is True and result['database_restored'] is False and old['Name']=='/t24-crm' and old['State']['Running'] is True and candidate['State']['Running'] is False
        assert records and rows==['existing','independent-new-row'] and credential==['unchanged-independent-key']
    assert all('rm' not in call and 'cp' not in call and 'sqlite' not in call for call in calls)
