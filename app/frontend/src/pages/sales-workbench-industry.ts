import { dealProductScope } from '@/lib/deal-product-scope';
import type { KnowledgeProduct } from '@/lib/sales-knowledge';

export const workbenchIndustryLabels = { all: '全部行业', restaurant: '餐厅', beauty: '美业' } as const;
export type WorkbenchIndustry = keyof typeof workbenchIndustryLabels;
type LeadIndustry = {
  industry?: string;
  industry_group?: 'restaurant' | 'beauty' | 'other';
  enrichment_summary?: { interest_product_names?: string[] };
};

export function workbenchIndustry(lead?: LeadIndustry): 'restaurant' | 'beauty' | 'other' {
  if (lead?.industry_group) return lead.industry_group;
  // Older responses may only carry the original industry label.
  const label = lead?.industry?.trim().toLowerCase();
  if (label === '餐厅' || label === '餐饮' || label === 'restaurant') return 'restaurant';
  if (label === '美业' || label === 'beauty') return 'beauty';
  return 'other';
}

export function workbenchKnowledgeProduct(lead?: LeadIndustry, savedProductNames?: string[]): KnowledgeProduct {
  const industry = workbenchIndustry(lead);
  const fallback = industry === 'beauty' ? 'beautyos' : industry === 'restaurant' ? 'restaurant' : 'general';
  const products = new Set<KnowledgeProduct>();
  for (const name of savedProductNames?.length ? savedProductNames : lead?.enrichment_summary?.interest_product_names || []) {
    const compact = name.toLowerCase().replace(/\s+/g, '');
    const scope = dealProductScope(name, name);
    if (scope === 'beauty_os' || compact === 'beautyos' || compact === 't24beautyos') products.add('beautyos');
    if (scope === 'restaurant_os' || compact === 'restaurantos' || compact === 't24menurestaurantos' || name === '线上点餐系统') products.add('restaurant');
    if (scope === 'managed' || name === '代运营服务') products.add('managed_service');
  }
  if (products.size === 1) return [...products][0];
  return products.size === 0 || products.has(fallback) ? fallback : 'general';
}
