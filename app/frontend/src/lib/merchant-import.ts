import { parsePhoneNumber } from './phone-format';

export const MERCHANT_IMPORT_HEADERS = ['商家名称', '商家电话', '商家位置', '地区', '来源'] as const;
export const MERCHANT_IMPORT_EXAMPLE = ['示例咖啡店', '+1 (212) 555 0123 ext 009', '1 Main St', 'New York, NY, US', 'Google Maps'] as const;

export type MerchantImportIssueRow = {
  status: string; reason: string; phone?: string | null; phone_country?: string | null;
  phone_status?: string; duplicate_row?: number; raw?: Record<string, string>;
};

// Advice explains the server's decision; it never changes eligibility or data.
export function merchantImportRepairAdvice(row: MerchantImportIssueRow): string | null {
  if (row.status === 'pending') return null;
  if (row.status === 'error') {
    if (/5列|五列/.test(row.reason)) return '保留模板的五列；用表格软件编辑，含逗号的地区或地址放在同一个单元格。';
    if (/商家名称|business_name|名称/.test(row.reason)) return '填写商家名称，长度不超过 200 字。';
    if (/来源|data_source/.test(row.reason)) return '来源填写简短的平台或文件名称，不超过 50 字。';
    return '按原行号修改原文件，保留固定五列表头，再重新预检。';
  }
  if (row.status === 'duplicate') return row.duplicate_row
    ? `与原第 ${row.duplicate_row} 行重复；核对后在原文件保留一条，勿为绕过重复而改造号码。`
    : '核对已有商家或线索，补充原记录，避免重复分配。';
  if (row.status === 'existing_customer') return '核对已关联的正式客户，继续客户跟进；此条不能作为新商家分配。';
  if (row.status === 'closed') return '核实营业状态；确已停业的商家保持隔离，不进入拨打名单。';
  if (row.status !== 'no_phone') return null;
  const raw = row.phone ?? row.raw?.['商家电话'] ?? '';
  if (!raw.trim()) return '补填一个完整联系电话；本地号码同时在“地区”列写明国家。';
  const wrapped = raw.normalize('NFKC').trim().match(/^\*\*([^*]+)\*\*$/);
  const content = wrapped ? wrapped[1] : raw;
  if (wrapped && parsePhoneNumber(content, row.phone_country).isValid) return '删除原文件电话两端的 **，保留号码和分机，再重新预检。';
  if (/[*•●]|\d[xX]{2,}\d/.test(content)) return '回到原始资料补齐真实号码；遮罩中的缺失数字不能推测。';
  const parsed = parsePhoneNumber(content, row.phone_country);
  const decorationAdvice = wrapped ? '删除电话两端的 **；' : '';
  if (row.phone_status === 'ambiguous' || parsed.status === 'ambiguous') return `${decorationAdvice}一行只保留一个联系电话；分机写为 ext 009，不要用斜线或逗号合并号码。`;
  if (row.phone_status === 'needs_country' || parsed.status === 'needs_country') return `${decorationAdvice}在“地区”列写明国家，例如 New York, NY, US；或填写含 + 国家码的完整号码。`;
  return `${decorationAdvice}核对原始号码的国家码和位数，去掉说明文字；号码单元格设为文本，保留 +、前导零和分机。`;
}

export type MerchantImportRecord = {
  business_name: string;
  phone: string | null;
  address: string | null;
  website: string | null;
  industry: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  rating: number | null;
  business_status: string | null;
};

const EMPTY_MARKERS = new Set([
  '待核验', '暂未确认', '官网未明确显示', '未明确显示', '无', '-', '–', '—', 'n/a', 'na',
]);

function normalizeOptional(value?: string) {
  const normalized = value?.trim();
  return normalized && !EMPTY_MARKERS.has(normalized.toLowerCase()) ? normalized : null;
}

function cleanWebsite(value?: string) {
  const normalized = normalizeOptional(value);
  if (!normalized) return null;
  const url = normalized.match(/https?:\/\/[^\s\])]+/i)?.[0];
  if (url) return url.replace(/[.,;:]+$/, '');
  const domain = normalized.match(/(?:www\.)?[a-z0-9][a-z0-9.-]+\.(?:com|net|org|co|us)(?:\/[^\s\])]*)?/i)?.[0];
  return domain ? domain.replace(/[.,;:]+$/, '') : normalized;
}

function parseRating(value?: string | null) {
  const normalized = normalizeOptional(value || undefined);
  if (!normalized) return null;
  const match = normalized.match(/[⭐★]\s*(\d+(?:\.\d+)?)/) || normalized.match(/^\s*(\d+(?:\.\d+)?)/);
  return match ? Number(match[1]) : null;
}

function splitRegion(value?: string) {
  const region = normalizeOptional(value);
  if (!region) return { city: null, state: null, country: null };
  const parts = region.split(',').map(part => part.trim()).filter(Boolean);
  const last = parts.at(-1) || '';
  const countryPattern = /^(?:US|USA|United States|美国)$/i;
  const statePattern = /^[A-Z]{2}$/i;
  let country: string | null = null;
  let state: string | null = null;
  if (countryPattern.test(last)) {
    country = 'US';
    parts.pop();
  }
  const stateCandidate = parts.at(-1) || '';
  if (statePattern.test(stateCandidate)) {
    state = stateCandidate.toUpperCase();
    parts.pop();
  }
  return { city: parts.join(', ') || null, state, country: country || (state ? 'US' : null) };
}

export function parseMerchantBulkRows(text: string): MerchantImportRecord[] {
  const lines = text
    .split('\n')
    .map(line => line.trim())
    .filter(line => Boolean(line) && !/^\[\d+\]:\s+https?:\/\//i.test(line));
  const normalizeHeader = (value?: string) => (value || '').replace(/[\s_\-()（）:：/]+/g, '').toLowerCase();
  const headerFields: Record<string, string> = {
    商家名称: 'business_name', 商家: 'business_name', 商户名称: 'business_name', 企业名称: 'business_name', 店铺名称: 'business_name', 名称: 'business_name', businessname: 'business_name', name: 'business_name',
    电话: 'phone', 电话网站: 'phone_website', 电话官网: 'phone_website', 联系电话: 'phone', 电话号码: 'phone', 手机: 'phone', phone: 'phone', phonenumber: 'phone', telephone: 'phone', tel: 'phone',
    地址: 'address', 详细地址: 'address', 营业地址: 'address', address: 'address', fulladdress: 'address',
    网站: 'website', 官网: 'website', 官网链接: 'website', 网站链接: 'website', website: 'website', url: 'website', domain: 'website',
    地区: 'region', location: 'region', region: 'region',
    行业: 'industry', 地区行业: 'industry', 类别: 'industry', 分类: 'industry', 商家类别: 'industry', industry: 'industry', category: 'industry',
    城市: 'city', city: 'city', 州: 'state', 省: 'state', 州省: 'state', state: 'state', province: 'state',
    国家: 'country', country: 'country', 公开评分: 'rating', 谷歌评分: 'rating', google评分: 'rating', googlerating: 'rating', 评分: 'rating', 星级: 'rating', rating: 'rating',
    营业状态: 'business_status', 商家状态: 'business_status', 状态: 'business_status', businessstatus: 'business_status', status: 'business_status',
  };
  const splitDelimitedRow = (line: string, delimiter: string) => {
    if (delimiter === '|') return line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(value => value.trim());
    const values: string[] = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (character === '"') {
        if (quoted && line[index + 1] === '"') { value += '"'; index += 1; }
        else quoted = !quoted;
      } else if (character === delimiter && !quoted) { values.push(value.trim()); value = ''; }
      else value += character;
    }
    values.push(value.trim());
    return values;
  };
  const splitRow = (line: string) => {
    if ((line.match(/\|/g) || []).length >= 2) return splitDelimitedRow(line, '|');
    if (line.includes('\t')) return splitDelimitedRow(line, '\t');
    return splitDelimitedRow(line, ',');
  };
  const rows = lines.map(splitRow).filter(values => values.length && !values.every(value => /^:?-{3,}:?$/.test(value.replace(/\s/g, ''))));
  const firstRow = rows[0] || [];
  const mappedHeaders = firstRow.map(value => headerFields[normalizeHeader(value)] || '');
  const hasHeader = mappedHeaders.includes('business_name');
  const dataRows = hasHeader ? rows.slice(1) : rows;
  return dataRows.map((values) => {
    const getByHeader = (field: string) => {
      const index = mappedHeaders.indexOf(field);
      if (index >= 0) return values[index];
      const combinedIndex = mappedHeaders.indexOf('phone_website');
      if (combinedIndex < 0) return undefined;
      const combinedValue = values[combinedIndex];
      const looksLikeWebsite = /(?:https?:\/\/|www\.|[\w.-]+\.(?:com|net|org|co|us)(?:\/|$))/i.test(combinedValue || '');
      if (field === 'website' && looksLikeWebsite) return combinedValue;
      if (field === 'phone' && !looksLikeWebsite) return combinedValue;
      return undefined;
    };
    const [businessName, phone, address, website, industry, city, state, country, rating, businessStatus] = values;
    const valueFor = (field: string, fallback?: string) => normalizeOptional(hasHeader ? getByHeader(field) : fallback);
    const region = splitRegion(valueFor('region') || undefined);
    const normalizedRating = valueFor('rating', rating);
    return {
      business_name: valueFor('business_name', businessName) || '',
      phone: valueFor('phone', phone),
      address: valueFor('address', address),
      website: cleanWebsite(hasHeader ? getByHeader('website') : website),
      industry: valueFor('industry', industry),
      city: valueFor('city', city) || region.city,
      state: valueFor('state', state) || region.state,
      country: valueFor('country', country) || region.country,
      rating: parseRating(normalizedRating),
      business_status: valueFor('business_status', businessStatus),
    };
  }).filter(record => record.business_name);
}
