"""Offline deployment rejection tests; no production paths, Docker or network."""
import hashlib
import importlib.util
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("private_release_deployment", HERE / "deploy_private.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def fixture_database(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, role TEXT, status TEXT)")
        db.execute("INSERT INTO employees VALUES (4, ?, 'super_admin', 'active')", ("李炳斌",))
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('ab6d8e2f0411')")
        db.execute("CREATE TABLE finance_sentinel (amount INTEGER)")
        db.execute("INSERT INTO finance_sentinel VALUES (70000)")
        for value in range(80):
            db.execute(f"CREATE TABLE synthetic_table_{value} (id INTEGER)")


class DeploymentSafety(unittest.TestCase):
    def test_static_html_retains_existing_crm_security_headers(self):
        block = deploy.static_block(Path("/opt/t24-crm/public-releases/synthetic-test"))
        locations = dict(re.findall(r"location ([^\n]+) \{\n(.*?)\n    \}", block, flags=re.S))
        body = locations["/"]
        for name in ("X-Frame-Options", "Content-Security-Policy", "Strict-Transport-Security",
                     "Referrer-Policy", "Permissions-Policy", "X-Content-Type-Options"):
            self.assertRegex(body, r"add_header " + re.escape(name) + r"\b")
        self.assertIn("frame-ancestors 'self'", body)
        self.assertIn("SAMEORIGIN", body)

    def test_private_and_existing_crm_routes_stay_separate(self):
        block = deploy.static_block(Path("/opt/t24-crm/public-releases/synthetic-test"))
        locations = dict(re.findall(r"location ([^\n]+) \{\n(.*?)\n    \}", block, flags=re.S))
        for location in ("= /api/v1/private-workspace", "^~ /api/v1/private-workspace/"):
            self.assertIn("proxy_pass http://127.0.0.1:8001;", locations[location])
            self.assertIn("access_log off;", locations[location])
        for location in ("^~ /api/", "= /health", "= /ready"):
            self.assertIn("proxy_pass http://127.0.0.1:8000;", locations[location])

    def test_snapshot_is_consistent_and_never_mutates_business(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "business.db", root / "backup.db"
            fixture_database(source)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            result = deploy.snapshot(source, output)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            self.assertEqual(len(result), 83)
            with sqlite3.connect(output) as db:
                self.assertEqual(db.execute("SELECT amount FROM finance_sentinel").fetchone(), (70000,))

    def test_snapshot_rejects_existing_output_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "business.db", root / "preexisting.db"
            fixture_database(source)
            output.write_bytes(b"synthetic preexisting content")
            with self.assertRaisesRegex(RuntimeError, "NEW_BACKUP_REQUIRED"):
                deploy.snapshot(source, output)
            self.assertEqual(output.read_bytes(), b"synthetic preexisting content")

    def test_snapshot_rejects_dangling_output_symlink_before_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, external = root / "business.db", root / "backup.db", root / "outside-target.db"
            fixture_database(source)
            output.symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, "NEW_BACKUP_REQUIRED"):
                deploy.snapshot(source, output)
            self.assertFalse(external.exists(), "A backup followed a preexisting output symlink")

    def test_snapshot_rejects_source_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, linked, output = root / "business.db", root / "linked.db", root / "backup.db"
            fixture_database(source)
            linked.symlink_to(source)
            with self.assertRaisesRegex(RuntimeError, "BUSINESS_FILE_REQUIRED"):
                deploy.snapshot(linked, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
