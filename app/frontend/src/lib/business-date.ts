export const BUSINESS_TIME_ZONE = 'Asia/Shanghai';

const BUSINESS_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_IN_MILLISECONDS = 24 * 60 * 60 * 1000;
const businessDateFormatter = new Intl.DateTimeFormat('en-US-u-ca-gregory', {
  timeZone: BUSINESS_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

type BusinessDateParts = {
  year: number;
  month: number;
  day: number;
};

function parseBusinessDate(dateKey: string): BusinessDateParts | null {
  const match = BUSINESS_DATE_PATTERN.exec(dateKey);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) {
    return null;
  }
  return { year, month, day };
}

function formatBusinessDateParts(parts: BusinessDateParts) {
  return [
    String(parts.year).padStart(4, '0'),
    String(parts.month).padStart(2, '0'),
    String(parts.day).padStart(2, '0'),
  ].join('-');
}

function businessDateOrdinal(dateKey: string) {
  const parts = parseBusinessDate(dateKey);
  if (!parts) return null;
  return Date.UTC(parts.year, parts.month - 1, parts.day) / DAY_IN_MILLISECONDS;
}

/** Returns the calendar date currently in effect for the China-based business. */
export function businessDateKey(reference: Date | number = new Date()) {
  const date = reference instanceof Date ? reference : new Date(reference);
  if (Number.isNaN(date.getTime())) return '';

  const parts = Object.fromEntries(
    businessDateFormatter
      .formatToParts(date)
      .filter(part => part.type === 'year' || part.type === 'month' || part.type === 'day')
      .map(part => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** Adds calendar days to a YYYY-MM-DD business date without using the device timezone. */
export function addBusinessDateDays(dateKey: string, days: number) {
  const parts = parseBusinessDate(dateKey);
  if (!parts || !Number.isFinite(days)) return '';

  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + Math.trunc(days)));
  return formatBusinessDateParts({
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
  });
}

/** Returns target - base in whole business calendar days. */
export function businessDateDifference(targetDateKey: string, baseDateKey = businessDateKey()) {
  const targetOrdinal = businessDateOrdinal(targetDateKey.slice(0, 10));
  const baseOrdinal = businessDateOrdinal(baseDateKey.slice(0, 10));
  if (targetOrdinal === null || baseOrdinal === null) return null;
  return targetOrdinal - baseOrdinal;
}

export function businessWeekRange(reference: Date | number = new Date()) {
  const today = businessDateKey(reference);
  const parts = parseBusinessDate(today);
  if (!parts) return { start: '', end: '' };

  const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay() || 7;
  return {
    start: addBusinessDateDays(today, 1 - weekday),
    end: addBusinessDateDays(today, 7 - weekday),
  };
}
