import { readCachedAppConfig } from './app-config';

const DEFAULT_EXPIRY_WARNING_DAYS = 7;
const LEGACY_EXPIRY_WARNING_DAYS = 30;
const PACKAGE_NAME_SEPARATOR = /[、,，]/;
const MANUAL_SUBSCRIPTION_STATUSES = new Set(['paused', 'lost', 'renewed']);

type ReminderConfig = {
  expiryDaysBefore?: number;
};

type SubscriptionLike = {
  id?: number | string | null;
  customer_id?: number | string | null;
  package_name?: string | null;
  product_name?: string | null;
  status?: string | null;
  end_date?: string | null;
  next_payment_date?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
};

function toTimestamp(value?: string | number | null) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  if (!value) return 0;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function compareSubscriptionsDesc(a: SubscriptionLike, b: SubscriptionLike) {
  const fields: Array<keyof SubscriptionLike> = ['end_date', 'next_payment_date', 'updated_at', 'created_at'];
  for (const field of fields) {
    const diff = toTimestamp(b[field] as string | null | undefined) - toTimestamp(a[field] as string | null | undefined);
    if (diff !== 0) return diff;
  }
  return Number(b.id || 0) - Number(a.id || 0);
}

export function getSubscriptionExpiryWarningDays() {
  const config = readCachedAppConfig<ReminderConfig>('reminder_config', { expiryDaysBefore: DEFAULT_EXPIRY_WARNING_DAYS });
  const warningDays = Number(config?.expiryDaysBefore);
  if (!Number.isFinite(warningDays) || warningDays < 0) return DEFAULT_EXPIRY_WARNING_DAYS;
  return warningDays === LEGACY_EXPIRY_WARNING_DAYS ? DEFAULT_EXPIRY_WARNING_DAYS : warningDays;
}

export function normalizeSubscriptionPackageNames(value?: string | string[] | null) {
  const rawValues = Array.isArray(value) ? value : String(value || '').split(PACKAGE_NAME_SEPARATOR);
  return rawValues
    .map(item => item.trim())
    .filter(Boolean)
    .map(item => item.toLowerCase())
    .sort((a, b) => a.localeCompare(b, 'en-US'));
}

export function buildSubscriptionPackageKey(customerId?: number | string | null, packageName?: string | string[] | null) {
  const customerKey = customerId == null || customerId === '' ? 'unknown_customer' : String(customerId);
  const packageKey = normalizeSubscriptionPackageNames(packageName).join('|') || '__empty_package__';
  return `${customerKey}::${packageKey}`;
}

export function getSubscriptionRemainingDays(subscription?: Pick<SubscriptionLike, 'end_date'> | null) {
  if (!subscription?.end_date) return null;
  const endDate = new Date(subscription.end_date);
  if (Number.isNaN(endDate.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((endDate.getTime() - today.getTime()) / 86400000);
}

export function computeSubscriptionStatus(subscription?: SubscriptionLike | null, warningDays = getSubscriptionExpiryWarningDays()) {
  if (!subscription) return 'active';
  if (!subscription.end_date) return subscription.status || 'active';
  if (subscription.status && MANUAL_SUBSCRIPTION_STATUSES.has(subscription.status)) return subscription.status;

  const diffDays = getSubscriptionRemainingDays(subscription);
  if (diffDays == null) return subscription.status || 'active';
  if (diffDays <= 0) return 'expired';
  if (diffDays <= warningDays) return 'expiring_soon';
  return 'active';
}

export function sortSubscriptionsByPriority<T extends SubscriptionLike>(subscriptions: T[]) {
  return [...subscriptions].sort(compareSubscriptionsDesc);
}

export function getEffectiveSubscriptions<T extends SubscriptionLike>(subscriptions: T[]) {
  const deduped = new Map<string, T>();

  for (const subscription of sortSubscriptionsByPriority(subscriptions)) {
    const key = buildSubscriptionPackageKey(
      subscription.customer_id,
      subscription.package_name || subscription.product_name || '',
    );
    if (!deduped.has(key)) {
      deduped.set(key, subscription);
    }
  }

  return sortSubscriptionsByPriority(Array.from(deduped.values()));
}

export function decorateEffectiveSubscriptions<T extends SubscriptionLike>(subscriptions: T[], warningDays = getSubscriptionExpiryWarningDays()) {
  return getEffectiveSubscriptions(subscriptions).map(subscription => ({
    ...subscription,
    status: computeSubscriptionStatus(subscription, warningDays),
  }));
}

export function findMatchingSubscription<T extends SubscriptionLike>(
  subscriptions: T[],
  options: { customerId: number | string; packageName?: string | string[] | null },
) {
  const customerSubscriptions = getEffectiveSubscriptions(subscriptions).filter(
    subscription => String(subscription.customer_id || '') === String(options.customerId),
  );
  if (customerSubscriptions.length === 0) return null;

  const targetKey = buildSubscriptionPackageKey(options.customerId, options.packageName);
  const exactMatch = customerSubscriptions.find(
    subscription => buildSubscriptionPackageKey(
      subscription.customer_id,
      subscription.package_name || subscription.product_name || '',
    ) === targetKey,
  );
  if (exactMatch) return exactMatch;

  return customerSubscriptions.length === 1 ? customerSubscriptions[0] : null;
}
