export type ContactTimezoneGroup = 'eastern' | 'central' | 'mountain' | 'pacific' | 'alaska' | 'hawaii' | 'unknown';
export type ContactTimezoneBasis = 'confirmed_profile' | 'address_state' | 'address_city' | 'unknown';
export type ContactTimezone = {
  timezone?: string | null;
  timezone_group?: ContactTimezoneGroup;
  timezone_basis?: ContactTimezoneBasis;
  timezone_needs_confirmation?: boolean;
};

export const contactTimezoneLabels: Record<ContactTimezoneGroup, string> = {
  eastern: '东部', central: '中部', mountain: '山地', pacific: '西部',
  alaska: '阿拉斯加', hawaii: '夏威夷', unknown: '待确认',
};

export function validContactTimezone(value?: unknown): string | undefined {
  const timezone = typeof value === 'string' ? value.trim() : '';
  if (!timezone) return undefined;
  try { new Intl.DateTimeFormat('en-US', { timeZone: timezone }); return timezone; }
  catch { return undefined; }
}

export function contactTimezoneBasisLabel(context: ContactTimezone): string {
  if (context.timezone_basis === 'confirmed_profile') return '人工确认';
  if (context.timezone_basis === 'address_state' || context.timezone_basis === 'address_city') return '地址推定';
  return '待确认';
}

export function contactTimezoneLabel(context: ContactTimezone): string {
  return contactTimezoneLabels[context.timezone_group || 'unknown'] || '待确认';
}

export function formatContactClock(timezone?: string | null, now = new Date()): string | undefined {
  const valid = validContactTimezone(timezone);
  if (!valid) return undefined;
  return new Intl.DateTimeFormat('zh-CN', { timeZone: valid, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now);
}

export function resolveContactTimezone(profileTimezone?: unknown, derived?: ContactTimezone): ContactTimezone {
  const unknown: ContactTimezone = { timezone: null, timezone_group: 'unknown', timezone_basis: 'unknown', timezone_needs_confirmation: true };
  // The server validates manual IANA values and address exceptions together.
  // Its explicit unknown result must not be overridden by a legacy raw value
  // which Intl may accept more loosely (for example, case-folded aliases).
  if (derived !== undefined) {
    const timezone = validContactTimezone(derived?.timezone);
    return timezone ? { ...derived, timezone } : unknown;
  }
  const manual = validContactTimezone(profileTimezone);
  return manual ? { timezone: manual, timezone_basis: 'confirmed_profile', timezone_needs_confirmation: false } : unknown;
}
