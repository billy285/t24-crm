"""Helper-only synthetic repair; no live runtime, network or Docker actions."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location('stripe_helper_repair', Path(__file__).with_name('repair_upgrade_helper.py'))
r = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(r)


def zip_bytes(carrier, entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo('t24-crm-' + carrier + '/' + name)
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return output.getvalue()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    tmp_path.chmod(0o700); monkeypatch.setattr(r, 'ROOT_UID', os.geteuid()); monkeypatch.setattr(r, 'ancestors', lambda path: None)
    release = tmp_path / 'release'; release.mkdir(mode=0o700)
    config = tmp_path / 'config'; config.mkdir(mode=0o700)
    for name, data in [('private-finance-release.lock', b''), ('runtime.env', b'SYNTHETIC_RUNTIME_ONLY=true\n')]:
        (config / name).write_bytes(data); (config / name).chmod(0o600)
    public = tmp_path / 'never-published'; monkeypatch.setattr(r, 'PUBLIC', public)
    old_helper = b'"""Synthetic previous upgrade helper."""\n'
    new_helper = b'"""Synthetic reviewed upgrade helper."""\n'
    monkeypatch.setattr(r, 'OLD_UPGRADE_HASH', r.sha(old_helper)); monkeypatch.setattr(r, 'NEW_UPGRADE_HASH', r.sha(new_helper))
    (release / 'prepared-backend/payload/frontend/dist').mkdir(mode=0o700, parents=True)
    for directory in (release / 'prepared-backend', release / 'prepared-backend/payload', release / 'prepared-backend/payload/frontend'):
        directory.chmod(0o700)
    static = release / 'prepared-backend/payload/frontend/dist/index.html'; static.write_bytes(b'Synthetic frozen UI'); static.chmod(0o600)
    frozen = {'source_sha': r.SOURCE}
    raw_frozen = r.encoded(frozen); raw_payload = b'Synthetic already verified payload'
    manifest = {'source_sha': r.SOURCE, 'frozen_manifest_sha256': r.sha(raw_frozen), 'payload_sha256': r.sha(raw_payload),
                'payload_files': {'frontend/dist/index.html': r.sha(static.read_bytes())}}
    raw_manifest = r.encoded(manifest)
    candidate = {'source_sha': r.SOURCE, 'stage': 'STRIPE_REPORT_BACKEND_CANDIDATE_VERIFIED', 'base_image_id': r.BASE_IMAGE,
                 'payload_manifest_sha256': r.sha(raw_manifest), 'frozen_source_sha256': r.sha(raw_frozen), 'payload_sha256': r.sha(raw_payload)}
    files = {'prepare_candidate.py': b'"""Synthetic immutable preparation."""\n', 'prepared-backend/candidate.json': r.encoded(candidate),
             'stripe-report-manifest.json': raw_manifest, 'frozen-source.json': raw_frozen, 'stripe-report-payload.tar.gz': raw_payload}
    for name, data in files.items():
        path = release / name; path.write_bytes(data); path.chmod(0o600)
    monkeypatch.setattr(r, 'PRESERVED', {name: r.sha(data) for name, data in files.items()})
    acquired = {'format_version': 1, 'stage': 'STRIPE_REPORT_CARRIER_ACQUIRED', 'directory': str(release), 'frontend_source_sha': r.SOURCE,
                'carrier_sha': 'a' * 40, 'archive_sha256': 'b' * 64,
                'files': {**{name: digest for name, digest in r.PRESERVED.items() if '/' not in name}, 'upgrade.py': r.OLD_UPGRADE_HASH},
                **{key: False for key in ('backend_services_modified', 'databases_modified', 'credentials_included', 'public_assets_published', 'deployed')}}
    raw_acquired = r.encoded(acquired); monkeypatch.setattr(r, 'OLD_ACQUIRED_HASH', r.sha(raw_acquired))
    for name, data in [('acquired.json', raw_acquired), ('upgrade.py', old_helper)]:
        path = release / name; path.write_bytes(data); path.chmod(0o600)
    carrier = 'c' * 40
    archive = zip_bytes(carrier, [('deployments/stripe-report-20261012/upgrade.py', new_helper, stat.S_IFREG | 0o644),
                                ('ignored-file.txt', b'Never extracted', stat.S_IFREG | 0o644)])
    nginx = b'Synthetic unchanged Nginx'; monkeypatch.setattr(r, 'NGINX_HASH', r.sha(nginx)); monkeypatch.setattr(r, 'ENV_HASH', r.sha((config / 'runtime.env').read_bytes()))
    runtime = {'crm': {'identity': 'synthetic unchanged'}, 'private': {'image': r.BASE_IMAGE, 'tables': 10}}
    base = SimpleNamespace(CONFIG=config, ENV=config / 'runtime.env', read_nginx=lambda: nginx)
    nav = SimpleNamespace(accepted_receipts=lambda base: ({}, {}, {}), runtime=lambda *args: copy.deepcopy(runtime))
    return SimpleNamespace(release=release, base=base, nav=nav, archive=archive, carrier=carrier, old_helper=old_helper,
                           new_helper=new_helper, old_receipt=raw_acquired, frozen=files, runtime=runtime, public=public)


def repair(lane, **overrides):
    arguments = {'old_acquired_hash': r.OLD_ACQUIRED_HASH, 'carrier': lane.carrier, 'archive_hash': r.sha(lane.archive),
                 'helper_hash': r.NEW_UPGRADE_HASH, 'base': lane.base, 'nav': lane.nav, 'archive_bytes': lane.archive}
    arguments.update(overrides)
    return r.repair(lane.release, **arguments)


def test_repairs_only_reviewed_helper_and_provenance_pair(lane):
    before = {name: ((lane.release / name).read_bytes(), (lane.release / name).stat().st_ino) for name in lane.frozen}
    config_before = {path.name: (path.read_bytes(), path.stat().st_ino) for path in lane.base.CONFIG.iterdir()}
    proof = repair(lane)
    assert proof['stage'] == 'STRIPE_REPORT_UPGRADE_HELPER_REPAIRED' and proof['deployed'] is False
    assert (lane.release / 'upgrade.py').read_bytes() == lane.new_helper
    assert {name: ((lane.release / name).read_bytes(), (lane.release / name).stat().st_ino) for name in lane.frozen} == before
    assert {path.name: (path.read_bytes(), path.stat().st_ino) for path in lane.base.CONFIG.iterdir()} == config_before
    acquired = json.loads((lane.release / 'acquired.json').read_bytes())
    original = json.loads(lane.old_receipt)
    assert acquired['files'] == {**original['files'], 'upgrade.py': r.NEW_UPGRADE_HASH}
    assert acquired['carrier_sha'] == lane.carrier and acquired['archive_sha256'] == r.sha(lane.archive)
    assert acquired['helper_repair']['previous_carrier_sha'] == original['carrier_sha']
    assert acquired['helper_repair']['old_acquired_sha256'] == r.sha(lane.old_receipt)
    folder = lane.release / 'upgrade-helper-repair'
    assert (folder / 'upgrade-before.py').read_bytes() == lane.old_helper
    assert (folder / 'acquired-before.json').read_bytes() == lane.old_receipt
    assert (folder / 'acquired-reviewed.json').read_bytes() == (lane.release / 'acquired.json').read_bytes()
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in folder.iterdir())
    assert not (lane.release / 'ignored-file.txt').exists() and not lane.public.exists()


@pytest.mark.parametrize('target,symlink', [('upgrade-state.json', False), ('upgrade-state.json', True), ('live-upgrade', False), ('live-upgrade', True), ('public', True)])
def test_rejects_activation_and_dangling_markers_before_any_repair(lane, target, symlink):
    path = lane.public if target == 'public' else lane.release / target
    if symlink: path.symlink_to('missing-target')
    else: path.write_bytes(b'synthetic activation marker')
    with pytest.raises(r.RepairError, match='ACTIVATION_ALREADY_STARTED_REPAIR_REJECTED'): repair(lane)
    assert (lane.release / 'upgrade.py').read_bytes() == lane.old_helper
    assert (lane.release / 'acquired.json').read_bytes() == lane.old_receipt
    assert not (lane.release / 'upgrade-helper-repair').exists()


@pytest.mark.parametrize('name', ['prepare_candidate.py', 'prepared-backend/candidate.json', 'stripe-report-manifest.json', 'frozen-source.json', 'stripe-report-payload.tar.gz', 'upgrade.py', 'acquired.json', 'prepared-backend/payload/frontend/dist/index.html'])
def test_rejects_any_old_artifact_helper_or_payload_drift(lane, name):
    (lane.release / name).write_bytes(b'synthetic drift')
    with pytest.raises(r.RepairError): repair(lane)
    assert not (lane.release / 'upgrade-helper-repair').exists()


@pytest.mark.parametrize('field,value', [('old_acquired_hash', '0' * 64), ('carrier', 'main'), ('archive_hash', '0' * 64), ('helper_hash', '0' * 64)])
def test_requires_independently_reviewed_old_new_and_carrier_hashes(lane, field, value):
    with pytest.raises(r.RepairError): repair(lane, **{field: value})
    assert not (lane.release / 'upgrade-helper-repair').exists()


def test_detects_runtime_drift_before_any_replacement(lane):
    calls = []
    def changing_runtime(*args):
        calls.append(True)
        return {**lane.runtime, 'change': len(calls)}
    lane.nav.runtime = changing_runtime
    with pytest.raises(r.RepairError, match='PRE_REPAIR_STATE_DRIFT'): repair(lane)
    assert (lane.release / 'upgrade.py').read_bytes() == lane.old_helper
    assert not (lane.release / 'upgrade-helper-repair').exists()


def test_immediate_activation_race_is_rejected_with_original_pair_intact(lane, monkeypatch):
    original = r.write_new
    def activation_race(path, data):
        original(path, data)
        if path.name == 'repair.json': (lane.release / 'upgrade-state.json').write_bytes(b'Synthetic race')
    monkeypatch.setattr(r, 'write_new', activation_race)
    with pytest.raises(r.RepairError, match='ACTIVATION_ALREADY_STARTED_REPAIR_REJECTED'): repair(lane)
    assert (lane.release / 'upgrade.py').read_bytes() == lane.old_helper
    assert (lane.release / 'acquired.json').read_bytes() == lane.old_receipt


def test_crash_between_pair_replacements_remains_fail_closed_with_exact_recovery_bytes(lane, monkeypatch):
    original = r.replace_fixed
    def crash(path, old_hash, data):
        if path.name == 'acquired.json': raise OSError('synthetic crash')
        original(path, old_hash, data)
    monkeypatch.setattr(r, 'replace_fixed', crash)
    with pytest.raises(OSError): repair(lane)
    assert (lane.release / 'upgrade.py').read_bytes() == lane.new_helper
    assert (lane.release / 'acquired.json').read_bytes() == lane.old_receipt
    acquired = json.loads(lane.old_receipt)
    assert acquired['files']['upgrade.py'] != r.sha((lane.release / 'upgrade.py').read_bytes())
    folder = lane.release / 'upgrade-helper-repair'
    assert json.loads((folder / 'repair.json').read_bytes())['stage'] == 'STRIPE_REPORT_UPGRADE_HELPER_REPAIR_PREPARED'
    assert (folder / 'upgrade-before.py').read_bytes() == lane.old_helper
    assert (folder / 'acquired-reviewed.json').read_bytes()
    with pytest.raises(r.RepairError): repair(lane)


def test_read_fixed_allows_atime_change_and_rejects_mutation_metadata(lane, monkeypatch):
    path = lane.release / 'upgrade.py'; original = r.protected; count = []
    def changed_atime(target, directory=False):
        info = original(target, directory); count.append(True)
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
        fields['st_atime_ns'] += len(count)
        return SimpleNamespace(**fields)
    monkeypatch.setattr(r, 'protected', changed_atime)
    assert r.read_fixed(path, r.OLD_UPGRADE_HASH) == lane.old_helper
    count.clear()
    def changed_mtime(target, directory=False):
        info = changed_atime(target, directory)
        if len(count) > 1: info.st_mtime_ns += 1
        return info
    monkeypatch.setattr(r, 'protected', changed_mtime)
    with pytest.raises(r.RepairError, match='FILE_MUTATED_DURING_READ'): r.read_fixed(path)


def test_atomic_replacement_tolerates_its_own_parent_timestamp_change(lane):
    target = lane.release / 'upgrade.py'
    r.replace_fixed(target, r.OLD_UPGRADE_HASH, lane.new_helper)
    assert target.read_bytes() == lane.new_helper and target.stat().st_mode & 0o777 == 0o600
    assert not list(lane.release.glob('.upgrade.py-reviewed-*'))


@pytest.mark.parametrize('change', ['symlink', 'hardlink', 'permission'])
def test_rejects_unprotected_helper_files(lane, change):
    target = lane.release / 'upgrade.py'
    if change == 'symlink':
        target.unlink(); target.symlink_to(lane.release / 'prepare_candidate.py')
    elif change == 'hardlink': os.link(target, lane.release / 'another-link')
    else: target.chmod(0o644)
    with pytest.raises(r.RepairError): r.read_fixed(target)


@pytest.mark.parametrize('relative,mode', [('../escape', stat.S_IFREG | 0o644), ('a/../../escape', stat.S_IFREG | 0o644),
    ('a\\escape', stat.S_IFREG | 0o644), ('deployments/stripe-report-20261012/upgrade.py', stat.S_IFLNK | 0o777)])
def test_archive_rejects_noncanonical_paths_and_selected_symlink(lane, relative, mode):
    payload = zip_bytes(lane.carrier, [(relative, lane.new_helper, mode)])
    with pytest.raises(r.RepairError): r.selected_helper(payload, lane.carrier, r.sha(payload), r.NEW_UPGRADE_HASH)


def test_archive_requires_unique_helper_and_exact_bytes(lane):
    name = 'deployments/stripe-report-20261012/upgrade.py'
    with pytest.warns(UserWarning): duplicate = zip_bytes(lane.carrier, [(name, lane.new_helper, stat.S_IFREG | 0o644)] * 2)
    with pytest.raises(r.RepairError, match='UNIQUE_BOUNDED_ARCHIVE_REQUIRED'): r.selected_helper(duplicate, lane.carrier, r.sha(duplicate), r.NEW_UPGRADE_HASH)
    wrong = zip_bytes(lane.carrier, [(name, b'wrong reviewed bytes', stat.S_IFREG | 0o644)])
    with pytest.raises(r.RepairError, match='NEW_HELPER_BYTES_DRIFT'): r.selected_helper(wrong, lane.carrier, r.sha(wrong), r.NEW_UPGRADE_HASH)
    missing = zip_bytes(lane.carrier, [('other.py', lane.new_helper, stat.S_IFREG | 0o644)])
    with pytest.raises(r.RepairError, match='NEW_HELPER_REQUIRED'): r.selected_helper(missing, lane.carrier, r.sha(missing), r.NEW_UPGRADE_HASH)


def test_archive_size_bound_precedes_zip_parsing(lane, monkeypatch):
    monkeypatch.setattr(r, 'MAX_ARCHIVE', 10)
    with pytest.raises(r.RepairError, match='EXACT_NEW_REVIEWED_CARRIER_REQUIRED'):
        r.selected_helper(lane.archive, lane.carrier, r.sha(lane.archive), r.NEW_UPGRADE_HASH)


def test_existing_lock_is_required_without_creating_config(lane):
    (lane.base.CONFIG / 'private-finance-release.lock').unlink()
    with pytest.raises(FileNotFoundError): repair(lane)
    assert not (lane.base.CONFIG / 'private-finance-release.lock').exists()
