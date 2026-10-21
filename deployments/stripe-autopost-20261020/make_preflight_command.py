"""Encode the reviewed read-only script without executing a server operation."""
import base64
import hashlib
import zlib
from pathlib import Path

root = Path(__file__).resolve().parent
source = (root / "preflight.py").read_bytes()
encoded = base64.b64encode(zlib.compress(source, 9)).decode()
sha = hashlib.sha256(source).hexdigest()
command = "#!/bin/bash\nset -eu\nsudo python3 -B - <<'PY'\nimport base64,hashlib,zlib\nsource=zlib.decompress(base64.b64decode(" + repr(encoded) + "))\nassert hashlib.sha256(source).hexdigest()==" + repr(sha) + "\nexec(compile(source,'reviewed-stripe-autopost-readonly-preflight','exec'),{'__name__':'__main__'})\nPY\n"
output = root / "preflight-command.sh"
output.write_text(command)
output.chmod(0o600)
print(str(output))
