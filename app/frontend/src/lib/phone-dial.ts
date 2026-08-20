export type CustomerDialMode = 'ringcentral' | 'ringcentral_web' | 'system';

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

export function launchCustomerDial(phone: string, mode: CustomerDialMode): CustomerDialTarget | null {
  const target = getCustomerDialTarget(phone);
  if (!target) return null;

  if (mode === 'ringcentral') {
    // RingCentral's registered URI expects digits only. Keeping this action
    // directly inside the user's click also avoids mobile browser popup blocks.
    window.location.assign(`rcmobile://call?number=${target.dialNumber}`);
    return target;
  }

  if (mode === 'ringcentral_web') {
    window.open(
      `https://app.ringcentral.com/r/call?number=${target.dialNumber}`,
      '_blank',
      'noopener,noreferrer',
    );
    return target;
  }

  window.location.assign(`tel:${target.displayNumber}`);
  return target;
}
