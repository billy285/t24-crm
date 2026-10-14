#!/usr/bin/env python3
"""Reuse exact reviewed app/static bytes for a separately reviewed runtime guard."""
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

SOURCE = 'f96eaa209f2d795efb6f5d780bf54b144a6ee380'
CARRIER = '866320ba65b896193df895bda1dd1165aa47f6a2'
VERSION = 'ebdd4929c921'
OLD_DIRECTORY = 'deployments/sales-note-templates-20261014/artifacts/'
OLD_MANIFEST_SHA = '1d3911a857415a3b917b9c5e9db4da1429de2a1887ab8ffa364db9f0455e49e6'
PAYLOAD_SHA = '9fd341069e77b2ba2146831b7fbf4fcb0acbb949420205630bf7dc735d6a4b3c'
FRONTEND = {'components/SalesCallRecord.tsx', 'pages/sales-calling-controls.css'}
BACKEND = set()
PRESERVED = {'company_finance_formulas': True, 'close_conditions': True,
             'private_workspace': True, 'customer_invitation_rules': True,
             'commission_attribution': True, 'import_template': True}
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value:
        raise RuntimeError(code)


def git(*args):
    return subprocess.check_output(['git', *args])


def inventory(ref):
    with tarfile.open(fileobj=io.BytesIO(git('archive', ref, 'app/')), mode='r:') as archive:
        return {item.name: H(archive.extractfile(item).read()) for item in archive if item.isfile()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    need(args.source == SOURCE, 'EXACT_REVIEWED_APP_SOURCE_REQUIRED')
    original = git('show', CARRIER + ':' + OLD_DIRECTORY + 'manifest.json')
    payload = git('show', CARRIER + ':' + OLD_DIRECTORY + 'payload.tar.gz')
    need(H(original) == OLD_MANIFEST_SHA and H(payload) == PAYLOAD_SHA, 'REVIEWED_ORIGINAL_ARTIFACT_DRIFT')
    manifest = json.loads(original)
    need(manifest['source_sha'] == SOURCE and manifest['frontend_version'] == VERSION and manifest['payload_sha256'] == PAYLOAD_SHA, 'REVIEWED_ORIGINAL_SOURCE_DRIFT')
    source = inventory(SOURCE)
    need(inventory('HEAD') == source, 'CURRENT_APP_SOURCE_DRIFT')
    for name, expected in source.items():
        need(H(Path(name).read_bytes()) == expected, 'WORKING_APP_SOURCE_DRIFT')
    before = inventory(manifest['baseline_source_sha'])
    changed = {name for name in before.keys() | source.keys() if before.get(name) != source.get(name)}
    need(changed == set(manifest['changed_source_files']), 'ORIGINAL_SOURCE_DELTA_DRIFT')
    tests = {name for name in changed if name.startswith('app/frontend/tests/')}
    need(changed - tests == {'app/frontend/src/' + name for name in FRONTEND}, 'EXACT_REVIEWED_APP_SCOPE_REQUIRED')
    need(manifest['protected_source_inventory'] == {name: value for name, value in before.items() if name not in changed}, 'PROTECTED_INVENTORY_DRIFT')
    need(all(source[name] == value for name, value in manifest['protected_source_inventory'].items()), 'PROTECTED_SOURCE_DRIFT')
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        seen = set()
        for item in archive:
            need(item.isfile() and item.name.startswith('static/') and item.name not in seen and item.name in manifest['files'], 'EXACT_STATIC_MEMBERS_REQUIRED')
            body = archive.extractfile(item).read()
            need(H(body) == manifest['files'][item.name], 'STATIC_MEMBER_DRIFT')
            if item.name == 'static/app-version.json':
                need(json.loads(body)['version'] == VERSION, 'STATIC_VERSION_DRIFT')
            seen.add(item.name)
        need(seen == set(manifest['files']), 'STATIC_MEMBERS_INCOMPLETE')
    manifest['runtime_guard'] = 'complete_mount_record_order_only'
    manifest['retry_of_release'] = 'sales-note-templates-f96eaa209f2d-20261014'
    manifest['original_artifact_carrier'] = CARRIER
    manifest['original_manifest_sha256'] = OLD_MANIFEST_SHA
    args.out.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    for name, content in {'manifest.json': body, 'payload.tar.gz': payload}.items():
        with (args.out / name).open('xb') as stream:
            stream.write(content)
    print(json.dumps({'source': SOURCE, 'version': VERSION, 'payload_sha256': H(payload),
                      'manifest_sha256': H(body), 'static_payload_unchanged': True,
                      'protected_files': len(manifest['protected_source_inventory'])}))


if __name__ == '__main__':
    main()
