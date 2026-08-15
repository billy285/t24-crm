import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Copy, RefreshCw, RotateCcw, Search, Sparkles, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import { invokeWithAuth } from '../lib/tokenStore';
import { getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { useBusinessDicts } from '../lib/dict-config';
import { useRole } from '../lib/role-context';

const platformOptions = [
  { value: 'internal', label: '内部运营' },
  { value: 'google_business', label: 'Google商家' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'yelp', label: 'Yelp' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'brand_website', label: '品牌官网' },
  { value: 'ads_campaign', label: '广告投放' },
];

const contentTypeOptions = [
  { value: 'business_intro', label: '商家介绍' },
  { value: 'promotion', label: '活动推广' },
  { value: 'holiday', label: '节日营销' },
  { value: 'review_reply', label: '评论回复' },
  { value: 'weekly_update', label: '每周更新' },
  { value: 'package_promo', label: '套餐宣传' },
  { value: 'operation_plan', label: '客户运营方案' },
  { value: 'weekly_plan', label: '每周运营计划' },
  { value: 'material_gap', label: '素材缺口提醒' },
  { value: 'weekly_report', label: '客户周报' },
  { value: 'copy_quality_check', label: '文案质量检查' },
  { value: 'staff_review', label: '员工执行复盘' },
];

const operationPresets = [
  {
    label: '运营方案',
    description: '给老板和运营看的客户整体打法',
    platform: 'internal',
    content_type: 'operation_plan',
    tone: 'professional',
    variants: '1',
    extra_requirements: '请结合客户套餐、平台、素材和菜单/项目，生成可执行的客户运营方案。',
  },
  {
    label: '每周计划',
    description: '让员工照着执行的一周任务',
    platform: 'internal',
    content_type: 'weekly_plan',
    tone: 'concise',
    variants: '1',
    extra_requirements: '请按平台输出本周更新节奏、主题、素材、负责人动作和验收标准。',
  },
  {
    label: '素材缺口',
    description: '判断还缺什么素材和资料',
    platform: 'internal',
    content_type: 'material_gap',
    tone: 'professional',
    variants: '1',
    extra_requirements: '请根据素材库和菜单/服务项目，列出缺失素材、客户补资料清单和优先级。',
  },
  {
    label: '客户周报',
    description: '整理本周完成和下周计划',
    platform: 'internal',
    content_type: 'weekly_report',
    tone: 'friendly',
    variants: '1',
    extra_requirements: '请生成适合发给客户的周报，包含本周完成、当前问题、下周计划、需要客户配合。',
  },
  {
    label: '评论回复',
    description: 'Google/Yelp/Facebook 回复草稿',
    platform: 'google_business',
    content_type: 'review_reply',
    tone: 'friendly',
    variants: '3',
    extra_requirements: '请在这里粘贴客户评论内容；如果是差评，请礼貌稳妥，不要争辩。',
  },
  {
    label: '文案质检',
    description: '检查员工或 AI 文案是否合格',
    platform: 'internal',
    content_type: 'copy_quality_check',
    tone: 'professional',
    variants: '1',
    extra_requirements: '请在这里粘贴要检查的文案，检查是否空泛、是否不相关、是否有虚假承诺，并给出修改版。',
  },
  {
    label: '执行复盘',
    description: '看员工任务执行风险',
    platform: 'internal',
    content_type: 'staff_review',
    tone: 'professional',
    variants: '1',
    extra_requirements: '请根据服务任务和进度，指出执行风险、低质量完成、未推进事项和下周监管重点。',
  },
];

const languageOptions = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英文' },
  { value: 'zh_en', label: '中英双语' },
];

const toneOptions = [
  { value: 'professional', label: '专业' },
  { value: 'friendly', label: '亲切' },
  { value: 'sales', label: '促销' },
  { value: 'lifestyle', label: '种草' },
  { value: 'local', label: '本地生活' },
  { value: 'concise', label: '简洁' },
];

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'used', label: '已使用' },
  { value: 'archived', label: '已归档' },
];

const statusColors: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700',
  used: 'bg-green-100 text-green-700',
  archived: 'bg-amber-100 text-amber-700',
};

const emptyCopyForm = {
  platform: 'google_business',
  content_type: 'weekly_update',
  language: 'zh_en',
  tone: 'friendly',
  variants: '3',
  extra_requirements: '',
};

const labelOf = (options: Array<{ value: string; label: string }>, value?: string) => (
  options.find(item => item.value === value)?.label || value || '-'
);

function parseMultiValue(value?: string | null) {
  return (value || '').split(',').map(item => item.trim()).filter(Boolean);
}

interface Props {
  customer: any;
}

export default function CustomerAiCopyTab({ customer }: Props) {
  const businessDicts = useBusinessDicts();
  const { canAccess, hasPermission, isAdmin } = useRole();
  const canRead = canAccess('/customers') || canAccess('/service-board');
  const canCreate = canRead && hasPermission('task_create');
  const canEdit = canRead && hasPermission('task_edit');
  const canDelete = canRead && (isAdmin || hasPermission('task_delete'));
  const customerId = Number(customer?.id || 0);
  const activeCustomerIdRef = useRef(customerId);
  const copiesRequestSeqRef = useRef(0);
  activeCustomerIdRef.current = customerId;

  const [copies, setCopies] = useState<any[]>([]);
  const [copiesCustomerId, setCopiesCustomerId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [drafts, setDrafts] = useState<Record<number, { title: string; content: string; status: string }>>({});
  const [copyTotal, setCopyTotal] = useState(0);
  const [copyPage, setCopyPage] = useState(1);
  const [copyPageSize, setCopyPageSize] = useState('10');
  const [copySearch, setCopySearch] = useState('');
  const [copyFilterPlatform, setCopyFilterPlatform] = useState('all');
  const [copyFilterType, setCopyFilterType] = useState('all');
  const [copyFilterStatus, setCopyFilterStatus] = useState('all');
  const [form, setForm] = useState(emptyCopyForm);

  const visibleCopies = copiesCustomerId === customerId ? copies : [];
  const activeDeleteTarget = canDelete && Number(deleteTarget?.customer_id) === customerId ? deleteTarget : null;

  const packageLabels = useMemo(() => (
    parseMultiValue(customer?.interested_packages)
      .map(key => businessDicts.customerPackages[key] || key)
      .join('、')
  ), [businessDicts.customerPackages, customer?.interested_packages]);

  const totalPages = Math.max(1, Math.ceil(copyTotal / Number(copyPageSize || 10)));

  const loadCopies = async (
    requestedCustomerId: number,
    queryState: {
      page: number;
      pageSize: string;
      search: string;
      platform: string;
      contentType: string;
      status: string;
    },
  ) => {
    if (!canRead || !requestedCustomerId) return;
    const requestSeq = ++copiesRequestSeqRef.current;
    if (activeCustomerIdRef.current === requestedCustomerId) {
      setLoading(true);
      setCopies([]);
      setCopiesCustomerId(null);
      setCopyTotal(0);
      setDrafts({});
    }
    try {
      const query: Record<string, any> = { customer_id: requestedCustomerId };
      if (queryState.platform !== 'all') query.platform = queryState.platform;
      if (queryState.contentType !== 'all') query.content_type = queryState.contentType;
      if (queryState.status !== 'all') query.status = queryState.status;
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_ai_copies',
        method: 'GET',
        data: {
          query: JSON.stringify(query),
          search: queryState.search.trim() || undefined,
          sort: '-created_at',
          skip: (queryState.page - 1) * Number(queryState.pageSize || 10),
          limit: Number(queryState.pageSize || 10),
        },
      });
      if (requestSeq !== copiesRequestSeqRef.current || activeCustomerIdRef.current !== requestedCustomerId) return;
      const items = res?.data?.items || [];
      setCopies(items);
      setCopiesCustomerId(requestedCustomerId);
      setCopyTotal(Number(res?.data?.total ?? items.length));
      setDrafts({});
    } catch (err: any) {
      if (requestSeq !== copiesRequestSeqRef.current || activeCustomerIdRef.current !== requestedCustomerId) return;
      console.error(err);
      toast.error(err?.data?.detail || '加载AI文案失败');
    } finally {
      if (requestSeq === copiesRequestSeqRef.current && activeCustomerIdRef.current === requestedCustomerId) {
        setLoading(false);
      }
    }
  };

  const currentQueryState = () => ({
    page: copyPage,
    pageSize: copyPageSize,
    search: copySearch,
    platform: copyFilterPlatform,
    contentType: copyFilterType,
    status: copyFilterStatus,
  });

  const refreshCopies = () => {
    const requestedCustomerId = activeCustomerIdRef.current;
    if (!canRead || requestedCustomerId !== customerId) return;
    void loadCopies(requestedCustomerId, currentQueryState());
  };

  useEffect(() => {
    copiesRequestSeqRef.current += 1;
    setCopies([]);
    setCopiesCustomerId(null);
    setCopyTotal(0);
    setDrafts({});
    setDeleteTarget(null);
    setSavingId(null);
    setGenerating(false);
    setForm(emptyCopyForm);
    if (!canRead || !customerId) setLoading(false);
  }, [canRead, customerId]);

  useEffect(() => {
    if (!canRead || !customerId) return;
    void loadCopies(customerId, currentQueryState());
    return () => {
      copiesRequestSeqRef.current += 1;
    };
    // Request functions intentionally capture this render's permission/filter snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canRead, customerId, copyPage, copyPageSize, copySearch, copyFilterPlatform, copyFilterType, copyFilterStatus]);

  const updateSearch = (value: string) => {
    setCopySearch(value);
    setCopyPage(1);
  };

  const updateCopyFilter = (field: 'platform' | 'type' | 'status' | 'pageSize', value: string) => {
    if (field === 'platform') setCopyFilterPlatform(value);
    if (field === 'type') setCopyFilterType(value);
    if (field === 'status') setCopyFilterStatus(value);
    if (field === 'pageSize') setCopyPageSize(value);
    setCopyPage(1);
  };

  const buildCustomerContext = () => ({
    industry_label: businessDicts.industries[customer?.industry] || customer?.industry || '',
    country_label: customer?.country ? getCountryLabel(customer.country) : '',
    state_label: customer?.country && customer?.state ? getStateLabel(customer.country, customer.state) : customer?.state || '',
    city: customer?.city || '',
    package_labels: packageLabels,
  });

  const applyPreset = (preset: typeof operationPresets[number]) => {
    if (!canCreate || activeCustomerIdRef.current !== customerId) return;
    setForm(prev => ({
      ...prev,
      platform: preset.platform,
      content_type: preset.content_type,
      tone: preset.tone,
      variants: preset.variants,
      extra_requirements: preset.extra_requirements,
    }));
    toast.success(`已选择「${preset.label}」，可直接生成或先补充要求`);
  };

  const requirementPlaceholder = useMemo(() => {
    if (form.content_type === 'review_reply') return '请粘贴客户评论内容、星级、平台，例如：Google 2星评论：“等餐太久...”';
    if (form.content_type === 'copy_quality_check') return '请粘贴需要检查的文案，AI会指出问题并给修改版。';
    if (form.content_type === 'weekly_report') return '可补充本周重点、客户反馈、需要客户配合的事项。';
    if (form.content_type === 'material_gap') return '可补充客户当前缺什么、哪些素材不能用、哪些项目是主推。';
    if (form.content_type === 'staff_review') return '可补充你想重点检查的员工、客户或时间范围。';
    if (form.content_type === 'weekly_plan') return '可补充本周重点平台、更新次数、主推活动或员工安排。';
    if (form.content_type === 'operation_plan') return '可补充老板关注点，例如先做Google/Yelp，还是先补素材和基础信息。';
    return '例如：突出周末优惠、适合餐厅午餐套餐、语气更本地化、不要太广告...';
  }, [form.content_type]);

  const handleGenerate = async () => {
    const requestedCustomerId = activeCustomerIdRef.current;
    if (!canCreate || !requestedCustomerId || requestedCustomerId !== customerId) return;
    const requestForm = { ...form };
    const customerContext = buildCustomerContext();
    setGenerating(true);
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_ai_copies/generate',
        method: 'POST',
        data: {
          customer_id: requestedCustomerId,
          platform: requestForm.platform,
          content_type: requestForm.content_type,
          language: requestForm.language,
          tone: requestForm.tone,
          variants: Number(requestForm.variants || 3),
          extra_requirements: requestForm.extra_requirements,
          customer_context: customerContext,
        },
      });
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      const items = res?.data?.items || [];
      setCopySearch('');
      setCopyFilterPlatform('all');
      setCopyFilterType('all');
      setCopyFilterStatus('all');
      setCopyPage(1);
      setCopies(prev => [
        ...items,
        ...prev.filter(copy => Number(copy?.customer_id) === requestedCustomerId),
      ].slice(0, Number(copyPageSize || 10)));
      setCopiesCustomerId(requestedCustomerId);
      setCopyTotal(prev => prev + items.length);
      setDrafts({});
      if (res?.data?.warning) {
        toast(res.data.warning);
      } else {
        toast.success('AI文案已生成并保存为草稿');
      }
    } catch (err: any) {
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      console.error(err);
      toast.error(err?.data?.detail || '生成失败，请检查AI配置');
    } finally {
      if (activeCustomerIdRef.current === requestedCustomerId) setGenerating(false);
    }
  };

  const updateDraft = (item: any, patch: Partial<{ title: string; content: string; status: string }>) => {
    if (!canEdit || Number(item?.customer_id) !== activeCustomerIdRef.current) return;
    setDrafts(prev => ({
      ...prev,
      [item.id]: {
        title: prev[item.id]?.title ?? item.title ?? '',
        content: prev[item.id]?.content ?? item.content ?? '',
        status: prev[item.id]?.status ?? item.status ?? 'draft',
        ...patch,
      },
    }));
  };

  const handleSave = async (item: any, patch?: Partial<{ status: string }>) => {
    const requestedCustomerId = activeCustomerIdRef.current;
    if (!canEdit || Number(item?.customer_id) !== requestedCustomerId) return;
    const draft = {
      title: drafts[item.id]?.title ?? item.title ?? '',
      content: drafts[item.id]?.content ?? item.content ?? '',
      status: patch?.status ?? drafts[item.id]?.status ?? item.status ?? 'draft',
    };
    if (!draft.content.trim()) {
      toast.error('文案内容不能为空');
      return;
    }
    setSavingId(item.id);
    try {
      const res = await invokeWithAuth({
        url: `/api/v1/entities/customer_ai_copies/${item.id}`,
        method: 'PUT',
        data: draft,
      });
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      setCopies(prev => prev.map(copy => (copy.id === item.id ? res.data : copy)));
      setDrafts(prev => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
      toast.success(patch?.status === 'used' ? '已标记为已使用' : '文案已保存');
    } catch (err: any) {
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      console.error(err);
      toast.error(err?.data?.detail || '保存失败');
    } finally {
      if (activeCustomerIdRef.current === requestedCustomerId) setSavingId(null);
    }
  };

  const handleDelete = async () => {
    const requestedCustomerId = activeCustomerIdRef.current;
    const target = deleteTarget;
    if (!canDelete || !target || Number(target.customer_id) !== requestedCustomerId) return;
    try {
      await invokeWithAuth({ url: `/api/v1/entities/customer_ai_copies/${target.id}`, method: 'DELETE' });
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      setCopies(prev => prev.filter(item => item.id !== target.id));
      setDeleteTarget(null);
      setCopyTotal(prev => Math.max(0, prev - 1));
      toast.success('文案已删除');
    } catch (err: any) {
      if (activeCustomerIdRef.current !== requestedCustomerId) return;
      console.error(err);
      toast.error(err?.data?.detail || '删除失败');
    }
  };

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text || '');
      toast.success('已复制文案');
    } catch {
      toast.error('复制失败，请手动选中文案复制');
    }
  };

  const reuseCopySettings = (item: any) => {
    if (!canCreate || Number(item?.customer_id) !== activeCustomerIdRef.current) return;
    setForm({
      platform: item.platform || 'google_business',
      content_type: item.content_type || 'weekly_update',
      language: item.language || 'zh_en',
      tone: item.tone || 'friendly',
      variants: form.variants || '3',
      extra_requirements: item.extra_requirements || '',
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
    toast.success('已复用这条文案的生成条件，可直接再次生成');
  };

  if (!canRead) {
    return (
      <Card className="border-slate-200">
        <CardContent className="py-10 text-center text-sm text-slate-500" role="alert">
          当前账号无权查看客户 AI 文案。
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {canCreate && <Card className="border-blue-100 bg-blue-50/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2 text-blue-700">
            <Sparkles className="w-4 h-4" /> AI文案生成
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-xl border border-blue-100 bg-white/80 p-3">
            <div className="flex flex-col gap-1 mb-3">
              <p className="text-sm font-medium text-slate-800">AI运营助手快捷工具</p>
              <p className="text-xs text-slate-500">先选一个运营动作，系统会自动带入用途和要求，生成后统一保存到下面的文案库。</p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {operationPresets.map(preset => (
                <Button
                  key={preset.content_type}
                  type="button"
                  variant={form.content_type === preset.content_type ? 'default' : 'outline'}
                  className={`h-auto flex-col items-start gap-1 px-3 py-2 text-left ${form.content_type === preset.content_type ? 'bg-blue-600 hover:bg-blue-700' : 'bg-white'}`}
                  onClick={() => applyPreset(preset)}
                >
                  <span className="text-sm font-semibold">{preset.label}</span>
                  <span className={`text-[11px] ${form.content_type === preset.content_type ? 'text-blue-50' : 'text-slate-500'}`}>{preset.description}</span>
                </Button>
              ))}
            </div>
          </div>
          <div className="grid md:grid-cols-3 gap-3">
            <div><Label>平台</Label><NativeSelect value={form.platform} onChange={v => setForm({ ...form, platform: v })} options={platformOptions} /></div>
            <div><Label>用途</Label><NativeSelect value={form.content_type} onChange={v => setForm({ ...form, content_type: v })} options={contentTypeOptions} /></div>
            <div><Label>语言</Label><NativeSelect value={form.language} onChange={v => setForm({ ...form, language: v })} options={languageOptions} /></div>
            <div><Label>语气</Label><NativeSelect value={form.tone} onChange={v => setForm({ ...form, tone: v })} options={toneOptions} /></div>
            <div><Label>生成数量</Label><NativeSelect value={form.variants} onChange={v => setForm({ ...form, variants: v })} options={[1, 2, 3, 4, 5].map(n => ({ value: String(n), label: `${n} 个版本` }))} /></div>
            <div><Label>客户资料</Label><Input value={`${businessDicts.industries[customer?.industry] || customer?.industry || '未知行业'} · ${customer?.city || ''} ${customer?.state || ''}`} disabled /></div>
          </div>
          <div>
            <Label>额外要求</Label>
            <Textarea
              value={form.extra_requirements}
              onChange={e => setForm({ ...form, extra_requirements: e.target.value })}
              placeholder={requirementPlaceholder}
              rows={3}
            />
          </div>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <p className="text-xs text-slate-500">只生成草稿，不会自动发布。生成后可编辑、复制、标记已使用。</p>
            <Button onClick={handleGenerate} disabled={generating} className="bg-blue-600 hover:bg-blue-700">
              <Sparkles className="w-4 h-4 mr-1" /> {generating ? '生成中...' : '生成并保存草稿'}
            </Button>
          </div>
        </CardContent>
      </Card>}

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <CardTitle className="text-base">文案库 ({copyTotal})</CardTitle>
              <p className="text-xs text-slate-500 mt-1">
                生成后的草稿都会保存在这里，可搜索、翻页、复制，也可以复用生成条件再次生成。
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={refreshCopies} disabled={loading}>
              <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
            <div className="relative md:col-span-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input
                className="pl-9"
                value={copySearch}
                onChange={e => updateSearch(e.target.value)}
                placeholder="搜索标题、内容、额外要求..."
              />
            </div>
            <NativeSelect
              value={copyFilterPlatform}
              onChange={v => updateCopyFilter('platform', v)}
              options={[{ value: 'all', label: '全部平台' }, ...platformOptions]}
            />
            <NativeSelect
              value={copyFilterType}
              onChange={v => updateCopyFilter('type', v)}
              options={[{ value: 'all', label: '全部用途' }, ...contentTypeOptions]}
            />
            <NativeSelect
              value={copyFilterStatus}
              onChange={v => updateCopyFilter('status', v)}
              options={[{ value: 'all', label: '全部状态' }, ...statusOptions]}
            />
            <NativeSelect
              value={copyPageSize}
              onChange={v => updateCopyFilter('pageSize', v)}
              options={[
                { value: '10', label: '每页 10 条' },
                { value: '20', label: '每页 20 条' },
                { value: '50', label: '每页 50 条' },
              ]}
            />
          </div>

          {loading ? (
            <p className="text-sm text-slate-400 text-center py-8">加载中...</p>
          ) : copyTotal === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">{canCreate ? '暂无匹配文案，可以先生成一组草稿' : '暂无匹配文案'}</p>
          ) : (
            <div className="space-y-4">
              {visibleCopies.map(item => {
                const draft = drafts[item.id];
                const content = draft?.content ?? item.content ?? '';
                const title = draft?.title ?? item.title ?? '';
                const itemStatus = draft?.status ?? item.status ?? 'draft';
                return (
                  <div key={item.id} data-testid={`customer-ai-copy-${item.id}`} className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="secondary">{labelOf(platformOptions, item.platform)}</Badge>
                        <Badge variant="secondary">{labelOf(contentTypeOptions, item.content_type)}</Badge>
                        <Badge className={statusColors[item.status] || statusColors.draft}>{labelOf(statusOptions, item.status)}</Badge>
                        {!item.is_ai_generated && <Badge className="bg-amber-100 text-amber-700">模板草稿</Badge>}
                      </div>
                      <span className="text-xs text-slate-400">{item.generated_by || '-'} · {item.created_at?.slice(0, 10) || '-'}</span>
                    </div>
                    <Input value={title} readOnly={!canEdit} onChange={e => updateDraft(item, { title: e.target.value })} />
                    <Textarea value={content} readOnly={!canEdit} onChange={e => updateDraft(item, { content: e.target.value })} rows={8} className="leading-relaxed" />
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <NativeSelect value={itemStatus} onChange={v => updateDraft(item, { status: v })} options={statusOptions} className="w-[130px]" disabled={!canEdit} />
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => copyText(content)}><Copy className="w-3.5 h-3.5 mr-1" />复制</Button>
                        {canCreate && <Button variant="outline" size="sm" onClick={() => reuseCopySettings(item)}><RotateCcw className="w-3.5 h-3.5 mr-1" />复用要求</Button>}
                        {canEdit && <Button variant="outline" size="sm" onClick={() => handleSave(item)} disabled={savingId === item.id}>{savingId === item.id ? '保存中...' : '保存'}</Button>}
                        {canEdit && <Button variant="outline" size="sm" className="text-green-600 hover:text-green-700" onClick={() => handleSave(item, { status: 'used' })} disabled={savingId === item.id}>标记已使用</Button>}
                        {canDelete && <Button aria-label={`删除AI文案：${item.title || item.id}`} variant="ghost" size="sm" className="min-h-11 min-w-11 text-red-600 hover:text-red-700 md:min-h-0 md:min-w-0" onClick={() => setDeleteTarget(item)}><Trash2 className="w-3.5 h-3.5" /></Button>}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div className="flex flex-col gap-2 border-t border-slate-100 pt-4 md:flex-row md:items-center md:justify-between">
                <p className="text-xs text-slate-500">
                  第 {copyPage} / {totalPages} 页，共 {copyTotal} 条
                </p>
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={() => setCopyPage(1)} disabled={copyPage <= 1}>首页</Button>
                  <Button variant="outline" size="sm" onClick={() => setCopyPage(prev => Math.max(1, prev - 1))} disabled={copyPage <= 1}>上一页</Button>
                  <Button variant="outline" size="sm" onClick={() => setCopyPage(prev => Math.min(totalPages, prev + 1))} disabled={copyPage >= totalPages}>下一页</Button>
                  <Button variant="outline" size="sm" onClick={() => setCopyPage(totalPages)} disabled={copyPage >= totalPages}>末页</Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {canDelete && <ConfirmDialog
        open={!!activeDeleteTarget}
        onOpenChange={open => !open && setDeleteTarget(null)}
        title="确认删除AI文案"
        description={`确定要删除「${activeDeleteTarget?.title || '这条文案'}」吗？`}
        onConfirm={handleDelete}
      />}
    </div>
  );
}
