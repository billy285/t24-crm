#!/usr/bin/env python3
"""Read-only live proof for the forthcoming unified sales handoff release.

Prints hashes/counts only. Does not save files, repair schema, build images,
change service state, or call provider/customer APIs.
"""
import hashlib
import base64
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import sys
import types
import zlib
from datetime import datetime
from zoneinfo import ZoneInfo

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
CLOSE = Path('/opt/t24-crm/releases/customer-dialog-close-b2655953a2d9-20261016/release.py')
CLOSE_SHA = 'b663334bee36c2ea60cf10dbf489322003930084c7d4beeeefe578357dfc3ae1'
AUDIT_DIR = Path('/opt/t24-crm/releases/sales-account-boundaries-033d971bf086-20261016')
AUDIT_SHA = '9f5b94cd321eca115771859d8ee8ca158bb0c01b2a41554472df7509fc1c1a9a'
AUDIT_PREPARED_SHA = '32a9ab2e7f00c8e262050a28348453045cb4e5598de350348f3eaecec753ccac'
PREFLIGHT = Path('/opt/t24-crm/releases/commission-service-month-preflight-20261013.json')
PREFLIGHT_SHA = 'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA = '50f196879271f34808f1a2eab911cfeda384c5b84caa23a78b4bbd6f5ab532e3'
PUBLIC = Path('/var/www/t24-crm-public/customer-dialog-close-b2655953a2d9-20261016')
PUBLIC_SHA = '0e2f440ec482b2868b36aa752f81c46d752e44e7a5ea6e67b619b26c71b500b2'
FRONTEND = '3361045efa5f'
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def digest(value):
    return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def read(path, expected):
    info = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(info.st_mode) and info.st_uid == 0
         and info.st_nlink == 1 and not info.st_mode & 0o077, 'PROTECTED_PROOF_FILE_REQUIRED')
    body = path.read_bytes()
    need(H(body) == expected, 'RETAINED_PROOF_HASH_DRIFT')
    return body


def load(path, expected, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(read(path, expected), str(path), 'exec'), module.__dict__)
    return module


def catalog_diagnostics(connection):
    """Existing catalog facts only; never infer or create a selling price."""
    connection.row_factory = sqlite3.Row
    lines = [dict(row) for row in connection.execute(
        'SELECT id,code,name,is_active,is_recurring FROM business_lines ORDER BY id')]
    products = [dict(row) for row in connection.execute(
        'SELECT id,business_line_id,code,name,billing_kind,default_currency,is_active,effective_from,effective_to '
        'FROM product_catalog ORDER BY id')]
    plans = [dict(row) for row in connection.execute(
        'SELECT p.id,p.product_id,p.code,p.name,p.standard_price,p.default_currency,p.default_billing_cycle,'
        'p.pricing_status,p.is_active,p.effective_from,p.effective_to,c.name AS product_name,'
        'c.is_active AS product_active,c.effective_from AS product_from,c.effective_to AS product_to,'
        'l.id AS business_line_id,l.name AS business_line_name,l.is_active AS business_line_active '
        'FROM product_plans p LEFT JOIN product_catalog c ON c.id=p.product_id '
        'LEFT JOIN business_lines l ON l.id=c.business_line_id ORDER BY p.id')]
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    for plan in plans:
        price = plan['standard_price']
        valid_price = price is not None and math.isfinite(float(price)) and float(price) >= 0
        dates_valid = all(not plan[field] or (plan[field] <= today if field.endswith('from') else plan[field] >= today)
                          for field in ('effective_from','effective_to','product_from','product_to'))
        plan['sellable_now'] = bool(plan['is_active'] and plan['product_active'] and plan['business_line_active']
                                    and plan['pricing_status'] == 'published' and valid_price and dates_valid)
    return {'as_of_business_date':today,'counts':{'business_lines':len(lines),'products':len(products),
        'plans':len(plans),'active_plans':sum(bool(row['is_active']) for row in plans),
        'published_plans':sum(row['pricing_status']=='published' for row in plans),
        'plans_with_price':sum(row['standard_price'] is not None for row in plans),
        'sellable_now':sum(row['sellable_now'] for row in plans)},
        'business_lines':lines,'products':products,'plans':plans}


def main():
    sys.dont_write_bytecode = True
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_SERVER_ROOT_REQUIRED')
    close = load(CLOSE, CLOSE_SHA, '_sales_unified_preflight_close')
    audit = load(AUDIT_DIR / 'release.py', AUDIT_SHA, '_sales_unified_preflight_audit')
    pins = json.loads(read(PREFLIGHT, PREFLIGHT_SHA))
    runtime = close.protected_boundary(pins)
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'CURRENT_NGINX_DRIFT')
    need(NGINX.read_bytes().count(('root ' + str(PUBLIC) + ';').encode()) == 1, 'CURRENT_STATIC_ROOT_DRIFT')
    public_files = close.tree_inventory(PUBLIC)
    need(digest(public_files) == PUBLIC_SHA, 'CURRENT_PUBLIC_FILES_DRIFT')
    need(json.loads((PUBLIC / 'app-version.json').read_bytes())['version'] == FRONTEND, 'CURRENT_FRONTEND_DRIFT')

    prepared = json.loads(read(AUDIT_DIR / 'prepared.json', AUDIT_PREPARED_SHA))
    expected = json.loads(read(AUDIT_DIR / 'backend-candidate-inventory.json', prepared['candidate_inventory_sha256']))
    actual = audit.inventory(runtime['id'])
    need(actual == expected, 'CURRENT_BACKEND_SOURCE_DRIFT')
    business = close.BUSINESS
    identity = business.stat()
    connection = sqlite3.connect(f'file:{business}?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        need(connection.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'BUSINESS_INTEGRITY_FAILED')
        catalog = catalog_diagnostics(connection)
    finally:
        connection.close()
    snapshot = close.retained().sql_snapshot(business)
    need(close.protected_boundary(pins) == runtime, 'RUNTIME_CHANGED_DURING_PREFLIGHT')
    need(H(NGINX.read_bytes()) == NGINX_SHA and digest(close.tree_inventory(PUBLIC)) == PUBLIC_SHA,
         'STATIC_CHANGED_DURING_PREFLIGHT')
    result = {
        'stage': 'SALES_UNIFIED_HANDOFF_READ_ONLY_PREFLIGHT',
        'baseline_carrier': '180a02697246416a42329ee6bc29c9f812b0b7b8',
        'backend_source': '033d971bf086e002b93c2da3788b337b53bf00b6',
        'frontend_source': 'b2655953a2d909ba3fd79dd37e7dddbe4dfc54bd',
        'frontend_version': FRONTEND, 'crm': runtime,
        'backend_inventory_count': len(actual), 'backend_inventory_sha256': digest(actual),
        'business_identity': {'device': identity.st_dev, 'inode': identity.st_ino},
        'business_table_count': len(snapshot), 'business_snapshot_sha256': digest(snapshot),
        'business_integrity': 'ok', 'schema_revision': close.SCHEMA_REVISION,
        'schema_sha256': close.SCHEMA_SHA, 'private_boundary_verified': True,
        'nginx_sha256': NGINX_SHA, 'public_root': str(PUBLIC),
        'public_file_count': len(public_files), 'public_inventory_sha256': PUBLIC_SHA,
        'readonly': True, 'files_written': False, 'database_modified': False,
        'services_modified': False, 'provider_requests': False,
        'catalog': catalog,
    }
    encoded = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
    print(json.dumps({'stage':result['stage'],'crm':runtime,'frontend_version':FRONTEND,
        'catalog_counts':catalog['counts'],'proof_bytes':len(encoded),'proof_sha256':H(encoded),
        'proof_zlib_base64':base64.b64encode(zlib.compress(encoded,9)).decode()}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        code = str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+', str(error)) else type(error).__name__.upper()
        print(json.dumps({'stage': 'SALES_UNIFIED_HANDOFF_PREFLIGHT_REJECTED', 'code': code}))
        sys.exit(1)
