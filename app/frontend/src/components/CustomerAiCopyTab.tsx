import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Copy, Sparkles, Trash2 } from 'lucide-react';
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

const platformOptions = [
  { value: 'google_business', label: 'Google商家' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'x', label: 'X' },
  { value: 'yelp', label: 'Yelp' },
  { value: 'xiaohongshu', label: '小红书' },
];

const contentTypeOptions = [
  { value: 'business_intro', label: '商家介绍' },
  { value: 'promotion', label: '活动推广' },
  { value: 'holiday', label: '节日营销' },
  { value: 'review_reply', label: '评论回复' },
  { value: 'weekly_update', label: '每周更新' },
  { value: 'package_promo', label: '套餐宣传' },
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
  const [copies, setCopies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [drafts, setDrafts] = useState<Record<number, { title: string; content: string; status: string }>>({});
  const [form, setForm] = useState({
    platform: 'google_business',
    content_type: 'weekly_update',
    language: 'zh_en',
    tone: 'friendly',
    variants: '3',
    extra_requirements: '',
  });

  const packageLabels = useMemo(() => (
    parseMultiValue(customer?.interested_packages)
      .map(key => businessDicts.customerPackages[key] || key)
      .join('、')
  ), [businessDicts.customerPackages, customer?.interested_packages]);

  useEffect(() => {
    loadCopies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customer?.id]);

  const loadCopies = async () => {
    if (!customer?.id) return;
    setLoading(true);
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_ai_copies',
        method: 'GET',
        data: { query: JSON.stringify({ customer_id: customer.id }), sort: '-created_at', limit: 100 },
      });
      setCopies(res?.data?.items || []);
      setDrafts({});
    } catch (err: any) {
      console.error(err);
      toast.error(err?.data?.detail || '加载AI文案失败');
    } finally {
      setLoading(false);
    }
  };

  const buildCustomerContext = () => ({
    industry_label: businessDicts.industries[customer?.industry] || customer?.industry || '',
    country_label: customer?.country ? getCountryLabel(customer.country) : '',
    state_label: customer?.country && customer?.state ? getStateLabel(customer.country, customer.state) : customer?.state || '',
    city: customer?.city || '',
    package_labels: packageLabels,
  });

  const handleGenerate = async () => {
    if (!customer?.id) return;
    setGenerating(true);
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_ai_copies/generate',
        method: 'POST',
        data: {
          customer_id: customer.id,
          platform: form.platform,
          content_type: form.content_type,
          language: form.language,
          tone: form.tone,
          variants: Number(form.variants || 3),
          extra_requirements: form.extra_requirements,
          customer_context: buildCustomerContext(),
        },
      });
      const items = res?.data?.items || [];
      setCopies(items.concat(copies));
      setDrafts({});
      if (res?.data?.warning) {
        toast(res.data.warning);
      } else {
        toast.success('AI文案已生成并保存为草稿');
      }
    } catch (err: any) {
      console.error(err);
      toast.error(err?.data?.detail || '生成失败，请检查AI配置');
    } finally {
      setGenerating(false);
    }
  };

  const updateDraft = (item: any, patch: Partial<{ title: string; content: string; status: string }>) => {
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
      setCopies(prev => prev.map(copy => (copy.id === item.id ? res.data : copy)));
      setDrafts(prev => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
      toast.success(patch?.status === 'used' ? '已标记为已使用' : '文案已保存');
    } catch (err: any) {
      console.error(err);
      toast.error(err?.data?.detail || '保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await invokeWithAuth({ url: `/api/v1/entities/customer_ai_copies/${deleteTarget.id}`, method: 'DELETE' });
      setCopies(prev => prev.filter(item => item.id !== deleteTarget.id));
      setDeleteTarget(null);
      toast.success('文案已删除');
    } catch (err: any) {
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

  return (
    <div className="space-y-4">
      <Card className="border-blue-100 bg-blue-50/40">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2 text-blue-700">
            <Sparkles className="w-4 h-4" /> AI文案生成
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
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
              placeholder="例如：突出周末优惠、适合餐厅午餐套餐、语气更本地化、不要太广告..."
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
      </Card>

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">历史文案 ({copies.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-slate-400 text-center py-8">加载中...</p>
          ) : copies.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">暂无AI文案，先生成一组草稿吧</p>
          ) : (
            <div className="space-y-4">
              {copies.map(item => {
                const draft = drafts[item.id] || {};
                const content = draft.content ?? item.content ?? '';
                const title = draft.title ?? item.title ?? '';
                const itemStatus = draft.status ?? item.status ?? 'draft';
                return (
                  <div key={item.id} className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="secondary">{labelOf(platformOptions, item.platform)}</Badge>
                        <Badge variant="secondary">{labelOf(contentTypeOptions, item.content_type)}</Badge>
                        <Badge className={statusColors[item.status] || statusColors.draft}>{labelOf(statusOptions, item.status)}</Badge>
                        {!item.is_ai_generated && <Badge className="bg-amber-100 text-amber-700">模板草稿</Badge>}
                      </div>
                      <span className="text-xs text-slate-400">{item.generated_by || '-'} · {item.created_at?.slice(0, 10) || '-'}</span>
                    </div>
                    <Input value={title} onChange={e => updateDraft(item, { title: e.target.value })} />
                    <Textarea value={content} onChange={e => updateDraft(item, { content: e.target.value })} rows={8} className="leading-relaxed" />
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <NativeSelect value={itemStatus} onChange={v => updateDraft(item, { status: v })} options={statusOptions} className="w-[130px]" />
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => copyText(content)}><Copy className="w-3.5 h-3.5 mr-1" />复制</Button>
                        <Button variant="outline" size="sm" onClick={() => handleSave(item)} disabled={savingId === item.id}>{savingId === item.id ? '保存中...' : '保存'}</Button>
                        <Button variant="outline" size="sm" className="text-green-600 hover:text-green-700" onClick={() => handleSave(item, { status: 'used' })} disabled={savingId === item.id}>标记已使用</Button>
                        <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700" onClick={() => setDeleteTarget(item)}><Trash2 className="w-3.5 h-3.5" /></Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={open => !open && setDeleteTarget(null)}
        title="确认删除AI文案"
        description={`确定要删除「${deleteTarget?.title || '这条文案'}」吗？`}
        onConfirm={handleDelete}
      />
    </div>
  );
}
