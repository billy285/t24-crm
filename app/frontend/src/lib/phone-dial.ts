export type CustomerDialTarget = {
  dialNumber: string;
  displayNumber: string;
};

export function getCustomerDialTarget(phone: string): CustomerDialTarget | null {
  const digits = phone.replace(/\D/g, '');
  if (!digits) return null;

  const dialNumber = digits.length === 10 ? `1${digits}` : digits;
  if (dialNumber.length < 10) return null;

  return {
    dialNumber,
    displayNumber: `+${dialNumber}`,
  };
}

export function launchCustomerDial(phone: string): CustomerDialTarget | null {
  const target = getCustomerDialTarget(phone);
  if (!target) return null;

  // Keep this as a direct, same-tab navigation from the user's click. Mobile
  // browsers and embedded webviews commonly block window.open(), while a
  // normal HTTPS navigation remains reliable and preserves Back navigation.
  window.location.assign(`https://app.ringcentral.com/r/call?number=${target.dialNumber}`);
  return target;
}
