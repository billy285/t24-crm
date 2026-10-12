"""Synthetic immutable Git packaging checks, with no server/provider operations."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("finance_donut_hover_payload", Path(__file__).with_name("build_payload.py"))
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


def run(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo)


def make_file(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def source(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q")
    run(repo, "config", "user.name", "Synthetic packaging test")
    run(repo, "config", "user.email", "synthetic@example.invalid")
    for name, text in {
        "app/backend/main.py": "# unchanged backend\n", "app/backend/.gitignore": "__pycache__/\n",
        "app/frontend/src/components/Layout.tsx": "// original layout\n",
        "app/frontend/src/components/crm-desktop-refined-type.css": "/* unchanged desktop scale */\n",
        "app/frontend/src/pages/Finance.tsx": "// original finance\n",
        "app/frontend/src/pages/PrivateWorkspace.tsx": "// unchanged private workspace\n",
        "app/frontend/src/components/MobileFinanceDetails.tsx": "// unchanged phone finance\n",
    }.items():
        make_file(repo, name, text)
    run(repo, "add", "app")
    run(repo, "commit", "-qm", "Synthetic baseline")
    baseline = run(repo, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(b, "BASELINE", baseline)
    for name in b.ALLOWED:
        make_file(repo, name, "// synthetic presentation " + name + "\n")
    run(repo, "add", "app")
    run(repo, "commit", "-qm", "Synthetic CRM presentation")
    previous_source = run(repo, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(b, "PREVIOUS_SOURCE", previous_source)
    for name in b.FOLLOWUP_ALLOWED:
        make_file(repo, name, "/* synthetic follow-up hover interaction */\n")
    run(repo, "add", *sorted(b.FOLLOWUP_ALLOWED))
    run(repo, "commit", "-qm", "Synthetic follow-up hover interaction")
    commit = run(repo, "rev-parse", "HEAD").decode().strip()
    # The version is supplied by the caller's frozen build, using the actual
    # established Node ordering rather than Python lexical ordering.
    node_script = """const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const h=crypto.createHash('sha256'),root=process.argv[1];
function visit(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
const p=path.join(dir,e.name);if(e.isDirectory())visit(p);else{h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}
visit(root);process.stdout.write(h.digest('hex').slice(0,12));"""
    version = subprocess.check_output([str(b.NODE), "-e", node_script, str(repo / "app/frontend/src")]).decode()
    dist = repo / "app/frontend/dist"
    dist.mkdir()
    (dist / "app-version.json").write_text(json.dumps({"version": version}))
    (dist / "index.html").write_text('<script src="/assets/synthetic.js"></script>')
    (dist / "assets").mkdir()
    (dist / "assets/synthetic.js").write_text("// synthetic built asset\n")
    proof = {"format_version": 1, "stage": "FINANCE_DONUT_PRESENTATION_SOURCE_PROOF", "source_mode": "committed",
        "baseline_source_sha": baseline, "source_sha": commit,
        "finance_file_before_sha256": b.sha(run(repo, "cat-file", "blob", baseline + ":app/frontend/src/pages/Finance.tsx")),
        "finance_file_after_sha256": b.sha(run(repo, "cat-file", "blob", commit + ":app/frontend/src/pages/Finance.tsx")),
        "financial_calculations_unchanged": True, "event_handlers_unchanged": True, "table_cells_unchanged": True,
        "dialogs_unchanged": True, "private_workspace_source_unchanged": True,
        "chart_inputs_unchanged": True, "component_presentation_only": True,
        "chart_regions_replaced": 4, "preserved_finance_ast_sha256": "e" * 64,
        "component_file_sha256": b.sha(run(repo, "cat-file", "blob", commit + ":app/frontend/src/components/FinanceDonutChart.tsx")),
        "styles_file_sha256": b.sha(run(repo, "cat-file", "blob", commit + ":app/frontend/src/components/finance-donut-chart.css"))}
    proof_file = tmp_path / "synthetic-approved-proof.json"
    proof_file.write_text(json.dumps(proof))
    args = SimpleNamespace(repo=repo, source_sha=commit, frontend_version=version, node=b.NODE,
        presentation_proof=proof_file, presentation_proof_sha256=b.sha(proof_file.read_bytes()), artifacts=tmp_path / "artifacts")
    return SimpleNamespace(repo=repo, args=args, proof=proof, baseline=baseline, commit=commit, version=version, dist=dist)


def test_real_git_source_checks_and_reproducible_complete_static_tar(source):
    result = b.package(source.args)
    manifest = json.loads((source.args.artifacts / "static-manifest.json").read_bytes())
    payload = (source.args.artifacts / "static-payload.tar.gz").read_bytes()
    assert result["source_sha"] == source.commit and manifest["payload_sha256"] == b.sha(payload)
    assert set(manifest["changed_source_files"]) == b.ALLOWED
    assert "app/backend/.gitignore" in manifest["preserved_source_inventories"]["backend"]
    assert manifest["preserved_source_inventories"]["private_frontend"]["app/frontend/src/pages/PrivateWorkspace.tsx"]
    assert manifest["changed_source_files"]["app/frontend/src/pages/Finance.tsx"]
    assert manifest["preserved_source_inventories"]["private_frontend"]["app/frontend/src/components/Layout.tsx"]
    assert manifest["preserved_source_inventories"]["private_frontend"]["app/frontend/src/components/crm-desktop-refined-type.css"]
    assert manifest["stage"] == "FINANCE_DONUT_HOVER_STATIC_PAYLOAD_PREPARED"
    assert manifest["presentation_preservation_proof"] == source.proof
    again, files = b.dist_archive(source.dist, source.version)
    assert payload == again and files == manifest["payload_files"]
    with tarfile.open(source.args.artifacts / "static-payload.tar.gz", "r:gz") as stream:
        members = stream.getmembers()
        assert {item.name.removeprefix("payload/") for item in members} == set(files)
        assert all(item.isfile() and item.uid == item.gid == item.mtime == 0 and item.mode == 0o644 for item in members)


@pytest.mark.parametrize("drift", ["working_source", "untracked_source", "build_version", "frozen_source", "expected_version"])
def test_packaging_rejects_checkout_or_build_drift(source, drift):
    if drift == "working_source":
        make_file(source.repo, "app/frontend/src/pages/Finance.tsx", "uncommitted change")
    elif drift == "untracked_source":
        make_file(source.repo, "app/frontend/src/Unexpected.tsx", "untracked change")
    elif drift == "build_version":
        (source.dist / "app-version.json").write_text('{"version":"ffffffffffff"}')
    elif drift == "frozen_source":
        source.args.source_sha = source.baseline
    else:
        source.args.frontend_version = "f" * 12
    with pytest.raises(b.PayloadError):
        b.package(source.args)
    assert not source.args.artifacts.exists()


@pytest.mark.parametrize("name", ["app/backend/main.py", "app/frontend/src/pages/PrivateWorkspace.tsx",
    "app/frontend/src/components/MobileFinanceDetails.tsx", "app/frontend/src/components/CompactFinanceTable.tsx",
    "app/frontend/src/components/crm-desktop-refined-type.css", "app/frontend/src/components/Layout.tsx"])
def test_committed_backend_private_or_phone_changes_cannot_enter_release(source, name):
    make_file(source.repo, name, "forbidden committed scope change")
    run(source.repo, "add", name)
    run(source.repo, "commit", "-qm", "Synthetic rejected scope")
    source.args.source_sha = run(source.repo, "rev-parse", "HEAD").decode().strip()
    with pytest.raises(b.PayloadError, match="EXACT_CHART_INTERACTION_ONLY_REQUIRED"):
        b.package(source.args)


@pytest.mark.parametrize("field,value", [
    ("stage", "CRM_FINANCE_REFINED_PRESENTATION_SOURCE_PROOF"),
    ("source_mode", "working_tree_preview"),
    ("source_sha", "f" * 40), ("finance_file_before_sha256", "f" * 64),
    ("finance_file_after_sha256", "f" * 64), ("financial_calculations_unchanged", False),
    ("event_handlers_unchanged", False), ("table_cells_unchanged", False),
    ("dialogs_unchanged", False), ("chart_inputs_unchanged", False),
    ("component_presentation_only", False), ("private_workspace_source_unchanged", False),
    ("component_file_sha256", "f" * 64), ("styles_file_sha256", "f" * 64),
    ("chart_regions_replaced", 3), ("chart_regions_replaced", "4"), ("preserved_finance_ast_sha256", "invalid"),
])
def test_independent_presentation_proof_must_match_exact_source_and_approved_scope(source, field, value):
    source.proof[field] = value
    source.args.presentation_proof.write_text(json.dumps(source.proof))
    source.args.presentation_proof_sha256 = b.sha(source.args.presentation_proof.read_bytes())
    with pytest.raises(b.PayloadError, match="EXACT_APPROVED_PRESENTATION_SOURCE_PROOF_REQUIRED"):
        b.package(source.args)


def test_proof_file_hash_cannot_be_replaced_by_unreviewed_content(source):
    source.args.presentation_proof.write_text(json.dumps({**source.proof, "unreviewed": True}))
    with pytest.raises(b.PayloadError, match="PRESENTATION_SOURCE_PROOF_HASH_DRIFT"):
        b.package(source.args)


@pytest.mark.parametrize("name", [".env", "assets/.gitignore", "db.sqlite", "extra.html"])
def test_no_secrets_databases_or_arbitrary_html_in_static_archive(source, name):
    make_file(source.dist, name, "synthetic forbidden bytes")
    with pytest.raises(b.PayloadError, match="STATIC_FILE_SCOPE_REJECTED"):
        b.package(source.args)


def test_static_symlink_is_not_packaged(source):
    (source.dist / "assets/symlink.js").symlink_to(source.dist / "assets/synthetic.js")
    with pytest.raises(b.PayloadError, match="STATIC_SYMLINK_REJECTED"):
        b.package(source.args)


def test_existing_frozen_artifacts_are_not_overwritten(source):
    b.package(source.args)
    payload = (source.args.artifacts / "static-payload.tar.gz").read_bytes()
    with pytest.raises(b.PayloadError, match="FRESH_FROZEN_ARTIFACT_NAMES_REQUIRED"):
        b.package(source.args)
    assert (source.args.artifacts / "static-payload.tar.gz").read_bytes() == payload


@pytest.mark.parametrize("name", ["app/frontend/src/pages/Finance.tsx"])
def test_hover_cannot_change_prior_reviewed_finance(source, name):
    make_file(source.repo, name, "unexpected presentation logic change")
    run(source.repo, "add", name)
    run(source.repo, "commit", "-qm", "Synthetic rejected hover scope")
    source.args.source_sha = run(source.repo, "rev-parse", "HEAD").decode().strip()
    with pytest.raises(b.PayloadError, match="EXACT_CHART_INTERACTION_ONLY_REQUIRED"):
        b.package(source.args)
