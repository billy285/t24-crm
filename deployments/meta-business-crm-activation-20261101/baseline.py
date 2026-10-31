"""Fresh current141 baseline and explicit safe key-rotation eligibility."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from types import ModuleType,SimpleNamespace

c=None
BASELINE_SHA='7648d02a0c85a2ea8d094e02337c1edea08c7166d739f16413ab33cc0d3380e5'
DIAGNOSTIC_ROOT=Path('/opt/t24-crm/releases/meta-oauth-diagnostics-a03766539ef3-20261101')
RELEASE_SHA='cf9cb0d2d173cd4300b479c1baadd371881c0c870f37e9d9ca0f248415f974be'
PREFLIGHT_SHA='f842386c5a9f4b9979324d81d5ef11d81a88e0518dee3dd0eeaa937c1b07b559'
LEGACY_APP_ID='1625116099132983'
LEGACY_CONFIG_ID='941072098875174'
_CACHE=None


def configure(core):
    global c
    c=core


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _load(path,sha,name):
    value=ModuleType(name);value.__file__=str(path);exec(compile(c.read(path,sha=sha),str(path),'exec'),value.__dict__);return value


def dependencies():
    global _CACHE
    c.need(c is not None,'REVIEWED_CORE_REQUIRED')
    c.read(DIAGNOSTIC_ROOT/'release.py',sha=RELEASE_SHA);c.read(DIAGNOSTIC_ROOT/'preflight.py',sha=PREFLIGHT_SHA)
    if _CACHE is None:
        release=_load(DIAGNOSTIC_ROOT/'release.py',RELEASE_SHA,'_crm_meta_retained_diagnostic_release')
        pf=_load(DIAGNOSTIC_ROOT/'preflight.py',PREFLIGHT_SHA,'_crm_meta_retained_diagnostic_preflight')
        old_core,old_baseline,old_activation,old_ctx=pf.dependencies()
        receipt=c.strict_json(c.read(DIAGNOSTIC_ROOT/'deployed.json',sha=c.DEPLOYED_SHA))
        c.need(receipt['stage']=='META_OAUTH_DIAGNOSTICS_DEPLOYED' and receipt['source_sha']==c.SOURCE_SHA and receipt['frontend_version']==c.FRONTEND and receipt['schema_revision']==c.SCHEMA_REVISION and receipt['crm']['id']==c.ORIGINAL_ID and receipt['crm']['image']==c.IMAGE,'EXACT_CURRENT_DIAGNOSTIC_DEPLOYMENT_REQUIRED')
        c.need(all(receipt[k] is True for k in ('all_141_current_business_rows_schema_and_private_preserved','existing_meta_nine_env_and_key_preserved','google_on_cutoff_preserved','frontend_static_nginx_csp_unchanged')),'EXACT_CURRENT_PRESERVED_BOUNDARIES_REQUIRED')
        inventory=c.strict_json(c.read(DIAGNOSTIC_ROOT/'backend-after.json',sha=receipt['candidate_inventory_sha256']))
        _CACHE=SimpleNamespace(release=release,pf=pf,legacy_core=old_core,legacy_baseline=old_baseline,legacy_activation=old_activation,ctx=old_ctx,m=old_ctx.m,safe=old_ctx.safe,base=old_ctx.base,helper=old_ctx.helper,receipt=receipt,inventory=inventory)
    return _CACHE


def key_rotation_eligibility(path,*,initial):
    # Only aggregate facts leave SQLite. No encrypted field/state/token value
    # is selected, printed, changed, expired or deleted by these tools.
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        counts={name:con.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('meta_business_connections','meta_business_assets','meta_business_bindings','meta_business_requests')}
        total,bad=con.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN consumed=1 AND flow_encrypted='' THEN 0 ELSE 1 END),0) FROM meta_business_oauth_states").fetchone()
        c.need(all(value==0 for value in counts.values()) and bad==0 and (total==3 if initial else total>=3),'META_DATA_REQUIRES_EXISTING_KEY_OR_MANUAL_RECOVERY')
        return {**counts,'oauth_flow_count':total,'unconsumed_or_encrypted_flow_count':bad,'safe_to_rotate':True}
    finally:con.close()


def legacy_environment(ctx,info):
    values={}
    for row in info['Config']['Env']:
        c.need(isinstance(row,str) and '=' in row and not any(ch in row for ch in '\r\n\0'),'STRICT_ORIGINAL_RUNTIME_ENV_REQUIRED')
        key,value=row.split('=',1);c.need(key not in values,'DUPLICATE_ORIGINAL_ENV_KEY');values[key]=value
    selected=[row for row in info['Config']['Env'] if row.split('=',1)[0].startswith('T24_META_')]
    old=ctx.legacy_core.validate_meta_env(selected)
    c.need(old['T24_META_APP_ID']==LEGACY_APP_ID and old['T24_META_CONFIG_ID']==LEGACY_CONFIG_ID and set(old)==c.META_KEYS,'EXACT_LEGACY_META_CONFIG_REQUIRED')
    return {'meta_environment_sha256':digest(selected),'non_meta_environment_sha256':digest([row for row in info['Config']['Env'] if not row.split('=',1)[0].startswith('T24_META_')])}


def protected_sample(ctx,*,initial=False):
    sample=ctx.legacy_baseline.protected_sample(ctx.ctx)
    c.need(len(sample['rows'])==141,'EXACT141_TABLES_REQUIRED')
    gate=key_rotation_eligibility(ctx.m.BUSINESS,initial=initial)
    c.directory(c.LEGACY_ENV_FILE.parent)
    return {**sample,'legacy_meta_credential_metadata':ctx.safe.protected_metadata(c.LEGACY_ENV_FILE),'key_rotation_eligibility':gate}


def source(ctx,info):return ctx.base.Release.source_overlay_boundary(SimpleNamespace(m=ctx.m),info,ctx.inventory)


def collect():
    ctx=dependencies();m=ctx.m;old=m.inspect('t24-crm');c.need(old['State']['Running'] is True and m.runtime(old)==ctx.receipt['crm'],'EXACT_CURRENT_RUNTIME_REQUIRED')
    ctx.ctx.pf.google_environment(old);m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old);c.need(m.inventory(old['Id'])==ctx.inventory,'EXACT_CURRENT_BACKEND_SOURCE_REQUIRED')
    environment=legacy_environment(ctx,old);sample=protected_sample(ctx,initial=True)
    return {**sample,**environment,'stage':'META_CRM_ROTATION_READONLY_BASELINE','host':c.HOST,'source_sha':c.SOURCE_SHA,'frontend_version':c.FRONTEND,'schema_revision':c.SCHEMA_REVISION,'deployed_sha256':c.DEPLOYED_SHA,'crm':m.runtime(old),'environment_sha256':digest(old['Config']['Env']),'backend_inventory_sha256':digest(ctx.inventory),'google_scheduler_enabled':True,'google_scheduler_activation_from':c.ACTIVATION_FROM}


def capture():
    # Capturing the current state is independent of the not-yet-created App.
    c.server_guard();first=collect();current=collect();dependencies().ctx.release.live_sequence_boundary(first['database_metadata'],current['database_metadata']);c.need({**current,'database_metadata':first['database_metadata']}==first,'ROTATION_BASELINE_CHANGED_DURING_CAPTURE')
    c.mkdir(c.ROOT);sha=c.write(c.ROOT/'baseline.json',current)
    return {'stage':'META_CRM_ROTATION_BASELINE_CAPTURED','sha256':sha,'path':str(c.ROOT/'baseline.json'),'source_sha':c.SOURCE_SHA,'frontend_version':c.FRONTEND,'schema_revision':c.SCHEMA_REVISION,'table_count':141,'runtime':current['crm'],'key_rotation_eligibility':current['key_rotation_eligibility'],'rows_sha256':digest(current['rows']),'google_scheduler_enabled':True,'google_scheduler_activation_from':c.ACTIVATION_FROM,'business_writes':False,'credential_file_content_read':False,'provider_requests':False,'runtime_changed':False}


def proof():
    c.need(isinstance(BASELINE_SHA,str) and re.fullmatch('[a-f0-9]{64}',BASELINE_SHA) and BASELINE_SHA!='0'*64,'ACTUAL_FRESH_ROTATION_BASELINE_REQUIRED')
    value=c.strict_json(c.read(c.ROOT/'baseline.json',sha=BASELINE_SHA));c.need(value['stage']=='META_CRM_ROTATION_READONLY_BASELINE' and value['source_sha']==c.SOURCE_SHA and value['deployed_sha256']==c.DEPLOYED_SHA and len(value['rows'])==141 and value['key_rotation_eligibility']['oauth_flow_count']==3,'EXACT_ROTATION_PROOF_REQUIRED');return value


def verify(stage,*,current=None,recovery=False):
    c.server_guard();p=proof();ctx=dependencies();sample=protected_sample(ctx,initial=not recovery)
    ctx.ctx.release.sequence_boundary(p['database_metadata'],sample['database_metadata'],recovery=True) if recovery else ctx.ctx.release.live_sequence_boundary(p['database_metadata'],sample['database_metadata'])
    for key in sample:
        if key=='database_metadata' or recovery and key in {'rows','key_rotation_eligibility'}:continue
        c.need(sample[key]==p[key],'ROTATION_DATA_SCHEMA_OR_PRIVATE_BOUNDARY_DRIFT')
    if current is None:
        current=ctx.m.inspect('t24-crm');c.need(current['State']['Running'] is True and ctx.m.runtime(current)==p['crm'],'EXACT_ROTATION_ORIGINAL_RUNTIME_REQUIRED');legacy_environment(ctx,current)
    c.need(current['Image']==c.IMAGE,'SAME_APPLICATION_IMAGE_REQUIRED');ctx.ctx.pf.google_environment(current);ctx.m.verify_secret_mount(current);ctx.m.verify_production_worker_enabled(current);source(ctx,current)
    return {'proof':p,'context':ctx,'current':current,'stage':stage}
