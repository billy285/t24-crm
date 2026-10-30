"""Emit a self-contained hash-pinned read-only command; never execute remotely."""
from pathlib import Path
import base64
import hashlib
import zlib


def generate(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    body = (root / 'preflight.py').read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    packed = base64.b64encode(zlib.compress(body, 9)).decode()
    command = ("#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<'MEDIA_OPS_MANAGEMENT_READONLY'\n"
        "import base64,hashlib,json,re,zlib\n"
        "body=zlib.decompress(base64.b64decode(" + repr(packed) + ",validate=True))\n"
        "assert hashlib.sha256(body).hexdigest()==" + repr(digest) + ",'PREFLIGHT_HASH_DRIFT'\n"
        "namespace={'__name__':'media_ops_management_readonly_preflight'}\n"
        "exec(compile(body,'hash-pinned-media-ops-management-preflight','exec'),namespace)\n"
        "try:\n namespace['main']()\n"
        "except BaseException as error:\n"
        " value=str(error)\n"
        " code=value if isinstance(error,RuntimeError) and re.fullmatch('[A-Z0-9_]{1,100}',value) else 'READONLY_PREFLIGHT_FAILED'\n"
        " print(json.dumps({'stage':'MEDIA_OPS_MANAGEMENT_PREFLIGHT_REJECTED','code':code}))\n"
        " raise SystemExit(1)\nMEDIA_OPS_MANAGEMENT_READONLY\n")
    path = root / 'preflight-command.sh'
    path.write_text(command)
    path.chmod(0o600)
    return {'readonly_preflight_sha256': digest, 'command_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'command_bytes': len(command.encode())}


if __name__ == '__main__':
    import json
    print(json.dumps(generate(), sort_keys=True))
