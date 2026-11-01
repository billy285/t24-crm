"""Execute the exact offline route/idle probe against synthetic local schema."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
r=load(HERE/'release.py','onboarding_exact_idle_release_test')
schema=load(HERE/'test_schema_migration.py','onboarding_exact_idle_schema_test')

def test_exact_actual_app_routes_owner_denial_and_empty_queue_readonly(tmp_path):
    path=tmp_path/'synthetic-only.db';schema.seed(path);schema.apply(path)
    probe=r.ONBOARDING_PROBE_TEMPLATE.replace('__EXPECTED__',repr(set(r.ONBOARDING_ROUTES)))
    assert probe.count('assert sys.version_info[:2]==(3,10)')==1
    assert probe.count('/app/backend/data/crm_prod.db')==1
    # Local Python differs from the pinned production3.10. Only interpreter
    # assertion and synthetic read-only fixture path change in this local test.
    probe=probe.replace('assert sys.version_info[:2]==(3,10)','assert sys.version_info[:2]=='+repr(sys.version_info[:2])).replace('/app/backend/data/crm_prod.db',str(path))
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(tmp_path),'LANG':'C.UTF-8','APP_ENV':'test','ENVIRONMENT':'test','PYTHONPATH':str(ROOT/'app/backend'),
        'T24_GBP_ONBOARDING_WORKER_ENABLED':'false','T24_MEDIA_ASSET_WORKER_ENABLED':'false','T24_GBP_EXECUTION_ENABLED':'false','T24_GBP_SCHEDULER_ENABLED':'false','T24_META_OPERATIONS_EXECUTION_ENABLED':'false','T24_META_OPERATIONS_SCHEDULER_ENABLED':'false'}
    before=schema.state(path)
    child=subprocess.run([sys.executable,'-B','-c',probe],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr[-12000:]+child.stdout[-2000:]
    assert 'EXACT_ONBOARDING_ROUTES_OWNER_IDLE_READONLY' in child.stdout
    assert schema.state(path)==before
