#!/usr/bin/env python3
"""Prepare a frozen local release carrier; never build, push or deploy it.

Backend and regression sources are read only from the reviewed Git commit.
The separately reviewed Vite output is pinned by a complete SHA-256 inventory.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

SOURCE_SHA = '1a9232dcc04a6d09d0f4f60193c693bbb6243476'
BASE_SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
BASE_IMAGE = 'sha256:3edf765dac63430764b5f294a1ac0e0114763c3a59e5afa6790bf3dfc49f5734'
FRONTEND_VERSION = '22b2d2ad92c2'
# Reproduced from the Git blobs with vite.config.ts localeCompare traversal.
FRONTEND_SOURCE_DIGEST = '22b2d2ad92c2c6c41722a1cbb9b37a38ba41fb3732672885f7bb8a5349d20441'
BACKEND_CHANGES = {
    'app/backend/models/private_personal_finance.py': 'A',
    'app/backend/routers/private_personal_finance.py': 'A',
    'app/backend/schemas/private_personal_finance.py': 'A',
    'app/backend/services/private_personal_finance.py': 'A',
    'app/backend/services/private_workspace.py': 'M',
    'app/backend/services/private_workspace_app.py': 'M',
    'app/backend/tests/test_private_personal_finance.py': 'A',
    'app/backend/tests/test_private_workspace_core.py': 'M',
}
PRIVATE_TEST = re.compile(r'app/backend/tests/test_private_[a-z0-9_]+\.py')
DEPENDENCY_NAMES = re.compile(r'(?:requirements(?:[.][A-Za-z0-9_-]+)?|requirements[A-Za-z0-9_.-]*\.txt|'
    r'package\.json|(?:package|npm-shrinkwrap)-lock\.json|pnpm-lock\.yaml|yarn\.lock|'
    r'pyproject\.toml|poetry\.lock|Pipfile(?:\.lock)?|Dockerfile(?:[.][A-Za-z0-9_-]+)?)')
STATIC_SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif',
                   '.svg', '.ico', '.txt', '.woff', '.woff2', '.ttf', '.webmanifest'}
FRONTEND_DIST_SHA256 = {
    "app-version.json": "2b858b13e0e4858dd7ef7ade1433d8cf42961acaed4e940a80a7f6740fc2b594",
    "apple-touch-icon.png": "f8738c81ffd4ad03e9f73cc60fa42f0556409e624c40078dd0343003795385fa",
    "assets/App-COQKDJSY.css": "f9d64d33653ef5415e76473b1ccd84ec6308ed8af8737875ce1d62e38f7cd617",
    "assets/App-CR0vu_0F.js": "bd67545cda4854aaf7a3752a122cfe1ea67a790ab1a16a10553a7d1635029d43",
    "assets/AuthCallback-5VZmQJtK.js": "fbee9dd46d754b332d413350ddbe4e8fa937a117be17690bbe57e3bda779c3e1",
    "assets/AuthError-CSC61QuX.js": "3318ce94d94feb55a1b8ab956587eb2b2a896fe076df609bef63f46f2526a3a7",
    "assets/BarChart-DW135V25.js": "1d5038be3acc6008bda92ab05c292f645a5ad33af174b2eb349490098457f7f6",
    "assets/Callbacks-DUHM5nUn.js": "4faba4c22f1f56157ec329bfc534dc92c3b48e7cdb9049ba684be998c0baecc2",
    "assets/Commissions-B6cpEw-v.css": "cdfd0375c39eb16882aac0a3873c791c1b45816f2f00bb974ad2d4387484073a",
    "assets/Commissions-BrRVdRVL.js": "d7d314b6a1f5734541f9dc56cc928dd03814940ebc97003a8f23bc9a3fa6677b",
    "assets/CompanyRoadmap-C6B2idYo.js": "903ad99cc4d3b7ddca7f57ca26fe71d5ea18235f856f1e798cce17065d53ca21",
    "assets/ConfirmDialog-CK4_6urb.js": "c62c4499bd56ed7e9eec25de0c1d67c3d95fe93c255b10f1baa8f61401d4a286",
    "assets/CustomerCombobox-C6ipTKoo.js": "4b5e514d83890d66a0cce88a3082e748e5512c5469e333221ae23570f44d82f0",
    "assets/CustomerLifecycle-BBks_S49.js": "a3989bffdcaaeffb7e15b69ddbc114c9b849f68d5ddc7f7d6b7ef0c4e0e64279",
    "assets/CustomerPhoneDial-BJQUSBLO.js": "39784e854aa63fe18d8c5692f9a02c244138a49e16f587a03bced126abf7faa5",
    "assets/Customers-BzOq9era.js": "3eee434f7522ebe29a564b1893ffe0a77577139900c22d40419c9db8668ac99e",
    "assets/Dashboard-B5iIHGLc.js": "53a4bd450e459ff851b4b0ab454986a551ffc4d02e1cde9fc3ce16ae0f52187b",
    "assets/Dashboard-HdLurmrA.css": "d5db6dbd01a8e3f046285d93422e46198ed1abbf40790877d4ba255f4c5a9fb1",
    "assets/Deals-C5rRvD1d.css": "c298dc4ba5f22e3bd19bef829426b462ebbfe02e371fca37432646a806d60cd4",
    "assets/Deals-CTL7IFbF.js": "2d81f91503a4f29245c8b4d9fa3939716f2e3b1dd0c0a3f84e0ab60398d10e82",
    "assets/DeliveryUI-CnfC8g0U.js": "4b1f91f54eea115d4a5644579177cc9c43dd346e7a4d24fe57446dab3b923d1b",
    "assets/DeliveryUI-DBOQPikG.css": "0bb9b912fdaccc9adc6cf92ed15b9fe00e37ee95b374b42b5d2886474249e95f",
    "assets/Employees-Co2ktdXq.js": "dee88b9c28f9195c027433e1cd293a8d9ebcfef95b982bffc1db00ffa7158992",
    "assets/ExportButton-BaCW-Gjy.js": "4e8005d88236a0c2cd64b4339cded40ad665296511b5abcdc15954e6c1528392",
    "assets/Finance-BgZDIa-q.css": "5baf7034a8f21dd6b24ad8759f9544a3f224e4b72db2ccc279c4ec160de73dc4",
    "assets/Finance-DWg6dqwC.js": "4aa1a32a6cbc03e736db8057e59bb451d50b4005764c17e2307257b15922127c",
    "assets/ImportCustomers-Dp8QRWPs.js": "cc4ea45a1232d100393a90d36effa9d42c3ca1e343a009dd1b96d0603cd5d5c2",
    "assets/Line-B7yGQeVN.js": "da49891ce11b736582d738ac219692d7fd5a45ab54b5b6c425b75f30f2b9e75c",
    "assets/LoginPage-DLkcxjQe.js": "afb9e57deac8c264689823fcea9f17bd6d2f37473639a730e55f8809303116b3",
    "assets/ManagementDecisions-XMtly9Pj.css": "47518f7b5dfb6d59d47ec47a29aed35461afb484d8e21239f06acea058202859",
    "assets/ManagementDecisions-ockeCct0.js": "ff9156cc422cc550b30f06748fb82b7b53c8319075ba55d1af7a9dd18b095fdb",
    "assets/MerchantPool-Syagh6Kf.css": "dfbdcda0ee239748d49fba7d369e5bfe6fad2b108c9065ceb75ff85c41e72d70",
    "assets/MerchantPool-ZjPmSiWb.js": "2c8d9f6ff74b57d4877497b194d49905a502694c9d768ef727a5ccd1572e0915",
    "assets/MonthlyDeduction-T818E1pw.js": "87c44600542bfbc8d4181290d3e1802599d124f8f2f136e21c6d8e053841a6c9",
    "assets/NotFound-Bl2SR2O8.js": "3ed861fe74c788375283512eb2f1a7a0725880221b4bf7873ce1df7bd25550aa",
    "assets/OperationsWorkbench-Duo-Fj5o.js": "40ab729f391d420547b45680acc31f84dd9933f3bee577ea67b4afc3fd01f92a",
    "assets/PartnerPortal-BKYEr0bd.css": "7d8f8eb18afdbed50ff39b2a634b76d4e472f9179273a5db7816c307039651e2",
    "assets/PartnerPortal-Cvp-6TlN.js": "95bf5d7734fff3e455fab293cb1082d2dfae3970a0473dae38b1ebb510700a77",
    "assets/Payroll-CnKuW44e.js": "ea027150e053ce8fe01199208c32a4f6ac2944ed70a4872241352b7afe567d8c",
    "assets/Permissions-BlciQSVu.js": "0afc73b2574f8bfb7afdbc63c71ba98a83a7bb73e57bf93220fb54039f44e50d",
    "assets/PrivateWorkspace-Byd8VMCt.css": "4d8e14756bf6b9dd1c903dac10466e7551d3cc76e2ddfea2483efad3123dd689",
    "assets/PrivateWorkspace-CMh9t__z.js": "40cde2a46f533484704d34e8abe135aee68b45925a6c5a9b568a6c37a0d191f8",
    "assets/RmbProfitEstimate-BBcgZRIR.css": "dd9756813030968d937a99c226280c57fc76541a8c0db13166ccfeee646dc9cd",
    "assets/RmbProfitEstimate-WSkZDGfh.js": "19b566b465cf52c76394e11b8230a31e154697c73b98617169328014150dfba8",
    "assets/Sales-Ddtlmfx_.js": "505a50df7add230cf7b0661c8798f9454cc7eabd69329a530282868b3a5baca7",
    "assets/SalesKnowledge-hNShpse8.js": "dbf5bf5d7928d9178f16b13a76a065c4b10a9328609401615970f2e696de2e95",
    "assets/SalesKnowledge-oaab3fsC.css": "6b1ed71f8ccbe3005a9347850664e3f1636bcacb0cc79fbd98e9594f50495140",
    "assets/SalesLeadDossier-C8euo2dr.js": "270c8a9829fb69b1b0ab32bc729e612b0371d68ffe9dd658c973e5bff1cad0cf",
    "assets/SalesLeads-CAdfXNY0.js": "16ee609588d12e9a1ae71ad9422fd9d3ae9efaa938a59a01ffc806045e7865e6",
    "assets/SalesLeads-CW3I7hCi.css": "eb192413ca406cca43433fdd09fe74570c7d1b09e6300daaec7943e9b1a80dc1",
    "assets/SalesLocalTime-yuDKHvkj.js": "bf9f3755494aabad6dbce90756cce180e664444ea9056f1b47f3ebd152c9be16",
    "assets/SalesWorkbench-B4eBSfzV.css": "9fe4176124631117443feff5a56ec37f617c1fc95fde33549d9bae3b30617d52",
    "assets/SalesWorkbench-C6Ve4cpK.js": "5b733020b690d26ba9d39bfa1105cfaeb286d28ce2d9d1506f79409ec9f56b72",
    "assets/ServiceBoard-CWxgXCtl.js": "aa5d6c430a4c4fbdc71eb637561652eb31d0fde6819045864efadc2f3e7aec33",
    "assets/Settings-b0aEONY2.js": "a95bcdc79f41d76b1322707e4c49f6f8316ae71a1cf650ab00ed4a51a4e608da",
    "assets/Tasks-CcTsSX4Q.js": "f75e9f7a971776d0515f2f4786023de4c5a6fdcfd99432c93644b912fff31058",
    "assets/admin-workspace-Cr8c5b7X.css": "c3ed38bceb52e6f46ce54d5c948130f17c08110bb7de9613921e8ac050c2841f",
    "assets/badge-B2ijX36p.js": "54cd9729d857cd3ec787cc9f2c9e5ae2ef388cb17db4d1dec086b1a643ac22d6",
    "assets/business-date-9Nfj7uJt.js": "14af8e887f297779bf432b5d23533a436a138f96fccd5ee9a15b92474a5d510c",
    "assets/card-DToFcEbl.js": "654a5472df2e96c381326c1c9b9bd9b6f2d5beff92722844bbf79b14635e9b36",
    "assets/combobox-DD7YtzJg.js": "7113e19c45cdce94b6aaa26966ad22923eda43411b53143c8983ca836e5f732f",
    "assets/country-state-data-X-9DgBQS.js": "547c8e630c39c1dd5923804d3ecbe1db147639847fdf6f4aeb13d5b5d37fdc24",
    "assets/customer-code-settings-aUW4zLxO.js": "ad327a1f392e030a9042a152e001139cb78b2a297356dda307a9ae5917a482d5",
    "assets/delivery-workspace-AfUjNPXr.css": "351b8ce3ed46f0eb28a0441052b249536df0dbcce34b91729d66b25ed4e82025",
    "assets/dict-config-CBmU1ZaB.js": "c0e64337ccfa796ecaa9612d959b31a8335e5fe5593e5702173d92562cd5a8bc",
    "assets/export-3ofP_ApE.js": "334234301073a723d8fb24206743681d2c6c912e689148a50ace86e99be14f94",
    "assets/form-vendor-B5bxR0YL.js": "4b7a44d1b38b2577f7fa768bb94fc7765f9b0808cf1aabf413a7a61172046ba5",
    "assets/generateCategoricalChart-DPv0H3_R.js": "f3fcd0d1cf1ea923e7499e2563799aa89552834570b2292796ac197e47653a8d",
    "assets/index-CEQdUgmw.js": "1be4c47d8452106f93ae5a49c352b529ec2a9c2e287e870c3ba2824c156a9238",
    "assets/index-DVJ6mDOk.css": "263d3bcc0d9ba5bc410fac87323dd9202dec8877f883bfa7878215ae0a579a43",
    "assets/load-utils-COpR0vIU.js": "aa3db7d13ba7b8059047b7bd9a78fa9476197526ad10d6a4da0534aef7605321",
    "assets/mobile-payroll-settings-BUKsKSFw.css": "bd3c54c9aebf2757a59fcf88ec19d6d0b31b5d102553724aca47ce298c09b04a",
    "assets/native-select-BHrkCZ33.js": "73b59074a7736081643923a27601be5f3820d7816952873552913cf67bb386a8",
    "assets/operation-log-helper-CN1MGEzH.js": "bbf64bba69ed74bdac68257e2790bfb2874b7edae56049a585018b1b84e50c16",
    "assets/payment-utils-Dmdojj25.js": "994af01f6411c7319de2bf719f91fa9931e5cae9c09c41d992a78f889ef6a049",
    "assets/phone-format-BkEErUXK.js": "632ea5f3649fbff61f5801986e7cddc1c3a966f0d8a9abb9a07b723c4a428b8e",
    "assets/progress-BcMN8VwW.js": "9150586cdd2c03f15bddb29aff7f3feaa17038281a4318a1a75136e60f038967",
    "assets/query-vendor-DbF57Vn0.js": "41a9f42e43f6e880c6b5655d7c7d5ca3a61d27c2c5e33a355413636409a07133",
    "assets/react-vendor-B5bxR0YL.js": "4b7a44d1b38b2577f7fa768bb94fc7765f9b0808cf1aabf413a7a61172046ba5",
    "assets/router-vendor-_2HZnb73.js": "b2c1da9f00ec658148967e4c81d8fdac662b2ecf4cd9499c1877515085d09f57",
    "assets/sales-knowledge-qfOBiL3h.js": "57957bdd570e365c738ec3ee946f374a013f59cb0ec88d77d22ced21cdb5d871",
    "assets/sales-workspace-Ds7f5pIp.css": "81533a0dc4ac9532b03f076c74c0210b34c2d5e87df4c411581bf803f49dd4c5",
    "assets/sheet-DS-9JrEW.js": "262ad25aff482bf795a45e572a7ace179cf4486e7a020812a4364dcd736b7a9f",
    "assets/switch-lC8Pcsm6.js": "049c70188033e96f76f429296190d404fd68380f51dd35138426fd2684c2e9c9",
    "assets/tabs-BRB4vDEo.js": "3aca1e557b4594d1932779048ac03eb64b5bc5eab02ecfe8f916ac3d6d158769",
    "assets/textarea-NK9o5-cG.js": "090afaeb260e1cbea559b40f0bfd13e6303d1f34a0bd8332d446b87e6678cdf9",
    "assets/ui-vendor-CsmHpUf-.js": "1abbe8cbeca834f518714a1fbd8d91a13b3060de0d351d0faa6c2e1f42f9031a",
    "assets/use-auto-refresh-HF2HFlRL.js": "870c43f74cc7ee9c5c6152f65630310b6af6bdf05aa983628a6de6b1f95fa86b",
    "assets/use-dialog-draft-BgD2hTMP.js": "67de41e2d5375df9dbb95da4661f2c383913f48aaed3aab0f5600ebbad5e6f7a",
    "assets/use-list-scroll-BbAJhkbZ.js": "75983bd73df412dd83bb581f3e19006242a32f3f2126322eba80b6b7c8806e10",
    "assets/use-mobile-57TiiM2L.js": "177d9c69bf4d65cefa1602219fc7f987c8fd62e48c3d79c1c198496628db4422",
    "assets/use-retained-view-CisCh7R1.js": "8c42b2b57484da2e113ad377f60ead6f2500d0966f1bf88fbf192ba500e22bf6",
    "assets/use-sales-list-position-B7v_INyS.js": "0787c8f60be56a5c37940a402ca366d609fa4e2c57be94d37066947a770716d1",
    "assets/utils-vendor-CyDQAZg7.js": "26b3ba8b82c807a06e0f66808a162ff196dd29bc4861d4ca015965ba6b326783",
    "assets/xlsx-BQptaUDQ.js": "d5f39f60b6ebeef459bf9408758147be19463256edba50309d96082f31feb8f7",
    "favicon.png": "a58b64ba3f310f9ad23d8752e79509b3cc20c70a46f0fc7b69e690030ee83fc9",
    "favicon.svg": "8df022f5161c2127f7206c2ded797cb05ce82c26332b308bec193318148226ba",
    "index.html": "fbeb421d74d816f9f38062675b61f188d1a9a0c2fb2c67657ea437662da7361a",
    "manifest.webmanifest": "394971a809254e569fdb53b09ea4ee9c554bcf3146a9ee0896ca74cc31296310",
    "offline.html": "4a2a1c85f7f7b1786d2fdc5d54aaa9ef9ce6bb7432c97dadbea5b59c9f1f3d69",
    "pwa-icon-192.png": "27ea904fe8aaa4e61a11b1dbb61b9aaef1de5add52b791ee38f88ff03e1706f9",
    "pwa-icon-512.png": "680e6df925cb2465324a6f0cbc61cdea85b510bd7ade5762847586d6d0e90513",
    "pwa-icon-maskable-512.png": "135755155c4b9ef73248dece2d22df6ed33ae9a4a69abfc77f66622988ab9946",
    "pwa-icon-maskable-source.svg": "d063af2f51c8155ac90d652e8e1ae33bb2c607b22abe7a253a2ad8658bf9098d",
    "pwa-icon-source.svg": "3b558e8076740097a0ef3fed920d7a1dbb71edec43c4602b7063e80b71ae235b",
    "robots.txt": "331ea9090db0c9f6f597bd9840fd5b171830f6e0b3ba1cb24dfa91f0c95aedc1",
    "sw.js": "5632c1a1cdcfd1c054595bff54d3609e9cdedceb298b9bf81add2d8580e27a27",
    "t2-app-icon-192.png": "8e48bd076cbe88761b154a426a150a76df61c62f58aae745b0768d266175dd50",
    "t2-app-icon-512.png": "57f3e5e0d7ce6fda1621042957e796bfec4527dba42e0e8eeaacdcbe3efaa2ec",
    "t2-app-icon-maskable-512.png": "d285f08802fc962dfe051eeb4222603e03844970d9881091abc5ffd17cb9da2f",
    "t2-apple-touch-icon-180.png": "49457c31a751e1f51bd4fc4315de6297131d733dc95a19a013a646594762958e",
    "t2-favicon-64.png": "04ccea24198b8b3ad5b981f8152be2e1b8de17d55f421b2b1da74fef8aafba36",
    "t2-marketing-logo.png": "57f3e5e0d7ce6fda1621042957e796bfec4527dba42e0e8eeaacdcbe3efaa2ec"
}

class PayloadError(RuntimeError): pass

def need(condition, code):
    if not condition: raise PayloadError(code)

def sha(data): return hashlib.sha256(data).hexdigest()

def git(repo, *args):
    need(args and args[0] in {'rev-parse', 'show', 'diff', 'ls-tree', 'status', 'merge-base'}, 'READONLY_GIT_COMMAND_REQUIRED')
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, timeout=30, check=False)
    need(result.returncode == 0, 'GIT_SOURCE_READ_FAILED')
    return result.stdout

def paths(repo, source):
    result = git(repo, 'ls-tree', '-r', '--name-only', '-z', source).decode()
    return result.rstrip('\0').split('\0') if result else []

def blob(repo, source, path):
    name = PurePosixPath(path)
    need(name.as_posix() == path and not path.startswith('/') and '..' not in name.parts, 'CANONICAL_SOURCE_PATH_REQUIRED')
    mode = git(repo, 'ls-tree', source, '--', path).decode().split()
    need(len(mode) >= 3 and mode[0] in {'100644', '100755'} and mode[1] == 'blob', 'REGULAR_GIT_SOURCE_REQUIRED')
    return git(repo, 'show', source + ':' + path)

def dependency_inventory(repo):
    old, new = set(paths(repo, BASE_SOURCE)), set(paths(repo, SOURCE_SHA))
    selected = sorted(path for path in old | new if DEPENDENCY_NAMES.fullmatch(PurePosixPath(path).name))
    need(selected and all(path in old and path in new for path in selected), 'DEPENDENCY_INVENTORY_CHANGED')
    hashes = {}
    for path in selected:
        before, after = blob(repo, BASE_SOURCE, path), blob(repo, SOURCE_SHA, path)
        need(before == after, 'RUNTIME_DEPENDENCY_CHANGED')
        hashes[path] = sha(after)
    return hashes

def backend_delta(repo):
    raw = git(repo, 'diff', '--name-status', '--no-renames', '-z', BASE_SOURCE, SOURCE_SHA, '--', 'app/backend').decode()
    parts = raw.rstrip('\0').split('\0') if raw else []
    need(len(parts) % 2 == 0, 'BACKEND_DIFF_FORMAT_INVALID')
    changes = dict(zip(parts[1::2], parts[::2]))
    need(changes == BACKEND_CHANGES, 'EXACT_PERSONAL_BACKEND_DELTA_REQUIRED')
    return {path: blob(repo, SOURCE_SHA, path) for path in sorted(changes)}

def static_files(dist):
    need(dist.is_dir() and not dist.is_symlink(), 'REGULAR_STATIC_BUILD_REQUIRED')
    files = {}
    for path in sorted(dist.rglob('*')):
        need(not path.is_symlink(), 'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir(): continue
        relative = path.relative_to(dist)
        need(path.is_file() and path.suffix in STATIC_SUFFIXES and not any(part.startswith('.') for part in relative.parts), 'NON_STATIC_PAYLOAD_REJECTED')
        need(path.suffix != '.html' or relative.as_posix() in {'index.html', 'offline.html'}, 'UNEXPECTED_STATIC_HTML')
        files[relative.as_posix()] = path.read_bytes()
    need({'index.html', 'app-version.json'} <= set(files), 'COMPLETE_FRONTEND_BUILD_REQUIRED')
    need(json.loads(files['app-version.json']) == {'version': FRONTEND_VERSION}, 'FRONTEND_VERSION_DRIFT')
    need({name: sha(data) for name, data in files.items()} == FRONTEND_DIST_SHA256, 'FROZEN_FRONTEND_BUILD_DRIFT')
    need(FRONTEND_SOURCE_DIGEST[:12] == FRONTEND_VERSION, 'FRONTEND_SOURCE_VERSION_MISMATCH')
    return files

def assemble(repo):
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    git(repo, 'merge-base', '--is-ancestor', SOURCE_SHA, head)
    need(not git(repo, 'diff', '--name-only', SOURCE_SHA, head, '--', 'app').strip(), 'CARRIER_APPLICATION_DELTA_REJECTED')
    need(not git(repo, 'status', '--porcelain', '--untracked-files=no', '--', 'app').strip(), 'TRACKED_APPLICATION_DRIFT')
    # Local QA helpers are deliberately outside these implementation roots.
    need(not git(repo, 'status', '--porcelain', '--untracked-files=all', '--',
        'app/backend/models', 'app/backend/routers', 'app/backend/schemas', 'app/backend/services',
        'app/backend/tests', 'app/frontend/src', 'app/frontend/tests').strip(), 'UNTRACKED_APPLICATION_SOURCE_REJECTED')
    dependencies = dependency_inventory(repo)
    changes = backend_delta(repo)
    files = {path.removeprefix('app/'): data for path, data in changes.items()}
    source_hashes = {path: sha(data) for path, data in changes.items()}
    all_paths = paths(repo, SOURCE_SHA)
    private_tests = sorted(path for path in all_paths if PRIVATE_TEST.fullmatch(path))
    need('app/backend/tests/test_private_personal_finance.py' in private_tests, 'PERSONAL_REGRESSION_TEST_REQUIRED')
    private_tests.append('app/backend/tests/conftest.py'); private_tests.sort()
    for path in private_tests:
        data = blob(repo, SOURCE_SHA, path); files[path.removeprefix('app/')] = data; source_hashes[path] = sha(data)
    frontend_source = {path: sha(blob(repo, SOURCE_SHA, path)) for path in all_paths if path.startswith('app/frontend/src/')}
    need(frontend_source, 'FRONTEND_SOURCE_PROVENANCE_REQUIRED')
    static = static_files(repo / 'app/frontend/dist')
    files.update({'frontend/dist/' + name: data for name, data in static.items()})
    need(len(files) < 10000 and sum(map(len, files.values())) < 64 * 1024 * 1024, 'PAYLOAD_SIZE_LIMIT')
    return files, source_hashes, dependencies, private_tests, frontend_source

def encode(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, data in sorted(files.items()):
            path = PurePosixPath(name)
            need(path.as_posix() == name and '..' not in path.parts and not path.is_absolute(), 'CANONICAL_PAYLOAD_PATH_REQUIRED')
            need(name.startswith(('backend/', 'frontend/dist/')), 'NON_RELEASE_PAYLOAD_REJECTED')
            entry = tarfile.TarInfo('payload/' + name)
            entry.size = len(data); entry.mode = 0o644; entry.mtime = 0
            entry.uid = entry.gid = 0; entry.uname = entry.gname = ''
            archive.addfile(entry, io.BytesIO(data))
    output = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as stream: stream.write(buffer.getvalue())
    return output.getvalue()

def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream: stream.write(data)

def main(args):
    repo, output = args.repo.resolve(), args.output.resolve()
    need(repo.is_dir() and output.is_dir() and not args.output.is_symlink(), 'EXISTING_LOCAL_OUTPUT_REQUIRED')
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', BASE_IMAGE) is not None, 'FRESH_PRIVATE_BASE_IMAGE_REQUIRED')
    files, source_hashes, dependencies, private_tests, frontend_source = assemble(repo)
    archive = encode(files)
    manifest = {
        'format_version': 1, 'stage': 'PERSONAL_FINANCE_PAYLOAD_PREPARED',
        'source_sha': SOURCE_SHA, 'baseline_private_source_sha': BASE_SOURCE, 'base_private_image': BASE_IMAGE,
        'frontend_version': FRONTEND_VERSION, 'frontend_source_version_sha256': FRONTEND_SOURCE_DIGEST,
        'frontend_source_file_sha256': frontend_source,
        'payload_sha256': sha(archive), 'payload_files': {name: sha(data) for name, data in sorted(files.items())},
        'source_file_sha256': source_hashes, 'backend_changes': sorted(BACKEND_CHANGES), 'private_tests': private_tests,
        'runtime_dependency_file_sha256': dependencies, 'runtime_dependency_changes': False,
        'backend_regression_tests_expected_minimum': 1192,
        'private_schema_table_count_before': 11, 'private_schema_table_count_after': 20,
        'credentials_included': False, 'production_access': False, 'deployed': False,
    }
    target, destination = output / 'payload.tar.gz', output / 'manifest.json'
    need(not target.exists() and not target.is_symlink() and not destination.exists() and not destination.is_symlink(), 'NEW_ARTIFACT_OUTPUT_REQUIRED')
    write_new(target, archive)
    document = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode(); write_new(destination, document)
    print(json.dumps({'stage': manifest['stage'], 'source_sha': SOURCE_SHA, 'frontend_version': FRONTEND_VERSION,
        'payload_files': len(files), 'payload_sha256': sha(archive), 'manifest_sha256': sha(document), 'deployed': False}, sort_keys=True))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--repo', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    try: main(parser.parse_args())
    except Exception as error:
        code = str(error) if isinstance(error, PayloadError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'PAYLOAD_PREPARATION_FAILED'
        print('PERSONAL_FINANCE_PAYLOAD_ERROR ' + code); raise SystemExit(1) from None
