// Customer code format settings - stored in localStorage

export interface IndustryPrefix {
  industry: string;
  prefix: string;
  label: string;
}

export interface CustomerCodeSettings {
  useIndustryPrefix: boolean; // Whether to use industry-based prefix
  defaultPrefix: string; // Default prefix when not using industry prefix (e.g. "C")
  industryPrefixes: IndustryPrefix[];
  digitCount: number; // Number of digits for the sequence number (e.g. 4 => 0001)
  includeYear: boolean; // Whether to include year in the code
  separator: string; // Separator between prefix and number (e.g. "-", "", etc.)
}

const STORAGE_KEY = 'crm_customer_code_settings';

export const defaultIndustryPrefixes: IndustryPrefix[] = [
  { industry: 'restaurant', prefix: 'R', label: '餐厅' },
  { industry: 'nail', prefix: 'N', label: '美甲' },
  { industry: 'massage', prefix: 'M', label: '按摩' },
  { industry: 'beauty', prefix: 'B', label: '美容' },
  { industry: 'supermarket', prefix: 'S', label: '超市' },
  { industry: 'other', prefix: 'O', label: '其他' },
];

export const defaultSettings: CustomerCodeSettings = {
  useIndustryPrefix: false,
  defaultPrefix: 'C',
  industryPrefixes: defaultIndustryPrefixes,
  digitCount: 4,
  includeYear: true,
  separator: '',
};

export function loadSettings(): CustomerCodeSettings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      // Merge with defaults to ensure all fields exist
      return { ...defaultSettings, ...parsed };
    }
  } catch {
    // ignore
  }
  return { ...defaultSettings };
}

export function saveSettings(settings: CustomerCodeSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

/**
 * Generate the next auto customer code based on settings and existing customers.
 * @param industry - The industry of the customer (used when useIndustryPrefix is true)
 * @param existingCodes - Array of existing customer codes to determine the next sequence number
 */
export function generateNextCode(
  settings: CustomerCodeSettings,
  industry: string,
  existingCodes: string[]
): string {
  const year = new Date().getFullYear();

  // Determine prefix
  let prefix: string;
  if (settings.useIndustryPrefix) {
    const found = settings.industryPrefixes.find(ip => ip.industry === industry);
    prefix = found?.prefix || settings.defaultPrefix;
  } else {
    prefix = settings.defaultPrefix;
  }

  // Build the full prefix (with optional year and separator)
  const yearPart = settings.includeYear ? String(year) : '';
  const fullPrefix = `${prefix}${settings.separator}${yearPart}${settings.separator}`;

  // Find the max existing sequence number for this prefix
  const existingNums = existingCodes
    .filter(code => code?.startsWith(fullPrefix))
    .map(code => {
      const numPart = code.slice(fullPrefix.length);
      return parseInt(numPart, 10);
    })
    .filter(n => !isNaN(n));

  const maxNum = existingNums.length > 0 ? Math.max(...existingNums) : 0;
  const nextNum = String(maxNum + 1).padStart(settings.digitCount, '0');

  return `${fullPrefix}${nextNum}`;
}

/**
 * Generate a preview of what a code would look like
 */
export function previewCode(settings: CustomerCodeSettings, industry: string): string {
  const year = new Date().getFullYear();
  let prefix: string;
  if (settings.useIndustryPrefix) {
    const found = settings.industryPrefixes.find(ip => ip.industry === industry);
    prefix = found?.prefix || settings.defaultPrefix;
  } else {
    prefix = settings.defaultPrefix;
  }
  const yearPart = settings.includeYear ? String(year) : '';
  const sampleNum = '1'.padStart(settings.digitCount, '0');
  return `${prefix}${settings.separator}${yearPart}${settings.separator}${sampleNum}`;
}