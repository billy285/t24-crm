import SalesLeadDossier from '@/components/SalesLeadDossier';
import { useEffect, useRef, useState } from 'react';
import { Archive, ArrowUpRight, CheckSquare, ChevronDown, Filter, MoreHorizontal, RefreshCw, Search, Send, Sparkles, Trash2, Upload, X } from 'lucide-react';
import { toast } from 'sonner';

import '@/components/sales-center.css';
import './sales-workspace.css';
import './merchant-pool.css';
import './merchant-pool-refined.css';
import MerchantImportDialog from '@/components/MerchantImportDialog';
import { formatPhoneNumber } from '@/lib/phone-format';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { invokeWithAuth } from '@/lib/tokenStore';
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
  pending: '未分配', no_phone: '电话待补齐', duplicate: '重复隔离',
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
  business_name: '', contact_name: '', phone: '', industry: '', country: '', state: '', city: '', address: '', website: '', rating: '', business_status: '',
  google_business_url: '', google_rating: '', google_review_count: '', yelp_url: '', yelp_rating: '', yelp_review_count: '',
  social_profiles: '', recent_negative_reviews: '', content_update_summary: '', content_last_updated_at: '',
};


function formatDate(value?: string) {
  return value ? value.slice(0, 16).replace('T', ' ') : '-';
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
  const [dossierId, setDossierId] = useState<number | null>(null);
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
  const previousSearchRef = useRef(search);
  const [poolStatus, setPoolStatus] = useState('pending');
  const [reviewing, setReviewing] = useState<Merchant | null>(null);
  const [regions, setRegions] = useState<string[]>([]);
  const [industry, setIndustry] = useState('');
  const [source, setSource] = useState('');
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<Merchant | null>(null);
  const [editForm, setEditForm] = useState(emptyEdit);
  const [enrichmentOpen, setEnrichmentOpen] = useState(false);
  const [enrichmentLoading, setEnrichmentLoading] = useState(false);
  const [enrichmentResults, setEnrichmentResults] = useState<EnrichmentResult[]>([]);
  const [enrichmentSelected, setEnrichmentSelected] = useState<Record<number, Record<string, boolean>>>({});
  const [applyingEnrichment, setApplyingEnrichment] = useState(false);
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
    if (!loading && page > totalPages) setPage(totalPages);
  }, [loading, page, totalPages]);

  useEffect(() => {
    if (!reviewing || loading) return;
    const current = items.find(item => item.id === reviewing.id);
    if (current !== reviewing) setReviewing(current || null);
  }, [items, loading, reviewing]);

  useEffect(() => {
    if (previousSearchRef.current === search) return;
    previousSearchRef.current = search;
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

  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !importOpen && !editing && !reviewing });

  const openEdit = (merchant: Merchant) => {
    setReviewing(null);
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

  const viewTitle = poolStatus === 'pending' ? '未分配商家' : poolStatus === 'converted' ? '已转销售线索' : poolStatus ? statusLabels[poolStatus] : '全部采集记录';
  const showStatusColumn = poolStatus !== 'pending';
  const tableColumnCount = (canManagePool ? 4 : 3) + Number(showStatusColumn);
  const extraFilterCount = Number(regions.length > 0) + Number(Boolean(industry)) + Number(Boolean(source)) + Number(Boolean(poolStatus && !['pending', 'converted'].includes(poolStatus)));
  const changeView = (status: string) => {
    setPoolStatus(status);
    setSelectedMerchantIds([]);
    setSelectedSalesId('');
    setReviewing(null);
    setPage(1);
  };
  const sourceLabel = (merchant: Merchant) => sourceOptions.find(option => option.value === merchant.data_source)?.label || merchant.data_source || '未记录';
  const merchantMenu = (merchant: Merchant) => isAdmin && merchant.pool_status !== 'converted' && !(isMobile && merchant.pool_status === 'archived') && (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="sm" variant="ghost" aria-label={`更多商家操作：${merchant.business_name}`}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="sales-center-menu">
        {merchant.pool_status !== 'archived' && <DropdownMenuItem onSelect={() => void archiveMerchant(merchant)}><Archive className="mr-2 h-4 w-4" />归档记录</DropdownMenuItem>}
        {!isMobile && <DropdownMenuItem className="text-rose-600" onSelect={() => void deleteMerchant(merchant)}><Trash2 className="mr-2 h-4 w-4" />永久删除</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
  );
  const merchantAction = (merchant: Merchant) => canManagePool && merchant.pool_status === 'pending' ? (
    <Button size="sm" variant="ghost" className="mp-inspect-action" aria-label={`${selectedMerchantIds.includes(merchant.id) ? '移出待分配' : '分配'}：${merchant.business_name}`} aria-pressed={selectedMerchantIds.includes(merchant.id)} onClick={() => toggleMerchantSelection(merchant.id)}>{selectedMerchantIds.includes(merchant.id) ? '已选择' : '分配'}</Button>
  ) : (
    <Button size="sm" variant="ghost" className="mp-inspect-action" aria-label={`商家详情：${merchant.business_name}`} onClick={() => setReviewing(merchant)}>详情<ArrowUpRight className="ml-1.5 h-3.5 w-3.5" /></Button>
  );
  const reviewDetails = reviewing && (
    <>
      <div className="mp-review-identity"><h3>{reviewing.business_name}</h3><p className="mp-merchant-meta">{formatRegion(reviewing)} · #{reviewing.id}</p>{reviewing.pool_status !== 'pending' && <Badge className={statusClasses[reviewing.pool_status] || 'bg-slate-100 text-slate-700'}>{statusLabels[reviewing.pool_status] || reviewing.pool_status}</Badge>}</div>
      <dl className="mp-review-fields">
        {[
          ['联系电话', reviewing.phone ? formatPhoneNumber(reviewing.phone, reviewing.country) : '无电话'],
          ['完整地址', reviewing.address || '未填写'],
          ['资料来源', sourceLabel(reviewing)],
        ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        {reviewing.isolation_reason && <div><dt>隔离原因</dt><dd>{reviewing.isolation_reason}</dd></div>}
        {reviewing.duplicate_of_id && <div><dt>重复记录</dt><dd>#{reviewing.duplicate_of_id}</dd></div>}
        {reviewing.existing_customer_id && <div><dt>关联客户</dt><dd>#{reviewing.existing_customer_id}</dd></div>}
      </dl>
      <details className="mp-review-extra"><summary>更多采集资料</summary><dl className="mp-review-fields"><div><dt>联系人</dt><dd>{reviewing.contact_name || '未填写'}</dd></div><div><dt>行业</dt><dd>{reviewing.industry || '未填写'}</dd></div><div><dt>采集时间</dt><dd>{formatDate(reviewing.collected_at)}</dd></div>{reviewing.website && <div><dt>商家网站</dt><dd>{/^https?:\/\//i.test(reviewing.website) ? <a href={reviewing.website} target="_blank" rel="noopener noreferrer">{reviewing.website}</a> : reviewing.website}</dd></div>}</dl></details>
      <div className="mp-review-actions">
        {canManagePool && !['converted', 'archived'].includes(reviewing.pool_status) && <Button variant="outline" onClick={() => openEdit(reviewing)}>补充资料</Button>}
        {canManagePool && reviewing.pool_status === 'pending' && <Button disabled={selectedMerchantIds.includes(reviewing.id)} onClick={() => { toggleMerchantSelection(reviewing.id, true); setReviewing(null); }}>{selectedMerchantIds.includes(reviewing.id) ? '已加入待分配' : '加入待分配'}<ArrowUpRight className="ml-2 h-4 w-4" /></Button>}
        {reviewing.converted_lead_id && <Button variant="outline" onClick={() => { setDossierId(reviewing.converted_lead_id!); setReviewing(null); }}>累计档案</Button>}
      </div>
      <p className="mp-review-note">{reviewing.pool_status === 'pending' ? '选择销售负责人后即可分配。' : ['converted', 'archived'].includes(reviewing.pool_status) ? '保留原始采集记录，此处仅查看资料。' : '补齐资料并重新清洗后，符合条件的商家才可分配。'}</p>
    </>
  );

  return (
    <div className="merchant-pool-page sales-center-ui sc-directory calm-sales-page calm-merchant-page merchant-review-page merchant-pool-refined-page app-page">
      <SalesLeadDossier leadId={dossierId} onClose={() => setDossierId(null)} />
      <header className="sc-section-heading mp-page-heading">
        <h2>商家池</h2>
        {!isMobile && <Button aria-label="导入商家数据" onClick={() => setImportOpen(true)}><Upload className="mr-2 h-4 w-4" />导入商家</Button>}
      </header>

      <div className="mp-list-tools">
        <nav className="mp-work-views" aria-label="商家工作视图">
          {[{ status: 'pending', label: '未分配', count: stats.pending }, { status: 'converted', label: '已转线索', count: stats.converted }, { status: '', label: '全部记录', count: stats.total }].map(view => <button type="button" key={view.label} aria-pressed={poolStatus === view.status} onClick={() => changeView(view.status)}>{view.label}<span>{view.count}</span></button>)}
        </nav>
        <div className="mp-search-toolbar">
          <label className="mp-search-field"><Search className="h-4 w-4" /><Input aria-label="搜索商家" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="搜索商家、电话或网站" /></label>
          <Button variant="outline" aria-expanded={filtersExpanded} aria-controls="merchant-pool-extra-filters" onClick={() => setFiltersExpanded(current => !current)}><Filter className="mr-2 h-4 w-4" />更多筛选{extraFilterCount ? ` · ${extraFilterCount}` : ''}</Button>
          {(search || regions.length > 0 || industry || source || (poolStatus && !['pending', 'converted'].includes(poolStatus))) && <Button variant="ghost" onClick={() => { setSearch(''); setRegions([]); setIndustry(''); setSource(''); if (!['pending', 'converted', ''].includes(poolStatus)) changeView('pending'); setPage(1); }}>清空筛选</Button>}
        </div>
      </div>
      {filtersExpanded && <div id="merchant-pool-extra-filters" className="mp-expanded-filters">
        <label><span className="sc-filter-label">记录状态</span><NativeSelect value={poolStatus} onChange={changeView} options={[{ value: '', label: '全部状态' }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))]} /></label>
        <div><span className="sc-filter-label">州 / 省</span><DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" className="w-full justify-between font-normal"><span className="truncate">{regions.length ? regions.join(' / ') : '州/省（可多选）'}</span><ChevronDown className="h-4 w-4 shrink-0" /></Button></DropdownMenuTrigger><DropdownMenuContent align="start" className="max-h-72 w-64 overflow-y-auto">{usStateOptions.map(state => <DropdownMenuCheckboxItem key={state} checked={regions.includes(state)} onCheckedChange={checked => { setRegions(previous => checked ? (previous.includes(state) ? previous : [...previous, state]) : previous.filter(item => item !== state)); setPage(1); }} onSelect={event => event.preventDefault()}>{state}</DropdownMenuCheckboxItem>)}</DropdownMenuContent></DropdownMenu></div>
        <label><span className="sc-filter-label">行业</span><Input value={industry} onChange={event => { setIndustry(event.target.value); setPage(1); }} placeholder="全部行业" /></label>
        <label><span className="sc-filter-label">资料来源</span><NativeSelect value={source} onChange={value => { setSource(value); setPage(1); }} options={sourceOptions} /></label>
        <p className="mp-filter-summary">自动隔离 {stats.isolated} · 其中重复 {stats.duplicates} · 已归档 {stats.archived}<span>归档记录可通过记录状态单独查看。</span></p>
      </div>}

      {canManagePool && selectedMerchantIds.length > 0 && (
        <Card className="mp-selection-bar" role="region" aria-label="商家批量操作">
          <CardContent className="flex flex-col gap-3 p-4">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><CheckSquare className="h-5 w-5 text-indigo-600" />已选择 {selectedMerchantIds.length} 家商家</div>
              <Button variant="ghost" size="sm" onClick={() => setReviewing(items.find(item => selectedMerchantIds.includes(item.id)) || null)}>查看所选资料</Button>
            </div>
            {isMobile ? <div className="flex flex-col gap-2">
              <label><span className="sr-only">选择销售负责人</span><NativeSelect value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售负责人' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /></label>
              <div className="grid grid-cols-2 gap-2">
                <Button className="h-11" disabled={bulkAssigning || !selectedSalesId} onClick={() => void assignSelectedMerchants()}><Send className="mr-1.5 h-4 w-4" />{bulkAssigning ? '分配中...' : '确认分配'}</Button>
                <Button className="h-11" variant="outline" disabled={bulkAssigning} onClick={() => { setSelectedMerchantIds([]); setSelectedSalesId(''); }}>取消选择</Button>
              </div>
            </div> : <div className="flex flex-col gap-2 md:flex-row md:flex-wrap lg:justify-end">
              <details className="calm-pool-bulk-tools"><summary>资料维护与删除<ChevronDown className="h-4 w-4" /></summary><div className="calm-pool-bulk-content">
              <NativeSelect className="md:w-52" value={bulkIndustry} onChange={setBulkIndustry} options={[{ value: '', label: '选择统一行业' }, ...industryOptions.map(value => ({ value, label: value }))]} />
              <Input className="md:w-52" value={bulkIndustry && !industryOptions.includes(bulkIndustry) ? bulkIndustry : ''} onChange={event => setBulkIndustry(event.target.value)} placeholder="或输入自定义行业" />
              <Button disabled={bulkUpdating || !bulkIndustry.trim()} onClick={() => void updateSelectedIndustry()}>{bulkUpdating ? '更新中...' : '批量设置行业'}</Button>
              <Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading || selectedMerchantIds.length > 20} onClick={() => void suggestEnrichment()}><Sparkles className="mr-2 h-4 w-4" />{enrichmentLoading ? '分析中...' : 'AI 补充空白资料'}</Button>
              {isAdmin && <Button variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" disabled={bulkUpdating || bulkAssigning} onClick={() => void deleteSelectedMerchants()}><Trash2 className="mr-2 h-4 w-4" />批量删除</Button>}
              </div></details>
              <label><span className="sr-only">选择销售负责人</span><NativeSelect className="md:w-52" value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售负责人' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /></label>
              <Button disabled={bulkAssigning || bulkUpdating || !selectedSalesId} onClick={() => void assignSelectedMerchants()}><Send className="mr-2 h-4 w-4" />{bulkAssigning ? '分配中...' : '确认分配'}</Button>
              <Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading} onClick={() => { setSelectedMerchantIds([]); setBulkIndustry(''); setSelectedSalesId(''); }}>取消选择</Button>
            </div>}
          </CardContent>
        </Card>
      )}

      <div className={`mp-workspace${reviewing && !isMobile ? ' has-review' : ''}`}>
        <Card className="merchant-results-card sc-table-card overflow-hidden border-slate-200/80 bg-white"><CardContent className="p-0">
          {poolStatus && !['pending', 'converted'].includes(poolStatus) && <div className="mp-active-status">当前筛选：{viewTitle}</div>}
          {isMobile ? <div data-testid="merchant-pool-mobile-list" aria-label={viewTitle} className="divide-y divide-slate-100">
            {loading ? <p className="px-4 py-12 text-center text-sm text-slate-400">正在加载商家池...</p> : items.length === 0 ? <p className="px-4 py-12 text-center text-sm text-slate-400">暂无符合条件的商家</p> : items.map(merchant => <article key={merchant.id} data-testid="merchant-mobile-card" className={`mp-merchant-card${selectedMerchantIds.includes(merchant.id) ? ' is-selected' : ''}`}>
              <div className="mp-merchant-identity"><button type="button" className="mp-merchant-name" aria-label={`查看资料：${merchant.business_name}`} onClick={() => setReviewing(merchant)}>{merchant.business_name}</button><p className="mp-merchant-meta">{merchant.industry && <span>{merchant.industry} · </span>}{formatRegion(merchant)}</p></div>
              <p className="mp-card-phone">{merchant.phone ? formatPhoneNumber(merchant.phone, merchant.country) : '无电话'}</p>
              {merchant.pool_status !== 'pending' && <Badge className={`mp-pool-status ${statusClasses[merchant.pool_status] || 'bg-slate-100 text-slate-700'}`}>{statusLabels[merchant.pool_status] || merchant.pool_status}</Badge>}
              <div className="mp-row-actions">{merchantAction(merchant)}{merchantMenu(merchant)}</div>
              {selectedMerchantIds.includes(merchant.id) && <p className="mp-merchant-meta">已加入本页待分配</p>}
            </article>)}
          </div> : <div data-testid="merchant-pool-desktop-table"><table className="mp-queue-table"><caption className="sr-only">{viewTitle}</caption><thead><tr>{canManagePool && <th className="mp-select-column"><label><input aria-label="选择本页可操作商家" type="checkbox" checked={items.filter(item => !['converted', 'archived'].includes(item.pool_status)).length > 0 && items.filter(item => !['converted', 'archived'].includes(item.pool_status)).every(item => selectedMerchantIds.includes(item.id))} onChange={event => toggleCurrentPageSelection(event.target.checked)} /></label></th>}<th aria-label="商家与地区">商家</th><th className="mp-phone-column">电话</th>{showStatusColumn && <th className="mp-state-column" aria-label="当前状态">状态</th>}<th className="mp-action-column">操作</th></tr></thead><tbody>
            {loading ? <tr><td colSpan={tableColumnCount} className="py-12 text-center text-slate-400">正在加载商家池...</td></tr> : items.length === 0 ? <tr><td colSpan={tableColumnCount} className="py-12 text-center text-slate-400">暂无符合条件的商家</td></tr> : items.map(merchant => <tr key={merchant.id} className={selectedMerchantIds.includes(merchant.id) || reviewing?.id === merchant.id ? 'is-selected' : ''}>
              {canManagePool && <td className="mp-select-column"><label><input aria-label={`选择 ${merchant.business_name}`} type="checkbox" disabled={['converted', 'archived'].includes(merchant.pool_status)} checked={selectedMerchantIds.includes(merchant.id)} onChange={event => toggleMerchantSelection(merchant.id, event.target.checked)} /></label></td>}
              <td><div className="mp-merchant-identity"><button type="button" className="mp-merchant-name" aria-label={`查看资料：${merchant.business_name}`} onClick={() => setReviewing(merchant)}>{merchant.business_name}</button><p className="mp-merchant-meta">{merchant.industry && <span>{merchant.industry} · </span>}{formatRegion(merchant)}</p><p className="mp-inline-phone">{merchant.phone ? formatPhoneNumber(merchant.phone, merchant.country) : '无电话'}</p></div></td>
              <td className="mp-phone-column">{merchant.phone ? formatPhoneNumber(merchant.phone, merchant.country) : <span className="text-rose-600">无电话</span>}</td>
              {showStatusColumn && <td className="mp-state-column">{merchant.pool_status !== 'pending' && <Badge className={`mp-pool-status ${statusClasses[merchant.pool_status] || 'bg-slate-100 text-slate-700'}`}>{statusLabels[merchant.pool_status] || merchant.pool_status}</Badge>}</td>}
              <td className="mp-action-column"><div className="mp-row-actions">{merchantAction(merchant)}{merchantMenu(merchant)}</div></td>
            </tr>)}
          </tbody></table></div>}
          <div className="mp-list-pagination flex flex-col gap-3 border-t bg-white px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-slate-500">显示 {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} 条 / 共 {total} 条</p><div className="flex flex-wrap items-center gap-2"><label><span className="sr-only">每页显示</span><NativeSelect className="w-24" value={String(pageSize)} onChange={value => { setPageSize(Number(value)); setPage(1); }} options={[20, 50, 100].map(value => ({ value: String(value), label: `${value}条` }))} /></label><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span className="text-xs text-slate-500">{page}/{totalPages}</span><Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</Button></div></div>
        </CardContent></Card>
        {reviewing && !isMobile && <aside className="mp-review-panel" aria-label="商家资料"><div className="mp-review-header"><span>商家资料</span><Button variant="ghost" size="sm" aria-label="关闭资料" onClick={() => setReviewing(null)}><X className="h-4 w-4" /></Button></div>{reviewDetails}</aside>}
      </div>
      {isMobile && <Dialog open={!!reviewing} onOpenChange={open => !open && setReviewing(null)}><DialogContent className="mp-review-dialog" aria-describedby={undefined}><DialogHeader><DialogTitle>商家资料</DialogTitle></DialogHeader>{reviewDetails}</DialogContent></Dialog>}

      {!isMobile && <MerchantImportDialog open={importOpen} onOpenChange={setImportOpen} onImported={() => loadData()} />}

      {!isMobile && <Dialog open={enrichmentOpen} onOpenChange={setEnrichmentOpen}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>AI 补充空白资料 · 人工确认</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900"><p className="font-medium">安全补充规则</p><p className="mt-1 text-indigo-800">只使用原始导入资料中已有、但尚未写入标准字段的内容；不会覆盖已填写资料，也不会根据商家名称猜测。Google/Yelp 外部检索尚未接入，找不到来源的字段显示为“信息不足”。</p></div>{enrichmentResults.map(result => <Card key={result.merchant_id} className="border-slate-200"><CardContent className="space-y-3 p-4"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><p className="font-semibold text-slate-900">{result.business_name}</p><Badge className={result.status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'}>{result.status === 'needs_review' ? '有待确认建议' : '信息不足'}</Badge></div><p className="text-xs text-slate-500">原始资料时间：{formatDate(result.source_updated_at || undefined)}</p></div>{result.warning && <p className="rounded-lg bg-amber-50 p-2 text-xs leading-5 text-amber-900">{result.warning}</p>}{result.suggestions.length ? <div className="grid gap-2 md:grid-cols-2">{result.suggestions.map(suggestion => <label key={`${result.merchant_id}-${suggestion.field}`} className="flex cursor-pointer items-start gap-2 rounded-lg border bg-white p-3"><input type="checkbox" checked={Boolean(enrichmentSelected[result.merchant_id]?.[suggestion.field])} onChange={event => setEnrichmentSelected(previous => ({ ...previous, [result.merchant_id]: { ...previous[result.merchant_id], [suggestion.field]: event.target.checked } }))} /><span className="min-w-0 text-sm"><span className="font-medium text-slate-800">{suggestion.field}</span><span className="block break-words text-slate-700">{String(suggestion.value)}</span><span className="block text-xs text-slate-500">来源：{suggestion.source_label} · 可信度：{Math.round(suggestion.confidence * 100)}%</span></span></label>)}</div> : <div className="rounded-lg border border-dashed p-3 text-sm text-slate-500">信息不足：原始导入资料中没有可追溯的空白字段补充内容。</div>}{result.missing_fields.length > 0 && <p className="text-xs text-slate-500">仍缺少：{result.missing_fields.join('、')}</p>}</CardContent></Card>)}<div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setEnrichmentOpen(false)}>取消</Button><Button disabled={applyingEnrichment} onClick={() => void applyEnrichment()}>{applyingEnrichment ? '写入中...' : '确认写入已勾选资料'}</Button></div></div></DialogContent></Dialog>}

      <Dialog open={!!editing} onOpenChange={open => !open && setEditing(null)}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>补充商家资料并重新清洗</DialogTitle></DialogHeader><div className="grid gap-4 sm:grid-cols-2"><div><Label>商家名称 *</Label><Input value={editForm.business_name} onChange={event => setEditForm({ ...editForm, business_name: event.target.value })} /></div><div><Label>电话</Label><Input value={editForm.phone} onChange={event => setEditForm({ ...editForm, phone: event.target.value })} /></div><div><Label>联系人</Label><Input value={editForm.contact_name} onChange={event => setEditForm({ ...editForm, contact_name: event.target.value })} /></div><div><Label>行业</Label><Input value={editForm.industry} onChange={event => setEditForm({ ...editForm, industry: event.target.value })} /></div><div><Label>国家</Label><Input value={editForm.country} onChange={event => setEditForm({ ...editForm, country: event.target.value })} /></div><div><Label>州/省</Label><Input value={editForm.state} onChange={event => setEditForm({ ...editForm, state: event.target.value })} /></div><div><Label>城市</Label><Input value={editForm.city} onChange={event => setEditForm({ ...editForm, city: event.target.value })} /></div><div className="sm:col-span-2"><Label>地址</Label><Input value={editForm.address} onChange={event => setEditForm({ ...editForm, address: event.target.value })} /></div><div className="sm:col-span-2"><Label>官网</Label><Input value={editForm.website} onChange={event => setEditForm({ ...editForm, website: event.target.value })} /></div></div><div className="mt-5 flex justify-end gap-2 border-t pt-4"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveEdit}><RefreshCw className="mr-2 h-4 w-4" />保存并重新清洗</Button></div></DialogContent></Dialog>
    </div>
  );
}
