import { useEffect, useState } from 'react';
import { getAuthSessionEpoch } from './auth-storage';
import { invokeWithAuth } from './tokenStore';

export const customerBusinessLabels: Record<string, string> = {
  all: '全部业务', restaurant_os: '餐饮 OS', beauty_os: '美业 OS', managed_service: '代运营', multiple: '多项业务',
};

type MembershipPage = {
  items: { customer_id: number; business_lines: string[] }[];
  next_after_id: number | null;
};

export function useCustomerBusinessFilter(business: string, scope: string, refreshedAt: string | null) {
  const session = getAuthSessionEpoch();
  const key = JSON.stringify([scope, business, session]);
  const [result, setResult] = useState<{ key: string; entries: Map<number, string[]> } | null>(null);
  const [failure, setFailure] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (business === 'all' || !refreshedAt) return;
    const controller = new AbortController();
    const active = () => !controller.signal.aborted && session === getAuthSessionEpoch();
    setFailure('');
    async function load() {
      const entries = new Map<number, string[]>();
      let after = 0;
      for (;;) {
        const response = await invokeWithAuth({
          url: '/api/v1/entities/customers/business-memberships', method: 'GET',
          data: { business, after_id: after, limit: 500 }, options: { signal: controller.signal },
        });
        if (!active()) return;
        const page = response.data as MembershipPage;
        if (!Array.isArray(page?.items)) throw new Error('业务分类暂不可用');
        for (const row of page.items) entries.set(row.customer_id, row.business_lines);
        if (page.next_after_id === null) break;
        if (!Number.isSafeInteger(page.next_after_id) || page.next_after_id <= after) throw new Error('业务分类分页异常');
        after = page.next_after_id;
      }
      if (active()) setResult({ key, entries });
    }
    void load().catch(() => {
      if (active()) { setResult(null); setFailure(key); }
    });
    return () => controller.abort();
  }, [business, key, session, refreshedAt, attempt]);

  return {
    entries: result?.key === key && business !== 'all' ? result.entries : null,
    error: business !== 'all' && failure === key,
    retry: () => setAttempt(value => value + 1),
  };
}
