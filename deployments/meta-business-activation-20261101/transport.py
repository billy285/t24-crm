"""One-use Meta App Secret transport; no runtime switch, SQL or network access."""
import base64
import fcntl
import json
import os
import re
import secrets
import subprocess
import time
import core as c

TTL = 900
ALGORITHM = 'RSA-OAEP-SHA256-3072'
DOMAIN = 'T24_CRM_META_USER_OAUTH_TRANSFER_V1'
MAXIMUM_CLEAR = 318
OPENSSL = '/usr/bin/openssl'


def _run(argv, code, *, data=None, maximum=8192, timeout=45):
    # Commands are fixed local OpenSSL operations. No plaintext enters argv,
    # stderr or caller-visible exceptions; only bounded returned bytes are used.
    try:
        result=subprocess.run(argv,input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired): raise c.GuardError(code) from None
    c.need(result.returncode==0 and len(result.stdout)<=maximum,code); return result.stdout


def _verify(verify, stage):
    c.server_guard(); c.pins_ready(); c.need(callable(verify),'REVIEWED_BASELINE_CALLBACK_REQUIRED'); verify(stage)


def label(context):
    return ('\n'.join((DOMAIN,c.HOST,c.APP_ID,c.BUSINESS_ID,c.CONFIG_ID,c.GRAPH_VERSION,c.CALLBACK,c.SOURCE_SHA,c.CONFIG_FREEZE_SHA,
        context['transfer_id'],context['public_sha256'],str(context['expires_at'])))).encode('ascii')


def _validate_context(context, transfer_id):
    keys={'host','app_id','business_id','config_id','graph_version','configuration_freeze_sha256','source_sha','callback','read_scopes','token_type','transfer_id','public_pem','public_sha256','created_at','expires_at','algorithm','payload_max_bytes','oaep_label_base64'}
    c.need(set(context)==keys,'EXACT_META_TRANSFER_CONTEXT_REQUIRED')
    expected={'host':c.HOST,'app_id':c.APP_ID,'business_id':c.BUSINESS_ID,'config_id':c.CONFIG_ID,'graph_version':c.GRAPH_VERSION,
        'configuration_freeze_sha256':c.CONFIG_FREEZE_SHA,'source_sha':c.SOURCE_SHA,'callback':c.CALLBACK,'read_scopes':list(c.READ_SCOPES),'token_type':'USER',
        'transfer_id':transfer_id,'algorithm':ALGORITHM,'payload_max_bytes':MAXIMUM_CLEAR}
    c.need(all(context[name]==value for name,value in expected.items()),'META_TRANSFER_CONTEXT_IDENTITY_DRIFT')
    now=int(time.time())
    c.need(type(context['created_at']) is int and type(context['expires_at']) is int and context['created_at']<=now<context['expires_at']==context['created_at']+TTL,'META_TRANSPORT_EXPIRED')
    public=context['public_pem']
    c.need(isinstance(public,str) and public.startswith('-----BEGIN PUBLIC KEY-----\n') and public.endswith('-----END PUBLIC KEY-----\n') and len(public)<1024 and c.H(public.encode('ascii'))==context['public_sha256'],'META_TRANSPORT_PUBLIC_KEY_DRIFT')
    c.need(context['oaep_label_base64']==base64.b64encode(label(context)).decode(),'META_TRANSPORT_LABEL_DRIFT')


def prepare(verify):
    _verify(verify,'transport-prepare')
    c.need(not c.ENV_FILE.exists() and not c.ENV_FILE.is_symlink(),'EXISTING_META_CREDENTIALS_PRESERVED')
    c.mkdir(c.SECRET_ROOT); c.mkdir(c.TRANSFERS); c.mkdir(c.ROOT)
    transfer_id=secrets.token_hex(16); path=c.TRANSFERS/transfer_id; c.mkdir(path)
    key=path/'private.pem'; c.write(key,b'RESERVED\n')
    _run([OPENSSL,'genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-pkeyopt','rsa_keygen_pubexp:65537','-out',str(key)],'META_TRANSPORT_KEY_GENERATION_FAILED')
    c.read(key,maximum=4096)
    public=_run([OPENSSL,'pkey','-in',str(key),'-pubout'],'META_TRANSPORT_PUBLIC_EXPORT_FAILED',maximum=1024)
    now=int(time.time()); context={'host':c.HOST,'app_id':c.APP_ID,'business_id':c.BUSINESS_ID,'config_id':c.CONFIG_ID,'graph_version':c.GRAPH_VERSION,
        'configuration_freeze_sha256':c.CONFIG_FREEZE_SHA,'source_sha':c.SOURCE_SHA,'callback':c.CALLBACK,'read_scopes':list(c.READ_SCOPES),'token_type':'USER',
        'transfer_id':transfer_id,'public_pem':public.decode('ascii'),'public_sha256':c.H(public),'created_at':now,'expires_at':now+TTL,
        'algorithm':ALGORITHM,'payload_max_bytes':MAXIMUM_CLEAR}
    context['oaep_label_base64']=base64.b64encode(label(context)).decode(); _validate_context(context,transfer_id)
    c.write(path/'context.json',context)
    return {'stage':'META_CREDENTIAL_TRANSPORT_READY',**context,'runtime_changed':False,'business_writes':False,'provider_requests':False}


def receive(verify, transfer_id, ciphertext):
    _verify(verify,'transport-install')
    c.need(isinstance(transfer_id,str) and bool(re.fullmatch('[a-f0-9]{32}',transfer_id)),'META_TRANSFER_ID_REJECTED')
    c.directory(c.SECRET_ROOT); c.directory(c.TRANSFERS); c.directory(c.ROOT)
    path=c.TRANSFERS/transfer_id; c.directory(path)
    context=c.strict_json(c.read(path/'context.json',maximum=8192)); _validate_context(context,transfer_id)
    try: raw=base64.b64decode(ciphertext,validate=True)
    except (ValueError,TypeError): raise c.GuardError('META_CIPHERTEXT_REJECTED') from None
    c.need(len(raw)==384,'META_CIPHERTEXT_REJECTED')
    lock_path=c.SECRET_ROOT/'install.lock'
    fd=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        c.read(lock_path,maximum=0); fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c.need(not c.ENV_FILE.exists() and not c.ENV_FILE.is_symlink(),'EXISTING_META_CREDENTIALS_PRESERVED')
        c.need(not (path/'claimed.json').exists() and not (path/'claimed.json').is_symlink(),'META_TRANSFER_ALREADY_CLAIMED')
        # Claim durably before decrypting. A claimed failure requires a fresh,
        # reviewed transfer rather than reusing captured ciphertext.
        c.write(path/'claimed.json',{'transfer_id':transfer_id,'claimed_at':int(time.time())})
        key=path/'private.pem'; c.read(key,maximum=4096)
        public=_run([OPENSSL,'pkey','-in',str(key),'-pubout'],'META_TRANSPORT_PUBLIC_EXPORT_FAILED',maximum=1024)
        c.need(c.H(public)==context['public_sha256'] and public.decode('ascii')==context['public_pem'],'META_TRANSPORT_PUBLIC_KEY_DRIFT')
        clear=_run([OPENSSL,'pkeyutl','-decrypt','-inkey',str(key),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256','-pkeyopt','rsa_oaep_label:'+label(context).hex()], 'META_CIPHERTEXT_REJECTED',data=raw,maximum=MAXIMUM_CLEAR)
        c.need(0<len(clear)<=MAXIMUM_CLEAR,'META_CREDENTIAL_PAYLOAD_SIZE_REJECTED')
        app_id,secret=c.validate_credentials(c.strict_json(clear))
        _validate_context(context,transfer_id); _verify(verify,'transport-install')
        values={'T24_META_ENABLED':'true','T24_META_APP_ID':app_id,'T24_META_APP_SECRET':secret,
            'T24_META_TOKEN_KEY':base64.urlsafe_b64encode(os.urandom(32)).decode(), 'T24_META_CONFIG_ID':c.CONFIG_ID,'T24_META_GRAPH_VERSION':c.GRAPH_VERSION,
            'T24_META_PUBLIC_URL':c.ORIGIN,'T24_META_EXPECTED_SCOPES':','.join(c.READ_SCOPES),'T24_META_LOGIN_CONFIG_REVIEWED':'true'}
        rows=[name+'='+values[name] for name in sorted(values)]; c.validate_meta_env(rows)
        _validate_context(context,transfer_id)
        env_sha=c.write(c.ENV_FILE, ('\n'.join(rows)+'\n').encode('ascii'))
        c.read(c.ENV_FILE,maximum=8192,sha=env_sha)
        receipt={'stage':'META_CREDENTIALS_STORED_RUNTIME_UNCHANGED','app_id':c.APP_ID,'business_id':c.BUSINESS_ID,'config_id':c.CONFIG_ID,'graph_version':c.GRAPH_VERSION,
            'configuration_freeze_sha256':c.CONFIG_FREEZE_SHA,'transfer_id':transfer_id,'stored_at':int(time.time()),'env_path':str(c.ENV_FILE),'env_sha256':env_sha,
            'independent_fernet_key_generated':True,'credential_values_exported':False,'runtime_changed':False,'business_writes':False,'provider_requests':False}
        c.write(c.ROOT/'credential-receipt.json',receipt)
        key.unlink(); c.fsync_dir(path)
        return receipt
    finally: os.close(fd)
