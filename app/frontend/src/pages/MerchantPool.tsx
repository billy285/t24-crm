import { ChangeEvent, useEffect, useRef, useState } from 'react';
import { Archive, CheckSquare, ChevronDown, Database, Download, FileUp, Filter, MoreHorizontal, RefreshCw, Search, Send, ShieldCheck, Sparkles, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { getToken, invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { useRole } from '@/lib/role-context';
import { useIsMobile } from '@/hooks/use-mobile';

type Merchant = {
  id: number;
  business_name: string;
  contact_name?: string;
  phone?: string;
  industry?: string;
  country?: string;
  state?: string;
  city?: string;
  address?: string;
  website?: string;
  rating?: number;
  google_business_url?: string;
  google_rating?: number;
  google_review_count?: number;
  yelp_url?: string;
  yelp_rating?: number;
  yelp_review_count?: number;
  social_profiles?: string;
  recent_negative_reviews?: string;
  content_update_summary?: string;
  content_last_updated_at?: string;
  data_source: string;
  collected_at: string;
  business_status?: string;
  pool_status: string;
  isolation_reason?: string;
  duplicate_of_id?: number;
  existing_customer_id?: number;
  converted_lead_id?: number;
};

const statusLabels: Record<string, string> = {
  pending: '待清洗', no_phone: '无电话隔离', duplicate: '重复隔离',
  existing_customer: '正式客户隔离', closed: '已关闭隔离', converted: '已转线索', archived: '已归档',
};
const statusClasses: Record<string, string> = {
  pending: 'bg-blue-100 text-blue-700', no_phone: 'bg-amber-100 text-amber-800',
  duplicate: 'bg-orange-100 text-orange-800', existing_customer: 'bg-violet-100 text-violet-800',
  closed: 'bg-rose-100 text-rose-700', converted: 'bg-emerald-100 text-emerald-700', archived: 'bg-slate-100 text-slate-600',
};
const sourceOptions = [
  { value: '', label: '全部来源' }, { value: 'api', label: 'API' }, { value: 'csv', label: 'CSV' },
  { value: 'bulk', label: '批量粘贴' }, { value: 'manual', label: '手动录入' },
];
const industryOptions = ['餐厅', '美甲', '美容', '美业', '水疗', '按摩', '理发', '超市', '其他'];
const usStateOptions = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA',
  'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK',
  'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
];
const usStateAbbreviations: Record<string, string> = {
  alabama: 'AL', alaska: 'AK', arizona: 'AZ', arkansas: 'AR', california: 'CA', colorado: 'CO', connecticut: 'CT', delaware: 'DE', florida: 'FL', georgia: 'GA',
  hawaii: 'HI', idaho: 'ID', illinois: 'IL', indiana: 'IN', iowa: 'IA', kansas: 'KS', kentucky: 'KY', louisiana: 'LA', maine: 'ME', maryland: 'MD',
  massachusetts: 'MA', michigan: 'MI', minnesota: 'MN', mississippi: 'MS', missouri: 'MO', montana: 'MT', nebraska: 'NE', nevada: 'NV',
  'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', ohio: 'OH',
  oklahoma: 'OK', oregon: 'OR', pennsylvania: 'PA', 'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', tennessee: 'TN', texas: 'TX',
  utah: 'UT', vermont: 'VT', virginia: 'VA', washington: 'WA', 'west virginia': 'WV', wisconsin: 'WI', wyoming: 'WY', 'district of columbia': 'DC',
};
type EnrichmentSuggestion = { field: string; value: string | number; source_label: string; source_updated_at?: string | null; confidence: number };
type EnrichmentResult = { merchant_id: number; business_name: string; status: string; suggestions: EnrichmentSuggestion[]; missing_fields: string[]; warning?: string | null; source_updated_at?: string | null };

const emptyEdit = {
  business_name: '', contact_name: '', phone: '', industry: '', country: 'US', state: '', city: '', address: '', website: '', rating: '', business_status: '',
  google_business_url: '', google_rating: '', google_review_count: '', yelp_url: '', yelp_rating: '', yelp_review_count: '',
  social_profiles: '', recent_negative_reviews: '', content_update_summary: '', content_last_updated_at: '',
};

const importTemplateHeaders = ['商家名称', '商家电话', '商家位置', '地区', '来源'];

function formatDate(value?: string) {
  return value ? value.slice(0, 16).replace('T', ' ') : '-';
}

function formatPhone(value?: string) {
  if (!value) return '';
  const digits = value.replace(/\D/g, '');
  const nationalNumber = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits;
  if (nationalNumber.length !== 10) return value.trim();
  return `+1 ${nationalNumber.slice(0, 3)}-${nationalNumber.slice(3, 6)}-${nationalNumber.slice(6)}`;
}

function normalizeState(value?: string) {
  if (!value) return '';
  const trimmed = value.trim();
  const upper = trimmed.toUpperCase();
  if (usStateOptions.includes(upper)) return upper;
  return usStateAbbreviations[trimmed.toLowerCase()] || trimmed;
}

function formatRegion(merchant: Merchant) {
  const state = normalizeState(merchant.state);
  const country = merchant.country?.trim();
  const isUnitedStates = !country || ['US', 'USA', 'UNITED STATES', '美国'].includes(country.toUpperCase());
  return [merchant.city, state, isUnitedStates ? '' : country].filter(Boolean).join(', ') || '-';
}

export default function MerchantPool() {
  const { isAdmin, role } = useRole();
  const isMobile = useIsMobile();
  const canManagePool = isAdmin || role === 'sales_manager';
  const [items, setItems] = useState<Merchant[]>([]);
  const [assignees, setAssignees] = useState<{ id: number; name: string }[]>([]);
  const [selectedMerchantIds, setSelectedMerchantIds] = useState<number[]>([]);
  const [selectedSalesId, setSelectedSalesId] = useState('');
  const [bulkIndustry, setBulkIndustry] = useState('');
  const [bulkAssigning, setBulkAssigning] = useState(false);
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const [stats, setStats] = useState({ total: 0, pending: 0, isolated: 0, converted: 0, duplicates: 0, archived: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [poolStatus, setPoolStatus] = useState('');
  const [regions, setRegions] = useState<string[]>([]);
  const [industry, setIndustry] = useState('');
  const [source, setSource] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editing, setEditing] = useState<Merchant | null>(null);
  const [editForm, setEditForm] = useState(emptyEdit);
  const [enrichmentOpen, setEnrichmentOpen] = useState(false);
  const [enrichmentLoading, setEnrichmentLoading] = useState(false);
  const [enrichmentResults, setEnrichmentResults] = useState<EnrichmentResult[]>([]);
  const [enrichmentSelected, setEnrichmentSelected] = useState<Record<number, Record<string, boolean>>>({});
  const [applyingEnrichment, setApplyingEnrichment] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const loadRequestSeqRef = useRef(0);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const loadData = async (options?: { page?: number }) => {
    const requestId = ++loadRequestSeqRef.current;
    const requestPage = options?.page ?? page;
    setLoading(true);
    const params = new URLSearchParams({ skip: String((requestPage - 1) * pageSize), limit: String(pageSize) });
    if (search.trim()) params.set('search', search.trim());
    if (poolStatus) params.set('pool_status', poolStatus);
    if (regions.length) params.set('region', regions.join(','));
    if (industry.trim()) params.set('industry', industry.trim());
    if (source) params.set('source', source);
    try {
      const [listResult, statsResult] = await Promise.allSettled([
        invokeWithAuth({ url: `/api/v1/merchant-pool?${params.toString()}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/merchant-pool/stats', method: 'GET' }),
      ]);
      if (requestId !== loadRequestSeqRef.current) return;
      const failedSections: string[] = [];
      if (listResult.status === 'fulfilled') {
        const nextItems = listResult.value.data?.items || [];
        setItems(nextItems);
        setTotal(listResult.value.data?.total || 0);
        setSelectedMerchantIds(current => current.filter(id => nextItems.some((item: Merchant) => item.id === id)));
      } else {
        failedSections.push('商家列表');
      }
      if (statsResult.status === 'fulfilled') setStats(statsResult.value.data || stats);
      else failedSections.push('统计');
      if (failedSections.length) toast.error(`${failedSections.join('、')}加载失败，已保留其他可用数据`);
    } catch (error: any) {
      if (requestId === loadRequestSeqRef.current) toast.error(error?.data?.detail || error?.message || '商家池数据加载失败');
    } finally {
      if (requestId === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, poolStatus, regions, industry, source]);

  useEffect(() => {
    setPage(1);
    const timer = window.setTimeout(() => void loadData({ page: 1 }), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    if (!canManagePool) return;
    void invokeWithAuth({ url: '/api/v1/sales-leads/assignees', method: 'GET' })
      .then(response => setAssignees(response.data || []))
      .catch(() => toast.error('电话销售人员列表加载失败'));
  }, [canManagePool]);

  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !importOpen && !editing });

  const downloadImportTemplate = () => {
    const csv = `\uFEFF${importTemplateHeaders.join(',')}\r\n`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'T24商家导入固定模板.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const importCsv = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.xlsx')) {
      toast.error('请上传 CSV 或 Excel（.xlsx）文件');
      return;
    }
    setImporting(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const response = await fetch('/api/v1/merchant-pool/import-csv?data_source=csv', {
        method: 'POST', headers: { Authorization: `Bearer ${getToken()}` }, body,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result?.detail || 'CSV 导入失败');
      const importedCount = Object.values(result.counts || {}).reduce<number>((sum, value) => sum + Number(value || 0), 0);
      toast.success(`已导入 ${result.total} 条；待清洗 ${result.counts?.pending || 0} 条，自动隔离 ${importedCount - Number(result.counts?.pending || 0)} 条`);
      if (result.errors?.length) toast.warning(`${result.errors.length} 行格式有问题，未导入`);
      setImportOpen(false);
      await loadData();
    } catch (error: any) {
      toast.error(error?.message || 'CSV 导入失败');
    } finally {
      setImporting(false);
      event.target.value = '';
    }
  };

  const openEdit = (merchant: Merchant) => {
    setEditing(merchant);
    setEditForm({
      business_name: merchant.business_name || '', contact_name: merchant.contact_name || '', phone: merchant.phone || '',
      industry: merchant.industry || '', country: merchant.country || '', state: merchant.state || '', city: merchant.city || '',
      address: merchant.address || '', website: merchant.website || '', rating: merchant.rating?.toString() || '', business_status: merchant.business_status || '',
      google_business_url: merchant.google_business_url || '', google_rating: merchant.google_rating?.toString() || '', google_review_count: merchant.google_review_count?.toString() || '',
      yelp_url: merchant.yelp_url || '', yelp_rating: merchant.yelp_rating?.toString() || '', yelp_review_count: merchant.yelp_review_count?.toString() || '',
      social_profiles: merchant.social_profiles || '', recent_negative_reviews: merchant.recent_negative_reviews || '',
      content_update_summary: merchant.content_update_summary || '', content_last_updated_at: merchant.content_last_updated_at ? merchant.content_last_updated_at.slice(0, 16) : '',
    });
  };

  const saveEdit = async () => {
    if (!editing || !editForm.business_name.trim()) return;
    try {
      await invokeWithAuth({
        url: `/api/v1/merchant-pool/${editing.id}`,
        method: 'PUT',
        data: {
          ...editForm,
          rating: editForm.rating ? Number(editForm.rating) : null,
          google_rating: editForm.google_rating ? Number(editForm.google_rating) : null,
          google_review_count: editForm.google_review_count ? Number(editForm.google_review_count) : null,
          yelp_rating: editForm.yelp_rating ? Number(editForm.yelp_rating) : null,
          yelp_review_count: editForm.yelp_review_count ? Number(editForm.yelp_review_count) : null,
          content_last_updated_at: editForm.content_last_updated_at || null,
        },
      });
      toast.success('已重新清洗该商家记录');
      setEditing(null);
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '保存失败');
    }
  };

  const suggestEnrichment = async () => {
    if (!selectedMerchantIds.length) return;
    if (selectedMerchantIds.length > 20) {
      toast.error('AI 补充一次最多选择 20 条商家');
      return;
    }
    setEnrichmentLoading(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/merchant-pool/enrichment/suggest', method: 'POST', data: { merchant_ids: selectedMerchantIds } });
      const results: EnrichmentResult[] = response.data?.items || [];
      setEnrichmentResults(results);
      setEnrichmentSelected(Object.fromEntries(results.map(item => [item.merchant_id, Object.fromEntries(item.suggestions.map(suggestion => [suggestion.field, true]))])));
      setEnrichmentOpen(true);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || 'AI 补充建议生成失败');
    } finally {
      setEnrichmentLoading(false);
    }
  };

  const applyEnrichment = async () => {
    const items = enrichmentResults.map(result => ({
      merchant_id: result.merchant_id,
      suggestions: result.suggestions.filter(suggestion => enrichmentSelected[result.merchant_id]?.[suggestion.field]),
    })).filter(item => item.suggestions.length);
    if (!items.length) {
      toast.error('请至少勾选一项有来源的补充资料');
      return;
    }
    setApplyingEnrichment(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/merchant-pool/enrichment/apply', method: 'POST', data: { items } });
      toast.success(`已写入 ${response.data?.applied_count || 0} 项空白资料，跳过 ${response.data?.skipped_count || 0} 项`);
      setEnrichmentOpen(false);
      setSelectedMerchantIds([]);
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '补充资料确认失败');
    } finally {
      setApplyingEnrichment(false);
    }
  };

  const toggleMerchantSelection = (merchantId: number, checked?: boolean) => {
    setSelectedMerchantIds(current => {
      const selected = current.includes(merchantId);
      if (checked === true || (checked === undefined && !selected)) return [...current, merchantId];
      return current.filter(id => id !== merchantId);
    });
  };

  const toggleCurrentPageSelection = (checked: boolean) => {
    const selectableIds = items.filter(item => !['converted', 'archived'].includes(item.pool_status)).map(item => item.id);
    setSelectedMerchantIds(current => checked
      ? Array.from(new Set([...current, ...selectableIds]))
      : current.filter(id => !selectableIds.includes(id)));
  };

  const assignSelectedMerchants = async () => {
    if (!selectedMerchantIds.length) return;
    if (!selectedSalesId) { toast.error('请先选择要分配的电话销售'); return; }
    const assignee = assignees.find(item => item.id === Number(selectedSalesId));
    if (!window.confirm(`确认将选中的 ${selectedMerchantIds.length} 条商家转入电话销售线索库，并分配给「${assignee?.name || '该销售'}」？`)) return;
    setBulkAssigning(true);
    try {
      const result = await invokeWithAuth({
        url: '/api/v1/merchant-pool/bulk-convert-to-lead', method: 'POST',
        data: { merchant_ids: selectedMerchantIds, assigned_sales_id: Number(selectedSalesId) },
      });
      toast.success(`已将 ${result.data?.converted_count || selectedMerchantIds.length} 条商家分配给 ${result.data?.assigned_sales_name || assignee?.name}`);
      setSelectedMerchantIds([]);
      setSelectedSalesId('');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '批量分配失败');
    } finally {
      setBulkAssigning(false);
    }
  };

  const updateSelectedIndustry = async () => {
    if (!selectedMerchantIds.length) return;
    if (!bulkIndustry.trim()) { toast.error('请先选择或填写行业'); return; }
    if (!window.confirm(`确认将选中的 ${selectedMerchantIds.length} 条商家行业统一设置为“${bulkIndustry.trim()}”？`)) return;
    setBulkUpdating(true);
    try {
      const result = await invokeWithAuth({
        url: '/api/v1/merchant-pool/bulk-update-industry', method: 'POST',
        data: { merchant_ids: selectedMerchantIds, industry: bulkIndustry.trim() },
      });
      toast.success(`已更新 ${result.data?.updated_count || selectedMerchantIds.length} 条商家的行业`);
      setSelectedMerchantIds([]);
      setBulkIndustry('');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '批量设置行业失败');
    } finally {
      setBulkUpdating(false);
    }
  };

  const deleteSelectedMerchants = async () => {
    if (!isAdmin || !selectedMerchantIds.length) return;
    if (!window.confirm(`确认永久删除选中的 ${selectedMerchantIds.length} 条商家池记录？已转入电话销售线索的记录不会被删除。`)) return;
    setBulkUpdating(true);
    try {
      const result = await invokeWithAuth({
        url: '/api/v1/merchant-pool/bulk-delete', method: 'POST',
        data: { merchant_ids: selectedMerchantIds },
      });
      toast.success(`已删除 ${result.data?.deleted_count || selectedMerchantIds.length} 条商家记录`);
      setSelectedMerchantIds([]);
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '批量删除失败');
    } finally {
      setBulkUpdating(false);
    }
  };

  const archiveMerchant = async (merchant: Merchant) => {
    if (!window.confirm(`确认将「${merchant.business_name}」归档？归档后默认列表不会显示，但可在“已归档”筛选中查看。`)) return;
    try {
      await invokeWithAuth({ url: `/api/v1/merchant-pool/${merchant.id}/archive`, method: 'POST', data: {} });
      toast.success('已归档该商家记录');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '归档失败');
    }
  };

  const deleteMerchant = async (merchant: Merchant) => {
    if (!window.confirm(`确认永久删除「${merchant.business_name}」？此操作只删除待清洗商家池记录，不会影响正式客户。`)) return;
    try {
      await invokeWithAuth({ url: `/api/v1/merchant-pool/${merchant.id}`, method: 'DELETE' });
      toast.success('已删除该商家记录');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '删除失败');
    }
  };

  return (
    <div className="merchant-pool-page app-page space-y-5">
      <section className="merchant-hero relative overflow-hidden rounded-[24px] border border-slate-200/80 bg-white px-5 py-5 shadow-[0_20px_55px_-38px_rgba(15,23,42,0.45)] sm:px-7 sm:py-7">
        <div className="pointer-events-none absolute -right-20 -top-28 h-64 w-64 rounded-full bg-blue-100/70 blur-3xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-semibold tracking-wide text-blue-700"><Database className="h-3.5 w-3.5" /> 售前数据缓冲区</div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-950 sm:text-[32px]">待清洗商家池</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">先导入，再清洗，最后分配。原始商家会在这里完成去重、正式客户比对和无效数据隔离，不会污染正式客户库。</p>
          </div>
          {!isMobile && <Button className="h-11 rounded-xl bg-slate-950 px-5 shadow-lg shadow-slate-900/15 hover:bg-blue-700" onClick={() => setImportOpen(true)}><Upload className="mr-2 h-4 w-4" />导入商家数据</Button>}
        </div>
      </section>

      <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm leading-6 text-blue-900 md:hidden">
        手机端用于补充单条资料和加入待分配列表。批量导入、永久删除与批量资料管理请使用电脑端完成。
      </div>

      <div className="merchant-kpi-grid grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: '全部采集记录', value: stats.total, tone: 'text-slate-950', dot: 'bg-slate-900' },
          { label: '待清洗可用', value: stats.pending, tone: 'text-blue-700', dot: 'bg-blue-500' },
          { label: '自动隔离', value: stats.isolated, tone: 'text-amber-700', dot: 'bg-amber-500' },
          { label: '重复记录', value: stats.duplicates, tone: 'text-orange-700', dot: 'bg-orange-500' },
          { label: '已转电话线索', value: stats.converted, tone: 'text-emerald-700', dot: 'bg-emerald-500' },
          { label: '已归档', value: stats.archived, tone: 'text-slate-500', dot: 'bg-slate-400' },
        ].map(item => <Card key={item.label} className="merchant-kpi-card overflow-hidden border-slate-200/80 bg-white"><CardContent className="p-4"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${item.dot}`} /><p className="text-xs font-medium leading-4 text-slate-500">{item.label}</p></div><p className={`mt-3 text-2xl font-bold tracking-tight sm:text-3xl ${item.tone}`}>{item.value}</p></CardContent></Card>)}
      </div>

      <Card className="merchant-filter-card border-slate-200/80 bg-white"><CardContent className="space-y-4 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100"><Filter className="h-4 w-4" /></span>精准筛选</div><p className="mt-1 pl-10 text-xs text-slate-500">快速定位可分配、待补充或异常商家</p></div>{(search || poolStatus || regions.length > 0 || industry || source) && <Button variant="ghost" size="sm" className="text-slate-500" onClick={() => { setSearch(''); setPoolStatus(''); setRegions([]); setIndustry(''); setSource(''); setPage(1); }}>清空筛选</Button>}</div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="商家、电话或网站" /></div>
          <NativeSelect value={poolStatus} onChange={setPoolStatus} options={[{ value: '', label: '全部清洗状态' }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))]} />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 w-full justify-between bg-white px-3 font-normal">
                <span className="truncate">{regions.length ? regions.join(' / ') : '州/省（可多选）'}</span>
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-72 w-64 overflow-y-auto">
              {usStateOptions.map(state => <DropdownMenuCheckboxItem key={state} checked={regions.includes(state)} onCheckedChange={checked => { setRegions(previous => checked ? (previous.includes(state) ? previous : [...previous, state]) : previous.filter(item => item !== state)); setPage(1); }} onSelect={event => event.preventDefault()}>{state}</DropdownMenuCheckboxItem>)}
            </DropdownMenuContent>
          </DropdownMenu>
          <Input value={industry} onChange={event => { setIndustry(event.target.value); setPage(1); }} placeholder="行业" />
          <NativeSelect value={source} onChange={value => { setSource(value); setPage(1); }} options={sourceOptions} />
        </div>
      </CardContent></Card>

      {canManagePool && selectedMerchantIds.length > 0 && (
        <Card className="border-indigo-200 bg-indigo-50/60 shadow-sm">
          <CardContent className="flex flex-col gap-3 p-4">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><CheckSquare className="h-5 w-5 text-indigo-600" />已加入 {selectedMerchantIds.length} 条待分配商家</div>
              <p className="text-xs text-indigo-700">选择负责人后，系统才会转入电话销售线索库。</p>
            </div>
            {isMobile ? <div className="flex flex-col gap-2">
              <NativeSelect value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售负责人' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />
              <div className="grid grid-cols-2 gap-2">
                <Button className="h-11" disabled={bulkAssigning || !selectedSalesId} onClick={() => void assignSelectedMerchants()}><Send className="mr-1.5 h-4 w-4" />{bulkAssigning ? '分配中...' : '确认分配'}</Button>
                <Button className="h-11" variant="outline" disabled={bulkAssigning} onClick={() => { setSelectedMerchantIds([]); setSelectedSalesId(''); }}>取消选择</Button>
              </div>
            </div> : <div className="flex flex-col gap-2 md:flex-row md:flex-wrap lg:justify-end">
              <NativeSelect className="md:w-52" value={bulkIndustry} onChange={setBulkIndustry} options={[{ value: '', label: '选择统一行业' }, ...industryOptions.map(value => ({ value, label: value }))]} />
              <Input className="md:w-52" value={bulkIndustry && !industryOptions.includes(bulkIndustry) ? bulkIndustry : ''} onChange={event => setBulkIndustry(event.target.value)} placeholder="或输入自定义行业" />
              <Button disabled={bulkUpdating || !bulkIndustry.trim()} onClick={() => void updateSelectedIndustry()}>{bulkUpdating ? '更新中...' : '批量设置行业'}</Button>
              <Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading || selectedMerchantIds.length > 20} onClick={() => void suggestEnrichment()}><Sparkles className="mr-2 h-4 w-4" />{enrichmentLoading ? '分析中...' : 'AI 补充空白资料'}</Button>
              <NativeSelect className="md:w-52" value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售人员' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />
              <Button disabled={bulkAssigning || bulkUpdating || !selectedSalesId} onClick={() => void assignSelectedMerchants()}><Send className="mr-2 h-4 w-4" />{bulkAssigning ? '分配中...' : '批量转线索并分配'}</Button>
              {isAdmin && <Button variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" disabled={bulkUpdating || bulkAssigning} onClick={() => void deleteSelectedMerchants()}><Trash2 className="mr-2 h-4 w-4" />批量删除</Button>}
              <Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading} onClick={() => { setSelectedMerchantIds([]); setBulkIndustry(''); setSelectedSalesId(''); }}>取消选择</Button>
            </div>}
          </CardContent>
        </Card>
      )}

      <Card className="merchant-results-card overflow-hidden border-slate-200/80 bg-white"><CardContent className="p-0"><div className="flex items-center justify-between border-b border-slate-200/80 bg-white px-4 py-4"><div><p className="text-sm font-semibold text-slate-900">商家数据结果</p><p className="mt-0.5 text-xs text-slate-500">共 {total} 条记录，确认后再加入销售分配</p></div><Badge className="bg-slate-100 text-slate-600">第 {page}/{totalPages} 页</Badge></div>
      {isMobile ? <div data-testid="merchant-pool-mobile-list" className="divide-y divide-slate-100">
        {loading ? <p className="px-4 py-12 text-center text-sm text-slate-400">正在加载商家池...</p>
          : items.length === 0 ? <p className="px-4 py-12 text-center text-sm text-slate-400">暂无商家记录</p>
          : items.map(merchant => {
            const selected = selectedMerchantIds.includes(merchant.id);
            const canQueue = canManagePool && merchant.pool_status === 'pending';
            return (
              <article key={merchant.id} data-testid="merchant-mobile-card" className={selected ? 'bg-indigo-50/70 p-4' : 'bg-white p-4'}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-words font-semibold leading-6 text-slate-950">{merchant.business_name}</p>
                    <p className="mt-0.5 text-xs text-slate-500">{merchant.contact_name || '未填写联系人'} · #{merchant.id}</p>
                  </div>
                  <Badge className={`shrink-0 ${statusClasses[merchant.pool_status] || 'bg-slate-100 text-slate-700'}`}>{statusLabels[merchant.pool_status] || merchant.pool_status}</Badge>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <div><dt className="text-xs text-slate-400">电话</dt><dd className={merchant.phone ? 'mt-0.5 break-words font-medium text-slate-800' : 'mt-0.5 text-rose-600'}>{merchant.phone ? formatPhone(merchant.phone) : '无电话'}</dd></div>
                  <div><dt className="text-xs text-slate-400">商家位置</dt><dd className="mt-0.5 break-words text-slate-700">{merchant.address || '-'}</dd></div>
                  <div><dt className="text-xs text-slate-400">地区</dt><dd className="mt-0.5 break-words text-slate-700">{formatRegion(merchant)}</dd></div>
                  <div><dt className="text-xs text-slate-400">来源</dt><dd className="mt-0.5 break-words text-slate-700">{merchant.data_source || '-'}</dd></div>
                </dl>
                <div className="mt-4 flex gap-2">
                  {canQueue ? (
                    <Button className="h-11 flex-1" variant={selected ? 'outline' : 'default'} onClick={() => toggleMerchantSelection(merchant.id, !selected)}>
                      <Send className="mr-1.5 h-4 w-4" />{selected ? '移出待分配' : '加入待分配'}
                    </Button>
                  ) : (
                    <Button className="h-11 flex-1" variant="outline" onClick={() => openEdit(merchant)}>补充资料</Button>
                  )}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild><Button className="h-11 w-11 shrink-0 p-0" variant="outline" aria-label={`更多商家操作：${merchant.business_name}`}><MoreHorizontal className="h-5 w-5" /></Button></DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-48">
                      {canQueue && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(merchant)}>补充资料</DropdownMenuItem>}
                      {isAdmin && merchant.pool_status !== 'converted' && merchant.pool_status !== 'archived' && <DropdownMenuItem className="min-h-11" onSelect={() => { void archiveMerchant(merchant); }}><Archive className="mr-2 h-4 w-4" />归档记录</DropdownMenuItem>}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </article>
            );
          })}
      </div> : <div data-testid="merchant-pool-desktop-table" className="merchant-pool-table overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead className="sticky top-0 z-10 border-b bg-slate-50/95 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 backdrop-blur"><tr>{canManagePool && <th className="w-12 px-4 py-3"><input aria-label="选择本页可操作商家" type="checkbox" checked={items.filter(item => !['converted', 'archived'].includes(item.pool_status)).length > 0 && items.filter(item => !['converted', 'archived'].includes(item.pool_status)).every(item => selectedMerchantIds.includes(item.id))} onChange={event => toggleCurrentPageSelection(event.target.checked)} /></th>}<th className="px-4 py-3">商家名称</th><th className="px-4 py-3">商家电话</th><th className="px-4 py-3">商家位置</th><th className="px-4 py-3">地区</th><th className="px-4 py-3">来源</th><th className="px-4 py-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-slate-100">
        {loading ? <tr><td colSpan={canManagePool ? 7 : 6} className="py-12 text-center text-slate-400">正在加载商家池...</td></tr>
          : items.length === 0 ? <tr><td colSpan={canManagePool ? 7 : 6} className="py-12 text-center text-slate-400">暂无商家记录</td></tr>
          : items.map(merchant => <tr key={merchant.id} className={selectedMerchantIds.includes(merchant.id) ? 'bg-indigo-50/60' : 'hover:bg-slate-50/70'}>{canManagePool && <td className="px-4 py-3"><input aria-label={`选择 ${merchant.business_name}`} type="checkbox" disabled={['converted', 'archived'].includes(merchant.pool_status)} checked={selectedMerchantIds.includes(merchant.id)} onChange={event => toggleMerchantSelection(merchant.id, event.target.checked)} /></td>}<td className="px-4 py-3"><p className="font-semibold text-slate-900">{merchant.business_name}</p><div className="mt-1 flex flex-wrap items-center gap-1.5"><Badge className={statusClasses[merchant.pool_status] || 'bg-slate-100 text-slate-700'}>{statusLabels[merchant.pool_status] || merchant.pool_status}</Badge><span className="text-xs text-slate-400">#{merchant.id}</span></div></td><td className="whitespace-nowrap px-4 py-3 tabular-nums">{merchant.phone ? formatPhone(merchant.phone) : <span className="text-rose-600">无电话</span>}</td><td className="px-4 py-3"><p className="max-w-72 break-words text-slate-700" title={merchant.address}>{merchant.address || '-'}</p></td><td className="whitespace-nowrap px-4 py-3 text-slate-600">{formatRegion(merchant)}</td><td className="px-4 py-3 font-medium text-slate-700">{merchant.data_source || '-'}</td><td className="px-4 py-3"><div className="flex flex-wrap justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => openEdit(merchant)}>补充资料</Button>{merchant.pool_status === 'pending' && <Button size="sm" onClick={() => toggleMerchantSelection(merchant.id, true)}><Send className="mr-1 h-3.5 w-3.5" />加入分配</Button>}{isAdmin && merchant.pool_status !== 'converted' && merchant.pool_status !== 'archived' && <Button size="sm" variant="outline" onClick={() => archiveMerchant(merchant)}><Archive className="mr-1 h-3.5 w-3.5" />归档</Button>}{isAdmin && merchant.pool_status !== 'converted' && <Button size="sm" variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" onClick={() => deleteMerchant(merchant)}><Trash2 className="mr-1 h-3.5 w-3.5" />删除</Button>}</div></td></tr>)}
      </tbody></table></div>}<div className="flex flex-col gap-3 border-t bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-slate-500">共 {total} 条，第 {page}/{totalPages} 页</p><div className="flex items-center gap-2"><NativeSelect className="w-24" value={String(pageSize)} onChange={value => { setPageSize(Number(value)); setPage(1); }} options={[20, 50, 100].map(value => ({ value: String(value), label: `${value}条` }))} /><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</Button></div></div></CardContent></Card>

      {!isMobile && <Dialog open={importOpen} onOpenChange={setImportOpen}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>按固定模板导入商家</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-950"><p className="font-semibold">只接受固定五列表格</p><p className="mt-1 text-indigo-800">第一行必须依次为：商家名称、商家电话、商家位置、地区、来源。缺列、多列、改名或调整顺序都会停止导入并明确提示。</p></div><div className="grid grid-cols-5 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-center text-xs font-medium text-slate-700">{importTemplateHeaders.map((header, index) => <div key={header} className={index ? 'border-l px-2 py-3' : 'px-2 py-3'}>{index + 1}. {header}</div>)}</div><div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-medium text-slate-900">先下载模板，再填写并上传</p><p className="mt-1 text-xs leading-5 text-slate-500">“商家位置”填写完整街道地址；“地区”建议填写“城市, 州/省, 国家”；“来源”填写 Google Maps、名单采购或实际采集渠道。</p><div className="mt-4 flex flex-wrap gap-2"><Button variant="outline" onClick={downloadImportTemplate}><Download className="mr-2 h-4 w-4" />下载固定模板</Button><input ref={fileRef} className="hidden" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={importCsv} /><Button disabled={importing} onClick={() => fileRef.current?.click()}><FileUp className="mr-2 h-4 w-4" />{importing ? '正在校验并导入...' : '选择填写好的文件'}</Button></div></div><div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">上传后仍会自动隔离无电话、正式客户重复或商家池重复的数据，不会直接进入电话销售线索库。</div></div></DialogContent></Dialog>}

      {!isMobile && <Dialog open={enrichmentOpen} onOpenChange={setEnrichmentOpen}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>AI 补充空白资料 · 人工确认</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900"><p className="font-medium">安全补充规则</p><p className="mt-1 text-indigo-800">只使用原始导入资料中已有、但尚未写入标准字段的内容；不会覆盖已填写资料，也不会根据商家名称猜测。Google/Yelp 外部检索尚未接入，找不到来源的字段显示为“信息不足”。</p></div>{enrichmentResults.map(result => <Card key={result.merchant_id} className="border-slate-200"><CardContent className="space-y-3 p-4"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><p className="font-semibold text-slate-900">{result.business_name}</p><Badge className={result.status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'}>{result.status === 'needs_review' ? '有待确认建议' : '信息不足'}</Badge></div><p className="text-xs text-slate-500">原始资料时间：{formatDate(result.source_updated_at || undefined)}</p></div>{result.warning && <p className="rounded-lg bg-amber-50 p-2 text-xs leading-5 text-amber-900">{result.warning}</p>}{result.suggestions.length ? <div className="grid gap-2 md:grid-cols-2">{result.suggestions.map(suggestion => <label key={`${result.merchant_id}-${suggestion.field}`} className="flex cursor-pointer items-start gap-2 rounded-lg border bg-white p-3"><input type="checkbox" checked={Boolean(enrichmentSelected[result.merchant_id]?.[suggestion.field])} onChange={event => setEnrichmentSelected(previous => ({ ...previous, [result.merchant_id]: { ...previous[result.merchant_id], [suggestion.field]: event.target.checked } }))} /><span className="min-w-0 text-sm"><span className="font-medium text-slate-800">{suggestion.field}</span><span className="block break-words text-slate-700">{String(suggestion.value)}</span><span className="block text-xs text-slate-500">来源：{suggestion.source_label} · 可信度：{Math.round(suggestion.confidence * 100)}%</span></span></label>)}</div> : <div className="rounded-lg border border-dashed p-3 text-sm text-slate-500">信息不足：原始导入资料中没有可追溯的空白字段补充内容。</div>}{result.missing_fields.length > 0 && <p className="text-xs text-slate-500">仍缺少：{result.missing_fields.join('、')}</p>}</CardContent></Card>)}<div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setEnrichmentOpen(false)}>取消</Button><Button disabled={applyingEnrichment} onClick={() => void applyEnrichment()}>{applyingEnrichment ? '写入中...' : '确认写入已勾选资料'}</Button></div></div></DialogContent></Dialog>}

      <Dialog open={!!editing} onOpenChange={open => !open && setEditing(null)}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>补充商家资料并重新清洗</DialogTitle></DialogHeader><div className="grid gap-4 sm:grid-cols-2"><div><Label>商家名称 *</Label><Input value={editForm.business_name} onChange={event => setEditForm({ ...editForm, business_name: event.target.value })} /></div><div><Label>电话</Label><Input value={editForm.phone} onChange={event => setEditForm({ ...editForm, phone: event.target.value })} /></div><div><Label>联系人</Label><Input value={editForm.contact_name} onChange={event => setEditForm({ ...editForm, contact_name: event.target.value })} /></div><div><Label>行业</Label><Input value={editForm.industry} onChange={event => setEditForm({ ...editForm, industry: event.target.value })} /></div><div><Label>国家</Label><Input value={editForm.country} onChange={event => setEditForm({ ...editForm, country: event.target.value })} /></div><div><Label>州/省</Label><Input value={editForm.state} onChange={event => setEditForm({ ...editForm, state: event.target.value })} /></div><div><Label>城市</Label><Input value={editForm.city} onChange={event => setEditForm({ ...editForm, city: event.target.value })} /></div><div className="sm:col-span-2"><Label>地址</Label><Input value={editForm.address} onChange={event => setEditForm({ ...editForm, address: event.target.value })} /></div><div className="sm:col-span-2"><Label>官网</Label><Input value={editForm.website} onChange={event => setEditForm({ ...editForm, website: event.target.value })} /></div></div><div className="mt-5 flex justify-end gap-2 border-t pt-4"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveEdit}><RefreshCw className="mr-2 h-4 w-4" />保存并重新清洗</Button></div></DialogContent></Dialog>
    </div>
  );
}
