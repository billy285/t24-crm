import { formatPrivateAmount, type PrivateBankAccount, type PrivateBankEnvironment, type PrivateItem, type PrivateSource } from './private-workspace-api';

const MAX_SNAPSHOT_AGE = 24 * 60 * 60 * 1000;
const nonempty = (value: unknown): value is string => typeof value === 'string' && Boolean(value.trim()) && value.length <= 240;
const environment = (value: unknown): value is PrivateBankEnvironment => value === 'production' || value === 'sandbox';
export function privateBankMoney(minor: unknown, currency: unknown): string {
  return typeof minor === 'number' && Number.isSafeInteger(minor) && typeof currency === 'string'
    ? formatPrivateAmount(minor, currency, 'bofa_bank') : '待提供';
}
export function privateBankTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '未提供更新时间';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }) : '时间待确认';
}
function accountValid(account: PrivateBankAccount): boolean {
  return Boolean(account && nonempty(account.account_id) && nonempty(account.name) && ['funds', 'owed', 'other'].includes(account.balance_kind)
    && account.balance_source === 'cached_accounts_get' && typeof account.type === 'string'
    && (account.mask === null || typeof account.mask === 'string' && /^\d{1,4}$/.test(account.mask)));
}
/** Cached provider balances remain separate by account and currency; missing values never become zero. */
export function currentBankCondition(source?: PrivateSource, now = Date.now()) {
  const metadata = source?.metadata;
  const snapshot = metadata?.bank_snapshot;
  const observed = snapshot && Date.parse(snapshot.observed_at);
  const valid = Boolean(source?.id === 'bofa_bank' && ['connected', 'error'].includes(source.status)
    && nonempty(metadata?.bank_item_id) && nonempty(metadata?.bank_institution_id) && environment(metadata?.bank_environment)
    && snapshot && nonempty(snapshot.id) && snapshot.item_id === metadata!.bank_item_id && snapshot.institution_id === metadata!.bank_institution_id
    && snapshot.environment === metadata!.bank_environment && snapshot.accounts_complete === true && snapshot.balance_realtime === false
    && typeof observed === 'number' && Number.isFinite(observed) && observed <= now + 5 * 60_000
    && Array.isArray(metadata?.bank_accounts) && metadata!.bank_accounts.every(accountValid)
    && new Set(metadata!.bank_accounts.map(account => account.account_id)).size === metadata!.bank_accounts.length);
  const fresh = valid && source?.status === 'connected' && !source.error && now - observed! <= MAX_SNAPSHOT_AGE;
  const accounts = valid ? metadata!.bank_accounts! : [];
  return {
    state: !valid ? 'unverified' as const : fresh ? 'fresh' as const : 'stale' as const,
    accounts,
    environment: environment(metadata?.bank_environment) ? metadata!.bank_environment : null,
    observedAt: valid ? snapshot!.observed_at : null,
    bankUpdatedAt: valid ? snapshot!.bank_updated_at : null,
    itemId: valid ? snapshot!.item_id : null,
    institutionId: valid ? snapshot!.institution_id : null,
    transactionsComplete: valid && snapshot!.transactions_complete === true,
    transactionUpdateStatus: valid ? snapshot!.transaction_update_status : null,
    label: !valid ? '银行连接待同步' : fresh ? '银行缓存余额' : '上次缓存余额 · 需更新',
  };
}
export function privateBankAccountLabels(account: PrivateBankAccount) {
  const owed = account.type === 'credit' || account.type === 'loan' || account.balance_kind === 'owed';
  const funds = !owed && account.type === 'depository' && account.balance_kind === 'funds';
  return {
    title: account.name,
    kind: owed ? account.type === 'loan' ? '贷款' : '信用账户' : funds ? account.subtype === 'savings' ? '储蓄账户' : '存款账户' : '银行账户',
    primaryLabel: owed ? '当前欠款' : funds ? '可用余额' : '来源余额',
    primaryAmount: privateBankMoney(owed || !funds ? account.current_minor : account.available_minor, account.currency),
    secondaryLabel: owed ? '可用额度' : funds ? '当前余额' : '可用数额',
    secondaryAmount: privateBankMoney(owed || !funds ? account.available_minor : account.current_minor, account.currency),
    limit: owed && account.limit_minor !== null ? privateBankMoney(account.limit_minor, account.currency) : null,
    currency: typeof account.currency === 'string' && /^[A-Z]{3}$/.test(account.currency) ? account.currency : '币种待提供',
  };
}
/** Incremental historical transactions belong to the bound Item/account, rather than only the newest snapshot. */
export function privateBankRecord(item: PrivateItem, source?: PrivateSource, now = Date.now()) {
  const condition = currentBankCondition(source, now);
  const evidence = item.evidence || {};
  const account = condition.accounts.find(value => value.account_id === evidence.bank_account_id);
  const current = condition.state !== 'unverified' && item.source_id === 'bofa_bank' && item.kind === 'bank_transaction'
    && ['posted', 'pending'].includes(item.status) && evidence.bank_item_id === condition.itemId
    && evidence.bank_environment === condition.environment && evidence.bank_institution_id === condition.institutionId && Boolean(account)
    && evidence.pending === (item.status === 'pending') && nonempty(evidence.bank_snapshot_id)
    && typeof evidence.bank_observed_at === 'string' && Number.isFinite(Date.parse(evidence.bank_observed_at))
    && Date.parse(evidence.bank_observed_at) <= now + 5 * 60_000;
  const minor = typeof item.amount_minor === 'number' && Number.isSafeInteger(item.amount_minor) ? item.amount_minor : null;
  const direction = minor === null ? 'unknown' : minor > 0 ? 'inflow' : minor < 0 ? 'outflow' : 'neutral';
  const amountVerified = current && minor !== null && evidence.amount_direction === direction && typeof item.currency === 'string' && /^[A-Z]{3}$/.test(item.currency);
  const rawDate = typeof evidence.transaction_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(evidence.transaction_date) ? evidence.transaction_date : null;
  const parsedDate = rawDate ? new Date(`${rawDate}T00:00:00Z`) : null;
  const date = parsedDate && Number.isFinite(parsedDate.getTime()) && parsedDate.toISOString().slice(0, 10) === rawDate ? rawDate : null;
  return {
    current, account,
    stateLabel: item.status === 'pending' ? '待入账' : item.status === 'posted' ? '已入账' : '来源状态待核实',
    state: item.status === 'pending' ? 'pending' as const : 'posted' as const,
    amount: amountVerified ? privateBankMoney(Math.abs(minor!), item.currency) : '待提供',
    direction: amountVerified ? direction : 'unknown',
    directionLabel: !amountVerified ? '金额待提供' : direction === 'inflow' ? '转入' : direction === 'outflow' ? '转出' : '变动金额',
    amountPrefix: !amountVerified ? '' : direction === 'inflow' ? '+' : direction === 'outflow' ? '−' : '',
    date,
    observedAt: typeof evidence.bank_observed_at === 'string' ? evidence.bank_observed_at : null,
    mode: condition.environment,
    needsUpdate: condition.state === 'stale',
  };
}
export function privateBankRecords(items: PrivateItem[], source?: PrivateSource, now = Date.now()): PrivateItem[] {
  return (Array.isArray(items) ? items : []).filter(item => privateBankRecord(item, source, now).current);
}
