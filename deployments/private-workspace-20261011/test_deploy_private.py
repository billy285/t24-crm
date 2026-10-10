"""Offline deployment rejection tests; no production paths, Docker or network."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("private_release_deployment", HERE / "deploy_private.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
prep_spec = importlib.util.spec_from_file_location("private_release_preparation", HERE / "prepare_private.py")
prep = importlib.util.module_from_spec(prep_spec)
prep_spec.loader.exec_module(prep)


def fixture_crm_inspection():
    return {
        "Id": deploy.BASE_CONTAINER,
        "Image": deploy.BASE_IMAGE,
        "State": {"StartedAt": deploy.BASE_STARTED, "Running": True, "Health": {"Status": "healthy"}},
        "Config": {
            "Env": ["SYNTHETIC_SETTING=original"],
            "Labels": {
                "t24.source.sha": prep.BASE_SOURCE,
                "com.docker.compose.service": "crm",
                "com.docker.compose.project.working_dir": str(prep.APP),
                "com.docker.compose.project.config_files": str(prep.APP / "docker-compose.yml") + "," +
                    str(prep.BASE_RELEASE / "compose-new.json"),
            },
        },
        "HostConfig": {"PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]},
                       "Memory": 0},
        "Mounts": [
            {"Source": str(prep.APP / "data"), "Destination": "/app/backend/data", "Type": "bind", "RW": True},
            {"Source": str(prep.APP / "logs"), "Destination": "/app/backend/logs", "Type": "bind", "RW": True},
        ],
    }


def fixture_crm_identity(inspection):
    return {
        "container_id": inspection["Id"], "image_id": inspection["Image"],
        "started_at": inspection["State"]["StartedAt"],
        "configuration_sha256": deploy.digest({key: inspection[key] for key in ("Config", "HostConfig", "Mounts")}),
    }


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
    def matches_preparation(self, current, before):
        # Exercise the real preparation identity guards and deploy runtime guard.
        # Both inspections are synthetic; no Docker command or network is used.
        result = SimpleNamespace(returncode=0, stdout=json.dumps([current]), stderr="")
        with mock.patch.object(deploy, "inspect", return_value=current), \
                mock.patch.object(prep.subprocess, "run", return_value=result):
            return deploy.crm_matches_preparation(prep, before)

    def test_crm_identity_accepts_only_mount_list_reordering(self):
        original = fixture_crm_inspection()
        before = fixture_crm_identity(original)
        self.assertTrue(self.matches_preparation(original, before))
        reordered = copy.deepcopy(original)
        reordered["Mounts"].reverse()
        self.assertTrue(self.matches_preparation(reordered, before))

    def test_crm_identity_rejects_environment_or_host_configuration_changes(self):
        original = fixture_crm_inspection()
        before = fixture_crm_identity(original)
        for field in ("Env", "HostConfig"):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed["Mounts"].reverse()
                if field == "Env":
                    changed["Config"]["Env"] = ["SYNTHETIC_SETTING=changed"]
                else:
                    changed["HostConfig"]["Memory"] = 1024
                self.assertFalse(self.matches_preparation(changed, before))

    def test_crm_identity_rejects_mount_read_write_permission_changes(self):
        original = fixture_crm_inspection()
        changed = copy.deepcopy(original)
        changed["Mounts"][0]["RW"] = False
        with self.assertRaisesRegex(prep.PrepareError, "CRM_MOUNTS_DRIFT"):
            self.matches_preparation(changed, fixture_crm_identity(original))

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
