import { invokeWithAuth } from './tokenStore';
import type { GbpConnection } from './google-business-api';

export type OnboardingCustomer = { id: number; name: string; status: string | null; address: string | null; city: string | null; state: string | null; country: string | null };
export type GoogleIdentity = { location_name: string; title: string; address: string; observed_at: string };
export type OnboardingBinding = { id: number; customer_id: number; location_name: string; active: boolean; title: string; address: string; google_identity: GoogleIdentity | null };
export type CatalogStatus = 'queued' | 'processing' | 'ready' | 'failed' | 'unknown' | 'expired';
export type CatalogSummary = { id: string; connection_id: number; customer_id: number | null; status: CatalogStatus; revision: number; observed_at: string | null; expires_at: string | null; message: string; error_code: string | null; total_locations: number; truncated: boolean };
export type ComparisonState = 'eligible' | 'review_needed' | 'already_bound' | 'unmatched' | 'inactive';
export type OnboardingComparison = { customer: OnboardingCustomer; match_state: ComparisonState; reasons: string[]; candidates: GoogleIdentity[]; existing_binding: OnboardingBinding | null };
export type BatchStatus = 'preview' | 'queued' | 'processing' | 'completed' | 'partial' | 'failed' | 'unknown' | 'cancelled';
export type BatchItemStatus = 'preview' | 'queued' | 'processing' | 'bound' | 'conflict' | 'failed' | 'cancelled' | 'unknown';
export type BatchCounts = Record<'total' | 'queued' | 'processing' | 'bound' | 'conflict' | 'failed' | 'cancelled' | 'unknown', number>;
export type BatchSummary = { id: string; catalog_id: string | null; customer_id: number | null; status: BatchStatus; revision: number; preview_hash: string; expires_at: string; created_at: string; updated_at: string; message: string; counts: BatchCounts };
export type BatchItem = { id: string; position: number; customer: OnboardingCustomer; google: GoogleIdentity; status: BatchItemStatus; warnings: string[]; binding_id: number | null; message: string; error_code: string | null; request_id: string };
export type OnboardingReceipt = { request_id: string; kind: 'discovery' | 'preview' | 'confirm' | 'cancel' | 'legacy_bind'; resource_id: string; created_at: string };
export type CatalogResponse = { is_owner: true; customer_id: number | null; catalog: CatalogSummary; locations: GoogleIdentity[]; comparisons: OnboardingComparison[]; request_receipt?: OnboardingReceipt };
export type BatchResponse = { is_owner: true; customer_id: number | null; batch: BatchSummary; items: BatchItem[]; request_receipt?: OnboardingReceipt };
export type OnboardingContext = { is_owner: true; customer_id: number | null; customers: OnboardingCustomer[]; connections: GbpConnection[]; bindings: OnboardingBinding[]; recent_catalogs: CatalogSummary[]; recent_batches: BatchSummary[]; worker_enabled: boolean };
export type RequestResponse = { is_owner: true; request_receipt: OnboardingReceipt; catalog: CatalogResponse | null; batch: BatchResponse | null };
export type OnboardingPair = { customer_id: number; location_name: string };
export type OnboardingExpected = { request_id: string; kind: 'discovery' | 'preview' | 'confirm' | 'cancel'; customer_id: number | null; resource_id?: string; connection_id?: number; preview_hash?: string; pairs?: OnboardingPair[] };

const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const integer = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === 'string';
const optionalText = (value: unknown) => value === null || text(value);
const instant = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const hex = (value: unknown) => text(value) && /^[a-f0-9]{32}$/.test(value);
const hash = (value: unknown) => text(value) && /^[a-f0-9]{64}$/.test(value);
const uuid = (value: unknown) => text(value) && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const location = (value: unknown) => text(value) && /^accounts\/[0-9]+\/locations\/[0-9]+$/.test(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const unique = <T,>(rows: T[], key: (row: T) => unknown) => new Set(rows.map(key)).size === rows.length;
function need(value: unknown, message = 'Google 接入资料不完整，请重新读取实际状态。'): asserts value { if (!value) throw new Error(message); }
const scoped = (actual: number | null, expected: number | null) => (actual === null || positive(actual)) && actual === expected;
const itemInScope = (id: number, scope: number | null) => positive(id) && (scope === null || id === scope);

export const comparisonLabels: Record<ComparisonState, string> = { eligible: '可核对接入', review_needed: '需要进一步确认', already_bound: '已绑定 · 保持不变', unmatched: '暂未找到匹配门店', inactive: '当前不在合作中' };
export const catalogLabels: Record<CatalogStatus, string> = { queued: '已保存读取任务', processing: '正在读取 Google 门店', ready: '门店资料已读取', failed: '读取未完成', unknown: '读取结果待确认', expired: '目录已过期' };
export const batchLabels: Record<BatchStatus, string> = { preview: '等待你确认对应关系', queued: '已保存 · 等待处理', processing: '正在逐家核验并接入', completed: '本批接入已完成', partial: '部分已接入 · 其余需核对', failed: '本批未完成', unknown: '接入结果待确认', cancelled: '已停止剩余接入' };
export const batchItemLabels: Record<BatchItemStatus, string> = { preview: '尚未绑定', queued: '等待核验', processing: '正在核验', bound: '已绑定', conflict: '归属或资料需核对', failed: '未绑定成功', cancelled: '已取消', unknown: '结果待确认' };
export const onboardingPending = (value: CatalogStatus | BatchStatus) => value === 'queued' || value === 'processing';
export const onboardingLocationKey = (value: string) => /^accounts\/[0-9]+\/locations\/[0-9]+$/.test(value) ? value.split('/').pop()! : '';
export const onboardingExpired = (value: string | null, now = Date.now()) => !value || !instant(value) || Date.parse(value) <= now;
export function onboardingAddress(customer: OnboardingCustomer): string { return [...new Set([customer.address, customer.city, customer.state, customer.country].filter((value): value is string => !!value?.trim()).map(value => value.trim()))].join(', ') || 'CRM 尚未填写完整地址'; }

export async function googleOnboardingApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/google-business/onboarding${path}`, method, ...(data === undefined ? {} : { data }), options: { ...(signal ? { signal } : {}), timeout: 20000 } });
  return response.data as T;
}

export function verifiedOnboardingCustomer(value: OnboardingCustomer, requireName = false): OnboardingCustomer {
  need(value && positive(value.id) && text(value.name) && (!requireName || value.name.trim()) && ['status', 'address', 'city', 'state', 'country'].every(key => optionalText(value[key as keyof OnboardingCustomer])));
  return value;
}
export function verifiedGoogleIdentity(value: GoogleIdentity): GoogleIdentity {
  need(value && location(value.location_name) && text(value.title) && text(value.address) && instant(value.observed_at)); return value;
}
function verifiedBinding(value: OnboardingBinding, scope: number | null) {
  need(value && positive(value.id) && itemInScope(value.customer_id, scope) && location(value.location_name) && typeof value.active === 'boolean' && text(value.title) && text(value.address));
  if (value.google_identity) { verifiedGoogleIdentity(value.google_identity); need(value.google_identity.location_name === value.location_name); }
  else need(value.google_identity === null);
  return value;
}
export function verifiedCatalogSummary(value: CatalogSummary, scope: number | null): CatalogSummary {
  need(value && hex(value.id) && positive(value.connection_id) && scoped(value.customer_id, scope) && Object.prototype.hasOwnProperty.call(catalogLabels, value.status) && positive(value.revision) && (value.observed_at === null || instant(value.observed_at)) && (value.expires_at === null || instant(value.expires_at)) && text(value.message) && optionalText(value.error_code) && integer(value.total_locations) && value.total_locations <= 500 && typeof value.truncated === 'boolean'); return value;
}
export function verifiedBatchSummary(value: BatchSummary, scope: number | null): BatchSummary {
  need(value && hex(value.id) && (value.catalog_id === null || hex(value.catalog_id)) && scoped(value.customer_id, scope) && Object.prototype.hasOwnProperty.call(batchLabels, value.status) && positive(value.revision) && hash(value.preview_hash) && [value.expires_at, value.created_at, value.updated_at].every(instant) && text(value.message) && value.counts && Object.values(value.counts).every(integer) && ['total', 'queued', 'processing', 'bound', 'conflict', 'failed', 'cancelled', 'unknown'].every(key => integer(value.counts[key as keyof BatchCounts])) && value.counts.total >= 1 && value.counts.total <= 50);
  return value;
}
function verifiedReceipt(value: OnboardingReceipt): OnboardingReceipt {
  need(value && uuid(value.request_id) && ['discovery', 'preview', 'confirm', 'cancel', 'legacy_bind'].includes(value.kind) && hex(value.resource_id) && instant(value.created_at), '请求记录不完整，请继续查询原请求，不要重复接入。'); return value;
}
export function verifiedOnboardingContext(value: OnboardingContext, scope: number | null): OnboardingContext {
  need(value && value.is_owner === true && value.customer_id === scope && Array.isArray(value.customers) && Array.isArray(value.connections) && Array.isArray(value.bindings) && Array.isArray(value.recent_catalogs) && Array.isArray(value.recent_batches) && typeof value.worker_enabled === 'boolean');
  value.customers.forEach(row => { verifiedOnboardingCustomer(row); need(itemInScope(row.id, scope)); });
  need(unique(value.customers, row => row.id) && unique(value.connections, row => row.id) && unique(value.bindings, row => row.id) && value.connections.every(row => row && positive(row.id) && text(row.label) && typeof row.active === 'boolean' && typeof row.needs_reconnect === 'boolean' && (row.connected_at === null || instant(row.connected_at)) && optionalText(row.last_error)));
  value.bindings.forEach(row => verifiedBinding(row, scope)); value.recent_catalogs.forEach(row => verifiedCatalogSummary(row, scope === null ? row.customer_id : scope)); value.recent_batches.forEach(row => verifiedBatchSummary(row, scope === null ? row.customer_id : scope)); return value;
}
export function verifiedCatalogResponse(value: CatalogResponse, scope: number | null, id?: string): CatalogResponse {
  need(value && value.is_owner === true && scoped(value.customer_id, scope) && Array.isArray(value.locations) && value.locations.length <= 500 && Array.isArray(value.comparisons));
  verifiedCatalogSummary(value.catalog, scope); need(value.catalog.customer_id === value.customer_id && (!id || value.catalog.id === id));
  need(value.catalog.status === 'ready' ? value.catalog.total_locations === value.locations.length : value.locations.length === 0, '本次门店目录数量或读取状态不一致，请重新读取实际清单。');
  value.locations.forEach(verifiedGoogleIdentity); need(unique(value.locations, row => row.location_name) && unique(value.comparisons, row => row.customer.id));
  const locations = new Map(value.locations.map(row => [row.location_name, row]));
  value.comparisons.forEach(row => { verifiedOnboardingCustomer(row.customer); need(itemInScope(row.customer.id, value.customer_id) && Object.prototype.hasOwnProperty.call(comparisonLabels, row.match_state) && strings(row.reasons) && Array.isArray(row.candidates)); row.candidates.forEach(candidate => { verifiedGoogleIdentity(candidate); const found = locations.get(candidate.location_name); need(found && ['location_name', 'title', 'address', 'observed_at'].every(key => found[key as keyof GoogleIdentity] === candidate[key as keyof GoogleIdentity])); }); if (row.existing_binding) { verifiedBinding(row.existing_binding, value.customer_id); need(row.existing_binding.customer_id === row.customer.id); } else need(row.existing_binding === null); });
  if (value.request_receipt) { verifiedReceipt(value.request_receipt); need(value.request_receipt.resource_id === value.catalog.id); }
  return value;
}
export function verifiedBatchResponse(value: BatchResponse, scope: number | null, id?: string): BatchResponse {
  need(value && value.is_owner === true && scoped(value.customer_id, scope) && Array.isArray(value.items)); verifiedBatchSummary(value.batch, scope);
  need(value.batch.customer_id === value.customer_id && (!id || value.batch.id === id) && value.items.length === value.batch.counts.total && unique(value.items, row => row.id) && unique(value.items, row => row.customer.id) && unique(value.items, row => onboardingLocationKey(row.google.location_name)));
  value.items.forEach(row => { verifiedOnboardingCustomer(row.customer, true); verifiedGoogleIdentity(row.google); need(hex(row.id) && integer(row.position) && itemInScope(row.customer.id, value.customer_id) && Object.prototype.hasOwnProperty.call(batchItemLabels, row.status) && strings(row.warnings) && (row.binding_id === null || positive(row.binding_id)) && text(row.message) && optionalText(row.error_code) && uuid(row.request_id) && (row.status !== 'bound' || positive(row.binding_id))); });
  if (value.batch.status === 'preview') need(value.items.every(row => row.status === 'preview') && Object.entries(value.batch.counts).every(([key, count]) => key === 'total' || count === 0));
  else for (const key of ['queued', 'processing', 'bound', 'conflict', 'failed', 'cancelled', 'unknown'] as const) need(value.batch.counts[key] === value.items.filter(row => row.status === key).length);
  if (value.request_receipt) { verifiedReceipt(value.request_receipt); need(value.request_receipt.resource_id === value.batch.id); }
  return value;
}
export function verifiedOnboardingMutation<T extends CatalogResponse | BatchResponse>(value: T, expected: OnboardingExpected): T {
  if (expected.kind === 'discovery') verifiedCatalogResponse(value as CatalogResponse, expected.customer_id, expected.resource_id);
  else verifiedBatchResponse(value as BatchResponse, expected.customer_id, expected.resource_id);
  const receipt = value.request_receipt; need(receipt && receipt.request_id === expected.request_id && receipt.kind === expected.kind, '返回结果与原请求不一致，请查询原编号。');
  if (expected.connection_id && 'catalog' in value) need(value.catalog.connection_id === expected.connection_id, '返回门店目录与原请求选择的 Google 连接不一致，请查询原编号。');
  if (expected.kind === 'confirm' && 'batch' in value) need(value.batch.status !== 'preview', '当前仍是未接入预检，请查询原确认请求，暂勿再次提交。');
  if (expected.preview_hash && 'batch' in value) need(value.batch.preview_hash === expected.preview_hash, '本批预检版本已变化，请重新核对当前批次。');
  if (expected.pairs && 'items' in value) need(value.items.length === expected.pairs.length && expected.pairs.every(pair => value.items.some(row => row.customer.id === pair.customer_id && row.google.location_name === pair.location_name)), '接入对象与已核对选择不一致，请重新读取。');
  return value;
}
export function verifiedOnboardingRequest(value: RequestResponse, expected: OnboardingExpected): CatalogResponse | BatchResponse {
  need(value && value.is_owner === true); verifiedReceipt(value.request_receipt); need(value.request_receipt.request_id === expected.request_id && value.request_receipt.kind === expected.kind, '原请求编号或操作类型不一致，请重新查询。');
  const result = expected.kind === 'discovery' ? value.catalog : value.batch;
  need(result && (expected.kind === 'discovery' ? value.batch === null : value.catalog === null));
  const verified = verifiedOnboardingMutation({ ...result, request_receipt: value.request_receipt }, expected); return verified;
}

export type OnboardingRecoveryPointer = Pick<OnboardingExpected, 'request_id' | 'kind' | 'customer_id' | 'resource_id'>;
export function onboardingRecoveryPointer(raw: string | null, customerId: number | null): OnboardingRecoveryPointer | null {
  if (!raw) return null;
  try { const value = JSON.parse(raw); return value && uuid(value.request_id) && ['discovery', 'preview', 'confirm', 'cancel'].includes(value.kind) && value.customer_id === customerId && (value.resource_id === undefined || hex(value.resource_id)) && Object.keys(value).every(key => ['request_id', 'kind', 'customer_id', 'resource_id'].includes(key)) ? value : null; } catch { return null; }
}
