#!/usr/bin/env python3
"""One explicitly reviewed Stripe seed recovery after a no-successful-seed proof.

The original bootstrap claim stays immutable. A separate exclusive recovery
claim allows one candidate-bound attempt, with credentials only on helper stdin.
Never restores databases, retries automatically, switches services or starts sync.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from uuid import uuid4

import credential_transfer as transfer
import diagnose_private_stripe as diagnosis
import live_preflight as live
import private_schema_guard as guard
import seed_private_stripe as seed
import switch_completed as switch

class ResumeSeedError(RuntimeError): pass
class SafeParser(argparse.ArgumentParser):
    def error(self,message): raise ResumeSeedError('ARGUMENTS_REJECTED')
def need(ok,code):
    if not ok: raise ResumeSeedError(code)
def sha(blob): return hashlib.sha256(blob).hexdigest()

def claim_paths(bootstrap_sha256):
    need(re.fullmatch('[a-f0-9]{64}',bootstrap_sha256 or ''),'EXACT_RETRY_BOOTSTRAP_REQUIRED')
    root=transfer.CONFIG/'stripe-seed-claims';transfer.protected_directory(root)
    return root/(bootstrap_sha256+'.json'),root/(bootstrap_sha256+'.reviewed-retry.json')

def checked_original_claim(value,state,bootstrap_sha256):
    lineage=state['resume_lineage']
    need(value.get('stage')=='STRIPE_SEED_ONE_USE_CLAIMED' and
         value.get('bootstrap_sha256')==bootstrap_sha256==lineage['bootstrap_sha256'] and
         value.get('candidate_sha256')==lineage['original_candidate_sha256'] and
         value.get('source_sha')==lineage['original_source_sha'] and
         re.fullmatch('[a-f0-9]{32}',value.get('attempt','')),'EXACT_ORIGINAL_FAILED_SEED_CLAIM_REQUIRED')

def retry_claim_value(args,state,original,attempt):
    need(re.fullmatch('[a-f0-9]{32}',attempt),'EXCLUSIVE_RETRY_ATTEMPT_REQUIRED')
    return {'format_version':1,'stage':'STRIPE_SEED_REVIEWED_RETRY_CLAIMED','attempt':attempt,
        'source_sha':args.source_sha,'candidate_sha256':args.candidate_sha256,
        'bootstrap_sha256':args.bootstrap_sha256,'original_claim_sha256':state['resume_lineage']['original_claim_sha256'],
        'original_attempt':original['attempt'],'resume_lineage_sha256':guard.digest(state['resume_lineage']),
        'schema_state_sha256':args.schema_state_sha256,'frozen_seed_before_sha256':state['schema_after_sha256'],
        'readonly_diagnosis_sha256':args.readonly_diagnosis_sha256}

def checked_diagnosis(value,args,state):
    need(args.readonly_diagnosis.parent==args.candidate.parent/'completed-release' and
         re.fullmatch('stripe-diagnosis-[a-f0-9]{32}\\.json',args.readonly_diagnosis.name),
         'EXACT_PRE_RETRY_READONLY_DIAGNOSIS_PATH_REQUIRED')
    lineage=state['resume_lineage']
    original_path,_=claim_paths(lineage['bootstrap_sha256'])
    original=seed.fixed_json(original_path,lineage['original_claim_sha256'])
    checked_original_claim(original,state,lineage['bootstrap_sha256'])
    need(value.get('format_version')==1 and value.get('stage')=='PRIVATE_STRIPE_READONLY_DIAGNOSIS_COMPLETE' and
         value.get('last_stage')=='complete' and value.get('probes')==list(diagnosis.PROBES) and
         value.get('source_sha')==args.source_sha and value.get('candidate_sha256')==args.candidate_sha256 and
         value.get('image_id')==state['candidate_image'] and value.get('schema_state_sha256')==args.schema_state_sha256 and
         value.get('schema_after_sha256')==state['schema_after_sha256'] and
         value.get('bootstrap_sha256')==lineage['bootstrap_sha256'] and
         value.get('failed_claim_sha256')==lineage['original_claim_sha256'] and
         value.get('failed_seed_attempt')==original['attempt'] and
         value.get('resume_lineage_sha256')==guard.digest(lineage) and
         value.get('before_snapshot_sha256')==value.get('after_snapshot_sha256')==state['frozen_seed_before_sha256'] and
         all(value.get(name) is True for name in ('success','stripe_connection_absent','exact_accepted_schema_after')) and
         all(value.get(name) is False for name in ('database_writes','connected','credential_seed_attempted',
             'one_use_claim_changed','production_services_changed','deployed')),
         'ACTUAL_COMPLETE_READONLY_SIX_GET_DIAGNOSIS_REQUIRED')

def claim_retry(args,state,original,attempt):
    old,new=claim_paths(args.bootstrap_sha256)
    need(sha(transfer.read_protected(old))==state['resume_lineage']['original_claim_sha256'],
         'ORIGINAL_CLAIM_MUST_REMAIN_UNCHANGED')
    value=retry_claim_value(args,state,original,attempt)
    try: transfer.write_exclusive(new,transfer.encoded(value))
    except FileExistsError: raise ResumeSeedError('REVIEWED_RETRY_ALREADY_CLAIMED_NO_AUTOMATIC_RETRY') from None
    return new,sha(transfer.read_protected(new))

def checked_seed_lineage(value,args,state):
    lineage=state.get('resume_lineage');need(isinstance(lineage,dict),'EXPLICIT_RESUME_LINEAGE_REQUIRED')
    bootstrap=lineage['bootstrap_sha256'];old,new=claim_paths(bootstrap)
    original=seed.fixed_json(old,lineage['original_claim_sha256']);checked_original_claim(original,state,bootstrap)
    need(value.get('resume_lineage_sha256')==guard.digest(lineage) and
         value.get('schema_state_sha256')==state.get('accepted_schema_state_sha256') and
         value.get('original_claim_sha256')==lineage['original_claim_sha256'] and
         value.get('retry_claim')==str(new) and re.fullmatch('[a-f0-9]{64}',value.get('retry_claim_sha256','')),
         'SEED_EXACT_REVIEWED_RESUME_LINEAGE_REQUIRED')
    diagnostic_args=argparse.Namespace(source_sha=args.source_sha,candidate_sha256=args.candidate_sha256,
        candidate=args.candidate,schema_state_sha256=state['accepted_schema_state_sha256'],
        readonly_diagnosis=Path(value['readonly_diagnosis']),readonly_diagnosis_sha256=value['readonly_diagnosis_sha256'])
    checked_diagnosis(seed.fixed_json(diagnostic_args.readonly_diagnosis,diagnostic_args.readonly_diagnosis_sha256),
        diagnostic_args,state)
    retry=seed.fixed_json(new,value['retry_claim_sha256'])
    expected=retry_claim_value(argparse.Namespace(source_sha=args.source_sha,candidate_sha256=args.candidate_sha256,
        bootstrap_sha256=bootstrap,schema_state_sha256=state['accepted_schema_state_sha256'],
        readonly_diagnosis_sha256=value['readonly_diagnosis_sha256']),state,original,retry.get('attempt',''))
    need(retry==expected,'EXACT_EXCLUSIVE_RETRY_CLAIM_REQUIRED')

def main(args):
    need(args.execute and os.geteuid()==0 and socket.gethostname()==live.HOST,'EXPLICIT_ROOT_REVIEWED_RETRY_REQUIRED')
    os.umask(0o077)
    with switch.release_lock():
        receipt=switch.checked_candidate(args)
        state,before,after,baseline=switch.checked_schema_state(args,receipt)
        need(state.get('phase')=='PRIVATE_COMPLETED_RESUME_VERIFIED_WRITERS_STOPPED' and state.get('resume_lineage'),
             'FROZEN_REVIEWED_RESUME_STATE_REQUIRED')
        need(args.output==args.candidate.parent/'stripe-seed-receipt.json' and not args.output.exists(),
             'NEW_EXCLUSIVE_RETRY_SEED_OUTPUT_REQUIRED')
        switch.no_writers();switch.runtime_guard(baseline)
        current=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
        need(current==after,'EXACT_FROZEN_RESUME_SEED_SNAPSHOT_REQUIRED')
        switch.disabled_data(current)
        checked_diagnosis(seed.fixed_json(args.readonly_diagnosis,args.readonly_diagnosis_sha256),args,state)
        connection_before=seed.connection_state(live.PRIVATE_DB)
        need(connection_before['row'] is None,'RESUME_REQUIRES_ABSENT_STRIPE_CONNECTION')
        generation=seed.seedable(connection_before)
        old_claim,_=claim_paths(args.bootstrap_sha256)
        original=seed.fixed_json(old_claim,state['resume_lineage']['original_claim_sha256'])
        checked_original_claim(original,state,args.bootstrap_sha256)
        need(sha(transfer.read_protected(transfer.BOOTSTRAP,32768))==args.bootstrap_sha256,
             'ORIGINAL_BOOTSTRAP_MUST_REMAIN_UNCHANGED')
        configuration=seed.checked_configuration(transfer.read_protected(transfer.ENV))
        payload=transfer.get_bootstrap(sealed_crypto='docker')
        attempt=uuid4().hex;identity=None;claimed=False;completed=False
        try:
            retry_path,retry_hash=claim_retry(args,state,original,attempt);claimed=True
            name='t24-private-stripe-seed-'+attempt
            exists=subprocess.run(['docker','inspect',name],capture_output=True,timeout=15,check=False)
            need(exists.returncode!=0,'EXCLUSIVE_RETRY_HELPER_NAME_REQUIRED')
            identity=seed.docker(seed.create_command(name,attempt,receipt['image_id'])).decode().strip()
            need(re.fullmatch('[a-f0-9]{64}',identity),'RETRY_HELPER_ID_REQUIRED')
            seed.checked_helper(seed.inspect_container(identity),identity,attempt,receipt['image_id'])
            switch.no_writers();switch.runtime_guard(baseline)
            need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)==current and
                 sha(transfer.read_protected(transfer.BOOTSTRAP,32768))==args.bootstrap_sha256 and
                 seed.fixed_json(old_claim,state['resume_lineage']['original_claim_sha256'])==original,
                 'FINAL_REVIEWED_RETRY_PREFLIGHT_DRIFT')
            packet=transfer.encoded({'configuration':configuration,'credentials':payload['credentials'],
                'stripe_before_sha256':connection_before['stripe_sha256'],
                'other_before_sha256':connection_before['other_connections_sha256'],'generation_before':generation})
            raw=seed.docker(['start','--attach','--interactive',identity],input=packet,timeout=75)
            result=seed.checked_report(raw,generation);completed=True
            info=seed.checked_helper(seed.inspect_container(identity),identity,attempt,receipt['image_id'])
            need(not info['State']['Running'] and info['State'].get('ExitCode')==0,'RETRY_HELPER_MUST_EXIT_SUCCESSFULLY')
            switch.no_writers();switch.runtime_guard(baseline)
            final=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
            seed.checked_after(current,final,connection_before,seed.connection_state(live.PRIVATE_DB))
            need(sha(transfer.read_protected(transfer.BOOTSTRAP,32768))==args.bootstrap_sha256 and
                 seed.fixed_json(old_claim,state['resume_lineage']['original_claim_sha256'])==original and
                 sha(transfer.read_protected(retry_path))==retry_hash,'REVIEWED_RETRY_CLAIMS_OR_BOOTSTRAP_CHANGED')
            value={**result,'format_version':1,'stage':'PRIVATE_STRIPE_SEED_VERIFIED_NOT_DEPLOYED',
                'source_sha':args.source_sha,'candidate_sha256':args.candidate_sha256,'image_id':receipt['image_id'],
                'bootstrap_sha256':args.bootstrap_sha256,'schema_acceptance_sha256':state['schema_validation_sha256'],
                'backup_sha256':state['backup_sha256'],'schema_state_sha256':args.schema_state_sha256,
                'resume_lineage_sha256':guard.digest(state['resume_lineage']),
                'readonly_diagnosis':str(args.readonly_diagnosis),'readonly_diagnosis_sha256':args.readonly_diagnosis_sha256,
                'original_claim_sha256':state['resume_lineage']['original_claim_sha256'],
                'retry_claim':str(retry_path),'retry_claim_sha256':retry_hash,'original_claim_preserved':True,
                'runtime_env_changed':False,'customer_data_changed':False,'other_private_connections_changed':False,
                'private_rows_changed_only_stripe_connection':True,'worker_started':False,'services_switched':False,
                'public_assets_published':False,'deployed':False,'before_snapshot_sha256':guard.digest(current),
                'after_snapshot_sha256':guard.digest(final)}
            transfer.write_exclusive(args.output,transfer.encoded(value))
            print(json.dumps({'stage':value['stage'],'receipt_sha256':sha(transfer.read_protected(args.output)),
                'original_claim_preserved':True,'deployed':False},sort_keys=True))
        except BaseException:
            if claimed:
                print(json.dumps({'stage':'STRIPE_REVIEWED_RETRY_OUTCOME_REQUIRES_OPERATOR_REVIEW',
                    'helper_success_observed':completed,'automatic_database_restore':False,'automatic_retry':False},sort_keys=True))
            raise
        finally:
            if identity:
                seed.checked_helper(seed.inspect_container(identity),identity,attempt,receipt['image_id'])
                seed.docker(['rm','--force',identity])

def cli(argv=None):
    parser=SafeParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--source-sha',required=True)
    for name in ('candidate','schema-state','readonly-diagnosis'):
        parser.add_argument('--'+name,type=Path,required=True);parser.add_argument('--'+name+'-sha256',required=True)
    parser.add_argument('--bootstrap-sha256',required=True);parser.add_argument('--output',type=Path,required=True)
    try: main(parser.parse_args(argv))
    except BaseException as error:
        code=str(error) if isinstance(error,ResumeSeedError) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else 'REVIEWED_RESUME_SEED_REJECTED'
        print(json.dumps({'stage':'PRIVATE_STRIPE_RESUME_SEED_REJECTED','error':code,'deployed':False},sort_keys=True));return 1
    return 0

if __name__=='__main__':raise SystemExit(cli())
