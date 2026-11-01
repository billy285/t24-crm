"""Synthetic additive draft-only release attacks; no provider/server actions."""
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

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

r=load(HERE/'release.py','asset_release_test')
retained=load(ROOT/'deployments/meta-business-20261031/release.py','asset_retained_primitives_test')

@pytest.fixture(autouse=True)
def pins(monkeypatch,request):
    if request.node.name=='test_unfrozen_release_fails_closed':return
    existing={name:'7'*64 for name in r.EXISTING_BACKEND_HASHES}
    values={'SOURCE_SHA':'a'*40,'FRONTEND':'b'*12,'APPLICATION_FREEZE_SHA':'c'*64,'ACTUAL_PREFLIGHT_SHA':'d'*64,'FRONTEND_FILES':frozenset({'app/frontend/src/pages/MediaOperations.tsx'}),'FINAL_BACKEND_HASHES':{name:'e'*64 for name in r.BACKEND_FILES},'EXISTING_BACKEND_HASHES':existing,'ORIGINAL_BACKEND_HASHES':{name:existing.get(name) for name in r.BACKEND_FILES},'NEW_INDEXES':frozenset({'ix_monthly_one','ix_monthly_two'}),'NEW_TABLE_SHAPES':{name:'f'*64 for name in r.NEW_TABLES},'MONTHLY_ROUTES':frozenset({('/api/v1/media-monthly/status','GET')}),'RENDERER_CANARY_SHA':'8'*64}
    for key,value in values.items():monkeypatch.setattr(r,key,value)
    for key in ('SOURCE_SHA','OLD_REVISION','NEW_REVISION','NEW_TABLES','NEW_INDEXES','NEW_TABLE_SHAPES'):monkeypatch.setattr(retained,key,getattr(r,key))


def test_unfrozen_release_fails_closed():
    if any(x is None for x in (r.SOURCE_SHA,r.FRONTEND,r.APPLICATION_FREEZE_SHA,r.ACTUAL_PREFLIGHT_SHA)):
        with pytest.raises(RuntimeError,match='FINAL_.*_REQUIRED'):r.pins_ready()
    else:r.pins_ready()


def test_exact_two_additive_tables_five_new_files_no_env_credentials_or_deps():
    r.pins_ready();assert len(r.BACKEND_FILES)==len(r.NEW_BACKEND_FILES)+len(r.EXISTING_BACKEND_HASHES) and len(r.NEW_BACKEND_FILES)==5 and r.ORIGINAL_BACKEND_HASHES=={name:r.EXISTING_BACKEND_HASHES.get(name) for name in r.BACKEND_FILES}
    assert r.NEW_TABLES=={'google_business_onboarding_catalogs','google_business_onboarding_batches','google_business_onboarding_items','google_business_onboarding_requests'}
    assert r.OLD_REVISION=='f21dc345d681' and r.NEW_REVISION=='g32ed456e792'
    assert r.MIGRATIONS==((r.MIGRATION,r.NEW_REVISION,r.OLD_REVISION),)
    assert 'dependencies_changed' in r.FALSE_FLAGS and 'database_migration' in r.TRUE_FLAGS and 'schema_changed' in r.TRUE_FLAGS


def prepared():
    value={'stage':'GOOGLE_ONBOARDING_PREPARED','source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'schema_revision':r.NEW_REVISION,'old_schema_revision':r.OLD_REVISION,'original_table_count':158,'new_table_count':162,'additive_tables':sorted(r.NEW_TABLES),
        'manifest_sha256':'1'*64,'payload_sha256':'2'*64,'preflight_sha256':r.ACTUAL_PREFLIGHT_SHA,'candidate_image':'sha256:'+'3'*64,
        'nginx_csp_policy_occurrences':6,'runtime_base_image':r.RUNTIME_BASE_IMAGE,'engine_metadata_sha256':r.ENGINE_METADATA_SHA,'retained_renderer_canary_sha256':r.RENDERER_CANARY_SHA,'retained_renderer_result_sha256':'9'*64,'public_root':'/var/www/t24-crm-public/'+r.SCOPE+'-'+r.SOURCE_SHA[:12]+'-20261102',**{k:True for k in r.PREPARED_TRUE},**{k:False for k in r.PREPARED_FALSE}}
    value.update({k:'4'*64 for k in ('schema_after_sha256','original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')});return value


def test_prepared_requires_all_additive_owner_only_no_publicwrite_or_ai_acceptance_gates():
    value=prepared();r.validate_prepared(value,'1'*64,'2'*64,r.ACTUAL_PREFLIGHT_SHA)
    for key in r.PREPARED_TRUE:
        with pytest.raises(RuntimeError):r.validate_prepared({**value,key:False},'1'*64,'2'*64,r.ACTUAL_PREFLIGHT_SHA)
    for key in r.PREPARED_FALSE:
        with pytest.raises(RuntimeError):r.validate_prepared({**value,key:True},'1'*64,'2'*64,r.ACTUAL_PREFLIGHT_SHA)
    for key,val in [('new_table_count',154),('original_table_count',149),('schema_revision',r.OLD_REVISION),('old_schema_revision','wrong'),('additive_tables',[])]:
        with pytest.raises(RuntimeError):r.validate_prepared({**value,key:val},'1'*64,'2'*64,r.ACTUAL_PREFLIGHT_SHA)


def tables():
    row={'columns':[['id','INTEGER']], 'schema':'synthetic schema','indexes':[], 'count':2,'rows_sha256':'a'*64}
    before={f'legacy_{i:03}':copy.deepcopy(row) for i in range(149)}
    before.update({name:{**copy.deepcopy(row),'count':count,'rows_sha256':name+'-polished'} for name,count in [('media_monthly_profiles',1),('media_monthly_runs',1),('media_monthly_items',12)]})
    before.update({name:{**copy.deepcopy(row),'count':1,'rows_sha256':name+'-prepared-private'} for name in ('media_monthly_workflows','media_monthly_workflow_requests')})
    before['alembic_version']={**copy.deepcopy(row),'count':1,'rows_sha256':'oldhead'}
    before.update({name:{**copy.deepcopy(row),'count':count,'rows_sha256':name+'-existing-private'} for name,count in [('media_asset_profiles',1),('media_asset_jobs',2),('media_asset_requests',5)]})
    assert len(before)==158
    after=copy.deepcopy(before);after['alembic_version']['rows_sha256']=r.H(json.dumps([r.NEW_REVISION]).encode())
    after.update({name:{**copy.deepcopy(row),'count':0} for name in r.NEW_TABLES});return before,after


def test_exact_original153_business_rows_unchanged_only_explicit_head_and_empty2_added():
    before,after=tables();retained.compare_original(before,after)
    for name,field,value in [('legacy_001','rows_sha256','bad'),('legacy_001','schema','changed'),('alembic_version','rows_sha256','wrong'),('google_business_onboarding_items','count',1)]:
        bad=copy.deepcopy(after);bad[name][field]=value
        with pytest.raises(RuntimeError):retained.compare_original(before,bad)
    with pytest.raises(RuntimeError):retained.compare_original(before,{**after,'foreign_table':after['legacy_001']})


def test_forward_recovery_preserves_independent_old_and_new_business_rows_without_empty_assumption():
    before,after=tables();after['legacy_001'].update(count=3,rows_sha256='independent-change');after['google_business_onboarding_items'].update(count=2,rows_sha256='new-private-jobs')
    retained.compare_original(before,after,rows=False,empty=False)
    with pytest.raises(RuntimeError):retained.compare_original(before,after)
    after['legacy_002']['columns']=['tampered']
    with pytest.raises(RuntimeError):retained.compare_original(before,after,rows=False,empty=False)


def test_no_schema_objects_may_change_except_exact_two_tables_and_reviewed_indexes():
    before={('table','legacy','legacy'):'oldsql'};after={**before,**{('table',name,name):'newsql' for name in r.NEW_TABLES},**{('index',name,'media_monthly_runs'):'indexsql' for name in r.NEW_INDEXES}}
    retained.additive_objects(before,after)
    for bad in [{**after,('table','legacy','legacy'):'changed'}, {**after,('table','foreign','foreign'):'bad'}, {k:v for k,v in after.items() if k[1]!='ix_monthly_one'}]:
        with pytest.raises(RuntimeError):retained.additive_objects(before,bad)


def test_transactional_migration_source_is_exact_forward_only_and_does_not_restore_sequences_or_pragma():
    retained.MIGRATIONS=r.MIGRATIONS
    source=retained.migration_script();ast.parse(source)
    assert "'BEGIN IMMEDIATE'" in source and 'm.upgrade()' in source and r.MIGRATION in source and r.OLD_REVISION in source and r.NEW_REVISION in source
    assert 'present_after==present' in source and '==sequence' in source and "UPDATE alembic_version" in source
    assert 'downgrade' not in source and 'DROP ' not in source and 'INSERT' not in source and 'DELETE' not in source


def test_candidate_id_is_durable_before_original_stop_and_migration_after_exact_stopped_snapshot():
    source=(HERE/'release.py').read_text();tree=ast.parse(source);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Methods');activate=ast.get_source_segment(source,next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='activate'))
    assert activate.index("self.record('candidate-created.json'")<activate.index("['docker','stop'")<activate.index("self.record('production-before-rows.json'")<activate.index('self.run_migration(')
    assert "self.record('original-runtime.json',m.runtime(old))" in source and 'original-container.json' not in source
    assert 'self.base.migration_script=retained.migration_script' in source
    assert 'self.retained.Release.recover_internal(self,r,old,before,expected)' in source


def test_offline_probes_have_exact_registration_owner_denial_before_sql_and_no_ai_network():
    source=r.Methods.monthly_probe(None);ast.parse(source)
    assert 'iter_route_contexts' in source and "for role in ('admin','ops','sales','finance')" in source
    assert 'NONOWNER_MONTHLY_MUST_NOT_QUERY_DATABASE' in source and 'NO_AI_OR_PUBLIC_PROVIDER_NETWORK' in source
    assert 'sys.version_info[:2]==(3,10)' in source and 'monthly.context(NoDb()' in source
    assert 'call_ai(' not in source and 'generate(' not in source and 'client.post' not in source


def test_fresh_rejects_full_staged_static_drift_before_runtime_or_migration_work():
    seen=[];probe=SimpleNamespace(protections=lambda **kw:seen.append(kw),m=SimpleNamespace(verify_public=lambda *a:'tampered'),public=Path('/synthetic'),manifest={},identities=lambda *a:pytest.fail('runtime work after changed JS'))
    with pytest.raises(RuntimeError,match='STAGED_STATIC_CONTENT_DRIFT'):r.Methods.fresh(probe,prepared(),{},{},{},{})
    assert seen[0]['head']==r.OLD_REVISION


@pytest.mark.parametrize('attack',['foreign','corrupt','duplicate','link'])
def test_payload_refuses_unreviewed_corrupt_duplicate_and_linked_files(tmp_path,attack):
    name='backend/services/google_business_onboarding.py';body=b'synthetic';expected={'files':{name:r.H(body)}};entries=[(name,body)]
    if attack=='foreign':entries.append(('backend/company_finance.py',body))
    if attack=='corrupt':entries=[(name,b'changed')]
    if attack=='duplicate':entries+=entries
    with tarfile.open(tmp_path/'payload.tar.gz','w:gz') as archive:
        for key,data in entries:
            row=tarfile.TarInfo(key);row.size=len(data)
            if attack=='link':row.type=tarfile.SYMTYPE;row.linkname='/etc/passwd'
            archive.addfile(row,io.BytesIO(data) if attack!='link' else None)
    with pytest.raises(RuntimeError):r.extract(tmp_path,expected,SimpleNamespace(mkdir=lambda p:p.mkdir(exist_ok=True),write=lambda p,b:p.write_bytes(b)))


def test_actual_current153_capture_requires_exact_runtime_source_authority_and_focus_hashes():
    value=json.loads((HERE/'preflight.json').read_text())
    # Production proof pin is exact even while final application pins remain unset.
    original=r.ACTUAL_PREFLIGHT_SHA
    r.ACTUAL_PREFLIGHT_SHA=value['sha256']
    try:
        r.validate_summary(value)
        for key,replacement in [('table_count',150),('backend_file_count',398),('source_sha','0'*40),('frontend_version','0'*12),('schema_revision','cefa9b12a358'),('all158_current_tables_preserved',False),('google_scheduler_enabled',False),('google_scheduler_activation_from','2026-11-01T00:00:00Z'),('environment_sha256','0'*64),('ops_environment_sha256','0'*64)]:
            with pytest.raises(RuntimeError):r.validate_summary({**value,key:replacement})
        for key in ('ops_execution_enabled','ops_scheduler_enabled','schema_changed','permissions_changed','credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed'):
            with pytest.raises(RuntimeError):r.validate_summary({**value,key:True})
        with pytest.raises(RuntimeError):r.validate_summary({**value,'crm':{**value['crm'],'id':'0'*64}})
        with pytest.raises(RuntimeError):r.validate_summary({**value,'new_onboarding_worker_env_present':True})
    finally:r.ACTUAL_PREFLIGHT_SHA=original


def test_populated_prior_monthly_items_are_existing_rows_not_new_empty_workflow_rows():
    before,after=tables()
    assert before['media_monthly_items']['count']==12 and before['media_monthly_runs']['count']==1
    assert not {'media_monthly_profiles','media_monthly_runs','media_monthly_items'}.intersection(r.NEW_TABLES)
    bad=copy.deepcopy(after);bad['media_monthly_items'].update(count=0,rows_sha256='lost polished copy')
    with pytest.raises(RuntimeError,match='ORIGINAL_BUSINESS_ROWS_CHANGED'):retained.compare_original(before,bad)
