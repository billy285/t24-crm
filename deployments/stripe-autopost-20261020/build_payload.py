"""Build an exact, secret-free source overlay and frontend payload locally."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("autopost_release_scope", ROOT / "release.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()
FRONTEND = {
    "components/StripeHistoryReconciliation.tsx", "components/StripeHistoryReminders.tsx",
    "components/stripe-history-reminders.css", "lib/stripe-history-reconciliation.ts",
    "lib/stripe-history-reminders.ts", "components/StripeAutoPosting.tsx",
    "components/stripe-auto-posting.css", "lib/stripe-auto-posting.ts",
}
TESTS = {
    "app/backend/tests/test_stripe_auto_posting.py",
    "app/backend/tests/test_stripe_autopost_close_serialization.py",
    "app/frontend/tests/stripe-auto-posting.unit.test.mjs",
    "app/frontend/tests/stripe-history-reconciliation-api.spec.ts",
    "app/frontend/tests/stripe-history-reconciliation.spec.ts",
}


def git(*args):
    return subprocess.check_output(["git", *args])


def inventory(ref):
    return {path: H(git("show", ref + ":" + path))
        for path in git("ls-tree", "-r", "--name-only", ref, "--", "app/").decode().splitlines()}


def source_version():
    node = "/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    script = """const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
    return subprocess.check_output([node, "-e", script, str(Path("app/frontend/src").resolve())]).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    r.need(bool(re.fullmatch("[a-f0-9]{40}", args.source)), "EXACT_APPLICATION_SOURCE_REQUIRED")
    proof_body = args.preflight.read_bytes()
    proof = json.loads(proof_body)
    r.need(proof["stage"] == "STRIPE_AUTOMATIC_POSTING_READONLY_PREFLIGHT" and proof["source_sha"] == r.BASE_SOURCE, "EXACT_READONLY_PREFLIGHT_REQUIRED")
    r.need(proof["schema_revision"] == r.OLD_REVISION and proof["frontend_version"] == r.BASE_FRONTEND, "EXACT_BASELINE_SCHEMA_AND_FRONTEND_REQUIRED")
    before, after = inventory(r.BASE_SOURCE), inventory(args.source)
    r.need(inventory("HEAD") == after, "SOURCE_HEAD_APPLICATION_DRIFT")
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    expected = {"app/backend/" + path for path in r.BACKEND_FILES} | {"app/frontend/src/" + path for path in FRONTEND} | TESTS
    r.need(changed == expected, "EXACT_APPLICATION_SOURCE_SCOPE_REQUIRED")
    for path, value in after.items():
        target = Path(path)
        r.need(target.is_file() and not target.is_symlink() and H(target.read_bytes()) == value, "WORKING_TREE_APPLICATION_DRIFT")
    # Preserve every unrelated source, including complete original finance and permissions.
    runtime_before = {name: before.get("app/backend/" + name) for name in r.BACKEND_FILES}
    r.need(all(proof["backend_changed_before"].get(name) == value for name, value in runtime_before.items()), "PRODUCTION_BACKEND_BASELINE_DRIFT")
    version = source_version()
    r.need(json.loads(Path("app/frontend/dist/app-version.json").read_bytes())["version"] == version, "EXACT_FRONTEND_BUILD_REQUIRED")
    payload = {"backend/" + name: Path("app/backend", name).read_bytes() for name in r.BACKEND_FILES}
    for path in Path("app/frontend/dist").rglob("*"):
        r.need(not path.is_symlink(), "DIST_LINK_REJECTED")
        if path.is_file():
            name = str(path.relative_to("app/frontend/dist"))
            # The exact retained static-path allowlist is mirrored here for local packaging.
            parts = Path(name).parts
            allowed = bool(parts) and not Path(name).is_absolute() and not any(part.startswith(".") for part in parts) and "\\" not in name
            allowed = allowed and ((len(parts) == 1 and (name in {"index.html", "offline.html", "app-version.json", "manifest.webmanifest", "robots.txt", "sw.js", "registerSW.js"} or path.suffix in {".png", ".svg", ".ico"} or re.fullmatch(r"workbox-[a-zA-Z0-9_-]+\.js", name))) or (parts[0] == "assets" and path.suffix in {".js", ".css", ".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".woff", ".woff2", ".ttf", ".eot"}))
            r.need(allowed, "DIST_PATH_REJECTED")
            payload["static/" + name] = path.read_bytes()
    r.need(sum(map(len, payload.values())) < 64 * 1024 ** 2 and all(len(body) < 16 * 1024 ** 2 for body in payload.values()), "PAYLOAD_LIMIT")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, filename="") as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, body in sorted(payload.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(body), 0o644, 0
                archive.addfile(info, io.BytesIO(body))
    manifest = {
        "format_version": 1, "source_sha": args.source, "baseline_source_sha": r.BASE_SOURCE,
        "frontend_version": version, "baseline_frontend_version": r.BASE_FRONTEND,
        "preflight_sha256": H(proof_body), "old_schema_revision": r.OLD_REVISION,
        "schema_revision": r.NEW_REVISION, "additive_tables": sorted(r.NEW_TABLES),
        "production_seed_rows": False, "credentials_included": False, "preserved": r.PRESERVED,
        "payload_sha256": H(buffer.getvalue()), "files": {name: H(body) for name, body in payload.items()},
        "backend_before": runtime_before,
        "backend_after": {name: after["app/backend/" + name] for name in sorted(r.BACKEND_FILES)},
        "changed_source_files": sorted(changed),
        "protected_source_inventory": {path: value for path, value in before.items() if path not in changed},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, body in {"payload.tar.gz": buffer.getvalue(), "manifest.json": (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()}.items():
        with (args.out / name).open("xb") as stream:
            stream.write(body)
    print(json.dumps({"source_sha": args.source, "frontend_version": version, "backend_file_count": len(r.BACKEND_FILES),
        "changed_source_files": sorted(changed), "payload_sha256": manifest["payload_sha256"],
        "manifest_sha256": H((args.out / "manifest.json").read_bytes())}))


if __name__ == "__main__":
    main()
