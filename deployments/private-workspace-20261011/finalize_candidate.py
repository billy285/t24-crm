#!/usr/bin/env python3
"""Finish the already built retry2 candidate after a mount-order-only guard failure.

No builds, test execution, database access, production service starts or Nginx
changes. Original preparation artifacts are read only; new checks have new logs.
"""
import argparse
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '1a4c9523cad250d32a8c1274c2f72c8c6cb6df8b'
ARCHIVE_SHA = '9a7274a8758d074b2577849fea39a26d1cc8fec72b5b5e671e2053bda83f5016'
SPEC_SHA = 'c2b9c3c085764d6833495dea907d9ee0c807dc30e887e7661faa06ab831d964e'
PREPARE_SHA = '8de2ecaec7aad3b56fa966a3d3509ebe522c46345f227c79584ebcaabfb73641'
RELEASE = Path('/opt/t24-crm/releases/private-workspace-1a4c952-20261011-retry2')
EXPECTED_TESTS = 87
ORIGINAL_CRM = {
    'container_id':'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26',
    'image_id':'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab',
    'started_at':'2026-10-10T17:19:07.948520307Z',
    'configuration_sha256':'2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0',
}


def need(value, code):
    if not value:
        raise RuntimeError(code)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trusted_file(path):
    need(path.is_file() and not path.is_symlink() and path.resolve() == path and
         path.stat().st_uid == 0 and not path.stat().st_mode & 0o077, 'PRIVATE_PROOF_UNTRUSTED')
    return path


def load_prep():
    sys.dont_write_bytecode = True
    path = trusted_file(RELEASE/'prepare_private_v3.py')
    need(sha(path) == PREPARE_SHA, 'FROZEN_PREPARER_DRIFT')
    spec = importlib.util.spec_from_file_location('frozen_private_preparer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def original_inventory():
    """Hash original evidence only, excluding the finalizer and its new log directory."""
    result = {}
    for path in sorted(RELEASE.rglob('*')):
        rel = path.relative_to(RELEASE)
        if any(part.startswith('finalize-attempt-') for part in rel.parts):
            continue
        if rel.as_posix() in ('finalize_candidate.py', 'candidate.json'):
            continue
        need(not path.is_symlink(), 'ORIGINAL_RELEASE_SYMLINK')
        if path.is_file():
            result[rel.as_posix()] = sha(path)
    return result


def source_manifest(root):
    need(root.is_dir() and not root.is_symlink() and root.resolve() == root, 'SOURCE_TREE_UNTRUSTED')
    result = {}
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink() and (path.is_dir() or path.is_file()) and
             path.stat().st_uid == 0 and not path.stat().st_mode & 0o022, 'SOURCE_NODE_UNTRUSTED')
        if path.is_file():
            need(path.stat().st_nlink == 1, 'SOURCE_HARDLINK')
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def verified_crm_identity(prep, original):
    need(original == ORIGINAL_CRM, 'FIXED_BASELINE_IDENTITY_DRIFT')
    # Raw inspection remains in memory: Config includes sensitive environment.
    result = subprocess.run(['docker','inspect','t24-crm'],stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,text=True,timeout=30)
    need(result.returncode == 0, 'CRM_INSPECTION_FAILED')
    info = json.loads(result.stdout)[0]
    need(info['Id'] == original['container_id'] and info['Image'] == original['image_id'] == prep.BASE_IMAGE and
         info['State']['StartedAt'] == original['started_at'] and info['State']['Running'] and
         info['State'].get('Health',{}).get('Status') == 'healthy', 'ORIGINAL_CRM_IDENTITY_OR_HEALTH_DRIFT')
    labels = info['Config'].get('Labels') or {}
    need(labels.get('t24.source.sha') == prep.BASE_SOURCE and
         labels.get('com.docker.compose.service') == 'crm' and
         labels.get('com.docker.compose.project.working_dir') == str(prep.APP) and
         labels.get('com.docker.compose.project.config_files') ==
         str(prep.APP/'docker-compose.yml')+','+str(prep.BASE_RELEASE/'compose-new.json'), 'CRM_COMPOSE_DRIFT')
    mounts = info['Mounts']
    expected = {(str(prep.APP/'data'),'/app/backend/data','bind',True),
                (str(prep.APP/'logs'),'/app/backend/logs','bind',True)}
    need(len(mounts) == 2 and {(m['Source'],m['Destination'],m['Type'],m['RW']) for m in mounts} == expected,
         'EXACT_CRM_MOUNTS_REQUIRED')
    need(info['HostConfig']['PortBindings'] == {'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'8000'}]}, 'CRM_PORT_DRIFT')
    need(re.fullmatch(r'[a-f0-9]{64}',original['configuration_sha256']) is not None, 'ORIGINAL_CONFIG_DIGEST_SHAPE')
    permutation_hashes = [
        prep.digest({'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':list(order)})
        for order in itertools.permutations(mounts)
    ]
    need(original['configuration_sha256'] in permutation_hashes, 'CRM_CONFIG_DIFFERENCE_BEYOND_MOUNT_ORDER')
    return {'container_id':original['container_id'],'image_id':original['image_id'],
            'started_at':original['started_at'],'original_configuration_sha256':original['configuration_sha256'],
            'mount_order_equivalence_verified':True,'permutation_count':2,
            'canonical_configuration_sha256':prep.digest({
                'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':sorted(mounts,key=prep.digest)})}


def verify_test_evidence(prep):
    summary_path = trusted_file(RELEASE/'candidate-runtime-regressions.json')
    # Pytest's original XML can be 0644 inside its root-owned 0700 directory.
    # Preserve it unchanged and reject writable or linked proof artifacts.
    xml_path = RELEASE/'test-results/regressions.xml'
    parent = xml_path.parent
    need(parent.is_dir() and not parent.is_symlink() and parent.resolve() == parent and
         parent.stat().st_uid == 0 and parent.stat().st_mode & 0o777 == 0o700 and
         xml_path.is_file() and not xml_path.is_symlink() and xml_path.resolve() == xml_path and
         xml_path.stat().st_uid == 0 and xml_path.stat().st_nlink == 1 and
         xml_path.stat().st_mode & 0o777 in (0o600,0o644), 'TEST_XML_PROOF_UNTRUSTED')
    summary = json.loads(summary_path.read_text())
    need(summary.get('stage') == 'PRIVATE_CANDIDATE_REGRESSIONS_PASSED' and summary.get('tests') == EXPECTED_TESTS and
         summary.get('source_test_files') == list(prep.REGRESSION_TESTS) and
         summary.get('actual_candidate_image_tested') is True and summary.get('network') == 'none' and
         summary.get('production_env_loaded') is False and summary.get('production_database_access') is False and
         summary.get('test_only_packages_in_tmpfs') is True, 'ACTUAL_CANDIDATE_TEST_SUMMARY_DRIFT')
    root = ET.parse(xml_path).getroot()
    suites = list(root.iter('testsuite'))
    cases = list(root.iter('testcase'))
    need(suites and sum(int(s.get('tests','0')) for s in suites) == EXPECTED_TESTS and len(cases) == EXPECTED_TESTS and
         all(int(s.get('failures','0')) == int(s.get('errors','0')) == int(s.get('skipped','0')) == 0 for s in suites) and
         not any(list(root.iter(tag)) for tag in ('failure','error','skipped')), 'ACTUAL_CANDIDATE_TEST_XML_FAILED_OR_INCOMPLETE')
    return summary, {'tests':EXPECTED_TESTS,'summary_sha256':sha(summary_path),'xml_sha256':sha(xml_path),
                     'existing_actual_candidate_tests_reverified':True,'tests_rerun':False}


def finalize():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'SERVER_IDENTITY_MISMATCH')
    os.umask(0o077)
    need(RELEASE.is_dir() and not RELEASE.is_symlink() and RELEASE.resolve() == RELEASE and
         RELEASE.stat().st_uid == 0 and not RELEASE.stat().st_mode & 0o077, 'RELEASE_DIRECTORY_UNTRUSTED')
    need(not (RELEASE/'candidate.json').exists() and not (RELEASE/'candidate.json').is_symlink(), 'CANDIDATE_RECEIPT_ALREADY_EXISTS')
    prep = load_prep()
    original = json.loads(trusted_file(RELEASE/'crm-before-safe.json').read_text())
    first_identity = verified_crm_identity(prep,original)
    preserved = original_inventory()
    logs = RELEASE/('finalize-attempt-'+uuid4().hex[:12])
    logs.mkdir(mode=0o700)
    prep.write_json(logs/'original-evidence-hashes.json',preserved)
    spec_path = trusted_file(RELEASE/'release-spec.json')
    archive = trusted_file(RELEASE/'source.tar.gz')
    need(sha(spec_path) == SPEC_SHA and sha(archive) == ARCHIVE_SHA, 'FROZEN_SOURCE_OR_SPEC_DRIFT')
    spec = json.loads(spec_path.read_text())
    base_archive = trusted_file(prep.BASE_RELEASE/'source.tar.gz')
    need(sha(base_archive) == prep.BASE_ARCHIVE_SHA, 'ACCEPTED_BASE_ARCHIVE_DRIFT')
    before = prep.archive_files(base_archive,prep.BASE_SOURCE)
    after = prep.archive_files(archive,SOURCE)
    need(source_manifest(RELEASE/'source') == after, 'EXTRACTED_SOURCE_BYTES_DRIFT')
    args = SimpleNamespace(source_sha=SOURCE,archive_sha256=ARCHIVE_SHA)
    changes = prep.checked_manifest(spec,args,before,after)
    need(json.loads(trusted_file(RELEASE/'source-files.json').read_text()) == after and
         json.loads(trusted_file(RELEASE/'reviewed-changes.json').read_text()) == changes, 'SOURCE_PROOF_DRIFT')
    release_name, tag = prep.release_identity(SOURCE,'retry2')
    need(RELEASE.name == release_name, 'RETRY2_RELEASE_IDENTITY_DRIFT')
    image = trusted_file(RELEASE/'candidate-image.log').read_text().strip()
    need(re.fullmatch(r'sha256:[a-f0-9]{64}',image) is not None and image != prep.BASE_IMAGE, 'BUILT_CANDIDATE_IMAGE_REQUIRED')
    need(prep.run('final-candidate-image',['docker','image','inspect','-f','{{.Id}}',tag],logs) == image and
         prep.run('final-candidate-source',['docker','image','inspect','-f','{{index .Config.Labels "t24.source.sha"}}',image],logs) == SOURCE and
         prep.run('final-base-image',['docker','image','inspect','-f','{{.Id}}',tag+'-base'],logs) == prep.BASE_IMAGE, 'IMMUTABLE_BUILT_IMAGE_DRIFT')
    base_backend = prep.image_scan('final-base-backend',prep.BASE_IMAGE,prep.SCAN_BACKEND,logs)
    actual_backend = prep.image_scan('final-candidate-backend',image,prep.SCAN_BACKEND,logs)
    expected = dict(base_backend)
    for backend_path in sorted(prep.BACKEND_ADDITIONS):
        relative = backend_path[len('app/backend/'):]
        need(relative not in expected, 'PRIVATE_ADDITION_IN_BASE_IMAGE')
        expected[relative] = after[backend_path]
    need(actual_backend == expected == json.loads(trusted_file(RELEASE/'expected-runtime-backend.json').read_text()),
         'ACTUAL_CANDIDATE_BACKEND_BYTES_DRIFT')
    packages = prep.image_scan('final-base-packages',prep.BASE_IMAGE,prep.SCAN_PACKAGES,logs)
    need(prep.image_scan('final-candidate-packages',image,prep.SCAN_PACKAGES,logs) == packages, 'RUNTIME_DEPENDENCIES_CHANGED')
    package_bytes = prep.image_scan('final-base-package-bytes',prep.BASE_IMAGE,prep.SCAN_PACKAGE_BYTES,logs)
    need(prep.image_scan('final-candidate-package-bytes',image,prep.SCAN_PACKAGE_BYTES,logs) == package_bytes, 'RUNTIME_PACKAGE_BYTES_CHANGED')
    baseline_dist = prep.image_scan('final-base-dist',prep.BASE_IMAGE,prep.SCAN_DIST,logs)
    candidate_dist = prep.image_scan('final-candidate-dist',image,prep.SCAN_DIST,logs)
    need(all(candidate_dist.get(filename) == value for filename,value in baseline_dist.items() if filename.startswith('assets/')),
         'BASELINE_ASSET_BYTES_CHANGED')
    public = prep.PUBLIC_RELEASES/release_name
    prep.trusted_parent(prep.PUBLIC_RELEASES,allow_public=True)
    need(public.is_dir() and not public.is_symlink() and public.resolve() == public and public.stat().st_uid == 0,
         'PUBLIC_RELEASE_DIRECTORY_UNTRUSTED')
    for path in [public,*public.rglob('*')]:
        need(not path.is_symlink() and path.stat().st_uid == 0 and
             path.stat().st_mode & 0o777 == (0o755 if path.is_dir() else 0o644), 'PUBLIC_TREE_METADATA_DRIFT')
    exported = prep.file_manifest(RELEASE/'static-dist')
    need(exported == candidate_dist == prep.file_manifest(public), 'EXPORTED_OR_PUBLIC_DIST_BYTES_DRIFT')
    public_proof = json.loads(trusted_file(RELEASE/'candidate-public-files.json').read_text())
    need(public_proof == {'/'+filename:value for filename,value in exported.items()}, 'COMPLETE_PUBLIC_MANIFEST_DRIFT')
    graph = prep.current_graph(public,spec['frontend_version'])
    need(graph == json.loads(trusted_file(RELEASE/'candidate-current-assets.json').read_text()), 'CURRENT_PUBLIC_GRAPH_DRIFT')
    summary,test_proof = verify_test_evidence(prep)
    last_identity = verified_crm_identity(prep,original)
    need(first_identity == last_identity and original_inventory() == preserved, 'ORIGINAL_CRM_OR_EVIDENCE_CHANGED_DURING_FINALIZE')
    final_proof = {'stage':'EXISTING_PRIVATE_CANDIDATE_FINALIZATION_VERIFIED','source_sha':SOURCE,'image_id':image,
                   'frozen_preparer_sha256':PREPARE_SHA,'crm_identity':last_identity,'test_evidence':test_proof,
                   'original_evidence_hashes':preserved,'candidate_backend_sha256':prep.digest(expected),
                   'package_tree_sha256':package_bytes['sha256'],'public_manifest_sha256':sha(RELEASE/'candidate-public-files.json'),
                   'current_graph_sha256':sha(RELEASE/'candidate-current-assets.json'),'production_database_accessed':False,
                   'production_services_started':False,'nginx_modified':False,'builds_rerun':False}
    proof_path = logs/'finalization-verified.json'
    prep.write_json(proof_path,final_proof)
    receipt = {'stage':'PRIVATE_WORKSPACE_CANDIDATE_VERIFIED','source_sha':SOURCE,'archive_sha256':ARCHIVE_SHA,
        'release_spec_sha256':SPEC_SHA,'baseline_source_sha':prep.BASE_SOURCE,'base_image_id':prep.BASE_IMAGE,
        'image_id':image,'image_tag':tag,'version':spec['frontend_version'],'release_directory':str(RELEASE),
        'public_directory':str(public),'backend_added_files':sorted(prep.BACKEND_ADDITIONS),'all_baseline_backend_bytes_identical':True,
        'backend_manifest_sha256':prep.digest(expected),'runtime_dependencies_unchanged':True,'runtime_package_bytes_identical':True,
        'runtime_package_tree_sha256':package_bytes['sha256'],'candidate_runtime_regression_tests':summary['tests'],
        'candidate_runtime_tests_verified':True,'existing_assets_preserved':True,
        'existing_asset_count':sum(filename.startswith('assets/') for filename in baseline_dist),'public_files':len(exported),
        'public_manifest_sha256':sha(RELEASE/'candidate-public-files.json'),'current_assets_proof_sha256':sha(RELEASE/'candidate-current-assets.json'),
        'crm_container_id':original['container_id'],'crm_container_unchanged':True,'production_database_accessed':False,
        'production_database_mutations_performed':False,'private_production_services_started':False,'nginx_modified':False,
        'deployment_performed':False,'release_suffix':'retry2','preparation_log_directory':str(RELEASE),
        'mount_order_equivalence_verified':True,'finalization_proof':str(proof_path),'finalization_proof_sha256':sha(proof_path)}
    need(original_inventory() == preserved and verified_crm_identity(prep,original) == last_identity,
         'PRE_RECEIPT_ORIGINAL_EVIDENCE_OR_CRM_DRIFT')
    prep.write_json(RELEASE/'candidate.json',receipt)
    print(json.dumps(receipt,sort_keys=True),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    if args.execute:
        finalize()
    else:
        print(json.dumps({'stage':'PLAN_ONLY','source_sha':SOURCE,'production_actions_performed':False},sort_keys=True))
