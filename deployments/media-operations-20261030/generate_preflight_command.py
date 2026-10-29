"""Emit a hash-pinned read-only preflight command, without executing it."""
from pathlib import Path
import base64, hashlib, zlib
root=Path(__file__).resolve().parent
body=(root/'preflight.py').read_bytes();digest=hashlib.sha256(body).hexdigest();packed=base64.b64encode(zlib.compress(body,9)).decode()
command="#!/bin/bash\nset -eu\nsudo python3 -B - <<'MEDIA_OPERATIONS_READONLY'\nimport base64,hashlib,zlib\nbody=zlib.decompress(base64.b64decode("+repr(packed)+"))\nassert hashlib.sha256(body).hexdigest()=="+repr(digest)+",'PREFLIGHT_HASH_DRIFT'\nnamespace={'__name__':'media_operations_readonly_preflight'}\nexec(compile(body,'hash-pinned-media-operations-preflight','exec'),namespace)\nnamespace['main']()\nMEDIA_OPERATIONS_READONLY\n"
(root/'preflight-command.sh').write_text(command);(root/'preflight-command.sh').chmod(0o600)
print('readonly_preflight_sha256='+digest)
