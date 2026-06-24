export const LEGACY_PAYMENT_METHOD_MAP: Record<string, string> = {
  subscription_debit: 'stripe',
};

export const AUTO_PAYMENT_METHOD_KEYS = new Set(['stripe']);

export function normalizePaymentMethodKey(method?: string | null): string {
  if (!method) return 'other';
  return LEGACY_PAYMENT_METHOD_MAP[method] || method;
}

export function inferPaymentModeKey(payment: { payment_mode?: string | null; payment_method?: string | null }): string {
  if (payment.payment_mode) return payment.payment_mode;
  return AUTO_PAYMENT_METHOD_KEYS.has(normalizePaymentMethodKey(payment.payment_method))
    ? 'subscription_auto'
    : 'manual_collection';
}

export function getPaymentMethodLabel(
  payment: { payment_method?: string | null },
  paymentMethodLabels: Record<string, string>,
): string {
  const methodKey = normalizePaymentMethodKey(payment.payment_method);
  return paymentMethodLabels[methodKey] || paymentMethodLabels[payment.payment_method || ''] || methodKey;
}

export function getPaymentModeLabel(
  payment: { payment_mode?: string | null; payment_method?: string | null },
  paymentModeLabels: Record<string, string>,
): string {
  const modeKey = inferPaymentModeKey(payment);
  return paymentModeLabels[modeKey] || modeKey;
}

export function normalizePaymentMethodOptions(paymentMethodLabels: Record<string, string>) {
  const deduped = new Map<string, string>();
  Object.entries(paymentMethodLabels).forEach(([key, label]) => {
    const normalizedKey = normalizePaymentMethodKey(key);
    if (!deduped.has(normalizedKey)) {
      deduped.set(normalizedKey, label);
    }
  });
  if (!deduped.has('stripe')) deduped.set('stripe', 'Stripe自动扣款');
  if (!deduped.has('other')) deduped.set('other', '其他');
  return Array.from(deduped.entries()).map(([value, label]) => ({ value, label }));
}
