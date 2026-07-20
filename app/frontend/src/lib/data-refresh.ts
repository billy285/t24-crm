export const BUSINESS_DATA_REFRESH_EVENT = 't24:business-data-refresh';

export type BusinessDataRefreshReason =
  | 'login'
  | 'auth-restored'
  | 'route-change'
  | 'page-show'
  | 'focus'
  | 'reconnect'
  | 'manual';

export function requestBusinessDataRefresh(reason: BusinessDataRefreshReason = 'manual') {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(BUSINESS_DATA_REFRESH_EVENT, { detail: { reason } }));
}
