#!/usr/bin/env python3
"""Package one frozen frontend. No credentials, databases or preview fixtures."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
ART = Path(__file__).resolve().parent / 'artifacts'
SOURCE = '0bc1dd5bba38ecd518dc3546bcacb02f91881807'
BASELINE = '9d10d98fff6779fd9e6bace22a761fa7b4c8b45f'
VERSION = '8f7b36df4162'
NODE = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
ALLOWED = {
    'app/frontend/src/components/Layout.tsx', 'app/frontend/src/components/crm-desktop-layout.css',
    'app/frontend/src/pages/Dashboard.tsx', 'app/frontend/src/pages/Customers.tsx',
    'app/frontend/src/pages/OperationsWorkbench.tsx',
}
H = lambda data: hashlib.sha256(data).hexdigest()

def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=REPO)

def inventory(ref, prefix):
    names = git('ls-tree', '-r', '--name-only', ref, prefix).decode().splitlines()
    return {name: H(git('show', ref + ':' + name)) for name in names}

def package():
    assert git('rev-parse', 'HEAD').decode().strip() == SOURCE
    assert set(git('diff', '--name-only', BASELINE, SOURCE).decode().splitlines()) == ALLOWED
    backend = inventory(SOURCE, 'app/backend/')
    assert backend == inventory(BASELINE, 'app/backend/')
    frontend = inventory(SOURCE, 'app/frontend/src/')
    previous = inventory(BASELINE, 'app/frontend/src/')
    kept = {name: value for name, value in frontend.items() if name not in ALLOWED}
    assert kept == {name: value for name, value in previous.items() if name not in ALLOWED}
    for name, value in frontend.items():
        assert H((REPO / name).read_bytes()) == value
    script = """const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=process.argv[1],digest=crypto.createHash('sha256'),files={};
function visit(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
 const file=path.join(dir,e.name);if(e.isDirectory())visit(file);else if(e.isFile()){
 const name=path.relative(root,file),data=fs.readFileSync(file);digest.update(name);digest.update(data);
 files[name]=crypto.createHash('sha256').update(data).digest('hex');}}}
visit(root);process.stdout.write(JSON.stringify({version:digest.digest('hex').slice(0,12),files}));"""
    actual = json.loads(subprocess.check_output([NODE, '-e', script, str(REPO / 'app/frontend/src')]))
    assert actual['version'] == VERSION
    assert actual['files'] == {name.removeprefix('app/frontend/src/'): value for name, value in frontend.items()}
    dist = REPO / 'app/frontend/dist'
    assert json.loads((dist / 'app-version.json').read_bytes()) == {'version': VERSION}
    files = {}
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(dist.rglob('*')):
                assert not path.is_symlink()
                if not path.is_file():
                    continue
                name, data = path.relative_to(dist).as_posix(), path.read_bytes()
                assert not any(part.startswith('.') for part in Path(name).parts)
                assert path.suffix in {'.html', '.js', '.css', '.json', '.png', '.svg', '.txt', '.webmanifest'}
                entry = tarfile.TarInfo('payload/' + name)
                entry.size, entry.mode, entry.uid, entry.gid, entry.mtime = len(data), 0o644, 0, 0, 0
                archive.addfile(entry, io.BytesIO(data))
                files[name] = H(data)
    payload = output.getvalue()
    manifest = {
        'format_version': 1, 'stage': 'CRM_DESKTOP_COMFORT_STATIC_PAYLOAD_PREPARED',
        'source_sha': SOURCE, 'baseline_source_sha': BASELINE,
        'frontend_version': VERSION, 'baseline_frontend_version': '22b2d2ad92c2',
        'static_only': True, 'backend_changes': False, 'credentials_included': False,
        'databases_modified': False, 'services_modified': False, 'environment_modified': False,
        'changed_source_files': {name: frontend[name] for name in sorted(ALLOWED)},
        'preserved_source_inventories': {'backend': backend, 'private_frontend': kept},
        'frontend_source_inventory': frontend,
        'layout_scope': {'min_width': 1024, 'max_width': 1599, 'large_desktop_geometry_preserved': True,
            'private_workspace_geometry_preserved': True, 'financial_calculations_preserved': True},
        'payload_files': files, 'payload_sha256': H(payload),
        'frontend_typecheck_passed': True, 'frontend_production_build_passed': True,
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / 'static-payload.tar.gz').write_bytes(payload)
    (ART / 'static-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'source': SOURCE, 'version': VERSION, 'dist_files': len(files),
        'backend_files_preserved': len(backend), 'private_dependencies_preserved': len(kept),
        'payload_sha256': H(payload), 'manifest_sha256': H((ART / 'static-manifest.json').read_bytes())}))

if __name__ == '__main__':
    package()
