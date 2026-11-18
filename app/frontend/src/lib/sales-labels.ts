import { useQuery } from '@tanstack/react-query';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';

export type SalesLabelKind = 'source' | 'provider' | 'operation';
export type SalesLabelIndustry = 'all' | 'restaurant' | 'beauty';
export type SalesLabel = {
  id: number;
  name: string;
  kind: SalesLabelKind;
  industry: SalesLabelIndustry;
  archived: boolean;
  confirmed?: boolean;
  confirmed_at?: string | null;
};

export const salesLabelKinds = { source: '名单来源', provider: '在用系统', operation: '经营标签' } as const;
export const salesLabelIndustries = { all: '全行业', restaurant: '餐厅', beauty: '美业' } as const;

export function useSalesLabels(enabled = true) {
  const { employee, role } = useRole();
  return useQuery<SalesLabel[]>({
    queryKey: ['sales-label-catalog', employee?.id, role],
    enabled: enabled && Boolean(employee?.id),
    queryFn: async () => (await invokeWithAuth({ url: '/api/v1/sales-labels', method: 'GET' })).data.items,
    staleTime: 30000,
  });
}

export function salesLabelText(label: SalesLabel) {
  return `${salesLabelKinds[label.kind]}：${label.name}${label.archived ? '（已停用）' : ''}`;
}

export function labelError(error: unknown) {
  const value = error as { data?: { detail?: unknown }; message?: string };
  return typeof value?.data?.detail === 'string' ? value.data.detail : value?.message || '标签操作未完成，请重试';
}
