"""Synthetic exact194 offline resume checks; no Docker or server requests."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType,SimpleNamespace
import zlib
import pytest

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


r=load('synthetic_asset_toolchain_resume',HERE/'resume_toolchain.py')
maker=load('synthetic_asset_toolchain_resume_maker',HERE/'make_resume_toolchain.py')
retry=load('synthetic_asset_toolchain_exact194',HERE/'toolchain_retry.py')
original=(HERE/'toolchain.py').read_bytes();variant=retry.derive_variant(original)
tool=ModuleType('synthetic_frozen8c_toolchain');exec(compile(variant,'<frozen8c>','exec'),tool.__dict__)


def test_all_frozen_sources_match_prior_reviewed_bytes():
    assert r.H(original)==r.ORIGINAL_SHA and r.H(variant)==r.OLD_SHA and len(variant)==25883
    assert r.H((HERE/'diagnose_toolchain_build.py').read_bytes())==r.DIAGNOSTIC_SHA
    assert r.H((HERE/'preflight.py').read_bytes())==r.PREFLIGHT_SHA
    assert r.H((HERE/'toolchain-command.sh').read_bytes())==r.COMMAND_SHA
    assert r.recover_preflight((HERE/'toolchain-command.sh').read_bytes(),original)==(HERE/'preflight.py').read_bytes()


def test_recovery_reads_data_only_and_rejects_tampered_carrier_or_source():
    command=(HERE/'toolchain-command.sh').read_bytes()
    with pytest.raises(RuntimeError):r.recover_preflight(command+b'x',original)
    with pytest.raises(RuntimeError):r.recover_preflight(command,original+b'x')


def test_installer_changes_only_two_trusted_sbin_path_segments():
    updated=r.installer(tool).decode()
    assert updated.replace(r.NEW_PATH,r.OLD_PATH,1)==tool.INSTALL
    assert r.NEW_PATH in updated and updated.count('/usr/sbin:/sbin')==1
    assert all(flag in updated for flag in ('--no-download','--no-remove','--no-upgrade','--no-install-recommends'))
    assert tool.INSTALL.count(r.OLD_PATH)==1


def test_unexpected_installer_shape_rejected():
    with pytest.raises(RuntimeError):r.installer(SimpleNamespace(INSTALL=tool.INSTALL.replace(r.OLD_PATH,'PATH_DRIFT')))
    with pytest.raises(RuntimeError):r.installer(SimpleNamespace(INSTALL=tool.INSTALL+'\n'+r.OLD_PATH))


def test_dockerfile_uses_exact_local_base_and_only_new_context_install():
    value=r.dockerfile().decode();assert value.startswith('FROM '+r.IMAGE+'\n')
    assert value.count('FROM ')==1 and 'apt-get' not in value and 'curl' not in value
    assert value.count('RUN ')==1 and '/usr/local/bin/python -I -B /tmp/t24-render-deps/install.py' in value


def test_probe_uses_unchanged_script_clean_env_readonly_root_networknone_tmpfs_only():
    argv=r.probe_command('fresh','sha256:'+'a'*64,tool.PROBE)
    assert argv[argv.index('--network')+1]=='none' and '--read-only' in argv
    assert argv[argv.index('--entrypoint')+1]=='/usr/bin/env' and '-i' in argv
    assert argv[-1]==tool.PROBE and '--mount' not in argv and '-v' not in argv
    assert 'PATH=/usr/local/bin:/usr/bin:/bin' in argv and 'DOCKER_BUILDKIT=0' not in argv
    assert argv[argv.index('--tmpfs')+1]=='/tmp:rw,noexec,nosuid,size=67108864'


def probe():
    return {'python_pillow':'12.3.0','freetype2':True,'cjk_and_latin_glyphs_verified':True,'no_business_data_credentials_or_provider_requests':True,'actual_h264_mp4':{'codec_name':'h264','width':32,'height':32,'pix_fmt':'yuv420p','sha256':'d'*64,'bytes':2048},'backend_file_count':408,'backend_inventory_sha256':'e'*64}


def info(image):
    return {'State':{'Running':False,'ExitCode':0},'Image':image,'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True},'Mounts':[{'Type':'tmpfs','Destination':'/tmp'}]}


@pytest.mark.parametrize('tamper',['backend','video','network','bind','running','readonly'])
def test_engine_probe_must_prove_actual_h264_cjk_408_and_isolation(tamper):
    value=probe();metadata=info(r.IMAGE)
    if tamper=='backend':value['backend_file_count']=407
    elif tamper=='video':value['actual_h264_mp4']['codec_name']='fake'
    elif tamper=='network':metadata['HostConfig']['NetworkMode']='bridge'
    elif tamper=='bind':metadata['Mounts'].append({'Type':'bind','Destination':'/app/data'})
    elif tamper=='running':metadata['State']['Running']=True
    else:metadata['HostConfig']['ReadonlyRootfs']=False
    with pytest.raises(RuntimeError):r.validate_probe(value,metadata,r.IMAGE,{'backend_inventory_sha256':'e'*64})


def test_engine_probe_exact_success():
    r.validate_probe(probe(),info(r.IMAGE),r.IMAGE,{'backend_inventory_sha256':'e'*64})


def harness(tmp_path,monkeypatch,build_ok=True,probe_ok=True,known=True):
    root=tmp_path.resolve();old=root/'old';old.mkdir();(old/'fetch-data').mkdir();(old/'build/packages').mkdir(parents=True)
    monkeypatch.setattr(r,'ROOT',root);monkeypatch.setattr(r,'OLD',old)
    blob=b'SYNTHETIC PUBLIC DEB';sha=r.H(blob)
    packages={f'synthetic{i}':{'file':f'synthetic{i}.deb','bytes':len(blob),'sha256':sha} for i in range(194)}
    manifest={'packages':packages,'base_packages':{'base':{'version':'unchanged'}},'total_download_bytes':194*len(blob),'estimated_installed_bytes':194*1024}
    body=r.ENCODE(manifest);(old/'fetch-data/packages.json').write_bytes(body)
    for row in packages.values():(old/'build/packages'/row['file']).write_bytes(blob)
    state={'built':False,'calls':[],'old_reads':0,'baseline':0};new_image='sha256:'+'f'*64
    proof={'database_metadata':{'synthetic':True},'backend_inventory_sha256':'e'*64,'render_capacity':{'synthetic':True}}
    observed={key:value for key,value in proof.items() if key!='render_capacity'}
    def sample():state['baseline']+=1;return observed
    c=SimpleNamespace(strict_json=json.loads,read=lambda *a,**k:r.ENCODE(proof))
    m=SimpleNamespace(inspect_optional=lambda _:None,inspect=lambda _:info(new_image))
    flow=SimpleNamespace(c=c,m=m,retained=SimpleNamespace(live_sequence_boundary=lambda *a:None))
    pf=SimpleNamespace(dependencies=lambda:(None,flow,None),sample=sample,RUNTIME={'image':r.IMAGE},SOURCE='d39337fccfd622e506ca3c1a655a126f5218dc42',FRONTEND='8113d14d204f',digest=lambda value:r.H(r.ENCODE(value)))
    def write(path,body):
        assert not path.exists();path.write_bytes(body);path.chmod(0o600)
    def read(path,maximum=1048576,sha=None):
        body=path.read_bytes();assert len(body)<=maximum
        if sha is not None:assert r.H(body)==sha
        return body
    def hash_package(path,sha,size):assert len(path.read_bytes())==size and r.H(path.read_bytes())==sha
    def old_context(_):
        state['old_reads']+=1;return {'approved_proposal_sha256':r.APPROVED_SHA,'package_count':194,'packages_manifest_sha256':r.H(body)}
    def image_id(tag):return r.IMAGE if tag==r.IMAGE else new_image if state['built'] else None
    def capture(argv,path,**kwargs):
        state['calls'].append(argv)
        if argv[1]=='build':
            assert d.ENV['DOCKER_BUILDKIT']=='0';state['built']=build_ok;data=b'SYNTHETIC OFFLINE BUILD';success=build_ok;result_known=known
        else:data=json.dumps(probe()).encode();success=probe_ok;result_known=True
        write(path,data)
        return {'exit_code':0 if success else 8,'build_daemon_result_known':result_known,'log_sha256':r.H(data),'log_bytes':len(data),'client_status':'BUILD_CLIENT_FINISHED','public_tail':data.decode()[-8192:]}
    def build_command(context):return ['docker','build','--network=none','--pull=false','--memory','768m','--cpu-period','100000','--cpu-quota','100000','-t',d.TAG,str(context)]
    d=SimpleNamespace(ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},runtime=lambda:{'running':True},validate_context=old_context,image_id=image_id,secure=lambda _:None,write_private=write,read_private=read,hash_package=hash_package,capture_build=capture,build_command=build_command)
    fake_tool=SimpleNamespace(INSTALL=tool.INSTALL,PROBE=tool.PROBE,TOP=tool.TOP,copy_public_package=lambda source,target,sha,size:(hash_package(source,sha,size),write(target,source.read_bytes())))
    monkeypatch.setattr(r.os,'statvfs',lambda _:SimpleNamespace(f_frsize=4096,f_bavail=2000000))
    return pf,fake_tool,d,state,root


def test_full_success_is_fresh_no_download_and_canonical_receipt_preserves_all_boundaries(tmp_path,monkeypatch):
    pf,t,d,state,root=harness(tmp_path,monkeypatch);result=r.perform(pf,t,d,b'SYNTHETIC REVIEWED RESUME SOURCE')
    assert result['stage']=='MEDIA_ASSET_STUDIO_TOOLCHAIN_PREPARED' and result['added_package_count']==194
    assert state['baseline']==3 and state['old_reads']==3
    assert len(state['calls'])==2 and state['calls'][0][1]=='build' and state['calls'][1][1]=='run'
    assert result['tool_sha256']==r.H(b'SYNTHETIC REVIEWED RESUME SOURCE') and result['base_toolchain_sha256']==r.OLD_SHA
    for key in ('all155_current_rows_and_private_packet_preserved','all408_backend_files_unchanged','no_existing_package_upgraded_or_removed','fetch_only_official_signed_debian','install_and_engine_probe_network_none','legacy_builder_enabled','trusted_install_path_sbin_added','original_context_unchanged'):assert result[key] is True
    for key in ('production_or_host_installation','production_container_changed','credentials_or_business_data_mounted','api_or_worker_started','official_debian_package_network_fetch_performed','social_ai_or_payment_provider_requests','publications_performed'):assert result[key] is False
    path=Path(result['receipt_path']);assert path.parent.parent==root and path.name=='toolchain-prepared.json'
    assert r.H(path.read_bytes())==result['receipt_sha256'] and json.loads(path.read_bytes())=={key:value for key,value in result.items() if key not in {'receipt_path','receipt_sha256'}}


@pytest.mark.parametrize('known',[True,False])
def test_failed_or_unknown_build_never_claims_prepared_or_runs_probe(tmp_path,monkeypatch,known):
    pf,t,d,state,_=harness(tmp_path,monkeypatch,build_ok=False,known=known);result=r.perform(pf,t,d,b'SYNTHETIC FAILED SOURCE')
    assert result['stage']=='MEDIA_ASSET_STUDIO_TOOLCHAIN_RESUME_BUILD_NOT_CONFIRMED' and len(state['calls'])==1
    assert Path(result['public_build_log_path']).exists() and not (Path(result['receipt_path']).parent/'toolchain-prepared.json').exists()


def test_failed_probe_never_claims_prepared_and_persists_actual_error_log(tmp_path,monkeypatch):
    pf,t,d,state,_=harness(tmp_path,monkeypatch,probe_ok=False);result=r.perform(pf,t,d,b'SYNTHETIC FAILED PROBE SOURCE')
    assert result['stage']=='MEDIA_ASSET_STUDIO_TOOLCHAIN_RESUME_PROBE_NOT_CONFIRMED' and len(state['calls'])==2
    assert Path(result['public_probe_log_path']).exists() and not (Path(result['receipt_path']).parent/'toolchain-prepared.json').exists()


def test_known_candidate_tag_blocks_before_any_build_or_scope_write(tmp_path,monkeypatch):
    pf,t,d,state,root=harness(tmp_path,monkeypatch);state['built']=True
    with pytest.raises(RuntimeError,match='FRESH_RESUME_CONTEXT_IMAGE_AND_PROBE_REQUIRED'):r.perform(pf,t,d,b'SYNTHETIC EXISTING IMAGE SOURCE')
    assert state['calls']==[] and len(list(root.iterdir()))==1


def test_current155_drift_blocks_before_build(tmp_path,monkeypatch):
    pf,t,d,state,_=harness(tmp_path,monkeypatch);pf.sample=lambda:{'database_metadata':{},'backend_inventory_sha256':'WRONG'}
    with pytest.raises(RuntimeError,match='EXACT_CURRENT155_AND_PRIVATE_PACKET_REQUIRED'):r.perform(pf,t,d,b'SYNTHETIC DRIFT SOURCE')
    assert state['calls']==[]


def test_short_wrapper_exact_byte_pins_and_failure_stage_exits_nonzero():
    body=(HERE/'resume_toolchain.py').read_bytes();command,pins=maker.generate(body)
    assert pins['command_bytes']==len(command.encode())<14000 and pins['resume_sha256']==r.H(body)
    assert pins['executed'] is False and pins['network_fetch_performed'] is False
    script=command.split("<<'EXACT194_LOCAL_TOOLCHAIN_RESUME'\n",1)[1].rsplit('\nEXACT194_LOCAL_TOOLCHAIN_RESUME\n',1)[0];ast.parse(script)
    assert "sys.exit(2)" in script and "except Exception" in script
    data=next(row for row in ast.walk(ast.parse(script)) if isinstance(row,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='body' for t in row.targets))
    packed=ast.literal_eval(data.value.args[0].args[0]);assert zlib.decompress(base64.b64decode(packed))==body


def test_source_has_no_redownload_host_install_current_container_mutation_or_app_code_changes():
    body=(HERE/'resume_toolchain.py').read_text()
    assert 'apt-get' not in body and '--download' not in body and '--network=bridge' not in body
    assert 'docker exec' not in body and 'Config.Env' not in body and 'crm_prod.db' not in body
    assert 'unlink(' not in body and 'rmtree' not in body
    assert "d.ENV={**d.ENV,'DOCKER_BUILDKIT':'0'}" in body
    assert "d.validate_context(tool)==old_context" in body
