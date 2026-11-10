/** Presentation-only guards: never change customer identity or address values. */
export function visibleCustomerColumns(keys: unknown, allowed: readonly string[], fallback: readonly string[]): string[] {
  const values = Array.isArray(keys) ? keys : fallback;
  return ['business_name', ...values.filter((key): key is string => typeof key === 'string' && key !== 'business_name' && allowed.includes(key))]
    .filter((key, index, result) => result.indexOf(key) === index);
}

export function currentPagePreview<T extends { id: number }>(items: readonly T[], selectedId: number | null): T | undefined {
  return items.find(item => item.id === selectedId) || items[0];
}

export function customerAddressLines(customer: { address?: string; city?: string; state?: string; country?: string }, stateLabel: string, countryLabel: string) {
  const clean = (value?: string) => String(value || '').trim();
  const city = clean(customer.city), state = clean(customer.state), country = clean(customer.country);
  const region = [city, clean(stateLabel) || state, clean(countryLabel) || country].filter(Boolean);
  const parts = clean(customer.address).split(/[,，]/).map(clean).filter(Boolean);
  const aliases = new Set([city, state, stateLabel, country, countryLabel, ...(country === 'US' ? ['USA', 'United States', 'United States of America'] : [])].filter(Boolean).map(value => value.toLocaleLowerCase()));
  let postal = '';
  while (parts.length > 0) {
    const tail = parts[parts.length - 1];
    if (aliases.has(tail.toLocaleLowerCase())) { parts.pop(); continue; }
    const statePostal = tail.match(/^(.+?)\s+(\d{5}(?:-\d{4})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d)$/i);
    if (statePostal && [state, stateLabel].filter(Boolean).some(value => value.toLocaleLowerCase() === statePostal[1].toLocaleLowerCase())) {
      postal = statePostal[2]; parts.pop(); continue;
    }
    break;
  }
  return { street: parts.join(', '), region: [...new Set(region), postal].filter(Boolean).join(', ') };
}
