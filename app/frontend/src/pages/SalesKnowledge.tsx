import { useEffect, useMemo, useState } from 'react';
import { BookOpen, CheckCircle2, CircleHelp, Copy, Pencil, Plus, Search, Send, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';

type Article = {
  id: number;
  category: string;
  title: string;
  customer_question?: string;
  standard_answer: string;
  action_steps: string[];
  related_links: string[];
  escalation_rule?: string;
  tags: string[];
  status: 'draft' | 'published' | 'archived';
  is_sensitive: boolean;
  sort_order: number;
  updated_at?: string;
};

type KnowledgeQuestion = {
  id: number;
  question: string;
  context?: string;
  status: 'open' | 'resolved';
  submitted_by_name?: string;
  created_at?: string;
};

type ArticleForm = {
  category: string;
  title: string;
  customer_question: string;
  standard_answer: string;
  action_steps: string;
  escalation_rule: string;
  tags: string;
  is_sensitive: boolean;
  sort_order: string;
};

const categoryOptions = ['销售准备与开场', '需求诊断', '产品与服务', '套餐与报价', '异议与合规', '收款与付款', '成交与交接', '售后与升级', '销售红线', '其他'];
const emptyArticleForm = (): ArticleForm => ({
  category: '其他', title: '', customer_question: '', standard_answer: '', action_steps: '', escalation_rule: '', tags: '', is_sensitive: false, sort_order: '200',
});
const compact = (value?: string, length = 132) => value && value.length > length ? `${value.slice(0, length)}...` : value || '';
const formatDate = (value?: string) => value ? value.slice(0, 16).replace('T', ' ') : '-';
const splitLines = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean);
const splitTags = (value: string) => value.split(/[，,]/).map(item => item.trim()).filter(Boolean);

export default function SalesKnowledge() {
  const { role, isAdmin } = useRole();
  const canManage = isAdmin || role === 'sales_manager';
  const [articles, setArticles] = useState<Article[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [questions, setQuestions] = useState<KnowledgeQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('全部');
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
  const [editorArticle, setEditorArticle] = useState<Article | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [articleForm, setArticleForm] = useState<ArticleForm>(emptyArticleForm);
  const [customCategory, setCustomCategory] = useState('');
  const [publishNow, setPublishNow] = useState(true);
  const [questionOpen, setQuestionOpen] = useState(false);
  const [questionForm, setQuestionForm] = useState({ question: '', context: '' });
  const [saving, setSaving] = useState(false);

  const loadKnowledge = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set('query', query.trim());
      if (category !== '全部') params.set('category', category);
      if (canManage) params.set('include_all', 'true');
      const response = await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?${params}`, method: 'GET' });
      setArticles(response.data?.items || []);
      setCategories(response.data?.categories || []);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '销售知识库加载失败');
    } finally {
      if (showLoader) setLoading(false);
    }
  };

  const loadQuestions = async () => {
    if (!canManage) { setQuestions([]); return; }
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-knowledge/questions', method: 'GET' });
      setQuestions(response.data?.items || []);
    } catch {
      setQuestions([]);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadKnowledge(); }, 160);
    return () => window.clearTimeout(timer);
    // The search terms intentionally refresh the server-side result set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, canManage, query]);

  useEffect(() => { void loadQuestions(); }, [canManage]);

  const openEditor = (article?: Article) => {
    setEditorArticle(article || null);
    setPublishNow(article ? article.status === 'published' : true);
    setArticleForm(article ? {
      category: article.category,
      title: article.title,
      customer_question: article.customer_question || '',
      standard_answer: article.standard_answer,
      action_steps: article.action_steps.join('\n'),
      escalation_rule: article.escalation_rule || '',
      tags: article.tags.join('，'),
      is_sensitive: article.is_sensitive,
      sort_order: String(article.sort_order || 200),
    } : emptyArticleForm());
    setCustomCategory('');
    setEditorOpen(true);
  };

  const copyAnswer = async (article: Article) => {
    const content = `${article.title}\n\n标准答复：\n${article.standard_answer}${article.action_steps.length ? `\n\n建议步骤：\n${article.action_steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}` : ''}`;
    try {
      await navigator.clipboard.writeText(content);
      toast.success('标准答复已复制，可按实际情况调整后发送');
    } catch {
      toast.error('复制失败，请手动选择内容复制');
    }
  };

  const saveArticle = async () => {
    if (!articleForm.title.trim() || !articleForm.standard_answer.trim()) {
      toast.error('请填写知识卡标题和标准答复');
      return;
    }
    setSaving(true);
    const payload = {
      category: customCategory.trim() || articleForm.category,
      title: articleForm.title.trim(),
      customer_question: articleForm.customer_question.trim() || null,
      standard_answer: articleForm.standard_answer.trim(),
      action_steps: splitLines(articleForm.action_steps),
      related_links: [],
      escalation_rule: articleForm.escalation_rule.trim() || null,
      tags: splitTags(articleForm.tags),
      is_sensitive: articleForm.is_sensitive,
      sort_order: Number(articleForm.sort_order) || 200,
    };
    try {
      if (editorArticle) {
        await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles/${editorArticle.id}`, method: 'PUT', data: payload });
        if (publishNow && editorArticle.status !== 'published') {
          await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles/${editorArticle.id}/publish`, method: 'POST' });
        }
        toast.success('知识卡已更新');
      } else {
        await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?publish_now=${publishNow}`, method: 'POST', data: payload });
        toast.success(publishNow ? '知识卡已发布' : '草稿已保存');
      }
      setEditorOpen(false);
      await Promise.all([loadKnowledge(false), loadQuestions()]);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '知识卡保存失败');
    } finally {
      setSaving(false);
    }
  };

  const submitQuestion = async () => {
    if (questionForm.question.trim().length < 3) {
      toast.error('请写清楚客户提出的问题');
      return;
    }
    setSaving(true);
    try {
      await invokeWithAuth({ url: '/api/v1/sales-knowledge/questions', method: 'POST', data: { question: questionForm.question.trim(), context: questionForm.context.trim() || null } });
      toast.success('问题已提交给销售主管，后续会补充为标准知识卡');
      setQuestionForm({ question: '', context: '' });
      setQuestionOpen(false);
      await loadQuestions();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '问题提交失败');
    } finally {
      setSaving(false);
    }
  };

  const resolveQuestion = async (question: KnowledgeQuestion) => {
    if (!window.confirm(`确认将“${question.question}”标记为已处理？请先确保已有对应知识卡。`)) return;
    try {
      await invokeWithAuth({ url: `/api/v1/sales-knowledge/questions/${question.id}/resolve`, method: 'POST', data: {} });
      toast.success('问题已标记为已处理');
      await loadQuestions();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '处理失败');
    }
  };

  const openQuestions = useMemo(() => questions.filter(item => item.status === 'open'), [questions]);
  const allCategories = useMemo(() => Array.from(new Set([...categories, ...categoryOptions])), [categories]);

  return <div className="space-y-5">
    <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <div className="mb-1 flex items-center gap-2 text-sm font-medium text-blue-600"><BookOpen className="h-4 w-4" /> 独立售前支持区</div>
        <h2 className="text-2xl font-bold text-slate-900">销售知识库</h2>
        <p className="mt-1 text-sm text-slate-500">把常见问题、标准答复和升级规则放在一个地方。知识卡不写入正式客户、成交或财务数据。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => setQuestionOpen(true)}><CircleHelp className="mr-1.5 h-4 w-4" />提交新问题</Button>
        {canManage && <Button onClick={() => openEditor()}><Plus className="mr-1.5 h-4 w-4" />新建知识卡</Button>}
      </div>
    </div>

    <Card className="border-blue-100 bg-gradient-to-r from-blue-50 via-white to-indigo-50 shadow-sm">
      <CardContent className="grid gap-4 p-5 lg:grid-cols-[1.3fr_repeat(3,1fr)]">
        <div><p className="text-sm font-medium text-blue-700">可直接使用的标准答复</p><p className="mt-1 text-3xl font-bold text-slate-900">{articles.filter(item => item.status === 'published').length}</p><p className="mt-1 text-xs text-slate-500">销售可查看、复制并按客户实际情况表达</p></div>
        <div className="rounded-xl bg-white/80 p-3"><ShieldAlert className="h-4 w-4 text-amber-600" /><p className="mt-2 text-sm font-semibold text-slate-800">先确认再承诺</p><p className="mt-1 text-xs text-slate-500">折扣、退款、定制和效果保证必须升级确认。</p></div>
        <div className="rounded-xl bg-white/80 p-3"><CheckCircle2 className="h-4 w-4 text-emerald-600" /><p className="mt-2 text-sm font-semibold text-slate-800">收款由财务确认</p><p className="mt-1 text-xs text-slate-500">销售可协助指引和留档，但不自行确认到账。</p></div>
        <div className="rounded-xl bg-white/80 p-3"><CircleHelp className="h-4 w-4 text-violet-600" /><p className="mt-2 text-sm font-semibold text-slate-800">待补充问题</p><p className="mt-1 text-2xl font-bold text-slate-900">{canManage ? openQuestions.length : '可提交'}</p></div>
      </CardContent>
    </Card>

    <Card className="shadow-sm"><CardContent className="space-y-4 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center"><div className="relative flex-1"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" /><Input className="pl-9" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索客户问题、套餐、Stripe、支票、折扣..." /></div>{canManage && <Badge className="w-fit bg-violet-100 text-violet-700">主管可持续新建、编辑和发布知识卡</Badge>}</div>
      <div><p className="mb-2 text-xs font-semibold tracking-wide text-slate-500">按销售过程分类</p><div className="flex flex-wrap gap-2">{['全部', ...allCategories].map(item => <Button key={item} size="sm" variant={category === item ? 'default' : 'outline'} className={category === item ? 'bg-blue-600' : 'bg-white'} onClick={() => setCategory(item)}>{item}</Button>)}</div></div>
    </CardContent></Card>

    {canManage && openQuestions.length > 0 && <Card className="border-amber-200 bg-amber-50/60 shadow-sm"><CardContent className="p-4"><div className="mb-3 flex items-center gap-2"><CircleHelp className="h-5 w-5 text-amber-700" /><div><p className="font-semibold text-amber-950">销售待解答问题</p><p className="text-xs text-amber-800">处理后请补充或关联一张知识卡，再标记完成。</p></div></div><div className="space-y-2">{openQuestions.slice(0, 6).map(item => <div key={item.id} className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-white/80 p-3 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><p className="text-sm font-medium text-slate-900">{item.question}</p><p className="mt-1 text-xs text-slate-500">{item.context || '未补充场景'} · {item.submitted_by_name || '销售'} · {formatDate(item.created_at)}</p></div><Button size="sm" variant="outline" onClick={() => void resolveQuestion(item)}>标记已处理</Button></div>)}</div></CardContent></Card>}

    {loading ? <Card><CardContent className="py-14 text-center text-sm text-slate-500">正在加载销售知识卡...</CardContent></Card> : articles.length === 0 ? <Card><CardContent className="py-14 text-center text-sm text-slate-500">没有匹配的知识卡。请换个关键词，或提交新问题。</CardContent></Card> : <div className="grid gap-4 xl:grid-cols-2">{articles.map(article => <Card key={article.id} className={`shadow-sm transition-shadow hover:shadow-md ${article.status === 'draft' ? 'border-dashed border-violet-200 bg-violet-50/30' : 'border-slate-200'}`}><CardContent className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Badge className="bg-blue-100 text-blue-700">{article.category}</Badge>{article.is_sensitive && <Badge className="bg-amber-100 text-amber-800">内部收款信息</Badge>}{article.status === 'draft' && <Badge className="bg-violet-100 text-violet-700">草稿</Badge>}</div><h3 className="mt-3 text-lg font-semibold text-slate-900">{article.title}</h3><p className="mt-1 text-sm text-slate-500">客户问：{article.customer_question || '适用于相关销售场景'}</p></div>{canManage && <Button size="icon" variant="ghost" title="编辑知识卡" onClick={() => openEditor(article)}><Pencil className="h-4 w-4" /></Button>}</div><div className="mt-4 rounded-lg bg-slate-50 p-3"><p className="text-xs font-medium text-slate-500">标准答复</p><p className="mt-1 whitespace-pre-line text-sm leading-6 text-slate-700">{compact(article.standard_answer)}</p></div><div className="mt-4 flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap gap-1.5">{article.tags.slice(0, 4).map(tag => <span key={tag} className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">{tag}</span>)}</div><div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setSelectedArticle(article)}>查看答案</Button><Button size="sm" onClick={() => void copyAnswer(article)}><Copy className="mr-1 h-3.5 w-3.5" />复制</Button></div></div></CardContent></Card>)}</div>}

    <Dialog open={!!selectedArticle} onOpenChange={open => !open && setSelectedArticle(null)}><DialogContent className="max-h-[86vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{selectedArticle?.title}</DialogTitle></DialogHeader>{selectedArticle && <div className="space-y-5"><div className="flex flex-wrap gap-2"><Badge className="bg-blue-100 text-blue-700">{selectedArticle.category}</Badge>{selectedArticle.is_sensitive && <Badge className="bg-amber-100 text-amber-800">仅内部销售使用</Badge>}</div><div><p className="text-sm font-medium text-slate-500">客户问题</p><p className="mt-1 text-slate-800">{selectedArticle.customer_question || '适用于此类问题'}</p></div><div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4"><p className="text-sm font-semibold text-blue-900">建议答复</p><p className="mt-2 whitespace-pre-line text-sm leading-7 text-slate-800">{selectedArticle.standard_answer}</p></div>{selectedArticle.action_steps.length > 0 && <div><p className="font-semibold text-slate-900">执行步骤</p><ol className="mt-2 space-y-2 text-sm text-slate-700">{selectedArticle.action_steps.map((step, index) => <li key={`${step}-${index}`} className="flex gap-2"><span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{index + 1}</span><span>{step}</span></li>)}</ol></div>}{selectedArticle.escalation_rule && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex gap-2"><ShieldAlert className="mt-0.5 h-4 w-4 flex-none text-amber-700" /><div><p className="text-sm font-semibold text-amber-950">需要升级确认</p><p className="mt-1 text-sm leading-6 text-amber-900">{selectedArticle.escalation_rule}</p></div></div></div>}<DialogFooter><Button onClick={() => void copyAnswer(selectedArticle)}><Copy className="mr-1.5 h-4 w-4" />复制标准答复</Button></DialogFooter></div>}</DialogContent></Dialog>

    <Dialog open={editorOpen} onOpenChange={setEditorOpen}><DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{editorArticle ? '编辑知识卡' : '新建知识卡'}</DialogTitle></DialogHeader><div className="grid gap-4 sm:grid-cols-2"><div><Label>销售过程分类</Label><NativeSelect value={articleForm.category} onChange={value => { setArticleForm(current => ({ ...current, category: value })); setCustomCategory(''); }} options={allCategories.map(item => ({ value: item, label: item }))} /></div><div><Label>新分类名称（选填）</Label><Input value={customCategory} onChange={event => setCustomCategory(event.target.value)} placeholder="没有合适分类时直接输入" /></div><div><Label>排序数字</Label><Input type="number" value={articleForm.sort_order} onChange={event => setArticleForm(current => ({ ...current, sort_order: event.target.value }))} /></div><div className="flex items-end"><p className="pb-2 text-xs text-slate-500">排序越小越靠前；新分类保存后会自动出现在分类栏。</p></div><div className="sm:col-span-2"><Label>标题</Label><Input value={articleForm.title} onChange={event => setArticleForm(current => ({ ...current, title: event.target.value }))} placeholder="例如：客户怎么付款？" /></div><div className="sm:col-span-2"><Label>客户问题</Label><Input value={articleForm.customer_question} onChange={event => setArticleForm(current => ({ ...current, customer_question: event.target.value }))} placeholder="销售常遇到的原始问法" /></div><div className="sm:col-span-2"><Label>标准答复</Label><Textarea rows={6} value={articleForm.standard_answer} onChange={event => setArticleForm(current => ({ ...current, standard_answer: event.target.value }))} placeholder="销售可直接参考并按实际情况表达的答复" /></div><div className="sm:col-span-2"><Label>执行步骤（每行一条）</Label><Textarea rows={4} value={articleForm.action_steps} onChange={event => setArticleForm(current => ({ ...current, action_steps: event.target.value }))} placeholder={'先确认客户购买的服务\n再发送正确的付款说明\n提交财务确认'} /></div><div className="sm:col-span-2"><Label>何时需要升级确认</Label><Textarea rows={3} value={articleForm.escalation_rule} onChange={event => setArticleForm(current => ({ ...current, escalation_rule: event.target.value }))} placeholder="如涉及折扣、退款、特殊价格或效果承诺..." /></div><div><Label>标签（用逗号分隔）</Label><Input value={articleForm.tags} onChange={event => setArticleForm(current => ({ ...current, tags: event.target.value }))} placeholder="付款，Stripe，收款" /></div><label className="mt-6 flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={articleForm.is_sensitive} onChange={event => setArticleForm(current => ({ ...current, is_sensitive: event.target.checked }))} />内部敏感信息</label><label className="sm:col-span-2 flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={publishNow} onChange={event => setPublishNow(event.target.checked)} />保存后立即发布给销售查看</label></div><DialogFooter><Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button><Button disabled={saving} onClick={() => void saveArticle()}>{saving ? '保存中...' : '保存知识卡'}</Button></DialogFooter></DialogContent></Dialog>

    <Dialog open={questionOpen} onOpenChange={setQuestionOpen}><DialogContent><DialogHeader><DialogTitle>提交销售新问题</DialogTitle></DialogHeader><div className="space-y-4"><p className="text-sm text-slate-500">把客户的原话和具体场景留下来，销售主管会整理为统一的标准答复。</p><div><Label>客户问了什么？</Label><Textarea rows={4} value={questionForm.question} onChange={event => setQuestionForm(current => ({ ...current, question: event.target.value }))} placeholder="例如：客户问广告费是否包含在代运营套餐中？" /></div><div><Label>补充场景（可选）</Label><Textarea rows={3} value={questionForm.context} onChange={event => setQuestionForm(current => ({ ...current, context: event.target.value }))} placeholder="客户行业、正在讨论的套餐、已承诺内容等" /></div><DialogFooter><Button variant="outline" onClick={() => setQuestionOpen(false)}>取消</Button><Button disabled={saving} onClick={() => void submitQuestion()}><Send className="mr-1.5 h-4 w-4" />提交问题</Button></DialogFooter></div></DialogContent></Dialog>
  </div>;
}
