"""Bounded transfer of the complete secret-free proof, never business/provider writes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import zlib

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
ROOT = Path('/opt/t24-crm/releases/media-ops-management-readonly-preflight-20261031')
PREFLIGHT_SHA = '12a65720a072901bbeb55cdc91ca69a3430c06da178d8d6d0b80d46e8787d95b'
OWNER = 0  # Offline tests only override this seam; emitted production commands never do.
CHUNK_BYTES = 3072
MAX_PROOF = 2 * 1024 * 1024
MAX_PACKED = 1024 * 1024
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok: raise RuntimeError(code)


def server_guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_SERVER_ROOT_REQUIRED')
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def directory(path, exact=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CAPTURE_CANONICAL_DIRECTORY_REQUIRED')
    for parent in (path, *path.parents):
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, OWNER} and not info.st_mode & 0o022,
            'CAPTURE_PROTECTED_PARENT_REQUIRED')
    if exact: need(stat.S_IMODE(path.lstat().st_mode) == 0o700, 'CAPTURE_DIRECTORY_MODE_REQUIRED')


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def checked_manifest(value):
    keys = {'stage', 'proof_sha256', 'proof_bytes', 'compressed_sha256', 'compressed_bytes',
        'chunk_bytes', 'chunk_count', 'path_sha256', 'preflight_sha256'}
    need(isinstance(value, dict) and set(value) == keys and value['stage'] == 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_CAPTURED', 'EXACT_CAPTURE_MANIFEST_REQUIRED')
    need(all(isinstance(value[key], str) and re.fullmatch('[a-f0-9]{64}', value[key]) for key in
        ('proof_sha256', 'compressed_sha256', 'path_sha256', 'preflight_sha256')), 'CAPTURE_SHA_REQUIRED')
    need(value['preflight_sha256'] == PREFLIGHT_SHA and type(value['proof_bytes']) is int and
        0 < value['proof_bytes'] <= MAX_PROOF and type(value['compressed_bytes']) is int and
        0 < value['compressed_bytes'] <= MAX_PACKED and value['chunk_bytes'] == CHUNK_BYTES and
        type(value['chunk_count']) is int and value['chunk_count'] == (value['compressed_bytes'] + CHUNK_BYTES - 1) // CHUNK_BYTES,
        'BOUNDED_CAPTURE_MANIFEST_REQUIRED')
    path = ROOT / (value['proof_sha256'] + '.json.zlib')
    need(value['path_sha256'] == H(str(path).encode()), 'EXACT_CAPTURE_PATH_REQUIRED')
    return path


def read_exact(path, expected_sha, expected_size):
    directory(path.parent, exact=True)
    before = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(before.st_mode) and before.st_uid == OWNER and
        before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size == expected_size,
        'CAPTURE_PROTECTED_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need(identity(before) == identity(opened), 'CAPTURE_FILE_OPEN_DRIFT')
        body = stream.read(expected_size + 1)
        need(identity(opened) == identity(os.fstat(stream.fileno())), 'CAPTURE_FILE_READ_DRIFT')
    need(identity(opened) == identity(path.lstat()) and len(body) == expected_size and H(body) == expected_sha,
        'CAPTURE_FILE_CONTENT_DRIFT')
    return body


def decode_proof(packed, manifest):
    need(len(packed) == manifest['compressed_bytes'] and H(packed) == manifest['compressed_sha256'], 'CAPTURE_COMPRESSED_HASH_DRIFT')
    decoder = zlib.decompressobj()
    body = decoder.decompress(packed, manifest['proof_bytes'] + 1)
    need(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail and
        len(body) == manifest['proof_bytes'] and H(body) == manifest['proof_sha256'], 'CAPTURE_PROOF_HASH_DRIFT')
    return body


def capture(preflight):
    server_guard()
    value = preflight['proof']()
    need(value['stage'] == 'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT' and
        all(value[key] is False for key in ('provider_requests', 'business_writes', 'credential_content_read',
            'private_file_content_read', 'customer_records_exported')), 'SECRET_FREE_COMPLETE_PROOF_REQUIRED')
    body = preflight['encoded'](value)
    need(0 < len(body) <= MAX_PROOF, 'CAPTURE_PROOF_SIZE_REJECTED')
    packed = zlib.compress(body, 9)
    need(0 < len(packed) <= MAX_PACKED, 'CAPTURE_COMPRESSED_SIZE_REJECTED')
    directory(ROOT.parent)
    if not ROOT.exists() and not ROOT.is_symlink():
        ROOT.mkdir(mode=0o700)
        fsync_dir(ROOT.parent)
    directory(ROOT, exact=True)
    proof_sha = H(body)
    path = ROOT / (proof_sha + '.json.zlib')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        read_exact(path, H(packed), len(packed))  # Same bytes only; never overwrite.
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(packed); stream.flush(); os.fsync(stream.fileno())
        fsync_dir(ROOT)
    manifest = {'stage': 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_CAPTURED', 'proof_sha256': proof_sha,
        'proof_bytes': len(body), 'compressed_sha256': H(packed), 'compressed_bytes': len(packed),
        'chunk_bytes': CHUNK_BYTES, 'chunk_count': (len(packed) + CHUNK_BYTES - 1) // CHUNK_BYTES,
        'path_sha256': H(str(path).encode()), 'preflight_sha256': PREFLIGHT_SHA}
    need(checked_manifest(manifest) == path, 'CAPTURE_MANIFEST_PATH_DRIFT')
    need(decode_proof(read_exact(path, H(packed), len(packed)), manifest) == body, 'CAPTURE_ROUNDTRIP_DRIFT')
    return manifest


def read_chunk(manifest, index):
    server_guard()
    path = checked_manifest(manifest)
    need(type(index) is int and 0 <= index < manifest['chunk_count'], 'EXACT_CAPTURE_CHUNK_INDEX_REQUIRED')
    packed = read_exact(path, manifest['compressed_sha256'], manifest['compressed_bytes'])
    decode_proof(packed, manifest)  # Every read independently checks full proof hash and exact size.
    piece = packed[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
    data = base64.b64encode(piece).decode()
    need(0 < len(data) <= 4096, 'BOUNDED_CAPTURE_CHUNK_REQUIRED')
    return {'stage': 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_CHUNK', 'proof_sha256': manifest['proof_sha256'],
        'compressed_sha256': manifest['compressed_sha256'], 'index': index, 'chunk_count': manifest['chunk_count'],
        'chunk_sha256': H(piece), 'data_base64': data}


def reassemble(manifest, chunks):
    checked_manifest(manifest)
    need(isinstance(chunks, list) and len(chunks) == manifest['chunk_count'], 'ALL_CAPTURE_CHUNKS_REQUIRED')
    result = {}
    for row in chunks:
        need(isinstance(row, dict) and set(row) == {'stage', 'proof_sha256', 'compressed_sha256', 'index', 'chunk_count', 'chunk_sha256', 'data_base64'} and
            row['stage'] == 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_CHUNK' and row['proof_sha256'] == manifest['proof_sha256'] and
            row['compressed_sha256'] == manifest['compressed_sha256'] and row['chunk_count'] == manifest['chunk_count'] and
            type(row['index']) is int and 0 <= row['index'] < manifest['chunk_count'] and row['index'] not in result and
            isinstance(row['data_base64'], str) and len(row['data_base64']) <= 4096, 'CAPTURE_CHUNK_IDENTITY_DRIFT')
        piece = base64.b64decode(row['data_base64'], validate=True)
        want = min(CHUNK_BYTES, manifest['compressed_bytes'] - row['index'] * CHUNK_BYTES)
        need(len(piece) == want and H(piece) == row['chunk_sha256'], 'CAPTURE_CHUNK_HASH_DRIFT')
        result[row['index']] = piece
    return decode_proof(b''.join(result[index] for index in range(manifest['chunk_count'])), manifest)
