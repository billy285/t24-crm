export const dealMediaPlatforms: Record<string, string> = {
  google_business: 'Google商家',
  facebook: 'Facebook',
  instagram: 'Instagram',
  yelp: 'Yelp',
  tiktok: 'TikTok',
  xiaohongshu: '小红书',
  x: 'X',
};

const systemProducts = {
  restaurant_os: '餐饮 OS 系统',
  beauty_os: '美业 OS 系统',
} as const;

export type DealProductScope = 'managed' | keyof typeof systemProducts | 'other';

export function dealProductScope(code: string, label = ''): DealProductScope {
  if (code === 'restaurant_os' || code === 'beauty_os') return code;
  if (code === 'social_media' || code === 'managed_service') return 'managed';

  // Existing custom dictionary keys can carry the same business meaning.
  const name = label.toLowerCase().replace(/\s+/g, '');
  if (/^餐饮os(?:系统)?$/.test(name)) return 'restaurant_os';
  if (/^美业os(?:系统)?$/.test(name)) return 'beauty_os';
  if (/^(?:新媒体|社交媒体|媒体)?代运营$/.test(name)) return 'managed';
  return 'other';
}

export function withSystemProductDefaults(products: Record<string, string>): Record<string, string> {
  const options = { ...products };
  const scopes = new Set(Object.entries(products).map(([code, name]) => dealProductScope(code, name)));
  for (const [code, name] of Object.entries(systemProducts)) {
    if (!scopes.has(dealProductScope(code))) options[code] = name;
  }
  return options;
}

export function dealProductValue(code: string, products: Record<string, string>): string {
  const scope = dealProductScope(code, products[code]);
  return scope === 'restaurant_os' || scope === 'beauty_os' ? scope : code;
}

/** Use canonical OS keys for new sales without changing saved dictionary or deal keys. */
export function dealProductOptions(products: Record<string, string>): Record<string, string> {
  const options: Record<string, string> = {};
  for (const [code, label] of Object.entries(withSystemProductDefaults(products))) {
    const key = dealProductValue(code, products);
    options[key] = products[key] || label;
  }
  return options;
}

/** Only enforce a platform count when the customer-facing package actually specifies it. */
export function dealPackagePlatformLimit(_key: string, label: string): number | null {
  const match = label.normalize('NFKC').match(/任选\s*(\d+|[一二两三四五六七八九十]+)/);
  if (!match) return null;
  const token = match[1];
  const numbers: Record<string, number> = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
  const limit = Number(token) || numbers[token];
  return Number.isSafeInteger(limit) && limit > 0 ? limit : null;
}

const platformAliases = new Map<string, string>([
  ...Object.entries(dealMediaPlatforms).flatMap(([key, label]): [string, string][] => [
    [key, key], [label.toLowerCase(), key],
  ]),
  ['google', 'google_business'],
  ['google business', 'google_business'],
  ['google business profile', 'google_business'],
  ['twitter', 'x'],
  ['广告投放', 'ads_campaign'],
  ['品牌官网', 'brand_website'],
  ['官网', 'brand_website'],
]);

export function readDealPlatforms(raw: unknown): string[] {
  let values: unknown = raw;
  if (typeof raw === 'string') {
    const text = raw.trim();
    if (text.startsWith('[')) {
      try { values = JSON.parse(text); }
      catch { values = [text]; }
    } else {
      values = text.split(/[,，、]/);
    }
  }
  if (!Array.isArray(values)) return [];
  const platforms = new Set<string>();
  for (const item of values) {
    if (typeof item !== 'string' || !item.trim()) continue;
    const name = item.trim();
    platforms.add(platformAliases.get(name.toLowerCase()) || name);
  }
  return [...platforms];
}

export function isManagedDealPackage(key: string, label: string): boolean {
  if (['ads_campaign', 'ads_campaign_management', 'brand_website', 'restaurant_os', 'beauty_os'].includes(key)) return false;
  const name = label.normalize('NFKC').replace(/\s/g, '');
  return !/^(?:广告投放|广告代投|广告投放套餐|投放套餐(?:\(投放\))?|品牌官网(?:套餐)?|网站设计|餐饮OS(?:系统)?|美业OS(?:系统)?)$/i.test(name);
}
