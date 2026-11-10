import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';

export type DeliveryAppliedFilter = { key: string; label: string; onClear: () => void };

export function DeliveryFilterSummary({ scope, count, filters, onClearAll, loading = false, stale = false }: {
  scope: string;
  count: number;
  filters: DeliveryAppliedFilter[];
  onClearAll: () => void;
  loading?: boolean;
  stale?: boolean;
}) {
  return <section className="dc-filter-context" aria-label="当前范围与生效筛选">
    <div className="dc-result-summary" role="status"><span>当前范围：{scope}</span><strong>{loading ? '正在读取…' : `${stale ? '最近读取' : '当前结果'} ${count} 条`}</strong></div>
    {filters.length > 0 && <div className="dc-applied-filters"><span>生效筛选</span>{filters.map(filter => <button key={filter.key} type="button" aria-label={`取消筛选：${filter.label}`} onClick={filter.onClear}><span>{filter.label}</span><X size={12} aria-hidden="true"/></button>)}<Button type="button" size="sm" variant="ghost" onClick={onClearAll}>清空筛选</Button></div>}
  </section>;
}

export function DeliveryPagination({ info, pageSize, sizes, onPage, onPageSize, label }: {
  info: { total: number; start: number; end: number; page: number; totalPages: number };
  pageSize: number;
  sizes: readonly number[];
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
  label: string;
}) {
  if (info.total === 0) return null;
  return <footer className="dc-list-pagination" aria-label={`${label}分页`}>
    <div className="dc-pagination-summary"><span>显示 {info.start}–{info.end} 条 / 共 {info.total} 条</span><NativeSelect aria-label={`${label}每页显示`} value={String(pageSize)} onChange={value => onPageSize(Number(value))} options={sizes.map(size => ({ value: String(size), label: `${size} 条/页` }))}/></div>
    <div className="dc-pagination-actions"><Button type="button" size="sm" variant="outline" className="dc-pagination-edge" disabled={info.page <= 1} onClick={() => onPage(1)}>首页</Button><Button type="button" size="sm" variant="outline" disabled={info.page <= 1} onClick={() => onPage(info.page - 1)}>上一页</Button><span aria-live="polite">{info.page} / {info.totalPages} 页</span><Button type="button" size="sm" variant="outline" disabled={info.page >= info.totalPages} onClick={() => onPage(info.page + 1)}>下一页</Button><Button type="button" size="sm" variant="outline" className="dc-pagination-edge" disabled={info.page >= info.totalPages} onClick={() => onPage(info.totalPages)}>末页</Button></div>
  </footer>;
}
