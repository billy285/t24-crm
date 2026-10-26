"""Pure, fail-closed gates for a future backend+DDL release. Not a deployer.

No Docker, HTTP, credential, production filesystem or database functions live here.
Final names/hashes must be independently frozen before a real publisher uses it.
"""
from copy import deepcopy
from hashlib import sha256
import json

OLD_REVISION = 'f3c7d1a9b456'
NEW_REVISION = 'a8d4e2c6f901'
NEW_TABLES = frozenset({'finance_entry_drafts', 'finance_entry_draft_audits', 'finance_entry_attachments'})
# Proposed exact application scope; final artifact must contain the reviewed subset,
# never an arbitrary prefix. Tests are admitted as source evidence, not runtime overlay.
BACKEND_SCOPE = frozenset({
    'main.py', 'services/schema_readiness.py', 'routers/app_config.py', 'services/role_permissions.py',
    'models/finance_entry_drafts.py', 'models/finance_entry_attachments.py',
    'services/finance_entry_attachments.py', 'routers/finance_entry_attachments.py',
    'services/finance_entry_drafts.py', 'routers/finance_entry_drafts.py',
    'alembic/versions/a8d4e2c6f901_finance_entry_drafts.py',
})
FRONTEND_SCOPE = frozenset({
    'app/frontend/src/App.tsx',
    'app/frontend/src/components/crm-route-modules.ts',
    'app/frontend/src/components/MobileAppLauncher.tsx',
    'app/frontend/src/lib/permissions.ts',
    'app/frontend/src/lib/app-navigation.ts',
    'app/frontend/src/lib/mobile-more-navigation.ts',
    'app/frontend/src/lib/role-context.tsx',
    'app/frontend/src/lib/finance-entry-api.ts',
    'app/frontend/src/pages/FinanceEntry.tsx',
    'app/frontend/src/pages/finance-entry.css',
    'app/frontend/src/pages/Finance.tsx',
    'app/frontend/src/pages/Permissions.tsx',
})
PROTECTED_FINANCE = frozenset({
    'routers/payments.py', 'routers/expenses.py', 'routers/company_expenses.py',
    'routers/deals.py', 'routers/subscriptions.py', 'routers/commissions.py',
    'routers/finance_adjustments.py', 'routers/finance_deduction.py',
    'routers/customer_finance_access.py', 'routers/management_decisions.py',
    'services/payments.py', 'services/expenses.py', 'services/company_expenses.py',
    'services/commissions.py', 'services/customer_lifecycle.py',
    'services/payment_deal_sync.py', 'services/deal_payment_sync.py',
    'services/finance_period_lock.py', 'services/customer_permissions.py',
    'services/stripe_history_reconciliation.py', 'services/stripe_auto_posting.py',
    'services/stripe_history_daily_scan.py', 'dependencies/auth.py',
})

class BoundaryRejected(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise BoundaryRejected(code)


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def source_scope(before, after, exact_backend_files, exact_frontend_files):
    require(set(exact_backend_files) <= BACKEND_SCOPE, 'UNREVIEWED_BACKEND_PATH')
    require(not (set(exact_backend_files) & PROTECTED_FINANCE), 'ORIGINAL_FINANCE_SOURCE_CHANGED')
    require(set(exact_frontend_files) <= FRONTEND_SCOPE, 'UNREVIEWED_FRONTEND_PATH')
    exact = {'app/backend/' + n for n in exact_backend_files} | set(exact_frontend_files)
    require(all(n.startswith('app/frontend/src/') and '..' not in n.split('/') and '\\' not in n and '/private' not in n.lower() for n in exact_frontend_files), 'UNREVIEWED_FRONTEND_PATH')
    changed = {n for n in before.keys() | after.keys() if before.get(n) != after.get(n)}
    require(changed == exact, 'EXACT_FROZEN_SOURCE_ALLOWLIST_REQUIRED')
    require(exact <= after.keys(), 'SOURCE_DELETION_REJECTED')
    return True


def role_settings_transition(before, after, exact_finance_config):
    """Input only in-memory app-settings projections, never export raw DB rows.

    If the persisted role_permissions row does not exist, leave it absent: the
    reviewed new source defaults apply. Other app settings and other roles remain
    byte/value-identical. Only finance and that row's updated_at may change.
    """
    require(before.keys() == after.keys(), 'APP_SETTINGS_KEY_SET_CHANGED')
    for key, value in before.items():
        if key != 'role_permissions':
            require(after[key] == value, 'OTHER_APP_CONFIG_CHANGED')
            continue
        old, new = deepcopy(value), deepcopy(after[key])
        old_roles, new_roles = old.pop('value'), new.pop('value')
        old.pop('updated_at', None); new.pop('updated_at', None)
        require(old == new, 'ROLE_SETTING_METADATA_CHANGED')
        require(isinstance(old_roles, dict) and isinstance(new_roles, dict), 'INVALID_ROLE_CONFIG')
        require(new_roles.get('finance') == exact_finance_config, 'EXACT_FINANCE_ROLE_REQUIRED')
        require({k:v for k,v in old_roles.items() if k != 'finance'} == {k:v for k,v in new_roles.items() if k != 'finance'}, 'OTHER_ROLE_CHANGED')
    require(exact_finance_config.get('dataScope') == 'self', 'FINANCE_SCOPE_MUST_BE_SELF')
    require(exact_finance_config.get('sensitiveFields',{}).get('viewFinance') is False, 'COMPANY_FINANCE_FLAG_REJECTED')
    require(not (set(exact_finance_config.get('buttons',[])) & {'payment_create','payment_edit','payment_delete','customer_export','customer_assign'}), 'FORMAL_LEDGER_OR_EXPORT_BUTTON_REJECTED')
    return True


def original_rows_transition(before, after, *, role_config_change_proved=False):
    """Rows are count/hash/schema projections generated internally on one snapshot."""
    require(set(after) == set(before) | NEW_TABLES, 'EXACT_ADDITIVE_TABLES_REQUIRED')
    for name, row in before.items():
        current = after[name]
        require(all(current[k] == row[k] for k in ['columns','schema','indexes']), 'ORIGINAL_SCHEMA_CHANGED')
        if name == 'alembic_version':
            require(row.get('revision') == OLD_REVISION and current.get('revision') == NEW_REVISION and row['count'] == current['count'] == 1, 'EXACT_REVISION_TRANSITION_REQUIRED')
        elif name == 'app_settings' and current != row:
            require(role_config_change_proved and current['count'] == row['count'], 'APP_CONFIG_EXCEPTION_NOT_PROVED')
        else:
            require(current == row, 'ORIGINAL_ROWS_CHANGED:' + name)
    require(all(after[name]['count'] == 0 for name in NEW_TABLES), 'NEW_DRAFT_TABLES_MUST_START_EMPTY')
    return True


def schema_objects_transition(before, after, exact_added_objects):
    require(all(after.get(k) == v for k,v in before.items()), 'ORIGINAL_SCHEMA_OBJECT_CHANGED')
    require(set(after) - set(before) == set(exact_added_objects), 'EXACT_ADDITIVE_OBJECTS_REQUIRED')
    require(all(k[0] in {'table','index'} and k[2] in NEW_TABLES for k in exact_added_objects), 'EXISTING_TABLE_INDEX_OR_TRIGGER_REJECTED')
    return True


def candidate_proof(proof):
    require(all(proof.get(k) is True for k in ['exact_source_inventory','original_rows_unchanged','new_tables_empty','private_runtime_unchanged','private_db_identity_schema_unchanged','environment_mount_networks_preserved','offline_network_none','offline_workers_disabled','offline_credentials_not_mounted','python310_verified','startup_no_original_row_writes']), 'CANDIDATE_PROOF_INCOMPLETE')
    require(all(proof.get(k) is False for k in ['provider_requests','ledger_posts','auto_posting_policy_changes','historical_pending_processed','accounts_created_or_modified']), 'FORBIDDEN_RELEASE_SIDE_EFFECT')
    return True


if __name__ == '__main__':
    raise SystemExit('PROTOTYPE_ONLY_NOT_A_DEPLOYER: freeze live baseline, source/schema and prepared receipt first')
