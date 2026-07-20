import { ChangeEvent, useEffect, useRef, useState } from 'react';
import { Archive, CheckSquare, Database, FileUp, Filter, Link2, RefreshCw, Search, Send, ShieldCheck, Sparkles, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { getToken, invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { useRole } from '@/lib/role-context';

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
type AnalysisSource = { id?: string; label: string; value?: string | number | null; updated_at?: string | null };
type AnalysisCard = { title: string; kind: 'fact' | 'recommendation' | 'insufficient'; content: string; sources: AnalysisSource[] };
type MerchantAnalysis = {
  id: number;
  analysis: { merchant_name: string; warning?: string | null; cards: AnalysisCard[] };
  ai_used: boolean;
  ai_model?: string | null;
  generated_at: string;
};
type EnrichmentSuggestion = { field: string; value: string | number; source_label: string; source_updated_at?: string | null; confidence: number };
type EnrichmentResult = { merchant_id: number; business_name: string; status: string; suggestions: EnrichmentSuggestion[]; missing_fields: string[]; warning?: string | null; source_updated_at?: string | null };

const emptyEdit = {
  business_name: '', contact_name: '', phone: '', industry: '', country: 'US', state: '', city: '', address: '', website: '', rating: '', business_status: '',
  google_business_url: '', google_rating: '', google_review_count: '', yelp_url: '', yelp_rating: '', yelp_review_count: '',
  social_profiles: '', recent_negative_reviews: '', content_update_summary: '', content_last_updated_at: '',
};

function formatDate(value?: string) {
  return value ? value.slice(0, 16).replace('T', ' ') : '-';
}

function parseBulkRows(text: string) {
  const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
  const emptyMarkers = new Set(['待核验', '暂未确认', '官网未明确显示', '未明确显示', '无', '-', 'n/a', 'na']);
  const normalizeHeader = (value?: string) => (value || '').replace(/[\s_\-()（）:：/]+/g, '').toLowerCase();
  const headerFields: Record<string, string> = {
    商家名称: 'business_name', 商户名称: 'business_name', 企业名称: 'business_name', 店铺名称: 'business_name', 名称: 'business_name', businessname: 'business_name', name: 'business_name',
    电话: 'phone', 联系电话: 'phone', 电话号码: 'phone', 手机: 'phone', phone: 'phone', phonenumber: 'phone', telephone: 'phone', tel: 'phone',
    地址: 'address', 详细地址: 'address', 营业地址: 'address', address: 'address', fulladdress: 'address',
    网站: 'website', 官网: 'website', 官网链接: 'website', 网站链接: 'website', website: 'website', url: 'website', domain: 'website',
    行业: 'industry', 类别: 'industry', 分类: 'industry', 商家类别: 'industry', industry: 'industry', category: 'industry',
    城市: 'city', city: 'city', 州: 'state', 省: 'state', 州省: 'state', state: 'state', province: 'state',
    国家: 'country', country: 'country', 公开评分: 'rating', 评分: 'rating', 星级: 'rating', rating: 'rating',
    营业状态: 'business_status', 商家状态: 'business_status', 状态: 'business_status', businessstatus: 'business_status', status: 'business_status',
  };
  const splitDelimitedRow = (line: string, delimiter: string) => {
    if (delimiter === '|') {
      return line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(value => value.trim());
    }
    const values: string[] = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (character === '"') {
        if (quoted && line[index + 1] === '"') { value += '"'; index += 1; }
        else quoted = !quoted;
      } else if (character === delimiter && !quoted) { values.push(value.trim()); value = ''; }
      else value += character;
    }
    values.push(value.trim());
    return values;
  };
  const splitRow = (line: string) => {
    const pipeCount = (line.match(/\|/g) || []).length;
    if (pipeCount >= 2) return splitDelimitedRow(line, '|');
    if (line.includes('\t')) return splitDelimitedRow(line, '\t');
    return splitDelimitedRow(line, ',');
  };
  const rows = lines.map(splitRow).filter(values => values.length && !values.every(value => /^:?-{3,}:?$/.test(value.replace(/\s/g, ''))));
  const firstRow = rows[0] || [];
  const mappedHeaders = firstRow.map(value => headerFields[normalizeHeader(value)] || '');
  const hasHeader = mappedHeaders.includes('business_name');
  const dataRows = hasHeader ? rows.slice(1) : rows;
  return dataRows.map((values) => {
    const getByHeader = (field: string) => {
      const index = mappedHeaders.indexOf(field);
      return index >= 0 ? values[index] : undefined;
    };
    const [business_name, phone, address, website, industry, city, state, country, rating, business_status] = values;
    const normalizeOptional = (value?: string) => value && !emptyMarkers.has(value.trim().toLowerCase()) ? value : null;
    const rowBusinessName = hasHeader ? getByHeader('business_name') : business_name;
    const normalizedRating = normalizeOptional(hasHeader ? getByHeader('rating') : rating);
    return {
      business_name: rowBusinessName,
      phone: normalizeOptional(hasHeader ? getByHeader('phone') : phone),
      address: normalizeOptional(hasHeader ? getByHeader('address') : address),
      website: normalizeOptional(hasHeader ? getByHeader('website') : website),
      industry: normalizeOptional(hasHeader ? getByHeader('industry') : industry),
      city: normalizeOptional(hasHeader ? getByHeader('city') : city),
      state: normalizeOptional(hasHeader ? getByHeader('state') : state),
      country: normalizeOptional(hasHeader ? getByHeader('country') : country),
      rating: normalizedRating && !Number.isNaN(Number(normalizedRating)) ? Number(normalizedRating) : null,
      business_status: normalizeOptional(hasHeader ? getByHeader('business_status') : business_status),
    };
  }).filter((record: any) => record.business_name);
}

export default function MerchantPool() {
  const { isAdmin, role } = useRole();
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
  const [region, setRegion] = useState('');
  const [industry, setIndustry] = useState('');
  const [source, setSource] = useState('');
  const [ratingMin, setRatingMin] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [importMode, setImportMode] = useState<'csv' | 'bulk'>('csv');
  const [bulkText, setBulkText] = useState('');
  const [importing, setImporting] = useState(false);
  const [editing, setEditing] = useState<Merchant | null>(null);
  const [editForm, setEditForm] = useState(emptyEdit);
  const [analysisMerchant, setAnalysisMerchant] = useState<Merchant | null>(null);
  const [analysis, setAnalysis] = useState<MerchantAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [generatingAnalysis, setGeneratingAnalysis] = useState(false);
  const [enrichmentOpen, setEnrichmentOpen] = useState(false);
  const [enrichmentLoading, setEnrichmentLoading] = useState(false);
  const [enrichmentResults, setEnrichmentResults] = useState<EnrichmentResult[]>([]);
  const [enrichmentSelected, setEnrichmentSelected] = useState<Record<number, Record<string, boolean>>>({});
  const [applyingEnrichment, setApplyingEnrichment] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const loadData = async () => {
    const params = new URLSearchParams({ skip: String((page - 1) * pageSize), limit: String(pageSize) });
    if (search.trim()) params.set('search', search.trim());
    if (poolStatus) params.set('pool_status', poolStatus);
    if (region.trim()) params.set('region', region.trim());
    if (industry.trim()) params.set('industry', industry.trim());
    if (source) params.set('source', source);
    if (ratingMin) params.set('rating_min', ratingMin);
    try {
      const [listResponse, statsResponse] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/merchant-pool?${params.toString()}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/merchant-pool/stats', method: 'GET' }),
      ]);
      setItems(listResponse.data?.items || []);
      setTotal(listResponse.data?.total || 0);
      setStats(statsResponse.data || stats);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '商家池数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, poolStatus, region, industry, source, ratingMin]);

  useEffect(() => {
    setPage(1);
    const timer = window.setTimeout(() => void loadData(), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    if (!canManagePool) return;
    void invokeWithAuth({ url: '/api/v1/sales-leads/assignees', method: 'GET' })
      .then(response => setAssignees(response.data || []))
      .catch(() => toast.error('电话销售人员列表加载失败'));
  }, [canManagePool]);

  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !importOpen && !editing && !analysisMerchant });

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
      toast.success(`已导入 ${result.total} 条；待清洗 ${result.counts?.pending || 0} 条，自动隔离 ${Object.values(result.counts || {}).reduce((sum: number, value: any) => sum + Number(value || 0), 0) - Number(result.counts?.pending || 0)} 条`);
      if (result.errors?.length) toast.warning(`${result.errors.length} 行格式有问题，未导入`);
      if (result.ignored_headers?.length) toast.info(`未识别列已忽略：${result.ignored_headers.slice(0, 4).join('、')}${result.ignored_headers.length > 4 ? ' 等' : ''}`);
      setImportOpen(false);
      await loadData();
    } catch (error: any) {
      toast.error(error?.message || 'CSV 导入失败');
    } finally {
      setImporting(false);
      event.target.value = '';
    }
  };

  const importBulk = async () => {
    const records = parseBulkRows(bulkText);
    if (!records.length || records.some((record: any) => !record.business_name)) {
      toast.error('请至少输入一行包含商家名称的数据');
      return;
    }
    setImporting(true);
    try {
      const result = await invokeWithAuth({ url: '/api/v1/merchant-pool/import', method: 'POST', data: { data_source: 'bulk', records } });
      toast.success(`已导入 ${result.data?.total || 0} 条商家记录，系统已自动完成清洗分流`);
      setBulkText('');
      setImportOpen(false);
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '批量导入失败');
    } finally {
      setImporting(false);
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

  const openAnalysis = async (merchant: Merchant) => {
    setAnalysisMerchant(merchant);
    setAnalysis(null);
    setAnalysisLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/merchant-pool/${merchant.id}/analysis`, method: 'GET' });
      setAnalysis(response.data || null);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '销售智能分析加载失败');
    } finally {
      setAnalysisLoading(false);
    }
  };

  const generateAnalysis = async () => {
    if (!analysisMerchant) return;
    setGeneratingAnalysis(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/merchant-pool/${analysisMerchant.id}/analysis/generate`, method: 'POST', data: {} });
      setAnalysis(response.data);
      toast.success(response.data?.ai_used ? '已生成可追溯的 AI 销售分析' : '已按现有资料生成保守销售建议');
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '销售智能分析生成失败');
    } finally {
      setGeneratingAnalysis(false);
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

  const analysisKindLabel: Record<AnalysisCard['kind'], string> = { fact: '已采集事实', recommendation: '销售建议', insufficient: '信息不足' };
  const analysisKindClass: Record<AnalysisCard['kind'], string> = { fact: 'bg-blue-100 text-blue-700', recommendation: 'bg-violet-100 text-violet-700', insufficient: 'bg-amber-100 text-amber-800' };

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
    <div className="merchant-pool-page space-y-4 sm:space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2 text-sm font-medium text-indigo-600"><Database className="h-4 w-4" /> 售前数据缓冲区</div>
          <h2 className="text-xl font-bold text-slate-900 sm:text-2xl">待清洗商家池</h2>
          <p className="mt-1 max-w-3xl text-sm leading-5 text-slate-500">原始商家先在此去重、比对正式客户并隔离无效数据；只有人工确认后才能进入电话销售线索库。</p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => setImportOpen(true)}><Upload className="mr-2 h-4 w-4" />导入商家数据</Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-6">
        {[
          { label: '全部采集记录', value: stats.total, tone: 'bg-indigo-50 text-indigo-700' },
          { label: '待清洗可用', value: stats.pending, tone: 'bg-blue-50 text-blue-700' },
          { label: '自动隔离', value: stats.isolated, tone: 'bg-amber-50 text-amber-800' },
          { label: '重复记录', value: stats.duplicates, tone: 'bg-orange-50 text-orange-800' },
          { label: '已转电话线索', value: stats.converted, tone: 'bg-emerald-50 text-emerald-700' },
          { label: '已归档', value: stats.archived, tone: 'bg-slate-50 text-slate-600' },
        ].map(item => <Card key={item.label} className="border-slate-200 shadow-sm"><CardContent className="p-3 sm:p-4"><p className="text-xs leading-4 text-slate-500">{item.label}</p><p className={`mt-1 text-xl font-bold sm:text-2xl ${item.tone.split(' ')[1]}`}>{item.value}</p></CardContent></Card>)}
      </div>

      <Card className="border-slate-200 shadow-sm"><CardContent className="space-y-3 p-3 sm:p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700"><Filter className="h-4 w-4" />精准筛选</div>
        <div className="grid gap-3 lg:grid-cols-6">
          <div className="relative lg:col-span-2"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="商家、电话或网站" /></div>
          <NativeSelect value={poolStatus} onChange={setPoolStatus} options={[{ value: '', label: '全部清洗状态' }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))]} />
          <Input value={region} onChange={event => { setRegion(event.target.value); setPage(1); }} placeholder="地区，如 CA / Los Angeles" />
          <Input value={industry} onChange={event => { setIndustry(event.target.value); setPage(1); }} placeholder="行业" />
          <NativeSelect value={source} onChange={value => { setSource(value); setPage(1); }} options={sourceOptions} />
          <NativeSelect value={ratingMin} onChange={value => { setRatingMin(value); setPage(1); }} options={[{ value: '', label: '全部评分' }, { value: '4', label: '4.0 分以上' }, { value: '4.5', label: '4.5 分以上' }]} />
        </div>
      </CardContent></Card>

      {canManagePool && selectedMerchantIds.length > 0 && <Card className="border-indigo-200 bg-indigo-50/60 shadow-sm"><CardContent className="flex flex-col gap-3 p-4"><div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><CheckSquare className="h-5 w-5 text-indigo-600" />已选 {selectedMerchantIds.length} 条商家</div><p className="text-xs text-indigo-700">已转线索或已归档记录不能批量修改；批量删除只对未转线索记录生效。</p></div><div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end"><NativeSelect className="sm:w-52" value={bulkIndustry} onChange={setBulkIndustry} options={[{ value: '', label: '选择统一行业' }, ...industryOptions.map(value => ({ value, label: value }))]} /><Input className="sm:w-52" value={bulkIndustry && !industryOptions.includes(bulkIndustry) ? bulkIndustry : ''} onChange={event => setBulkIndustry(event.target.value)} placeholder="或输入自定义行业" /><Button disabled={bulkUpdating || !bulkIndustry.trim()} onClick={() => void updateSelectedIndustry()}>{bulkUpdating ? '更新中...' : '批量设置行业'}</Button><Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading || selectedMerchantIds.length > 20} onClick={() => void suggestEnrichment()}><Sparkles className="mr-2 h-4 w-4" />{enrichmentLoading ? '分析中...' : 'AI 补充空白资料'}</Button><NativeSelect className="sm:w-52" value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售人员' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /><Button disabled={bulkAssigning || bulkUpdating || !selectedSalesId} onClick={() => void assignSelectedMerchants()}><Send className="mr-2 h-4 w-4" />{bulkAssigning ? '分配中...' : '批量转线索并分配'}</Button>{isAdmin && <Button variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" disabled={bulkUpdating || bulkAssigning} onClick={() => void deleteSelectedMerchants()}><Trash2 className="mr-2 h-4 w-4" />批量删除</Button>}<Button variant="outline" disabled={bulkUpdating || bulkAssigning || enrichmentLoading} onClick={() => { setSelectedMerchantIds([]); setBulkIndustry(''); setSelectedSalesId(''); }}>取消选择</Button></div></CardContent></Card>}

      <Card className="overflow-hidden border-slate-200 shadow-sm"><CardContent className="p-0"><div className="flex items-center justify-between border-b bg-slate-50 px-3 py-2 text-xs text-slate-500 sm:hidden"><span>商家列表</span><span>左右滑动查看全部</span></div><div className="merchant-pool-table overflow-x-auto"><table className="w-full min-w-[1100px] text-left text-sm"><thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>{canManagePool && <th className="w-12 px-4 py-3"><input aria-label="选择本页可操作商家" type="checkbox" checked={items.filter(item => !['converted', 'archived'].includes(item.pool_status)).length > 0 && items.filter(item => !['converted', 'archived'].includes(item.pool_status)).every(item => selectedMerchantIds.includes(item.id))} onChange={event => toggleCurrentPageSelection(event.target.checked)} /></th>}<th className="px-4 py-3">商家</th><th className="px-4 py-3">电话 / 网站</th><th className="px-4 py-3">地区 / 行业</th><th className="px-4 py-3">评分</th><th className="px-4 py-3">来源 / 采集时间</th><th className="px-4 py-3">清洗结果</th><th className="px-4 py-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-slate-100">
        {loading ? <tr><td colSpan={canManagePool ? 8 : 7} className="py-12 text-center text-slate-400">正在加载商家池...</td></tr>
          : items.length === 0 ? <tr><td colSpan={canManagePool ? 8 : 7} className="py-12 text-center text-slate-400">暂无商家记录</td></tr>
          : items.map(merchant => <tr key={merchant.id} className={selectedMerchantIds.includes(merchant.id) ? 'bg-indigo-50/60' : 'hover:bg-slate-50/70'}>{canManagePool && <td className="px-4 py-3"><input aria-label={`选择 ${merchant.business_name}`} type="checkbox" disabled={['converted', 'archived'].includes(merchant.pool_status)} checked={selectedMerchantIds.includes(merchant.id)} onChange={event => toggleMerchantSelection(merchant.id, event.target.checked)} /></td>}<td className="px-4 py-3"><p className="font-semibold text-slate-900">{merchant.business_name}</p><p className="text-xs text-slate-500">{merchant.contact_name || '未填写联系人'} · #{merchant.id}</p></td><td className="px-4 py-3"><p>{merchant.phone || <span className="text-rose-600">无电话</span>}</p><p className="max-w-44 truncate text-xs text-blue-600">{merchant.website || '-'}</p></td><td className="px-4 py-3 text-slate-600"><p>{[merchant.city, merchant.state, merchant.country].filter(Boolean).join(', ') || '-'}</p><p className="text-xs text-slate-400">{merchant.industry || '未分类'}</p></td><td className="px-4 py-3">{merchant.rating ? <span className="font-medium text-amber-600">{merchant.rating.toFixed(1)} ★</span> : '-'}</td><td className="px-4 py-3"><p className="font-medium text-slate-700">{merchant.data_source}</p><p className="text-xs text-slate-400">{formatDate(merchant.collected_at)}</p></td><td className="px-4 py-3"><Badge className={statusClasses[merchant.pool_status] || 'bg-slate-100 text-slate-700'}>{statusLabels[merchant.pool_status] || merchant.pool_status}</Badge><p className="mt-1 max-w-56 text-xs text-slate-500">{merchant.isolation_reason || '已通过基础检查，等待确认'}</p></td><td className="px-4 py-3"><div className="flex flex-wrap justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => openEdit(merchant)}>补充资料</Button>{['pending', 'converted'].includes(merchant.pool_status) && <Button size="sm" variant="outline" onClick={() => void openAnalysis(merchant)}><Sparkles className="mr-1 h-3.5 w-3.5" />AI 分析</Button>}{merchant.pool_status === 'pending' && <Button size="sm" onClick={() => toggleMerchantSelection(merchant.id, true)}><Send className="mr-1 h-3.5 w-3.5" />加入分配</Button>}{isAdmin && merchant.pool_status !== 'converted' && merchant.pool_status !== 'archived' && <Button size="sm" variant="outline" onClick={() => archiveMerchant(merchant)}><Archive className="mr-1 h-3.5 w-3.5" />归档</Button>}{isAdmin && merchant.pool_status !== 'converted' && <Button size="sm" variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" onClick={() => deleteMerchant(merchant)}><Trash2 className="mr-1 h-3.5 w-3.5" />删除</Button>}</div></td></tr>)}
      </tbody></table></div><div className="flex flex-col gap-3 border-t bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-slate-500">共 {total} 条，第 {page}/{totalPages} 页</p><div className="flex items-center gap-2"><NativeSelect className="w-24" value={String(pageSize)} onChange={value => { setPageSize(Number(value)); setPage(1); }} options={[20, 50, 100].map(value => ({ value: String(value), label: `${value}条` }))} /><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</Button></div></div></CardContent></Card>

      <Dialog open={importOpen} onOpenChange={setImportOpen}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>导入待清洗商家数据</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-900"><p className="font-medium">自动清洗规则</p><p className="mt-1 text-indigo-700">无电话、已关闭、与正式客户重复、或与商家池重复的数据会被自动隔离，不会进入电话销售线索库。</p></div><div className="flex gap-2"><Button size="sm" variant={importMode === 'csv' ? 'default' : 'outline'} onClick={() => setImportMode('csv')}>Excel / CSV 文件</Button><Button size="sm" variant={importMode === 'bulk' ? 'default' : 'outline'} onClick={() => setImportMode('bulk')}>批量粘贴</Button></div>{importMode === 'csv' ? <div className="space-y-3"><p className="text-sm text-slate-600">支持 Excel（.xlsx）及 CSV（UTF-8、Excel 常见编码）。会自动识别中文/英文表头，例如：商家名称、Business Name、电话/Phone、地址/Address、官网/Website、类别/Category、评分/Rating。</p><p className="text-xs text-slate-500">导入后会提示未识别列；地址中有逗号时，请使用 Excel 文件或用双引号包住该地址。</p><input ref={fileRef} className="hidden" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={importCsv} /><Button disabled={importing} onClick={() => fileRef.current?.click()}><FileUp className="mr-2 h-4 w-4" />{importing ? '导入中...' : '选择 Excel 或 CSV'}</Button></div> : <div className="space-y-2"><Label>每行一条：商家名称, 电话, 地址, 网站, 行业, 城市, 州/省, 国家, 评分, 营业状态</Label><Textarea rows={9} value={bulkText} onChange={event => setBulkText(event.target.value)} placeholder={'支持直接从 Excel 粘贴（制表符）或粘贴 Markdown 表格\n示例餐厅, 626-123-4567, "123 Main St, Suite 1", example.com, 餐厅, Los Angeles, CA, US, 4.5, open'} /><p className="text-xs text-slate-500">支持你刚才发来的 Markdown 表格；“待核验、暂未确认、官网未明确显示”会按空资料处理，不会造成导入失败。</p><Button disabled={importing} onClick={importBulk}><Sparkles className="mr-2 h-4 w-4" />{importing ? '清洗中...' : '导入并自动清洗'}</Button></div>}<div className="border-t pt-3 text-xs text-slate-500"><Link2 className="mr-1 inline h-3.5 w-3.5" />接口导入：主管或管理员可向 <code>/api/v1/merchant-pool/import</code> 提交 JSON 批次，来源填写 <code>api</code>。</div></div></DialogContent></Dialog>

      <Dialog open={enrichmentOpen} onOpenChange={setEnrichmentOpen}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>AI 补充空白资料 · 人工确认</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900"><p className="font-medium">安全补充规则</p><p className="mt-1 text-indigo-800">只使用原始导入资料中已有、但尚未写入标准字段的内容；不会覆盖已填写资料，也不会根据商家名称猜测。Google/Yelp 外部检索尚未接入，找不到来源的字段显示为“信息不足”。</p></div>{enrichmentResults.map(result => <Card key={result.merchant_id} className="border-slate-200"><CardContent className="space-y-3 p-4"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><p className="font-semibold text-slate-900">{result.business_name}</p><Badge className={result.status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'}>{result.status === 'needs_review' ? '有待确认建议' : '信息不足'}</Badge></div><p className="text-xs text-slate-500">原始资料时间：{formatDate(result.source_updated_at || undefined)}</p></div>{result.warning && <p className="rounded-lg bg-amber-50 p-2 text-xs leading-5 text-amber-900">{result.warning}</p>}{result.suggestions.length ? <div className="grid gap-2 md:grid-cols-2">{result.suggestions.map(suggestion => <label key={`${result.merchant_id}-${suggestion.field}`} className="flex cursor-pointer items-start gap-2 rounded-lg border bg-white p-3"><input type="checkbox" checked={Boolean(enrichmentSelected[result.merchant_id]?.[suggestion.field])} onChange={event => setEnrichmentSelected(previous => ({ ...previous, [result.merchant_id]: { ...previous[result.merchant_id], [suggestion.field]: event.target.checked } }))} /><span className="min-w-0 text-sm"><span className="font-medium text-slate-800">{suggestion.field}</span><span className="block break-words text-slate-700">{String(suggestion.value)}</span><span className="block text-xs text-slate-500">来源：{suggestion.source_label} · 可信度：{Math.round(suggestion.confidence * 100)}%</span></span></label>)}</div> : <div className="rounded-lg border border-dashed p-3 text-sm text-slate-500">信息不足：原始导入资料中没有可追溯的空白字段补充内容。</div>}{result.missing_fields.length > 0 && <p className="text-xs text-slate-500">仍缺少：{result.missing_fields.join('、')}</p>}</CardContent></Card>)}<div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setEnrichmentOpen(false)}>取消</Button><Button disabled={applyingEnrichment} onClick={() => void applyEnrichment()}>{applyingEnrichment ? '写入中...' : '确认写入已勾选资料'}</Button></div></div></DialogContent></Dialog>

      <Dialog open={!!editing} onOpenChange={open => !open && setEditing(null)}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>补充商家资料并重新清洗</DialogTitle></DialogHeader><div className="grid gap-4 sm:grid-cols-2"><div><Label>商家名称 *</Label><Input value={editForm.business_name} onChange={event => setEditForm({ ...editForm, business_name: event.target.value })} /></div><div><Label>电话</Label><Input value={editForm.phone} onChange={event => setEditForm({ ...editForm, phone: event.target.value })} /></div><div><Label>联系人</Label><Input value={editForm.contact_name} onChange={event => setEditForm({ ...editForm, contact_name: event.target.value })} /></div><div><Label>行业</Label><Input value={editForm.industry} onChange={event => setEditForm({ ...editForm, industry: event.target.value })} /></div><div><Label>国家</Label><Input value={editForm.country} onChange={event => setEditForm({ ...editForm, country: event.target.value })} /></div><div><Label>州/省</Label><Input value={editForm.state} onChange={event => setEditForm({ ...editForm, state: event.target.value })} /></div><div><Label>城市</Label><Input value={editForm.city} onChange={event => setEditForm({ ...editForm, city: event.target.value })} /></div><div><Label>综合评分</Label><Input type="number" min="0" max="5" step="0.1" value={editForm.rating} onChange={event => setEditForm({ ...editForm, rating: event.target.value })} /></div><div className="sm:col-span-2"><Label>地址</Label><Input value={editForm.address} onChange={event => setEditForm({ ...editForm, address: event.target.value })} /></div><div className="sm:col-span-2"><Label>官网</Label><Input value={editForm.website} onChange={event => setEditForm({ ...editForm, website: event.target.value })} /></div><div className="sm:col-span-2"><Label>营业状态</Label><Input value={editForm.business_status} onChange={event => setEditForm({ ...editForm, business_status: event.target.value })} placeholder="open / closed / 已关闭" /></div></div><div className="my-5 border-t pt-4"><p className="mb-3 text-sm font-semibold text-slate-800">销售分析资料</p><p className="mb-4 text-xs text-slate-500">只填写已实际采集到的资料；未填写的项目会在 AI 分析卡中明确显示“信息不足”。</p><div className="grid gap-4 sm:grid-cols-2"><div><Label>Google 商家链接</Label><Input value={editForm.google_business_url} onChange={event => setEditForm({ ...editForm, google_business_url: event.target.value })} /></div><div><Label>Google 评分</Label><Input type="number" min="0" max="5" step="0.1" value={editForm.google_rating} onChange={event => setEditForm({ ...editForm, google_rating: event.target.value })} /></div><div><Label>Google 评论数</Label><Input type="number" min="0" step="1" value={editForm.google_review_count} onChange={event => setEditForm({ ...editForm, google_review_count: event.target.value })} /></div><div><Label>Yelp 链接</Label><Input value={editForm.yelp_url} onChange={event => setEditForm({ ...editForm, yelp_url: event.target.value })} /></div><div><Label>Yelp 评分</Label><Input type="number" min="0" max="5" step="0.1" value={editForm.yelp_rating} onChange={event => setEditForm({ ...editForm, yelp_rating: event.target.value })} /></div><div><Label>Yelp 评论数</Label><Input type="number" min="0" step="1" value={editForm.yelp_review_count} onChange={event => setEditForm({ ...editForm, yelp_review_count: event.target.value })} /></div><div className="sm:col-span-2"><Label>社交平台情况</Label><Textarea rows={2} value={editForm.social_profiles} onChange={event => setEditForm({ ...editForm, social_profiles: event.target.value })} placeholder="例如：Instagram 已采集链接，最近更新于 7 月 1 日" /></div><div className="sm:col-span-2"><Label>近期差评重点</Label><Textarea rows={2} value={editForm.recent_negative_reviews} onChange={event => setEditForm({ ...editForm, recent_negative_reviews: event.target.value })} placeholder="只填写已采集的评论摘要，不确定请留空" /></div><div className="sm:col-span-2"><Label>素材及内容更新情况</Label><Textarea rows={2} value={editForm.content_update_summary} onChange={event => setEditForm({ ...editForm, content_update_summary: event.target.value })} placeholder="例如：菜单图片最后更新于 2026-06，近期无活动帖" /></div><div><Label>内容资料更新时间</Label><Input type="datetime-local" value={editForm.content_last_updated_at} onChange={event => setEditForm({ ...editForm, content_last_updated_at: event.target.value })} /></div></div></div><div className="mt-4 flex justify-end gap-2"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveEdit}><RefreshCw className="mr-2 h-4 w-4" />保存并重新清洗</Button></div></DialogContent></Dialog>

      <Dialog open={!!analysisMerchant} onOpenChange={open => !open && setAnalysisMerchant(null)}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>{analysisMerchant?.business_name} · 销售智能分析</DialogTitle></DialogHeader><div className="space-y-4"><div className="flex flex-col gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium text-indigo-950">仅依据已采集资料生成</p><p className="mt-1 text-xs text-indigo-800">每个结论都附有来源和更新时间。显示“信息不足”的内容需要人工补充，系统不会由 AI 补造事实。</p></div><Button disabled={generatingAnalysis} onClick={() => void generateAnalysis()}><Sparkles className="mr-2 h-4 w-4" />{generatingAnalysis ? '分析生成中...' : analysis ? '重新生成分析' : '生成销售分析'}</Button></div>{analysisLoading ? <div className="py-12 text-center text-sm text-slate-500">正在读取分析记录...</div> : !analysis ? <div className="rounded-xl border border-dashed p-8 text-center text-sm text-slate-500">尚未生成分析。请先确认或补充线上资料后，点击“生成销售分析”。</div> : <><div className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><Badge className={analysis.ai_used ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'}>{analysis.ai_used ? `AI 已生成${analysis.ai_model ? ` · ${analysis.ai_model}` : ''}` : '保守规则建议'}</Badge><span>生成时间：{formatDate(analysis.generated_at)}</span></div>{analysis.analysis.warning && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{analysis.analysis.warning}</div>}<div className="grid gap-3 md:grid-cols-2">{analysis.analysis.cards.map((card, index) => <Card key={`${card.title}-${index}`} className="border-slate-200 shadow-sm"><CardContent className="space-y-3 p-4"><div className="flex items-start justify-between gap-2"><p className="font-semibold text-slate-900">{card.title}</p><Badge className={analysisKindClass[card.kind]}>{analysisKindLabel[card.kind]}</Badge></div><p className="whitespace-pre-line text-sm leading-6 text-slate-700">{card.content}</p><div className="border-t pt-2 text-xs text-slate-500"><p className="mb-1 font-medium text-slate-600">来源与更新时间</p>{card.sources.map((source, sourceIndex) => <p key={`${source.label}-${sourceIndex}`} className="leading-5">{source.label}{source.value !== undefined && source.value !== null && source.value !== '' ? `：${source.value}` : ''} · {source.updated_at ? formatDate(source.updated_at) : '未采集'}</p>)}</div></CardContent></Card>)}</div></>}</div></DialogContent></Dialog>
    </div>
  );
}
