"""Synthetic staging quarantine and aggregate-only diagnostics; no live actions."""
import copy
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('meta_ops_stale_quarantine_test', HERE/'quarantine_stale_prepare.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)


def proof():
    return {'stage':'META_OPERATIONS_READONLY_PREFLIGHT','host':q.HOST,'source_sha':q.SOURCE,'frontend_version':q.FRONTEND,'schema_revision':q.REVISION,
        'rows':{f'table_{i:03}':{'count':i,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for i in range(141)},'database_metadata':{'aggregate_only':1},'schema_sha256':'c'*64,
        'crm':{'id':'d'*64,'image':'sha256:'+'e'*64,'started':'2026-10-31T19:34:06Z','restart':0,'config':'f'*64},
        'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False,'meta_operations_environment_absent':True}


def changed_proof():
    old=proof();new=copy.deepcopy(old);new['database_metadata']={'aggregate_only':2};new['rows']['table_002']['count']=3;new['rows']['table_002']['rows_sha256']='9'*64;new['rows']['table_003']['rows_sha256']='8'*64
    return old,new


@pytest.fixture
def staging(tmp_path,monkeypatch):
    root=tmp_path.resolve()/'releases';root.mkdir(mode=0o700);source=root/q.NAME;source.mkdir(mode=0o700);blobs={name:('SYNTHETIC '+name).encode() for name in q.PINS}
    pins={name:(q.H(body),len(body)) for name,body in blobs.items()}
    for name,body in blobs.items():path=source/name;path.write_bytes(body);path.chmod(0o600)
    (root/q.LOCK).write_bytes(b'');(root/q.LOCK).chmod(0o600)
    monkeypatch.setattr(q,'ROOT',root);monkeypatch.setattr(q,'OWNER_UID',os.geteuid());monkeypatch.setattr(q,'PINS',pins);monkeypatch.setattr(q,'ARCHIVED',False);monkeypatch.setattr(q,'protected_parents',lambda:None)
    old,new=changed_proof();calls=[];runtime={**{key:new['crm'][key] for key in ('id','image','started','restart')},'running':True}
    context=SimpleNamespace(inventory={'main.py':'synthetic-source-sha'},m=SimpleNamespace(BUSINESS=root/'never-opened.db',inventory=lambda _:{'main.py':'synthetic-source-sha'},schema_signature=lambda *_:new['schema_sha256']))
    monkeypatch.setattr(q,'context_from_frozen_preflight',lambda body:(context,new,q.aggregate_changes(old,new)))
    monkeypatch.setattr(q,'current_runtime',lambda p:copy.deepcopy(runtime));monkeypatch.setattr(q,'no_started_prepare',lambda:calls.append('metadata-only-no-prepare'))
    def rename(parent_fd):
        calls.append('atomic-noreplace')
        if not q.absent(q.ARCHIVE,parent_fd):raise RuntimeError('FRESH_QUARANTINE_TARGET_REQUIRED')
        os.rename(q.NAME,q.ARCHIVE,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
    monkeypatch.setattr(q,'rename_noreplace',rename)
    return SimpleNamespace(root=root,source=source,target=root/q.ARCHIVE,blobs=blobs,proof=new,calls=calls,context=context,runtime=runtime)


def test_quarantine_preserves_exact_four_files_and_exports_only_changed_names_counts(staging):
    before=staging.source.stat();result=q.quarantine()
    assert not staging.source.exists() and staging.target.stat().st_ino==before.st_ino and q.ARCHIVED is True
    assert {p.name:p.read_bytes() for p in staging.target.iterdir()}==staging.blobs
    assert result['changed_tables']==[{'table':'table_002','before_count':2,'after_count':3},{'table':'table_003','before_count':3,'after_count':3}]
    assert result['files_preserved']==4 and result['raw_business_rows_read'] is False and result['credential_values_read'] is False
    assert result['business_writes'] is False and result['database_migrated'] is False and result['preflight_captured_or_approved'] is False
    assert staging.calls==['metadata-only-no-prepare','atomic-noreplace']
    encoded=json.dumps(result);assert 'rows_sha256' not in encoded and 'shape_sha256' not in encoded and 'crm' not in encoded
    assert not (staging.root/'never-opened.db').exists()


@pytest.mark.parametrize('attack',['extra_file','extra_directory','changed_bytes','file_mode','source_mode','member_symlink','member_hardlink','target_exists','target_symlink'])
def test_any_nonexact_or_previously_used_staging_is_rejected_before_rename(staging,attack):
    source=staging.source;member=source/'manifest.json'
    if attack=='extra_file':(source/'prepared.json').write_text('{}')
    if attack=='extra_directory':(source/'backend').mkdir()
    if attack=='changed_bytes':member.write_bytes(b'X'*len(staging.blobs['manifest.json']))
    if attack=='file_mode':member.chmod(0o644)
    if attack=='source_mode':source.chmod(0o755)
    if attack=='member_symlink':member.unlink();member.symlink_to(source/'release.py')
    if attack=='member_hardlink':os.link(member,staging.root/'extra-hardlink')
    if attack=='target_exists':staging.target.mkdir()
    if attack=='target_symlink':staging.target.symlink_to(staging.root/'nonexistent')
    with pytest.raises((RuntimeError,OSError)):q.quarantine()
    assert staging.source.exists() and 'atomic-noreplace' not in staging.calls and q.ARCHIVED is False


def test_target_collision_at_rename_never_overwrites_existing_archive(staging,monkeypatch):
    def collision(_):
        staging.target.mkdir();(staging.target/'marker').write_text('preserved');raise RuntimeError('FRESH_QUARANTINE_TARGET_REQUIRED')
    monkeypatch.setattr(q,'rename_noreplace',collision)
    with pytest.raises(RuntimeError,match='FRESH_QUARANTINE_TARGET_REQUIRED'):q.quarantine()
    assert staging.source.exists() and (staging.target/'marker').read_text()=='preserved' and q.ARCHIVED is False


def test_concurrent_member_change_fails_before_quarantine(staging,monkeypatch):
    def changed(context,proof):
        (staging.source/'manifest.json').write_bytes(b'Z'*len(staging.blobs['manifest.json']));return staging.runtime
    monkeypatch.setattr(q,'original_boundary',changed)
    with pytest.raises(RuntimeError,match='EXACT_STAGING_MEMBER_HASH_SIZE_REQUIRED'):q.quarantine()
    assert staging.source.exists() and not staging.target.exists() and q.ARCHIVED is False


def test_wrong_source_or_schema_never_archives(staging,monkeypatch):
    monkeypatch.setattr(staging.context.m,'schema_signature',lambda *_:'0'*64)
    with pytest.raises(RuntimeError,match='EXACT_ORIGINAL_SCHEMA_REQUIRED'):q.quarantine()
    assert staging.source.exists() and 'atomic-noreplace' not in staging.calls


@pytest.mark.parametrize('attack',['source','count','raw_value','shape','environment','no_drift','extra_table'])
def test_frozen_proof_diagnostics_refuse_nonaggregate_or_nonrow_changes(attack):
    old,new=changed_proof()
    if attack=='source':new['source_sha']='0'*40
    if attack=='count':new['rows']['table_002']['count']=True
    if attack=='raw_value':new['rows']['table_002']['customer_name']='NEVER_EXPORT'
    if attack=='shape':new['rows']['table_002']['shape_sha256']='0'*64
    if attack=='environment':new['environment_sha256']='changed'
    if attack=='no_drift':new=copy.deepcopy(old)
    if attack=='extra_table':new['rows']['meta_operations_drafts']=new['rows'].pop('table_140')
    with pytest.raises(RuntimeError):q.aggregate_changes(old,new)


def test_actual_linux_rename_primitive_requires_noreplace_flag_and_rejects_collision(monkeypatch):
    calls=[]
    class Function:
        def __call__(self,*args):calls.append(args);return 0
    function=Function();monkeypatch.setattr(q.sys,'platform','linux');monkeypatch.setattr(q.ctypes,'CDLL',lambda *a,**k:SimpleNamespace(renameat2=function))
    q.rename_noreplace(99)
    assert calls==[(99,os.fsencode(q.NAME),99,os.fsencode(q.ARCHIVE),1)]
    function.__class__.__call__=lambda self,*a:-1;monkeypatch.setattr(q.ctypes,'get_errno',lambda:errno.EEXIST)
    with pytest.raises(RuntimeError,match='FRESH_QUARANTINE_TARGET_REQUIRED'):q.rename_noreplace(99)


def test_no_fallback_to_overwriting_rename_when_atomic_primitive_unavailable(monkeypatch):
    monkeypatch.setattr(q.sys,'platform','linux');monkeypatch.setattr(q.ctypes,'CDLL',lambda *a,**k:SimpleNamespace())
    with pytest.raises(RuntimeError,match='ATOMIC_RENAME_NOREPLACE_UNAVAILABLE'):q.rename_noreplace(99)


def test_runtime_inspection_requests_only_filtered_local_docker_metadata(monkeypatch):
    calls=[];old=proof();runtime={**{key:old['crm'][key] for key in ('id','image','started','restart')},'running':True}
    def run(argv,**kwargs):calls.append((argv,kwargs));return SimpleNamespace(returncode=0,stdout=json.dumps(runtime).encode())
    monkeypatch.setattr(q.subprocess,'run',run)
    assert q.current_runtime(old)==runtime
    argv,kwargs=calls[0];assert argv[:3]==['docker','--host','unix:///var/run/docker.sock'];assert argv[-1]=='t24-crm' and '--format' in argv
    assert 'Config' not in ' '.join(argv) and 'Env' not in ' '.join(argv) and 'logs' not in argv
    assert set(kwargs['env'])=={'PATH','LANG','LC_ALL'} and kwargs['stdin'] is subprocess.DEVNULL


@pytest.mark.parametrize('kind',['container','image'])
def test_started_prepare_metadata_is_never_ignored(monkeypatch,kind):
    def metadata(*args):
        if args[0]=='container':return b't24-crm-candidate-meta-operations-95588aa2e630\n' if kind=='container' else b't24-crm\n'
        return b't24-crm:meta-operations-95588aa2e630\n'
    monkeypatch.setattr(q,'docker_metadata',metadata)
    with pytest.raises(RuntimeError,match='PREPARE_.*EVIDENCE_REQUIRES_SEPARATE_REVIEW'):q.no_started_prepare()


def test_exact_old_carrier_four_file_pins_do_not_follow_repacked_local_files():
    mapping={'manifest.json':'artifacts/manifest.json','payload.tar.gz':'artifacts/payload.tar.gz'}
    for name,(sha,size) in q.PINS.items():
        data=subprocess.check_output(['git','show','05eaebcd0c282c34c8ca88647be712cae00bdbc5:deployments/meta-operations-20261101/'+mapping.get(name,name)])
        assert len(data)==size and hashlib.sha256(data).hexdigest()==sha


def test_staging_directory_replacement_is_not_followed(staging,monkeypatch):
    def swapped(context,proof):
        staging.source.rename(staging.root/'held-original');staging.source.mkdir(mode=0o700)
        for name,body in staging.blobs.items():path=staging.source/name;path.write_bytes(body);path.chmod(0o600)
        return staging.runtime
    monkeypatch.setattr(q,'original_boundary',swapped)
    with pytest.raises(RuntimeError,match='STAGING_CHANGED_DURING_REVIEW'):q.quarantine()
    assert staging.source.exists() and not staging.target.exists() and q.ARCHIVED is False


def test_frozen_context_reads_only_the_two_pinned_aggregate_proofs(monkeypatch):
    old,new=changed_proof();calls=[];context=SimpleNamespace(legacy_baseline=SimpleNamespace(protected_sample=lambda *_:pytest.fail('Do not hash live business row values')))
    def read(path,*,sha):
        calls.append((path,sha));assert path==q.ROOT/('meta-operations-preflight-'+sha[:12]+'.json')
        assert sha in {q.OLD_PROOF_SHA,q.NEW_PROOF_SHA};return json.dumps(old if sha==q.OLD_PROOF_SHA else new).encode()
    core=SimpleNamespace(read=read,strict_json=json.loads)
    monkeypatch.setattr(q,'ModuleType',lambda _:SimpleNamespace(dependencies=lambda:(core,None,context)))
    actual,proof_value,changes=q.context_from_frozen_preflight(b'pass\n')
    assert actual is context and proof_value==new and len(changes)==2 and [sha for _,sha in calls]==[q.OLD_PROOF_SHA,q.NEW_PROOF_SHA]


def test_quarantine_wrapper_reproduces_the_pinned_helper_and_only_runs_on_known_root_host():
    import ast,base64,sys,zlib
    generator_spec=importlib.util.spec_from_file_location('meta_ops_quarantine_generator_test',HERE/'make_quarantine_command.py')
    generator=importlib.util.module_from_spec(generator_spec);generator_spec.loader.exec_module(generator)
    body=(HERE/'quarantine_stale_prepare.py').read_bytes();command,pins=generator.generate(body);again,again_pins=generator.generate(body)
    assert command==again and pins==again_pins and pins['executed'] is False and pins['command_bytes']<11000
    embedded=command.split("<<'QUARANTINE'\n",1)[1].rsplit('\nQUARANTINE\n',1)[0];tree=ast.parse(embedded)
    packed=next(node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='b64decode')
    assert zlib.decompress(base64.b64decode(packed,validate=True))==body and pins['helper_sha256']==q.H(body)
    if os.geteuid()!=0 or q.socket.gethostname()!=q.HOST:
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',embedded],capture_output=True,text=True,timeout=10)
        assert result.returncode==1 and json.loads(result.stdout)=={'stage':'META_OPERATIONS_QUARANTINE_REJECTED','code':'EXACT_ROOT_SERVER_REQUIRED','archive_completed':False}
        assert result.stderr==''
