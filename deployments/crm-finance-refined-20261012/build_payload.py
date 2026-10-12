#!/usr/bin/env python3
"""Package an independently approved, committed finance presentation release.

The complete Git source tree and build version are checked before packaging.
No checkout, network, live data, credentials or fixture files enter the payload.
Source/proof inputs are full immutable hashes supplied by the release reviewer.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
BASELINE = "0bc1dd5bba38ecd518dc3546bcacb02f91881807"
BASELINE_VERSION = "8f7b36df4162"
NODE = Path("/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
ALLOWED = frozenset("app/frontend/src/" + name for name in (
    "components/Layout.tsx", "pages/Finance.tsx", "components/CompactFinanceTable.tsx",
    "components/compact-finance-table.css", "components/crm-desktop-refined-type.css",
    "components/finance-desktop-tables.ts", "pages/finance-desktop-refined.css"))
SUFFIXES = {".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".svg", ".ico", ".txt", ".woff", ".woff2", ".ttf", ".webmanifest"}
HASH = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"[a-f0-9]{40}")
VERSION = re.compile(r"[a-f0-9]{12}")
PROOF_FLAGS = ("financial_calculations_unchanged", "event_handlers_unchanged", "table_cells_unchanged")


class PayloadError(RuntimeError):
    pass


def need(value, code):
    if not value:
        raise PayloadError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo)


def canonical(name, *, hidden=False):
    if not isinstance(name, str) or not name or "\\" in name or any(ord(char) < 32 for char in name):
        return False
    relative = PurePosixPath(name)
    return name == relative.as_posix() and not relative.is_absolute() and ".." not in relative.parts \
        and (hidden or not any(part.startswith(".") for part in relative.parts))


def inventory(repo, ref, prefix):
    need(COMMIT.fullmatch(ref or ""), "FULL_IMMUTABLE_GIT_COMMIT_REQUIRED")
    result = {}
    for row in git(repo, "ls-tree", "-r", "-z", ref, "--", prefix).split(b"\0"):
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, _object = header.decode("ascii").split(" ")
        name = raw_name.decode("utf-8")
        need(mode in {"100644", "100755"} and kind == "blob" and canonical(name, hidden=True)
             and name.startswith(prefix) and name not in result, "TRACKED_REGULAR_SOURCE_FILES_REQUIRED")
        result[name] = sha(git(repo, "cat-file", "blob", ref + ":" + name))
    need(bool(result), "COMPLETE_TRACKED_SOURCE_INVENTORY_REQUIRED")
    return result


def reviewed_proof(path, expected, source, previous, current):
    need(HASH.fullmatch(expected or "") and path.is_file() and not path.is_symlink()
         and path.stat().st_size <= 1024**2, "INDEPENDENT_FINANCE_SOURCE_PROOF_REQUIRED")
    blob = path.read_bytes()
    need(sha(blob) == expected, "FINANCE_SOURCE_PROOF_HASH_DRIFT")
    value = json.loads(blob)
    need(isinstance(value, dict) and value.get("format_version") == 1
         and value.get("stage") == "CRM_FINANCE_REFINED_PRESENTATION_SOURCE_PROOF"
         and value.get("baseline_source_sha") == BASELINE and value.get("source_sha") == source
         and value.get("finance_file_before_sha256") == previous["app/frontend/src/pages/Finance.tsx"]
         and value.get("finance_file_after_sha256") == current["app/frontend/src/pages/Finance.tsx"]
         and all(value.get(flag) is True for flag in PROOF_FLAGS)
         and value.get("dialogs_unchanged") is True and value.get("mobile_render_unchanged") is True
         and isinstance(value.get("calculation_prefix_sha256"), str) and HASH.fullmatch(value["calculation_prefix_sha256"])
         and type(value.get("event_handler_count")) is int and value["event_handler_count"] > 0
         and isinstance(value.get("ledger_body_sha256"), dict) and len(value["ledger_body_sha256"]) == 8
         and all(isinstance(name, str) and isinstance(fingerprint, str) and HASH.fullmatch(fingerprint)
             for name, fingerprint in value["ledger_body_sha256"].items()), "EXACT_APPROVED_FINANCE_SOURCE_PROOF_REQUIRED")
    return value


def frontend_tree(repo, source, version, node):
    need(COMMIT.fullmatch(source or "") and VERSION.fullmatch(version or "") and source != BASELINE,
         "REVIEWED_FROZEN_SOURCE_AND_VERSION_REQUIRED")
    need(git(repo, "rev-parse", "HEAD").decode().strip() == source, "CHECKOUT_MUST_MATCH_FROZEN_SOURCE")
    need(subprocess.run(["git", "merge-base", "--is-ancestor", BASELINE, source], cwd=repo,
                        capture_output=True).returncode == 0, "ACCEPTED_BASELINE_ANCESTRY_REQUIRED")
    changed = git(repo, "diff", "--name-only", "-z", BASELINE, source, "--", "app/").split(b"\0")
    need({name.decode() for name in changed if name} == ALLOWED, "EXACT_SEVEN_PRESENTATION_SOURCE_CHANGES_REQUIRED")
    backend = inventory(repo, source, "app/backend/")
    need(backend == inventory(repo, BASELINE, "app/backend/"), "BACKEND_BYTES_MUST_REMAIN_IDENTICAL")
    frontend = inventory(repo, source, "app/frontend/src/")
    previous = inventory(repo, BASELINE, "app/frontend/src/")
    kept = {name: fingerprint for name, fingerprint in frontend.items() if name not in ALLOWED}
    need(kept == {name: fingerprint for name, fingerprint in previous.items() if name not in ALLOWED},
         "EVERY_UNCHANGED_FRONTEND_DEPENDENCY_MUST_MATCH_BASELINE")
    for name, expected in frontend.items():
        path = repo / name
        need(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == expected,
             "WORKING_SOURCE_BYTES_MUST_MATCH_FROZEN_COMMIT")
    # Use the build's own localeCompare ordering, without assuming Python sort
    # yields the same source version. Reject untracked files and source symlinks.
    script = """const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=process.argv[1],digest=crypto.createHash('sha256'),files={};
function visit(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
 if(e.isSymbolicLink())throw new Error('SOURCE_SYMLINK_REJECTED');
 const file=path.join(dir,e.name);if(e.isDirectory())visit(file);else if(e.isFile()){
 const name=path.relative(root,file),data=fs.readFileSync(file);digest.update(name);digest.update(data);
 files[name]=crypto.createHash('sha256').update(data).digest('hex');}else throw new Error('SOURCE_TYPE_REJECTED');}}
visit(root);process.stdout.write(JSON.stringify({version:digest.digest('hex').slice(0,12),files}));"""
    actual = json.loads(subprocess.check_output([str(node), "-e", script, str(repo / "app/frontend/src")]))
    need(actual["version"] == version and actual["files"] == {
        name.removeprefix("app/frontend/src/"): fingerprint for name, fingerprint in frontend.items()},
        "COMPLETE_SOURCE_VERSION_AND_TRACKED_BYTES_REQUIRED")
    return frontend, previous, backend, kept


def dist_archive(dist, version):
    need(dist.is_dir() and not dist.is_symlink()
         and json.loads((dist / "app-version.json").read_bytes()) == {"version": version}, "FROZEN_BUILD_VERSION_REQUIRED")
    files, total = {}, 0
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(dist.rglob("*")):
                need(not path.is_symlink(), "STATIC_SYMLINK_REJECTED")
                if path.is_dir():
                    continue
                name = path.relative_to(dist).as_posix()
                need(path.is_file() and canonical(name) and path.suffix in SUFFIXES
                     and (path.suffix != ".html" or name in {"index.html", "offline.html"}), "STATIC_FILE_SCOPE_REJECTED")
                data = path.read_bytes()
                total += len(data)
                need(len(data) <= 16 * 1024**2 and total <= 64 * 1024**2, "BOUNDED_COMPLETE_STATIC_PAYLOAD_REQUIRED")
                entry = tarfile.TarInfo("payload/" + name)
                entry.size, entry.mode, entry.uid, entry.gid, entry.mtime = len(data), 0o644, 0, 0, 0
                archive.addfile(entry, io.BytesIO(data))
                files[name] = sha(data)
    need({"index.html", "app-version.json"} <= set(files), "COMPLETE_BUILD_ENTRYPOINTS_REQUIRED")
    return output.getvalue(), files


def package(args):
    repo = args.repo.resolve()
    frontend, previous, backend, kept = frontend_tree(repo, args.source_sha, args.frontend_version, args.node)
    proof = reviewed_proof(args.finance_proof, args.finance_proof_sha256, args.source_sha, previous, frontend)
    payload, files = dist_archive(repo / "app/frontend/dist", args.frontend_version)
    manifest = {"format_version": 1, "stage": "CRM_FINANCE_REFINED_STATIC_PAYLOAD_PREPARED",
        "source_sha": args.source_sha, "baseline_source_sha": BASELINE, "frontend_version": args.frontend_version,
        "baseline_frontend_version": BASELINE_VERSION, "static_only": True, "backend_changes": False,
        "credentials_included": False, "databases_modified": False, "services_modified": False, "environment_modified": False,
        "changed_source_files": {name: frontend[name] for name in sorted(ALLOWED)},
        "preserved_source_inventories": {"backend": backend, "private_frontend": kept},
        "frontend_source_inventory": frontend, "finance_preservation_proof": proof,
        "finance_preservation_proof_sha256": args.finance_proof_sha256,
        "layout_scope": {"min_width": 1024, "mobile_source_unchanged": True, "private_workspace_source_unchanged": True},
        "payload_files": files, "payload_sha256": sha(payload)}
    args.artifacts.mkdir(parents=True, exist_ok=True)
    need(not (args.artifacts / "static-payload.tar.gz").exists() and not (args.artifacts / "static-manifest.json").exists(),
         "FRESH_FROZEN_ARTIFACT_NAMES_REQUIRED")
    (args.artifacts / "static-payload.tar.gz").write_bytes(payload)
    blob = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (args.artifacts / "static-manifest.json").write_bytes(blob)
    return {"source_sha": args.source_sha, "frontend_version": args.frontend_version, "dist_files": len(files),
        "backend_files_preserved": len(backend), "frontend_dependencies_preserved": len(kept),
        "payload_sha256": sha(payload), "manifest_sha256": sha(blob)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--artifacts", type=Path, default=Path(__file__).resolve().parent / "artifacts")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--frontend-version", required=True)
    parser.add_argument("--finance-proof", type=Path, required=True)
    parser.add_argument("--finance-proof-sha256", required=True)
    parser.add_argument("--node", type=Path, default=NODE)
    print(json.dumps(package(parser.parse_args()), sort_keys=True))
