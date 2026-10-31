"""Real local RSA-OAEP/browser-WebCrypto seams, synthetic secret only."""
import base64
import copy
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('meta_transport_actual_core_test',HERE/'core.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
sys.modules['core']=c
spec=importlib.util.spec_from_file_location('meta_transport_actual_test',HERE/'transport.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
NODE='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
SECRET='SYNTHETIC_META_SECRET_12345678'


@pytest.fixture
def scope(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);monkeypatch.setattr(c,'FS_ANCHOR',tmp_path);monkeypatch.setattr(c,'OWNER_UID',os.getuid());monkeypatch.setattr(c,'server_guard',lambda:None)
    monkeypatch.setattr(c,'CONFIG_ID','2222222222222222');monkeypatch.setattr(c,'CONFIG_FREEZE_SHA','a'*64)
    for name in ('secrets','releases'):(tmp_path/name).mkdir(mode=0o700)
    monkeypatch.setattr(c,'SECRET_ROOT',tmp_path/'secrets/meta-business');monkeypatch.setattr(c,'TRANSFERS',c.SECRET_ROOT/'transfers');monkeypatch.setattr(c,'ENV_FILE',c.SECRET_ROOT/'runtime.env');monkeypatch.setattr(c,'ROOT',tmp_path/'releases/meta-activation')
    calls=[]
    def verify(stage):assert stage in {'transport-prepare','transport-install'};calls.append(stage)
    return verify,calls


def public_context(receipt):return {k:v for k,v in receipt.items() if k not in {'stage','runtime_changed','business_writes','provider_requests'}}


def encrypt(context, *, secret=SECRET, label_override=None, app_id=None, extra=None):
    from cryptography.hazmat.primitives import serialization,hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key=serialization.load_pem_public_key(context['public_pem'].encode())
    payload={'app_id':c.APP_ID if app_id is None else app_id,'app_secret':secret};payload.update(extra or {})
    raw=key.encrypt(json.dumps(payload,separators=(',',':')).encode(),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=t.label(context) if label_override is None else label_override))
    return base64.b64encode(raw).decode()


def test_unknown_pins_fail_before_baseline_or_filesystem(scope,monkeypatch):
    monkeypatch.setattr(c,'CONFIG_ID',None)
    with pytest.raises(c.GuardError):t.prepare(lambda _:pytest.fail('baseline before known pins'))
    assert not c.SECRET_ROOT.exists() and not c.ROOT.exists()


def test_baseline_must_pass_before_any_mutation(scope):
    with pytest.raises(RuntimeError,match='SYNTHETIC_DRIFT'):t.prepare(lambda _:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_DRIFT')))
    assert not c.SECRET_ROOT.exists() and not c.ROOT.exists()


def test_real_rsa_transport_installs_only_meta_env_and_destroys_transport_key(scope,capsys):
    verify,calls=scope;receipt=t.prepare(verify);context=public_context(receipt)
    assert set(context['read_scopes'])==set(c.READ_SCOPES) and context['token_type']=='USER'
    assert SECRET not in json.dumps(receipt) and not c.ENV_FILE.exists()
    key=c.TRANSFERS/context['transfer_id']/'private.pem';assert key.exists()
    result=t.receive(verify,context['transfer_id'],encrypt(context));assert not key.exists()
    values=c.validate_meta_env(c.read(c.ENV_FILE,maximum=8192).decode().splitlines());assert values['T24_META_APP_SECRET']==SECRET and len(values)==9
    assert result['runtime_changed'] is result['business_writes'] is result['provider_requests'] is False
    assert result['env_sha256']==c.H(c.ENV_FILE.read_bytes())
    assert SECRET not in json.dumps(result) and values['T24_META_TOKEN_KEY'] not in json.dumps(result)
    assert calls==['transport-prepare','transport-install','transport-install'] and not capsys.readouterr().out
    original=c.ENV_FILE.read_bytes()
    with pytest.raises(c.GuardError,match='EXISTING_META_CREDENTIALS_PRESERVED'):t.prepare(verify)
    with pytest.raises(c.GuardError):t.receive(verify,context['transfer_id'],encrypt(context))
    assert c.ENV_FILE.read_bytes()==original


def test_browser_webcrypto_ciphertext_opens_only_with_exact_meta_context(scope):
    verify,_=scope;context=public_context(t.prepare(verify));script=(HERE/'encrypt-in-browser.js').read_text();script=re.sub(r"const APPROVED_CONFIG_ID = (?:null|'[0-9]+');","const APPROVED_CONFIG_ID = '"+c.CONFIG_ID+"';",script,count=1);script=re.sub(r"const APPROVED_CONFIG_FREEZE_SHA = (?:null|'[a-f0-9]{64}');","const APPROVED_CONFIG_FREEZE_SHA = '"+c.CONFIG_FREEZE_SHA+"';",script,count=1)
    runner="const fs=require('node:fs'),{webcrypto}=require('node:crypto');globalThis.crypto=webcrypto;const input=JSON.parse(fs.readFileSync(0,'utf8'));\n"+script+"\nencryptMetaApp(input.context,input.app_id,input.secret).then(value=>process.stdout.write(value)).catch(()=>process.exit(19));"
    result=subprocess.run([NODE,'-e',runner],input=json.dumps({'context':context,'app_id':c.APP_ID,'secret':SECRET}).encode(),capture_output=True,check=True)
    assert len(base64.b64decode(result.stdout))==384 and SECRET.encode() not in result.stdout and not result.stderr
    t.receive(verify,context['transfer_id'],result.stdout.decode());assert SECRET in c.ENV_FILE.read_text()


@pytest.mark.parametrize('kind',['wrong_label','wrong_app','extra','secret'])
def test_failed_claim_is_not_replayable_and_cannot_install(scope,kind):
    verify,_=scope;context=public_context(t.prepare(verify))
    kwargs={'label_override':b'WRONG_GOOGLE_OR_OTHER_CONTEXT'} if kind=='wrong_label' else {'app_id':'different'} if kind=='wrong_app' else {'extra':{'extra':'unexpected'}} if kind=='extra' else {'secret':'bad secret'}
    ciphertext=encrypt(context,**kwargs)
    with pytest.raises(c.GuardError):t.receive(verify,context['transfer_id'],ciphertext)
    assert not c.ENV_FILE.exists() and (c.TRANSFERS/context['transfer_id']/'claimed.json').exists()
    with pytest.raises(c.GuardError,match='META_TRANSFER_ALREADY_CLAIMED'):t.receive(verify,context['transfer_id'],encrypt(context))


@pytest.mark.parametrize('field,value',[('config_id',c.FORBIDDEN_CONFIG_ID),('app_id','different'),('graph_version','v25.0'),('callback','https://external.example/callback'),('token_type','SYSTEM_USER'),('source_sha','b'*40),('configuration_freeze_sha256','b'*64),('read_scopes',['instagram_content_publish']),('oaep_label_base64','AA==')])
def test_persisted_context_cannot_be_retargeted(scope,field,value):
    verify,_=scope;context=public_context(t.prepare(verify));path=c.TRANSFERS/context['transfer_id']/'context.json';changed=copy.deepcopy(context);changed[field]=value;path.write_text(json.dumps(changed))
    with pytest.raises(c.GuardError):t.receive(verify,context['transfer_id'],encrypt(context))
    assert not c.ENV_FILE.exists() and not (path.parent/'claimed.json').exists()


def test_expired_transfer_cannot_claim(scope,monkeypatch):
    verify,_=scope;context=public_context(t.prepare(verify));monkeypatch.setattr(t.time,'time',lambda:context['expires_at'])
    with pytest.raises(c.GuardError,match='META_TRANSPORT_EXPIRED'):t.receive(verify,context['transfer_id'],encrypt(context))
    assert not c.ENV_FILE.exists() and not (c.TRANSFERS/context['transfer_id']/'claimed.json').exists()


def test_second_baseline_check_blocks_install_after_claim(scope):
    verify,_=scope;context=public_context(t.prepare(verify));calls=[]
    def drift(stage):
        calls.append(stage)
        if len(calls)==2:raise RuntimeError('SYNTHETIC_FRESH_BASELINE_DRIFT')
    with pytest.raises(RuntimeError,match='SYNTHETIC_FRESH_BASELINE_DRIFT'):t.receive(drift,context['transfer_id'],encrypt(context))
    assert not c.ENV_FILE.exists() and (c.TRANSFERS/context['transfer_id']/'claimed.json').exists()


def test_receipt_failure_keeps_private_env_and_key_for_manual_review_never_overwrites(scope,monkeypatch):
    verify,_=scope;context=public_context(t.prepare(verify));write=c.write
    def fail(path,value):
        if path.name=='credential-receipt.json':raise OSError('synthetic full disk')
        return write(path,value)
    monkeypatch.setattr(c,'write',fail)
    with pytest.raises(OSError):t.receive(verify,context['transfer_id'],encrypt(context))
    before=c.ENV_FILE.read_bytes();assert (c.TRANSFERS/context['transfer_id']/'private.pem').exists()
    with pytest.raises(c.GuardError):t.receive(verify,context['transfer_id'],encrypt(context))
    assert c.ENV_FILE.read_bytes()==before
