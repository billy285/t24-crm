"""Generate capture/read commands and reassemble full facts locally; never call a server."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()


def helper(root=HERE):
    spec = importlib.util.spec_from_file_location('_media_management_capture_tool', root / 'capture_preflight.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def shell(code):
    return "#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'MEDIA_OPS_MANAGEMENT_FACTS'\n" + code + "\nMEDIA_OPS_MANAGEMENT_FACTS\n"


def save_command(path, command):
    path.write_text(command); path.chmod(0o600)
    return {'path': str(path), 'sha256': H(command.encode()), 'bytes': len(command.encode())}


def execute_wrapper(load, action):
    return ("import base64,hashlib,json,re,zlib\n" + load + "\ntry:\n " + action + "\n"
        "except BaseException as error:\n"
        " value=str(error)\n"
        " code=value if isinstance(error,RuntimeError) and re.fullmatch('[A-Z0-9_]{1,100}',value) else 'CAPTURE_OPERATION_FAILED'\n"
        " print(json.dumps({'stage':'MEDIA_OPS_MANAGEMENT_CAPTURE_REJECTED','code':code}))\n"
        " raise SystemExit(1)\n")


def generate_capture(root=HERE):
    module = helper(root)
    preflight = (root / 'preflight.py').read_bytes()
    capture = (root / 'capture_preflight.py').read_bytes()
    if H(preflight) != module.PREFLIGHT_SHA: raise RuntimeError('ORIGINAL_PREFLIGHT_SOURCE_HASH_REQUIRED')
    bundle = json.dumps({'preflight': preflight.decode(), 'capture': capture.decode()}, sort_keys=True).encode()
    packed = base64.b64encode(zlib.compress(bundle, 9)).decode()
    load = ("blob=zlib.decompress(base64.b64decode(" + repr(packed) + ",validate=True))\n"
        "assert hashlib.sha256(blob).hexdigest()==" + repr(H(bundle)) + ",'FACTS_BUNDLE_HASH_DRIFT'\n"
        "sources=json.loads(blob)\n"
        "assert hashlib.sha256(sources['preflight'].encode()).hexdigest()==" + repr(H(preflight)) + ",'PREFLIGHT_HASH_DRIFT'\n"
        "assert hashlib.sha256(sources['capture'].encode()).hexdigest()==" + repr(H(capture)) + ",'CAPTURE_TOOL_HASH_DRIFT'\n"
        "p={'__name__':'media_management_readonly_preflight'}\n"
        "c={'__name__':'media_management_capture'}\n"
        "exec(compile(sources['preflight'],'fixed-readonly-preflight','exec'),p)\n"
        "exec(compile(sources['capture'],'fixed-proof-capture','exec'),c)")
    command = shell(execute_wrapper(load, "print(json.dumps(c['capture'](p),sort_keys=True))"))
    return {**save_command(root / 'capture-preflight-command.sh', command), 'preflight_sha256': H(preflight), 'capture_tool_sha256': H(capture)}


def generate_chunks(manifest, root=HERE):
    module = helper(root); module.checked_manifest(manifest)
    capture = (root / 'capture_preflight.py').read_bytes()
    packed = base64.b64encode(zlib.compress(capture, 9)).decode()
    load = ("body=zlib.decompress(base64.b64decode(" + repr(packed) + ",validate=True))\n"
        "assert hashlib.sha256(body).hexdigest()==" + repr(H(capture)) + ",'CAPTURE_READER_HASH_DRIFT'\n"
        "c={'__name__':'media_management_fact_reader'}\n"
        "exec(compile(body,'fixed-complete-proof-reader','exec'),c)\n"
        "manifest=json.loads(" + repr(json.dumps(manifest, sort_keys=True, separators=(',', ':'))) + ")")
    result = []
    for index in range(manifest['chunk_count']):
        command = shell(execute_wrapper(load, "print(json.dumps(c['read_chunk'](manifest," + str(index) + "),sort_keys=True))"))
        result.append({**save_command(root / ('read-preflight-chunk-%02d.sh' % index), command), 'index': index})
    return result


def reassemble_files(manifest, chunks, output, root=HERE):
    module = helper(root); body = module.reassemble(manifest, chunks)
    value = json.loads(body)
    if value.get('stage') != 'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT': raise RuntimeError('PREFLIGHT_PROOF_STAGE_REQUIRED')
    output = Path(output)
    if output.exists():
        if output.is_symlink() or output.read_bytes() != body: raise RuntimeError('EXISTING_PREFLIGHT_OUTPUT_DRIFT')
    else:
        with output.open('xb') as stream: stream.write(body)
        output.chmod(0o600)
    return {'stage': value['stage'], 'proof_bytes': len(body), 'proof_sha256': H(body),
        'path': str(output), 'chunk_count': len(chunks)}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('phase', choices=['capture', 'chunks', 'reassemble'])
    parser.add_argument('--manifest', type=Path); parser.add_argument('--chunks-directory', type=Path); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.phase == 'capture': result = generate_capture()
    else:
        if args.manifest is None: raise RuntimeError('CAPTURE_MANIFEST_FILE_REQUIRED')
        manifest = json.loads(args.manifest.read_text())
        if args.phase == 'chunks': result = generate_chunks(manifest)
        else:
            if args.chunks_directory is None or args.output is None: raise RuntimeError('CHUNK_DIRECTORY_AND_OUTPUT_REQUIRED')
            chunks = [json.loads((args.chunks_directory / ('chunk-%02d.json' % index)).read_text()) for index in range(manifest['chunk_count'])]
            result = reassemble_files(manifest, chunks, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
