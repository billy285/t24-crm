export const BANK_CSV_MAX_BYTES = 1_048_576;
export type BankEvidenceScope = 'complete_transactions' | 'payout_only' | 'unknown';
export type BankPayout = { id: string; amount_minor: number; currency: 'USD'; arrival_date: string; status: string; automatic: boolean; bank_destination?: string | null; eligible: boolean; evidence_scope?: Exclude<BankEvidenceScope, 'unknown'> };
export type BankStatementRow = { row_index: number; date: string; amount_minor: number; currency: 'USD'; description: string; reference: string; ambiguous: boolean };
export type BankInspection = { headers: string[]; sample: string[][]; row_count: number; currency: 'USD'; writes_ledger: false };
export type BankColumns = { account_label: string; currency: 'USD'; date_format: 'ymd' | 'mdy'; date_column: string; amount_column: string; description_column: string; reference_column?: string };
export type BankStatementPreview = { token: string; expires_at: string; account_label: string; currency: 'USD'; file_sha256: string; rows: BankStatementRow[]; writes_ledger: false };
export type BankMatchPreview = { token: string; payout: BankPayout; bank_row: BankStatementRow; account_label: string; transaction_count: number; writes_ledger: false; requires_owner_confirmation: true; evidence_scope?: Exclude<BankEvidenceScope, 'unknown'> };
export type BankMatch = { id: number; payout_id: string; amount_minor: number; currency: 'USD'; account_label: string; bank_date: string; bank_reference: string; payment_ids: number[]; review_ids: number[]; status: 'statement_manually_matched'; confirmed_at?: string; confirmed_by?: string; note: string; evidence_scope?: BankEvidenceScope };
export type BankOverview = { items: BankMatch[]; total: number; currency: 'USD'; bank_connection: 'statement_upload'; provider_writes: false; ledger_writes: false };
export type BankPayoutPage = { items: BankPayout[]; has_more: boolean; next_cursor: string | null; read_only: true; bank_deposit_proven: false; excluded_noncredit_count?: number };
const positive = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const date = (value: unknown): value is string => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};
const payoutId = (value: unknown): value is string => typeof value === 'string' && /^po_[A-Za-z0-9_]{1,220}$/.test(value);
const token = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value);
const object = (value: unknown): value is Record<string, any> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const own = (value: Record<string, any>, key: string) => Object.prototype.hasOwnProperty.call(value, key);
const validPayout = (value: unknown): value is BankPayout => {
  if (!object(value) || !payoutId(value.id) || !positive(value.amount_minor) || value.currency !== 'USD' || !date(value.arrival_date) || typeof value.status !== 'string' || typeof value.automatic !== 'boolean' || typeof value.eligible !== 'boolean') return false;
  if (!own(value, 'evidence_scope')) return !value.eligible || value.automatic === true;
  return value.eligible === true && ((value.evidence_scope === 'payout_only' && value.automatic === false) || (value.evidence_scope === 'complete_transactions' && value.automatic === true));
};
const noPaymentLinks = (value: Record<string, any>) => ['payment_ids', 'review_ids'].every(key => !own(value, key) || (Array.isArray(value[key]) && value[key].length === 0));
const validSavedScope = (value: Record<string, any>) => !own(value, 'evidence_scope') || value.evidence_scope === 'unknown' || value.evidence_scope === 'complete_transactions' || (value.evidence_scope === 'payout_only' && noPaymentLinks(value));
const validRow = (value: unknown): value is BankStatementRow => object(value) && positive(value.row_index) && value.row_index >= 2 && value.row_index <= 1001 && positive(value.amount_minor) && value.currency === 'USD' && date(value.date) && typeof value.description === 'string' && typeof value.reference === 'string' && typeof value.ambiguous === 'boolean';
const invalid = (): never => { throw new Error('银行核对资料格式不完整，请重新读取。'); };

export function readBankOverview(value: unknown): BankOverview {
  if (!object(value) || value.currency !== 'USD' || value.bank_connection !== 'statement_upload' || value.provider_writes !== false || value.ledger_writes !== false || !Number.isSafeInteger(value.total) || value.total < 0 || !Array.isArray(value.items) || value.total < value.items.length || !value.items.every((row: unknown) => object(row) && positive(row.id) && payoutId(row.payout_id) && positive(row.amount_minor) && row.currency === 'USD' && date(row.bank_date) && typeof row.account_label === 'string' && typeof row.bank_reference === 'string' && row.status === 'statement_manually_matched' && Array.isArray(row.payment_ids) && row.payment_ids.every(positive) && Array.isArray(row.review_ids) && row.review_ids.every(positive) && typeof row.note === 'string' && validSavedScope(row))) return invalid();
  return value as BankOverview;
}
export function readBankPayoutPage(value: unknown): BankPayoutPage {
  if (!object(value) || value.read_only !== true || value.bank_deposit_proven !== false || !Array.isArray(value.items) || !value.items.every(validPayout) || typeof value.has_more !== 'boolean' || (value.has_more && !payoutId(value.next_cursor)) || (Object.prototype.hasOwnProperty.call(value, 'excluded_noncredit_count') && (!Number.isSafeInteger(value.excluded_noncredit_count) || value.excluded_noncredit_count < 0))) return invalid();
  return value as BankPayoutPage;
}
export function bankPayoutExclusionNotice(count?: number): string | null {
  return typeof count === 'number' && Number.isSafeInteger(count) && count > 0 ? `本页省略 ${count} 笔零额或负数结算；这里只核对银行入账。` : null;
}
export function readBankInspection(value: unknown): BankInspection {
  if (!object(value) || value.currency !== 'USD' || value.writes_ledger !== false || !Array.isArray(value.headers) || value.headers.length < 2 || value.headers.length > 40 || !value.headers.every((name: unknown) => typeof name === 'string' && name.trim() && name.length <= 80) || new Set(value.headers).size !== value.headers.length || !positive(value.row_count) || value.row_count > 1000 || !Array.isArray(value.sample) || !value.sample.every((row: unknown) => Array.isArray(row) && (row.length === 0 || row.length === value.headers.length) && row.every(cell => typeof cell === 'string'))) return invalid();
  return value as BankInspection;
}
export function readBankStatement(value: unknown): BankStatementPreview {
  if (!object(value) || !token(value.token) || value.currency !== 'USD' || value.writes_ledger !== false || typeof value.account_label !== 'string' || typeof value.expires_at !== 'string' || !/^[a-f0-9]{64}$/.test(value.file_sha256 || '') || !Array.isArray(value.rows) || !value.rows.length || !value.rows.every(validRow) || new Set(value.rows.map((row: BankStatementRow) => row.row_index)).size !== value.rows.length) return invalid();
  return value as BankStatementPreview;
}
export function readBankMatchPreview(value: unknown): BankMatchPreview {
  if (!object(value) || !token(value.token) || value.writes_ledger !== false || value.requires_owner_confirmation !== true || !validPayout(value.payout) || !validRow(value.bank_row) || typeof value.account_label !== 'string' || !bankPayoutEligible(value.payout) || value.bank_row.ambiguous || value.bank_row.amount_minor !== value.payout.amount_minor) return invalid();
  const scope = bankEvidenceScope(value);
  if (scope === 'payout_only') {
    if (value.payout.evidence_scope !== 'payout_only' || value.payout.automatic !== false || value.transaction_count !== 0 || !noPaymentLinks(value)) return invalid();
  } else if (scope === 'complete_transactions') {
    if (value.payout.evidence_scope !== 'complete_transactions' || value.payout.automatic !== true || !positive(value.transaction_count)) return invalid();
  } else if (own(value, 'evidence_scope') || own(value.payout, 'evidence_scope') || value.payout.automatic !== true || !positive(value.transaction_count)) return invalid();
  return value as BankMatchPreview;
}
export function bankPayoutEligible(value?: BankPayout): boolean { return Boolean(value && validPayout(value) && value.eligible === true && value.status === 'paid'); }
export function bankEvidenceScope(value?: { evidence_scope?: unknown } | null): BankEvidenceScope { return value && own(value, 'evidence_scope') && (value.evidence_scope === 'payout_only' || value.evidence_scope === 'complete_transactions') ? value.evidence_scope : 'unknown'; }
export function bankPayoutEvidenceLabel(value: BankPayout): string {
  const scope = bankEvidenceScope(value);
  return scope === 'payout_only' ? '手动结算 · 仅核对银行整笔金额，未核验所含客户收款' : scope === 'complete_transactions' ? '自动结算 · 需完整交易明细核验' : '结算明细核验范围待确认';
}
export function bankMatchEvidenceLabel(value: BankMatchPreview): string {
  const scope = bankEvidenceScope(value);
  return scope === 'payout_only' ? '手动结算 · 仅核对银行整笔金额，未核验所含客户收款' : scope === 'complete_transactions' ? `已核验 ${value.transaction_count} 条完整结算交易明细` : '历史预览 · 明细核验范围未记录';
}
export function bankSavedEvidenceLabel(value: BankMatch): string {
  const scope = bankEvidenceScope(value);
  return scope === 'payout_only' ? '手动结算整笔已匹配 · 不代表逐笔客户收入已核验' : scope === 'complete_transactions' ? '自动结算已匹配 · 完整交易明细已核验' : '历史人工匹配 · 明细核验范围未记录';
}
export function bankOwnerConfirmation(value: BankMatchPreview): string {
  const scope = bankEvidenceScope(value);
  return scope === 'payout_only' ? '我已核对公司银行原始流水与这笔 Stripe 手动结算整笔金额，确认仅保存整笔匹配证据，不代表已核验客户收款，不关联或新增收入。' : scope === 'complete_transactions' ? '我已核对公司银行原始流水与这笔 Stripe 自动结算及完整交易明细，确认仅保存人工匹配证据，不新增收入。' : '我已核对公司银行原始流水与这笔 Stripe 结算整笔金额；历史预览未记录明细核验范围，确认仅保存人工匹配证据，不新增收入。';
}
export function bankColumnsError(columns: BankColumns, headers: readonly string[]): string {
  if (columns.account_label.trim().length < 2 || columns.account_label.trim().length > 80) return '请填写 2–80 字的公司账户标记，无需完整账号。';
  if (columns.currency !== 'USD' || !['ymd', 'mdy'].includes(columns.date_format)) return '当前仅支持美元流水及指定的两种日期格式。';
  const selected = [columns.date_column, columns.amount_column, columns.description_column, ...(columns.reference_column ? [columns.reference_column] : [])];
  return selected.some(name => !headers.includes(name)) || new Set(selected).size !== selected.length ? '请分别选择不同的日期、金额、摘要和可选流水编号列。' : '';
}
export function bankMatchReady(statement: BankStatementPreview | null, row: BankStatementRow | undefined, payout: BankPayout | undefined): boolean {
  return Boolean(statement && token(statement.token) && row && validRow(row) && statement.rows.includes(row) && !row.ambiguous && bankPayoutEligible(payout) && row.amount_minor === payout!.amount_minor);
}
export function bankMatchConfirmReady(preview: BankMatchPreview | null, verified: boolean, note: string): boolean {
  if (!preview || !verified || note.trim().length < 3 || note.trim().length > 1000) return false;
  try { readBankMatchPreview(preview); return true; } catch { return false; }
}
export function bankMoney(value: unknown): string { return positive(value) ? `USD ${(value / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '金额待确认'; }
export function decodeBankCsv(name: string, bytes: ArrayBuffer): string {
  if (!/\.csv$/i.test(name) || bytes.byteLength === 0 || bytes.byteLength > BANK_CSV_MAX_BYTES) throw new Error('请上传不超过 1 MB 的 UTF-8 CSV 公司银行流水。');
  let text: string;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { throw new Error('文件不是 UTF-8 编码，请从银行导出 UTF-8 CSV 后重试。'); }
  if (!text.trim()) throw new Error('流水文件为空，请重新选择。');
  return text;
}
export class BankRequestGuard {
  private generation = 0;
  begin(scope: string, session: string) { return { scope, session, generation: ++this.generation }; }
  current(request: { scope: string; session: string; generation: number }, scope: string, session: string): boolean { return request.generation === this.generation && request.scope === scope && request.session === session; }
  invalidate() { this.generation++; }
}
