import { googleBusinessApi } from './google-business-api';

export type GbpAiStatus = {
  enabled: boolean; provider: string; model: string; destination_host: string;
  runtime_fingerprint: string; owner_consented: boolean; is_owner: boolean;
};
export type GbpAiDraft = {
  id: string; reply: string; summary?: string | null; issues?: string[]; risk_flags?: string[];
  sensitive: boolean; requires_owner_approval: boolean; approved: boolean; model?: string | null;
  review_version: string; expires_at: string; actor_name?: string; created_at?: string; status?: string;
};
const validId = (value: unknown) => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export function verifiedAiStatus(value: GbpAiStatus): GbpAiStatus {
  if (!value || typeof value.enabled !== 'boolean' || typeof value.owner_consented !== 'boolean' || typeof value.is_owner !== 'boolean'
    || !['provider', 'model', 'destination_host', 'runtime_fingerprint'].every(key => typeof value[key as keyof GbpAiStatus] === 'string')) throw new Error('AI 配置状态返回不完整，请重新读取。');
  return value;
}
export function verifiedAiDraft(value: GbpAiDraft): GbpAiDraft {
  if (!value || !validId(value.id) || typeof value.reply !== 'string' || typeof value.review_version !== 'string'
    || typeof value.approved !== 'boolean' || typeof value.requires_owner_approval !== 'boolean' || typeof value.sensitive !== 'boolean'
    || value.issues && (!Array.isArray(value.issues) || value.issues.some(row => typeof row !== 'string'))
    || value.risk_flags && (!Array.isArray(value.risk_flags) || value.risk_flags.some(row => typeof row !== 'string'))) throw new Error('回复草稿返回不完整，请重新读取。');
  return value;
}
export async function readGbpAiStatus(bindingId: number) { return verifiedAiStatus(await googleBusinessApi<GbpAiStatus>('/ai/status')); }
export async function readGbpAiDrafts(bindingId: number, reviewName: string): Promise<GbpAiDraft[]> {
  const value = await googleBusinessApi<{ items: GbpAiDraft[] }>(`/bindings/${bindingId}/reply-drafts?review_name=${encodeURIComponent(reviewName)}`);
  if (!value || !Array.isArray(value.items)) throw new Error('回复草稿列表返回不完整。');
  return value.items.map(verifiedAiDraft);
}
/** A visible hint only; the server independently checks the live review before publication. */
export function googleReviewNeedsOwner(review: string, reply: string): boolean {
  return /食品安全|食物中毒|过敏|歧视|诉讼|律师|法律|人身|威胁|退款|赔偿|food\s*poison|allerg|discriminat|racis|lawsuit|lawyer|legal\s*action|threat|refund|compensat/i.test(`${review}\n${reply}`);
}
