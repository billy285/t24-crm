#!/usr/bin/env python3
"""Create and verify one immutable T24 CRM Docker candidate artifact."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

COMMIT = "75997c6f351eba1b35aaa6faf7fc801f42921c18"
PARENTS = (
    "d6a434d8705b07a67b4dbe59f11b160a1eb91613",
    "6e841e2b963ec576da6bdf2a9d496d02e90e07c0",
)
ROOT_TREE = "3e56f34dc7e858e656af3fc9508a57c6a9a75aa1"
APP_TREE = "cea0fc1f2c414e0f5606900a93895e04a567c0b2"
ARCHIVE_SHA256 = "17eda80f52db8d2fefe35c52047d13535a57ecdb4459d01209562f1b909f26af"
ORIGINAL_DOCKERFILE_SHA256 = "3fa8ded1c7d1ca14325bb94a5aca6d4cb25d1ff9f620d7e1c73eae04aa0a769c"
DOCKERIGNORE_SHA256 = "00904b81cc471610bce2ea2881a3d8f85c31a05f863952f6917a9a8a09a7c8b4"
PNPM_LOCK_SHA256 = "a06f7ec6aed5abfaef495900d3f49833b7e262d8338a98b3d876299774ca4aee"
REQUIREMENTS_SHA256 = "2946db48dcb9bdc03d2295f929d65c7cc000ed83a5c9d9888ac88b61ea7633ed"
EXPECTED_FILE_COUNT = 503
HEX64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(root: Path, *args: str, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def validate_source(root_raw: str, report_raw: str) -> None:
    root = Path(root_raw).resolve(strict=True)
    report = Path(report_raw)
    if run_git(root, "rev-parse", "HEAD") != COMMIT:
        fail("source checkout commit differs from approved integration commit")
    parents = tuple(run_git(root, "show", "-s", "--format=%P", "HEAD").split())
    if parents != PARENTS:
        fail("source merge parents differ")
    if run_git(root, "show", "-s", "--format=%T", "HEAD") != ROOT_TREE:
        fail("source root tree differs")
    if run_git(root, "rev-parse", "HEAD:app") != APP_TREE:
        fail("source app tree differs")
    entries = run_git(root, "ls-files", "-s", "app").splitlines()
    if len(entries) != EXPECTED_FILE_COUNT:
        fail("tracked app file count differs")
    for entry in entries:
        fields = entry.split(None, 3)
        if len(fields) != 4 or fields[0] not in {"100644", "100755"}:
            fail("source contains a symlink, submodule, or unexpected tracked mode")
        working_blob = run_git(root, "hash-object", "--no-filters", "--", fields[3])
        if working_blob != fields[1]:
            fail(f"source working file differs from approved Git blob: {fields[3]}")
    if run_git(root, "ls-files", "--others", "--exclude-standard", "app"):
        fail("source app tree contains an untracked file")

    for path_text in run_git(root, "ls-files", "app").splitlines():
        data = (root / path_text).read_bytes()
        if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
            fail("source contains a Git LFS pointer")

    expected_hashes = {
        "app/Dockerfile": ORIGINAL_DOCKERFILE_SHA256,
        "app/.dockerignore": DOCKERIGNORE_SHA256,
        "app/frontend/pnpm-lock.yaml": PNPM_LOCK_SHA256,
        "app/backend/requirements.txt": REQUIREMENTS_SHA256,
    }
    for name, expected in expected_hashes.items():
        if sha256_file(root / name) != expected:
            fail(f"approved build input differs: {name}")

    archive = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "filter.lfs.required=false",
            "-c",
            "filter.lfs.process=",
            "-c",
            "filter.lfs.smudge=cat",
            "archive",
            "--format=tar",
            "--prefix=source/",
            COMMIT,
            "app",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        fail("stable source archive hash differs")

    report.write_text(
        "\n".join(
            (
                "SOURCE_VALIDATION=PASS",
                f"SOURCE_COMMIT={COMMIT}",
                f"SOURCE_PARENTS={','.join(PARENTS)}",
                f"SOURCE_ROOT_TREE={ROOT_TREE}",
                f"SOURCE_APP_TREE={APP_TREE}",
                f"SOURCE_FILE_COUNT={EXPECTED_FILE_COUNT}",
                "SOURCE_LFS_POINTER_COUNT=0",
                "SOURCE_SYMLINK_COUNT=0",
                f"SOURCE_ARCHIVE_SHA256={ARCHIVE_SHA256}",
            )
        )
        + "\n",
        encoding="ascii",
    )


def rewrite_dockerfile(args: list[str]) -> None:
    if len(args) != 5 or any(HEX64.fullmatch(value) is None for value in args[2:]):
        fail("rewrite-dockerfile arguments are invalid")
    source, destination = Path(args[0]), Path(args[1])
    text = source.read_text(encoding="utf-8")
    replacements = {
        "# syntax=docker/dockerfile:1": f"# syntax=docker/dockerfile:1@sha256:{args[2]}",
        "FROM node:22-bookworm-slim AS frontend-builder": (
            f"FROM node:22-bookworm-slim@sha256:{args[3]} AS frontend-builder"
        ),
        "FROM python:3.10-slim AS runtime": (
            f"FROM python:3.10-slim@sha256:{args[4]} AS runtime"
        ),
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            fail(f"Dockerfile pin target is missing or duplicated: {old}")
        text = text.replace(old, new)
    destination.write_text(text, encoding="utf-8")
    os.chmod(destination, 0o600)


def safe_tar_name(raw: str) -> str:
    if (
        not raw
        or raw.startswith("/")
        or raw.endswith("/")
        or "\\" in raw
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw)
    ):
        fail("unsafe tar member path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        fail("unsafe tar member path")
    canonical = PurePosixPath(*parts).as_posix()
    if canonical != raw:
        fail("non-canonical tar member path")
    return canonical


def inventory(export_raw: str, output_raw: str) -> None:
    export = Path(export_raw)
    output = Path(output_raw)
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    with tarfile.open(export, "r:*") as archive:
        for member in archive:
            raw = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            name = safe_tar_name(raw)
            if name in seen:
                fail("duplicate rootfs export member")
            seen.add(name)
            if not (name.startswith("app/backend/") or name.startswith("app/frontend/dist/")):
                continue
            if member.isdir():
                continue
            if not member.isfile() or member.islnk() or member.issym():
                fail(f"candidate application root contains a non-regular file: {name}")
            handle = archive.extractfile(member)
            if handle is None:
                fail("candidate rootfs member cannot be read")
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            rows.append((f"/{name}", digest.hexdigest()))
    if not rows or not any(path.startswith("/app/backend/") for path, _ in rows):
        fail("candidate backend inventory is empty")
    if not any(path.startswith("/app/frontend/dist/") for path, _ in rows):
        fail("candidate frontend inventory is empty")
    rows.sort()
    output.write_text("".join(f"{digest}  {path}\n" for path, digest in rows), encoding="ascii")
    os.chmod(output, 0o600)


def verify_inventory(export_raw: str, manifest_raw: str) -> None:
    expected: dict[str, str] = {}
    for line in Path(manifest_raw).read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (/(?:app/backend|app/frontend/dist)/.+)", line)
        if match is None or match.group(2) in expected:
            fail("candidate filesystem manifest is malformed")
        expected[match.group(2)] = match.group(1)
    temporary = Path(manifest_raw).with_suffix(".verify")
    inventory(export_raw, str(temporary))
    actual = temporary.read_text(encoding="ascii")
    temporary.unlink()
    if actual != Path(manifest_raw).read_text(encoding="ascii"):
        fail("candidate filesystem inventory is not reproducible from its export")


def strict_json(handle):
    def pairs(values):
        result = {}
        for key, value in values:
            if not isinstance(key, str) or key in result:
                fail("duplicate or non-string JSON key")
            result[key] = value
        return result

    return json.load(handle, object_pairs_hook=pairs)


def sanitize_save(source_raw: str, destination_raw: str) -> None:
    source_path = Path(source_raw).resolve(strict=True)
    destination = Path(destination_raw).resolve(strict=False)
    if source_path == destination or destination.exists():
        fail("docker archive sanitization paths are unsafe")
    seen: set[str] = set()
    manifest_seen = False
    with tarfile.open(source_path, "r:*") as source, tarfile.open(
        destination, "w", format=tarfile.GNU_FORMAT
    ) as output:
        for member in source:
            raw = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            name = safe_tar_name(raw)
            if name in seen:
                fail("docker archive has duplicate members before sanitization")
            seen.add(name)
            if not (member.isfile() or member.isdir()):
                fail("docker archive has a linked or special member before sanitization")
            if member.uid != 0 or member.gid != 0:
                fail("docker archive ownership differs before sanitization")
            if name == "repositories":
                continue
            if name == "manifest.json":
                handle = source.extractfile(member)
                if handle is None:
                    fail("docker manifest cannot be read before sanitization")
                manifest = strict_json(handle)
                if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
                    fail("docker archive must contain exactly one image before sanitization")
                required_fields = {"Config", "RepoTags", "Layers"}
                if not required_fields.issubset(manifest[0]):
                    fail("docker manifest is missing required fields before sanitization")
                sanitized_manifest = [
                    {
                        "Config": manifest[0]["Config"],
                        "RepoTags": None,
                        "Layers": manifest[0]["Layers"],
                    }
                ]
                payload = json.dumps(
                    sanitized_manifest, separators=(",", ":"), sort_keys=False
                ).encode("utf-8")
                rewritten = tarfile.TarInfo("manifest.json")
                rewritten.mode = 0o600
                rewritten.uid = 0
                rewritten.gid = 0
                rewritten.mtime = int(member.mtime)
                rewritten.size = len(payload)
                with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as staged:
                    staged.write(payload)
                    staged.seek(0)
                    output.addfile(rewritten, staged)
                manifest_seen = True
                continue
            handle = source.extractfile(member) if member.isfile() else None
            output.addfile(member, handle)
    if not manifest_seen:
        destination.unlink(missing_ok=True)
        fail("docker manifest is missing before sanitization")
    os.chmod(destination, 0o600)


def validate_save(archive_raw: str, image_id: str, revision: str) -> None:
    if IMAGE_ID.fullmatch(image_id) is None or revision != COMMIT:
        fail("docker archive identity arguments are invalid")
    expected = image_id.split(":", 1)[1]
    with tarfile.open(archive_raw, "r:*") as archive:
        members: dict[str, tarfile.TarInfo] = {}
        for member in archive:
            raw = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            name = safe_tar_name(raw)
            if name in members or not (member.isfile() or member.isdir()):
                fail("docker archive has duplicate, linked, or special members")
            if member.uid != 0 or member.gid != 0:
                fail("docker archive member ownership differs")
            members[name] = member
        manifest_member = members.get("manifest.json")
        if manifest_member is None or not manifest_member.isfile():
            fail("docker archive manifest is missing")
        source = archive.extractfile(manifest_member)
        if source is None:
            fail("docker archive manifest cannot be read")
        manifest = strict_json(source)
        if not isinstance(manifest, list) or len(manifest) != 1:
            fail("docker archive must contain exactly one image")
        entry = manifest[0]
        if set(entry) != {"Config", "RepoTags", "Layers"} or entry["RepoTags"] not in (None, []):
            fail("docker archive must be single-image and untagged")
        config_name = safe_tar_name(entry["Config"])
        config_member = members.get(config_name)
        if config_member is None or not config_member.isfile():
            fail("docker config is missing")
        config_source = archive.extractfile(config_member)
        if config_source is None:
            fail("docker config cannot be read")
        config_bytes = config_source.read()
        if hashlib.sha256(config_bytes).hexdigest() != expected:
            fail("docker config digest differs from full image ID")
        config = json.loads(config_bytes)
        labels = (config.get("config") or {}).get("Labels") or {}
        if labels.get("org.opencontainers.image.revision") != COMMIT:
            fail("candidate revision label differs")
        layers = entry["Layers"]
        diff_ids = (config.get("rootfs") or {}).get("diff_ids")
        if not isinstance(layers, list) or not layers or not isinstance(diff_ids, list):
            fail("docker layer contract is malformed")
        if len(layers) != len(diff_ids) or len(layers) != len(set(layers)):
            fail("docker layer counts differ")
        allowed = {"manifest.json", config_name}
        for name, diff_id in zip(layers, diff_ids, strict=True):
            safe = safe_tar_name(name)
            member = members.get(safe)
            if member is None or not member.isfile():
                fail("referenced docker layer is missing")
            handle = archive.extractfile(member)
            if handle is None:
                fail("referenced docker layer cannot be read")
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            if diff_id != f"sha256:{digest.hexdigest()}":
                fail("docker layer digest differs")
            allowed.add(safe)
            parent = PurePosixPath(safe).parent
            allowed.update({str(parent / "json"), str(parent / "VERSION")})
        if "repositories" in members:
            fail("untagged docker archive contains repositories metadata")
        extra = [name for name, member in members.items() if member.isfile() and name not in allowed]
        if extra:
            fail("docker archive contains unreferenced files")


def write_env(path_raw: str, values: list[tuple[str, str]]) -> None:
    path = Path(path_raw)
    for key, value in values:
        if not re.fullmatch(r"[A-Z0-9_]+", key) or "\n" in value or "\r" in value:
            fail("unsafe provenance field")
    path.write_text("".join(f"{key}='{value}'\n" for key, value in values), encoding="ascii")
    os.chmod(path, 0o600)


def write_base_evidence(args: list[str]) -> None:
    if len(args) != 7 or any(HEX64.fullmatch(value) is None for value in (args[2], args[4], args[6])):
        fail("base image evidence arguments are invalid")
    write_env(
        args[0],
        [
            ("FORMAT", "t24-base-image-digests-v1"),
            ("DOCKERFILE_FRONTEND_REF", args[1]),
            ("DOCKERFILE_FRONTEND_DIGEST", f"sha256:{args[2]}"),
            ("NODE_REF", args[3]),
            ("NODE_DIGEST", f"sha256:{args[4]}"),
            ("PYTHON_REF", args[5]),
            ("PYTHON_DIGEST", f"sha256:{args[6]}"),
        ],
    )


def write_provenance(args: list[str]) -> None:
    if len(args) != 11 or IMAGE_ID.fullmatch(args[1]) is None:
        fail("build provenance arguments are invalid")
    keys = (
        "IMAGE_ID",
        "EFFECTIVE_DOCKERFILE_SHA256",
        "BASE_IMAGE_DIGESTS_SHA256",
        "BUILD_LOG_SHA256",
        "CANDIDATE_IMAGE_FILES_SHA256",
        "IMAGE_ARCHIVE_SHA256",
        "IMAGE_ARCHIVE_SIZE",
        "BUILD_STARTED_AT_UTC",
        "BUILD_FINISHED_AT_UTC",
        "BUILD_RUN_ID",
    )
    values = list(zip(keys, args[1:11], strict=True))
    values = [
        ("FORMAT", "t24-github-build-once-provenance-v1"),
        ("SOURCE_COMMIT", COMMIT),
        ("BUILD_PLATFORM", "linux/amd64"),
        ("PRODUCTION_SECRETS_USED", "NO"),
        ("PRODUCTION_CONNECTION", "NOT_PERFORMED"),
        *values,
    ]
    write_env(args[0], values)


def artifact_manifest(directory_raw: str, output_raw: str) -> None:
    directory = Path(directory_raw).resolve(strict=True)
    output = Path(output_raw).resolve(strict=False)
    rows = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path == output:
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail("artifact directory contains a non-regular or linked entry")
        rows.append(f"{sha256_file(path)}  {path.name}\n")
    if not rows:
        fail("artifact directory is empty")
    output.write_text("".join(rows), encoding="ascii")
    os.chmod(output, 0o600)


def main() -> None:
    if len(sys.argv) < 2:
        fail("missing command")
    command, args = sys.argv[1], sys.argv[2:]
    if command == "validate-source" and len(args) == 2:
        validate_source(*args)
    elif command == "rewrite-dockerfile":
        rewrite_dockerfile(args)
    elif command == "inventory" and len(args) == 2:
        inventory(*args)
    elif command == "verify-inventory" and len(args) == 2:
        verify_inventory(*args)
    elif command == "validate-save" and len(args) == 3:
        validate_save(*args)
    elif command == "sanitize-save" and len(args) == 2:
        sanitize_save(*args)
    elif command == "write-base-evidence":
        write_base_evidence(args)
    elif command == "write-provenance":
        write_provenance(args)
    elif command == "artifact-manifest" and len(args) == 2:
        artifact_manifest(*args)
    else:
        fail("unknown command or invalid arguments")


if __name__ == "__main__":
    main()
