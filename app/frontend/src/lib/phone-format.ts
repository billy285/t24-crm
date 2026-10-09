import { getCountries, parsePhoneNumberWithError, type CountryCode } from 'libphonenumber-js/max';

export type PhoneNumberStatus = 'valid' | 'invalid' | 'ambiguous' | 'needs_country' | 'empty';
export type ParsedPhoneNumber = {
  raw: string; e164: string | null; extension: string | null;
  status: PhoneNumberStatus; reason: string; country: CountryCode | null;
  nationalDisplay: string | null; internationalDisplay: string | null; isValid: boolean;
};
const COUNTRY_ALIASES: Record<string, CountryCode> = {
  USA: 'US', 'UNITED STATES': 'US', 'UNITED STATES OF AMERICA': 'US', 美国: 'US',
  CANADA: 'CA', 加拿大: 'CA', UK: 'GB', 'UNITED KINGDOM': 'GB', 英国: 'GB',
  CHINA: 'CN', 中国: 'CN', AUSTRALIA: 'AU', 澳大利亚: 'AU',
  'NEW ZEALAND': 'NZ', 新西兰: 'NZ', 'HONG KONG': 'HK', 香港: 'HK',
  TAIWAN: 'TW', 台湾: 'TW', SINGAPORE: 'SG', 新加坡: 'SG',
};
const SUPPORTED_COUNTRIES = new Set<string>(getCountries());
const EXTENSION = /\s*(?:;ext=|\bext(?:ension)?\.?\s*[:=]?|x|#|分机\s*[:：]?)\s*(\d{1,10})\s*$/i;

export function normalizePhoneCountry(country?: string | null): CountryCode | null {
  const value = String(country || '').trim().toUpperCase();
  const normalized = COUNTRY_ALIASES[value] || value;
  return SUPPORTED_COUNTRIES.has(normalized) ? normalized as CountryCode : null;
}

export function parsePhoneNumber(raw?: string | null, country?: string | null): ParsedPhoneNumber {
  const original = raw == null ? '' : String(raw);
  let text = original.normalize('NFKC').trim();
  const region = normalizePhoneCountry(country);
  const result: ParsedPhoneNumber = {
    raw: original, e164: null, extension: null, status: 'invalid',
    reason: '电话号码格式不正确', country: region,
    nationalDisplay: null, internationalDisplay: null, isValid: false,
  };
  if (!text) return { ...result, status: 'empty', reason: '请填写电话号码' };
  const extension = text.match(EXTENSION);
  if (extension) {
    result.extension = extension[1];
    text = text.slice(0, extension.index).trim();
  }
  if (/[/,;|&\n\r]/.test(text) || (text.match(/\+/g) || []).length > 1) {
    return { ...result, status: 'ambiguous', reason: '请只填写一个电话号码，分机请单独标明' };
  }
  if (!/^\+?[0-9\s().-]+$/.test(text) || !/\d/.test(text)) {
    return { ...result, reason: '电话号码含有无法识别的字符' };
  }
  if (!text.startsWith('+') && !region) {
    return { ...result, status: 'needs_country', reason: '本地号码需要明确国家或地区；也可填写以 + 开头的国际号码' };
  }
  try {
    const parsed = parsePhoneNumberWithError(text, { defaultCountry: region || undefined, extract: false });
    if (!parsed.isValid()) return { ...result, reason: '电话号码无效，请核对国家码和位数' };
    return {
      ...result, e164: parsed.number, status: 'valid', reason: '', isValid: true,
      country: parsed.country || region, nationalDisplay: parsed.formatNational(),
      internationalDisplay: parsed.formatInternational(),
    };
  } catch {
    return { ...result, reason: '无法识别电话号码，请核对国家码和位数' };
  }
}

export function phoneMatchKey(raw?: string | null, country?: string | null): string | null {
  return parsePhoneNumber(raw, country).e164;
}

// Presentation compatibility never changes strict write/import validation or
// match keys. Only one fully wrapped, otherwise valid number is accepted.
export function parsePhoneNumberForDisplay(raw?: string | null, country?: string | null): ParsedPhoneNumber & { hasPresentationDecoration: boolean } {
  const strict = parsePhoneNumber(raw, country);
  if (strict.isValid) return { ...strict, hasPresentationDecoration: false };
  const wrapped = strict.raw.normalize('NFKC').trim().match(/^\*\*([^*]+)\*\*$/);
  if (wrapped) {
    const inner = parsePhoneNumber(wrapped[1], country);
    if (inner.isValid) return { ...inner, raw: strict.raw, hasPresentationDecoration: true };
  }
  return { ...strict, hasPresentationDecoration: false };
}

export function formatPhoneNumber(raw?: string | null, country?: string | null): string {
  const parsed = parsePhoneNumberForDisplay(raw, country);
  if (!parsed.isValid) return parsed.raw || '—';
  const northAmerican = (parsed.country === 'US' || parsed.country === 'CA') && parsed.e164?.match(/^\+1(\d{3})(\d{3})(\d{4})$/);
  const display = northAmerican ? `+1 (${northAmerican[1]}) ${northAmerican[2]}-${northAmerican[3]}` : parsed.internationalDisplay;
  return `${display}${parsed.extension ? ` 分机 ${parsed.extension}` : ''}`;
}

export function getPhoneCopyValue(raw?: string | null, country?: string | null): string | null {
  return parsePhoneNumberForDisplay(raw, country).isValid ? formatPhoneNumber(raw, country) : null;
}

export function phoneSearchMatches(raw: string | null | undefined, query: string, country?: string | null): boolean {
  const needle = query.normalize('NFKC').trim().toLowerCase();
  if (!needle) return true;
  const original = raw == null ? '' : String(raw);
  if (original.normalize('NFKC').toLowerCase().includes(needle)) return true;
  if (!/^[+0-9\s().-]+$/.test(needle)) return false;
  const digits = needle.replace(/\D/g, '');
  if (!digits) return false;
  const parsed = parsePhoneNumber(raw, country);
  return [parsed.e164, parsed.nationalDisplay, parsed.internationalDisplay, parsed.raw]
    .filter(Boolean).some(value => value!.replace(/\D/g, '').includes(digits));
}
