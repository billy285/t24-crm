import { parsePhoneNumberForDisplay } from './phone-format';

export type CustomerDialTarget = {
  dialNumber: string;
  displayNumber: string;
};

export function getCustomerDialValidation(phone: string, country?: string | null) {
  return parsePhoneNumberForDisplay(phone, country);
}

export function getCustomerDialTarget(phone: string, country?: string | null): CustomerDialTarget | null {
  const parsed = getCustomerDialValidation(phone, country);
  if (!parsed.isValid || !parsed.e164) return null;
  return { dialNumber: parsed.e164.slice(1), displayNumber: parsed.e164 };
}

export function launchCustomerDial(phone: string, country?: string | null): CustomerDialTarget | null {
  const target = getCustomerDialTarget(phone, country);
  if (!target) return null;

  // Keep this as a direct, same-tab navigation from the user's click. Mobile
  // browsers and embedded webviews commonly block window.open(), while a
  // normal HTTPS navigation remains reliable and preserves Back navigation.
  window.location.assign(`https://app.ringcentral.com/r/call?number=${target.dialNumber}`);
  return target;
}
