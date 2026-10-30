"""Offline capture/read/reassembly attack tests; no server or provider operations."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('test_media_management_capture', HERE / 'capture_preflight.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location('test_media_management_capture_generator', HERE / 'generate_capture_commands.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)


def proof_value():
    return {'stage': 'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT', 'provider_requests': False, 'business_writes': False,
        'credential_content_read': False, 'private_file_content_read': False, 'customer_records_exported': False,
        'rows': {str(index): {'rows_sha256': hashlib.sha256(str(index).encode()).hexdigest(),
            'shape_sha256': hashlib.sha256(('shape' + str(index)).encode()).hexdigest(), 'count': index} for index in range(400)},
        'original_columns': {'table': ['id', 'status', 'token_encrypted']}}


class CaptureFixture:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name).resolve(); self.root = self.base / 'capture'
        self.patches = [patch.object(c, 'ROOT', self.root), patch.object(c, 'OWNER', os.geteuid()), patch.object(c, 'server_guard')]
        for item in self.patches: item.start()
        def test_directory(path, exact=False):
            path = Path(path)
            c.need(path in {self.base, self.root} and path.resolve() == path and path.is_dir() and not path.is_symlink(), 'CAPTURE_PROTECTED_PARENT_REQUIRED')
            if exact: c.need(stat.S_IMODE(path.stat().st_mode) == 0o700, 'CAPTURE_DIRECTORY_MODE_REQUIRED')
        self.directory = patch.object(c, 'directory', test_directory); self.directory.start()
        self.value = proof_value(); self.body = (json.dumps(self.value, sort_keys=True, indent=2) + '\n').encode()
        self.preflight = {'proof': lambda: self.value, 'encoded': lambda value: (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()}
        return self
    def __exit__(self, *args):
        self.directory.stop()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()
    def capture(self): return c.capture(self.preflight)
    def chunks(self, manifest): return [c.read_chunk(manifest, index) for index in range(manifest['chunk_count'])]


class CaptureTests(unittest.TestCase):
    def test_complete_large_proof_is_preserved_and_stdout_manifest_is_small(self):
        with CaptureFixture() as f:
            manifest = f.capture(); path = c.checked_manifest(manifest)
            self.assertGreater(manifest['proof_bytes'], 24 * 1024)
            self.assertLess(len(json.dumps(manifest)), 1200)
            self.assertEqual(manifest['proof_sha256'], c.H(f.body))
            self.assertEqual(path.name, c.H(f.body) + '.json.zlib')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(f.root.stat().st_mode), 0o700)
            chunks = f.chunks(manifest)
            self.assertTrue(all(len(row['data_base64']) <= 4096 and len(json.dumps(row)) < 5000 for row in chunks))
            self.assertEqual(c.reassemble(manifest, list(reversed(chunks))), f.body)

    def test_exact_idempotence_without_overwrite(self):
        with CaptureFixture() as f:
            first = f.capture(); path = c.checked_manifest(first); before = c.identity(path.stat())
            self.assertEqual(f.capture(), first); self.assertEqual(c.identity(path.stat()), before)

    def test_existing_wrong_content_is_not_overwritten(self):
        with CaptureFixture() as f:
            first = f.capture(); path = c.checked_manifest(first); path.write_bytes(b'x' * first['compressed_bytes'])
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_FILE_CONTENT_DRIFT'): f.capture()
            self.assertEqual(path.read_bytes(), before)

    def test_capture_rejects_non_secret_free_or_incomplete_proof(self):
        for key in ['provider_requests', 'business_writes', 'credential_content_read', 'private_file_content_read', 'customer_records_exported']:
            with self.subTest(key=key), CaptureFixture() as f:
                f.value[key] = True
                with self.assertRaisesRegex(RuntimeError, 'SECRET_FREE_COMPLETE_PROOF_REQUIRED'): f.capture()
                self.assertFalse(f.root.exists())

    def test_exact_host_and_root_required_before_access(self):
        for uid, host in [(501, c.HOST), (0, 'other-host')]:
            with patch.object(c.os, 'geteuid', return_value=uid), patch.object(c.socket, 'gethostname', return_value=host):
                with self.assertRaisesRegex(RuntimeError, 'EXACT_SERVER_ROOT_REQUIRED'): c.server_guard()

    def test_missing_duplicate_wrong_identity_and_tampered_chunk_rejected(self):
        with CaptureFixture() as f:
            manifest = f.capture(); chunks = f.chunks(manifest)
            with self.assertRaisesRegex(RuntimeError, 'ALL_CAPTURE_CHUNKS_REQUIRED'): c.reassemble(manifest, chunks[:-1])
            duplicate = copy.deepcopy(chunks); duplicate[-1] = duplicate[0]
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_CHUNK_IDENTITY_DRIFT'): c.reassemble(manifest, duplicate)
            for key, value in [('proof_sha256', '0' * 64), ('compressed_sha256', '0' * 64), ('index', True), ('chunk_count', 999), ('stage', 'wrong')]:
                wrong = copy.deepcopy(chunks); wrong[0][key] = value
                with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'CAPTURE_CHUNK_IDENTITY_DRIFT'): c.reassemble(manifest, wrong)
            wrong = copy.deepcopy(chunks); wrong[0]['chunk_sha256'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_CHUNK_HASH_DRIFT'): c.reassemble(manifest, wrong)

    def test_exact_manifest_and_index_are_pinned(self):
        with CaptureFixture() as f:
            manifest = f.capture()
            for key, value in [('preflight_sha256', '0' * 64), ('proof_bytes', True), ('compressed_bytes', c.MAX_PACKED + 1),
                ('chunk_count', 99999), ('path_sha256', '0' * 64), ('proof_sha256', '../escape'), ('extra', 'value')]:
                wrong = dict(manifest); wrong[key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError): c.read_chunk(wrong, 0)
            for index in [-1, manifest['chunk_count'], True, '0']:
                with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, 'EXACT_CAPTURE_CHUNK_INDEX_REQUIRED'): c.read_chunk(manifest, index)

    def test_modified_file_and_insecure_mode_rejected(self):
        with CaptureFixture() as f:
            manifest = f.capture(); path = c.checked_manifest(manifest)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROTECTED_FILE_REQUIRED'): c.read_chunk(manifest, 0)
            path.chmod(0o600); body = path.read_bytes(); path.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_FILE_CONTENT_DRIFT'): c.read_chunk(manifest, 0)

    def test_symlink_and_hardlink_file_rejected(self):
        with CaptureFixture() as f:
            manifest = f.capture(); path = c.checked_manifest(manifest); other = path.with_name('other')
            path.rename(other); path.symlink_to(other)
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROTECTED_FILE_REQUIRED'): c.read_chunk(manifest, 0)
            path.unlink(); os.link(other, path)
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROTECTED_FILE_REQUIRED'): c.read_chunk(manifest, 0)

    def test_replaced_inode_between_lstat_and_open_rejected(self):
        with CaptureFixture() as f:
            manifest = f.capture(); path = c.checked_manifest(manifest); replacement = path.with_name('replacement')
            replacement.write_bytes(path.read_bytes()); replacement.chmod(0o600); original = os.open
            def raced(file, flags, *args):
                if Path(file) == path: os.replace(replacement, path)
                return original(file, flags, *args)
            with patch.object(c.os, 'open', raced):
                with self.assertRaisesRegex(RuntimeError, 'CAPTURE_FILE_OPEN_DRIFT'): c.read_chunk(manifest, 0)

    def test_changed_open_fd_metadata_rejected(self):
        with CaptureFixture() as f:
            manifest = f.capture(); original = os.fstat; calls = []
            def drift(fd):
                info = original(fd); calls.append(fd)
                if len(calls) == 2:
                    return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                        st_mtime_ns=info.st_mtime_ns + 1, st_ctime_ns=info.st_ctime_ns)
                return info
            with patch.object(c.os, 'fstat', drift):
                with self.assertRaisesRegex(RuntimeError, 'CAPTURE_FILE_READ_DRIFT'): c.read_chunk(manifest, 0)

    def test_full_uncompressed_hash_checked_for_every_read(self):
        with CaptureFixture() as f:
            manifest = f.capture(); wrong = dict(manifest); wrong['proof_bytes'] += 1
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROOF_HASH_DRIFT'): c.read_chunk(wrong, 0)
            packed = c.read_exact(c.checked_manifest(manifest), manifest['compressed_sha256'], manifest['compressed_bytes'])
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_COMPRESSED_HASH_DRIFT'): c.decode_proof(packed + b'extra', manifest)

    def test_decompression_bomb_size_bound(self):
        packed = zlib.compress(b'A' * 20000)
        manifest = {'compressed_bytes': len(packed), 'compressed_sha256': c.H(packed), 'proof_bytes': 5, 'proof_sha256': c.H(b'AAAAA')}
        with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROOF_HASH_DRIFT'): c.decode_proof(packed, manifest)

    def test_secure_directory_rejects_writable_ancestor_and_wrong_exact_mode(self):
        root = Path('/fixed/capture')
        good = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
        bad = SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0)
        with patch.object(Path, 'resolve', lambda path: path), patch.object(Path, 'lstat', lambda path: bad if path == Path('/fixed') else good):
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_PROTECTED_PARENT_REQUIRED'): c.directory(root, exact=True)
        other = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        with patch.object(Path, 'resolve', lambda path: path), patch.object(Path, 'lstat', return_value=other):
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_DIRECTORY_MODE_REQUIRED'): c.directory(root, exact=True)


class GeneratorTests(unittest.TestCase):
    def test_capture_hash_pins_original_preflight_and_generated_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('preflight.py', 'capture_preflight.py'): (root / name).write_bytes((HERE / name).read_bytes())
            result = g.generate_capture(root); command = (root / 'capture-preflight-command.sh').read_text()
            self.assertEqual(result['preflight_sha256'], c.PREFLIGHT_SHA)
            self.assertEqual(result['sha256'], c.H(command.encode())); self.assertLess(len(command), 16000)
            self.assertIn("c['capture'](p)", command); self.assertNotIn("p['main']()", command)
            self.assertIn('sudo python3 -I -S -B', command)
            (root / 'preflight.py').write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_PREFLIGHT_SOURCE_HASH_REQUIRED'): g.generate_capture(root)

    def test_fixed_reader_commands_and_local_exact_output(self):
        with CaptureFixture() as f:
            manifest = f.capture(); chunks = f.chunks(manifest)
            with tempfile.TemporaryDirectory() as temp:
                local = Path(temp); (local / 'capture_preflight.py').write_bytes((HERE / 'capture_preflight.py').read_bytes())
                with patch.object(g, 'helper', return_value=c):
                    commands = g.generate_chunks(manifest, local)
                    self.assertEqual(len(commands), manifest['chunk_count'])
                    self.assertTrue(all(row['bytes'] < 10000 for row in commands))
                    first = Path(commands[0]['path']).read_text()
                    self.assertIn(manifest['proof_sha256'], first); self.assertIn(manifest['path_sha256'], first)
                    output = local / 'preflight.json'; result = g.reassemble_files(manifest, chunks, output, local)
                    self.assertEqual(output.read_bytes(), f.body); self.assertEqual(result['proof_sha256'], manifest['proof_sha256'])
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                    g.reassemble_files(manifest, chunks, output, local)
                    output.write_text('corrupt')
                    with self.assertRaisesRegex(RuntimeError, 'EXISTING_PREFLIGHT_OUTPUT_DRIFT'): g.reassemble_files(manifest, chunks, output, local)


if __name__ == '__main__': unittest.main()
