#!/usr/bin/env python3
"""Pinned frontend-only release; abort on source drift and preserve the existing backend."""
import concurrent.futures, hashlib, json, os, pathlib, re, sqlite3, subprocess, time, urllib.request
APP = pathlib.Path('/opt/t24-crm/app')
REL = pathlib.Path('/opt/t24-crm/releases/system-layout-20261008')
OLD_IMAGE = 't24-crm:commission-fd12d9d'
NEW_IMAGE = 't24-crm:system-layout-20261008'
SOURCE_SHA = '601e17662e2d181a6000e53cd0259eda15c7a7a2'
MANIFEST = [{'path': 'frontend/src/components/Layout.tsx', 'before': '1da5f8b2cb28173a325a60938b7623a207fd7393f0256450890a40d6654f29e5', 'after': '31c762852bfce90c71cad12738bb366b82313cb7ba935a9e15e6b300c06bef98'}, {'path': 'frontend/src/pages/Callbacks.tsx', 'before': '4ef286aed39204e2b107677647934b724144f260578131a4a4fbdfd7f15aab53', 'after': '74514053c905fd4e3d3506bfec1470922174f535e6c825f4942903db9cc813e3'}, {'path': 'frontend/src/pages/Commissions.tsx', 'before': 'ed0dac8fa6befd12639633bc37f8477d1389bc15ad9b2781e463fd151194a410', 'after': 'ed0dac8fa6befd12639633bc37f8477d1389bc15ad9b2781e463fd151194a410'}, {'path': 'frontend/src/pages/CompanyRoadmap.tsx', 'before': '1d8d40c2a74b5118e8d6e4274bec673fa332ebcec9f3487c5b1692680ffed700', 'after': '8d9cf80c6597d7ed04a8269bebd06ebf1cbfbb7eb9a2be537d890f7e217ac4d4'}, {'path': 'frontend/src/pages/CustomerLifecycle.tsx', 'before': 'e5e6a678aedb261a83b4df731f2b78dc0996d50cddfdf404c939ec9ab35672f4', 'after': 'ad8172c40333f15e6442c971c5420019e465ffb640b3ce29888f5a0221975ba6'}, {'path': 'frontend/src/pages/Customers.tsx', 'before': '65241f13531842ec8265e4e99a3b52c3f5c734bc84014b9d94f2edf1cd95ac18', 'after': '87f2c21df27cb4fc1bc8b007789146eae3f7ab7d3eca48143cb2b2a6806bc782'}, {'path': 'frontend/src/pages/Dashboard.tsx', 'before': '824cee89edb8f51df45834a277acf920a1081fe1f6fbe8a36ceba0004d124a20', 'after': '6b2f6f5f47403ffdb4006623355a2d95f64e815b808ebd713e01af8f79557293'}, {'path': 'frontend/src/pages/Deals.tsx', 'before': '4ffecad912ae88daeb1cc8991342788fac80d0c70194ede7ccb4e676947230e6', 'after': 'c3b411c7d8d754e0939c848ebe562a5378d5f8c26cd170a5179a44c03cf5bfad'}, {'path': 'frontend/src/pages/Employees.tsx', 'before': '0f0c1146a57cf51eea11559e315b8a861c0b42d5472380deb2ede02e3aeeccdb', 'after': '0db037fd55330472373ac71bdb7aeca9bd36e6fe38c9d01502395d2dea018050'}, {'path': 'frontend/src/pages/Finance.tsx', 'before': '6c548620c8e20102fd0626b459476986275f9e80cbe7cc806667f2a3f93f5f94', 'after': 'd666b9704dadd91200248bdf44d04aadc57613a469af921be05b36a0de041010'}, {'path': 'frontend/src/pages/ManagementDecisions.tsx', 'before': '7813b8363008d8baa10b878f46c5abe77c576d690d2e60d2e1666bfda033bc0c', 'after': '78f2720799ea1d84941c11f05c7d11c77a5f4cbf3ba7b4a2600a452453e419dc'}, {'path': 'frontend/src/pages/MerchantPool.tsx', 'before': '07a437749cef638ef905c4c3f5052497fad0547e8f5848a38f539e0fb5ce462a', 'after': '79da820f0170390a6c10a2f8b138120cfc108bd002b940bf80f9c4a32b91544b'}, {'path': 'frontend/src/pages/MonthlyDeduction.tsx', 'before': 'd45517f8f4c4b3b0d09b1a7fec7a245ced4ab260ec407f144f2c76dd9bfd739a', 'after': '62461f1a9ee1f382e068e82b963c420ec25d193de44e4815df076a6d1bbaa428'}, {'path': 'frontend/src/pages/OperationsWorkbench.tsx', 'before': 'a3217cf10b0b183ba28036289f8d5909c7334008adf34b4879111aa96aaaeef0', 'after': 'a82e0fed430facc87b065d7cdb2e05aa5efaf68c13b6c4eee8be265e8487cb76'}, {'path': 'frontend/src/pages/PartnerPortal.tsx', 'before': '09995d258a5be233f10a129ea34956a1001bb0741cf6e48bd6a52687d0291ded', 'after': 'f03e9b298ebe30f56eb900ce4af0e116d75351dce681672f0ee30f0e3638251a'}, {'path': 'frontend/src/pages/Payroll.tsx', 'before': 'fa553738eb53e7fcda14721947527197353053542b3f113afd9e2d1d950ca43c', 'after': '344103e54c3bc3e6eb60d58a506185c7d70d5df83a0560283336653e9c643f12'}, {'path': 'frontend/src/pages/Permissions.tsx', 'before': '424825bfb108051fa68e7ebd7b028f4486042c54aa31b0f14643c4a452e3fb6e', 'after': '318f2a12238598cc92f93f487f008ce3db90211a483e3aa5d184de0f1dd51533'}, {'path': 'frontend/src/pages/RmbProfitEstimate.tsx', 'before': 'ac560a0d686e80c02a30e446bf85cdf1a2c00d8c26e0fbe4fb4651a59e836468', 'after': 'd79f1a1b991cbddb7a59051110b1d31a3db35af4d56fe1fb317836369e739a31'}, {'path': 'frontend/src/pages/Sales.tsx', 'before': 'a27d4d9cc00e0720d2bf0b0e6374438914f353c00ec5a413baa62b7aaf079f5c', 'after': '1857875e4a0cd1db409be78e7c32483decdc3edaa0e76f63cf01e81b7f45d417'}, {'path': 'frontend/src/pages/SalesKnowledge.tsx', 'before': '01b63e4694314ae09d26e66d7b01f1192fc134183b1235e477a0920e1dfbad86', 'after': '574b48ed3fdca2755994f14c4963a89415ac7d2cdc3076a30f2cfa4975b0cf92'}, {'path': 'frontend/src/pages/SalesLeads.tsx', 'before': '20df4ecd2881303f86c95070f08947244a215e09834449b5a83df3b634b62b74', 'after': '62c37c2b3214119c43fd35aa7891e24cf89448862ba6eb762ec7169f7688344e'}, {'path': 'frontend/src/pages/SalesWorkbench.tsx', 'before': 'b0a22d6804504dcbc76d0f2f261e9127c2c202abfa3d6f9b6cd4137ee0ef26ca', 'after': 'fa2f38aecaa9a23f9324b8a2d93eb27d95affc1ef2758d66b011b17601004cd8'}, {'path': 'frontend/src/pages/ServiceBoard.tsx', 'before': 'b252b4779d1486b5aa20b10f9c7ca7b392e66204785aa290028b3006ee890949', 'after': 'a69e5dc6e53a3f2967543271bce9ee93c57b593934947ef41fdf9f1129f0ed54'}, {'path': 'frontend/src/pages/Settings.tsx', 'before': '38898a2e6a2d58714fed02d4c136402449ce048b68f3b8efa71c6932d9637ac4', 'after': '3780fd76e4c3ad61a340e118a191426e42b81743119912664bf8d60961652291'}, {'path': 'frontend/src/pages/Tasks.tsx', 'before': 'd51904cdba7fc81bb0b9dff9a83d3fb018106a28be336d35667715ae02d3318b', 'after': '603cd299de605ed42eff4619755b52be40219048c3d4bb1f9bf5f93f7fa72a01'}, {'path': 'frontend/src/pages/admin-workspace.css', 'before': None, 'after': '526c9adae2ee6c1b4b176dfdde6890b6750950978d82fe3c6ca286a4df14d628'}, {'path': 'frontend/src/pages/commissions.css', 'before': '3a4e1e15eeb62e573f99c24e549144fe404224519683355f3522ebe40e0dde0e', 'after': '3a4e1e15eeb62e573f99c24e549144fe404224519683355f3522ebe40e0dde0e'}, {'path': 'frontend/src/pages/delivery-workspace.css', 'before': None, 'after': '9a8739e91aa4f43a6f4616734fc3a1bf5e05425e0122b095a63227217bf954aa'}, {'path': 'frontend/src/pages/sales-workspace.css', 'before': None, 'after': '5b73c68e2d6aa8c5826244f1f7579dbd1044536f1a93c4e923f0838f0aadcc08'}, {'path': 'frontend/src/pages/workspace-layout.css', 'before': None, 'after': '287b019949d6468252766a354ee797fd689e86b0ecb93c4e7a4e3406e1f1fa4f'}]

def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def financial_snapshot():
    con = sqlite3.connect(f'file:{APP}/data/crm_prod.db?mode=ro', uri=True)
    try:
        con.execute('BEGIN')
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result = {}
        for name in names:
            if not re.search(r'payment|refund|deal|expense|commission|payroll|subscription|deduction|finance_period', name):
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            rows = con.execute(f'SELECT * FROM {quoted} ORDER BY rowid').fetchall()
            payload = json.dumps(rows, ensure_ascii=False, default=str, separators=(',', ':')).encode()
            result[name] = {'count': len(rows), 'sha256': hashlib.sha256(payload).hexdigest()}
        return result
    finally:
        con.close()

def download(row):
    url = f'https://raw.githubusercontent.com/billy285/t24-crm/{SOURCE_SHA}/app/{row["path"]}'
    blob = urllib.request.urlopen(url, timeout=45).read()
    assert hashlib.sha256(blob).hexdigest() == row['after'], row['path']
    return row, blob

os.chdir(APP)
assert run(['hostname'], capture_output=True, text=True).stdout.strip() == 'iZj6c4cj7edgnhdimts4l7Z'
actual = run(['docker', 'inspect', '-f', '{{.Config.Image}}', 't24-crm'], capture_output=True, text=True).stdout.strip()
assert actual == OLD_IMAGE, f'Unexpected running image: {actual}'
for row in MANIFEST:
    p = APP / row['path']
    assert (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) == row['before'], f'Production source drift: {p}'
print('SOURCE_PRECHECK_OK', len(MANIFEST), flush=True)
REL.mkdir(parents=True, exist_ok=True)
assert (REL / 'frontend-before.tar.gz').exists(), 'Source backup required'
run(['bash', 'deploy/backup-sqlite.sh'])
run(['bash', 'deploy/verify-backup-restore.sh'])
before = financial_snapshot()
(REL / 'financial-before.json').write_text(json.dumps(before, indent=2))
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    downloaded = list(pool.map(download, MANIFEST))
for row, blob in downloaded:
    p = APP / row['path']
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
print('FRONTEND_FILES_VERIFIED', SOURCE_SHA, flush=True)
original = (APP / 'Dockerfile').read_text()
frontend_stage = original.split('FROM python:', 1)[0]
(REL / 'Dockerfile.ui').write_text(frontend_stage + f'FROM {OLD_IMAGE}\nCOPY --from=frontend-builder /app/frontend/dist /app/frontend/dist\n')
run(['docker', 'build', '-f', str(REL / 'Dockerfile.ui'), '-t', NEW_IMAGE, '.'])
run(['docker', 'tag', OLD_IMAGE, 't24-crm:before-system-layout-20261008'])
def backend_digest(image):
    command = "find /app/backend -type f ! -name '*.pyc' ! -path '*/data/*' ! -path '*/logs/*' -print0 | sort -z | xargs -0 sha256sum | sha256sum"
    return run(['docker', 'run', '--rm', '--entrypoint', 'sh', image, '-c', command], capture_output=True, text=True).stdout.strip()
assert backend_digest(OLD_IMAGE) == backend_digest(NEW_IMAGE), 'Backend changed'
print('BACKEND_IDENTICAL', flush=True)
release_env = dict(os.environ, CRM_IMAGE=NEW_IMAGE)
try:
    run(['docker', 'compose', 'up', '-d', '--no-build', 'crm'], env=release_env)
    for _ in range(45):
        try:
            urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError('New container is not ready')
    for url in ['http://127.0.0.1:8000/health', 'https://t24-crm.com/ready', 'https://t24-crm.com/health']:
        assert urllib.request.urlopen(url, timeout=20).status == 200, url
    after = financial_snapshot()
    (REL / 'financial-after.json').write_text(json.dumps(after, indent=2))
    assert before == after, 'Business records changed during release; inspect before proceeding'
except Exception:
    run(['docker', 'compose', 'up', '-d', '--no-build', 'crm'], env=dict(os.environ, CRM_IMAGE=OLD_IMAGE))
    raise
run(['docker', 'tag', NEW_IMAGE, 't24-crm:local'])
(REL / 'release.json').write_text(json.dumps({'source_sha': SOURCE_SHA, 'image': NEW_IMAGE, 'financial_tables': len(before), 'backend_identical': True, 'business_records_identical': True}, indent=2))
print('RELEASE_VERIFIED', SOURCE_SHA, 'financial_tables', len(before), flush=True)
