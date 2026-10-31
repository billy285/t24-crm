import { invokeWithAuth } from './tokenStore';

export type MetaPlatform = 'facebook' | 'instagram';
export type MetaAuthorization = { provider: 'Meta'; flow: string; client_id: string; config_id: string; graph_version: string; token_type: 'user'; requested_scopes: string[]; redirect_uri: string; token_storage: string; purpose: string; asset_types: string[] };
export type MetaConnection = { id: number; label: string; active: boolean; needs_reconnect: boolean; connected_at: string | null; last_error: string | null; revision: number };
export type MetaBinding = { id: number; customer_id: number; customer_name: string; connection_id: number; platform: MetaPlatform; asset_name: string; asset_username?: string | null; active: boolean; revision: number; publishing_implemented: false; comments_implemented: false };
export type MetaStatus = { enabled: boolean; configured: boolean; setup_missing: string[]; is_owner: boolean; phase: 'connection'; publishing_implemented: false; comments_implemented: false; connections: MetaConnection[]; bindings: MetaBinding[]; capability_observations?: string[]; authorization: MetaAuthorization | null };
export type MetaOptions = { customers: { id: number; name: string }[] };
export type MetaAsset = { asset_ref: string; platform: MetaPlatform; name: string; username?: string | null; linked_page_name?: string | null; capability_observations: string[]; publishing_implemented: false; comments_implemented: false };
export type MetaAssets = { items: MetaAsset[]; truncated: boolean };
export type MetaOAuthStart = { authorization_url: string; expires_in: number };
export const META_CALLBACK_URI = 'https://t24-crm.com/api/v1/meta-business/oauth/callback';
export const metaPlatformLabel = (platform: MetaPlatform) => platform === 'facebook' ? 'Facebook 主页' : 'Instagram 专业账号';
const id = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const bool = (value: unknown) => typeof value === 'boolean';
const text = (value: unknown) => typeof value === 'string';
const textOrNull = (value: unknown) => value === undefined || value === null || text(value);
const platform = (value: unknown) => value === 'facebook' || value === 'instagram';
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);

/** Invalidating the generation prevents an old A result from surviving A → B → A. */
export function metaRequestScope(initial: string) {
  let identity = initial, generation = 0, active = true;
  return {
    update(next: string) { if (next !== identity) { identity = next; generation++; } },
    activate() { active = true; generation++; },
    invalidate() { active = false; generation++; },
    capture() { const key = identity, version = generation; return () => active && key === identity && version === generation; },
  };
}
export async function metaBusinessApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/meta-business${path}`, method, ...(data === undefined ? {} : { data }) });
  return response.data as T;
}
export function verifiedMetaBinding(value: MetaBinding): MetaBinding {
  if (!value || !id(value.id) || !id(value.customer_id) || !id(value.connection_id) || !id(value.revision) || !platform(value.platform) || !text(value.customer_name) || !text(value.asset_name) || !textOrNull(value.asset_username) || !bool(value.active) || value.publishing_implemented !== false || value.comments_implemented !== false) throw new Error('Meta 客户账号绑定返回不完整，请重新读取。');
  return value;
}
export function verifiedMetaStatus(value: MetaStatus): MetaStatus {
  if (!value || !bool(value.enabled) || !bool(value.configured) || !bool(value.is_owner) || !strings(value.setup_missing) || value.phase !== 'connection' || value.publishing_implemented !== false || value.comments_implemented !== false || !Array.isArray(value.connections) || !Array.isArray(value.bindings)) throw new Error('Meta 连接状态返回不完整，请重新读取。');
  if (value.connections.some(row => !row || !id(row.id) || !id(row.revision) || !text(row.label) || !bool(row.active) || !bool(row.needs_reconnect) || !textOrNull(row.connected_at) || !textOrNull(row.last_error))) throw new Error('Meta 连接资料返回不完整。');
  value.bindings.forEach(verifiedMetaBinding);
  if (!value.is_owner && (value.connections.length || value.bindings.length || value.authorization !== null)) throw new Error('当前账号的 Meta 访问范围无法核实。');
  const auth = value.authorization;
  if (auth && (auth.provider !== 'Meta' || !text(auth.flow) || !/^\d{5,40}$/.test(auth.client_id) || !/^\d{5,40}$/.test(auth.config_id) || !/^v\d{1,3}\.\d{1,2}$/.test(auth.graph_version) || auth.token_type !== 'user' || !strings(auth.requested_scopes) || auth.requested_scopes.some(scope => !/^[a-z][a-z0-9_]{0,99}$/.test(scope)) || auth.redirect_uri !== META_CALLBACK_URI || !text(auth.token_storage) || !text(auth.purpose) || !strings(auth.asset_types))) throw new Error('Meta 授权说明无法核实，请老板重新读取配置。');
  if (value.configured && value.is_owner && !auth) throw new Error('Meta 授权范围说明尚未返回。');
  return value;
}
export function verifiedMetaOptions(value: MetaOptions): MetaOptions {
  if (!value || !Array.isArray(value.customers) || value.customers.some(row => !id(row.id) || !text(row.name))) throw new Error('Meta 可绑定客户返回不完整。');
  return value;
}
export function verifiedMetaAssets(value: MetaAssets): MetaAssets {
  if (!value || !Array.isArray(value.items) || !bool(value.truncated) || value.items.some(row => !row || !text(row.asset_ref) || row.asset_ref.length < 1 || row.asset_ref.length > 1024 || !platform(row.platform) || !text(row.name) || !textOrNull(row.username) || !textOrNull(row.linked_page_name) || !strings(row.capability_observations) || row.publishing_implemented !== false || row.comments_implemented !== false) || new Set(value.items.map(row => row.asset_ref)).size !== value.items.length) throw new Error('Meta 返回的可选账号不完整，请重新读取。');
  return value;
}
export function metaAuthorizationUrl(value: unknown, authorization: MetaAuthorization | null): string | null {
  if (!text(value) || !authorization || authorization.redirect_uri !== META_CALLBACK_URI) return null;
  try {
    const url = new URL(value as string);
    const allowed = new Set(['client_id', 'redirect_uri', 'response_type', 'state', 'config_id']), keys = [...url.searchParams.keys()];
    if (url.protocol !== 'https:' || url.hostname !== 'www.facebook.com' || url.port || url.username || url.password || url.hash || url.pathname !== `/${authorization.graph_version}/dialog/oauth`
      || keys.length !== allowed.size || new Set(keys).size !== keys.length || keys.some(key => !allowed.has(key)) || authorization.token_type !== 'user'
      || url.searchParams.get('redirect_uri') !== META_CALLBACK_URI || url.searchParams.get('response_type') !== 'code' || url.searchParams.get('client_id') !== authorization.client_id || url.searchParams.get('config_id') !== authorization.config_id || !/^[A-Za-z0-9_-]{20,1024}$/.test(url.searchParams.get('state') || '')) return null;
    return url.href;
  } catch { return null; }
}
