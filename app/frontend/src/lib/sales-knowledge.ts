export type KnowledgeProduct = 'beautyos' | 'general' | 'restaurant' | 'managed_service';
export type KnowledgeAvailability = 'ready' | 'requires_setup' | 'pending_confirmation';
export type SalesKnowledgeArticle = {
  id: number;
  category: string;
  title: string;
  customer_question?: string;
  standard_answer: string;
  phone_answer?: string;
  followup_question?: string;
  demo_steps?: string[];
  next_action?: string;
  internal_notes?: string;
  product_scope?: KnowledgeProduct;
  store_types?: string[];
  availability?: KnowledgeAvailability;
  high_frequency?: boolean;
  revision?: number;
  published_revision?: number;
  reviewed_at?: string;
  reviewed_by_name?: string;
  legacy_profile?: boolean;
  inferred_product_scope?: boolean;
  action_steps: string[];
  related_links: string[];
  escalation_rule?: string;
  tags: string[];
  status: 'draft' | 'published' | 'archived';
  is_sensitive: boolean;
  sort_order: number;
  published_at?: string;
  published_by_name?: string;
  updated_at?: string;
};

export const knowledgeProductOptions = [
  { value: 'beautyos', label: '美业 OS' },
  { value: 'general', label: '通用话术' },
  { value: 'restaurant', label: '餐饮 OS' },
  { value: 'managed_service', label: '代运营服务' },
  { value: '', label: '全部产品' },
];

export const knowledgeStoreOptions = [
  { value: '', label: '全部门店类型' },
  { value: '美甲', label: '美甲' },
  { value: '美发', label: '美发' },
  { value: '美容护肤', label: '美容护肤' },
  { value: '美睫', label: '美睫' },
  { value: '个人工作室', label: '个人工作室' },
  { value: 'SPA', label: 'SPA / 养生' },
  { value: '医美经营', label: '医美经营 / 美容激光' },
];

export const knowledgeAvailabilityOptions = [
  { value: 'ready', label: '标准话术' },
  { value: 'requires_setup', label: '需先开通或完成配置' },
  { value: 'pending_confirmation', label: '具体能力或规则待确认' },
];

export function knowledgeProductLabel(value?: string) {
  return knowledgeProductOptions.find(option => option.value === (value || 'general'))?.label || '待确认产品';
}

export function knowledgeAvailabilityLabel(value?: KnowledgeAvailability) {
  return knowledgeAvailabilityOptions.find(option => option.value === value)?.label || '原有口径待复核';
}

export function matchesKnowledgeProduct(article: SalesKnowledgeArticle, product: string) {
  return !product || (article.product_scope || 'general') === product;
}

/** Only explicitly customer-facing fields may enter the clipboard. */
export function getKnowledgeCopyBlockReason(article: SalesKnowledgeArticle, version: 'phone' | 'full' = 'full') {
  if (article.is_sensitive) return '内部信息待核对，暂不能复制给客户。';
  if (article.status !== 'published') return '这张知识卡尚未发布，请先核对后发布。';
  if (version === 'phone' && !article.phone_answer?.trim()) return '电话短版尚未整理，请查看完整答复。';
  if (version === 'full' && !article.standard_answer?.trim()) return '对外答复尚未整理。';
  return '';
}

export function getPhoneKnowledgeAnswer(article: SalesKnowledgeArticle) {
  return getKnowledgeCopyBlockReason(article, 'phone') ? '' : article.phone_answer!.trim();
}

export function getFullKnowledgeAnswer(article: SalesKnowledgeArticle) {
  return getKnowledgeCopyBlockReason(article, 'full') ? '' : article.standard_answer.trim();
}

export type BeautyKnowledgePackPreview = {
  pack_id: string;
  version: string;
  manifest_hash: string;
  total: number;
  high_frequency_count: number;
  existing_count: number;
  new_count: number;
  items: Omit<SalesKnowledgeArticle, 'id'>[];
};
