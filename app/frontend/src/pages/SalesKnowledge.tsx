import { useEffect, useMemo, useState } from 'react';
import { BookOpen, CircleHelp, Copy, MessageSquareText, Pencil, Plus, Search, Send, ShieldAlert } from 'lucide-react';
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
import { getFullKnowledgeAnswer, getShortKnowledgeAnswer, type SalesKnowledgeArticle } from '@/lib/sales-knowledge';
import { invokeWithAuth } from '@/lib/tokenStore';

type Article = SalesKnowledgeArticle;

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

  const copyText = async (content: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(content);
      toast.success(successMessage);
    } catch {
      toast.error('复制失败，请手动选择内容复制');
    }
  };

  const copyAnswer = async (article: Article) => {
    await copyText(getFullKnowledgeAnswer(article), '完整答复已复制，可按实际情况调整后发送');
  };

  const copyShortAnswer = async (article: Article) => {
    await copyText(getShortKnowledgeAnswer(article.standard_answer), '电话短版话术已复制');
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
  const activeArticle = useMemo(
    () => articles.find(item => item.id === selectedArticle?.id) || articles[0] || null,
    [articles, selectedArticle?.id],
  );

  return (
    <div className="knowledge-v4-page app-page">
      <header className="knowledge-v4-header app-page-title">
        <div>
          <p className="app-page-kicker"><BookOpen className="h-4 w-4" /> Sales Enablement</p>
          <h2 className="app-page-heading">销售知识库</h2>
          <p className="app-page-description">输入客户原话，快速找到可直接表达的短版话术、完整答复和升级规则。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setQuestionOpen(true)}><CircleHelp className="mr-1.5 h-4 w-4" />提交新问题</Button>
          {canManage ? <Button onClick={() => openEditor()}><Plus className="mr-1.5 h-4 w-4" />新建知识卡</Button> : null}
        </div>
      </header>

      <div className="knowledge-v4-toolbar">
        <div className="knowledge-v4-search">
          <Search className="h-4 w-4" />
          <Input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="直接输入客户原话：太贵、已有系统、怎么付款、能保证排名吗…"
            aria-label="搜索销售知识库"
          />
        </div>
        <div className="knowledge-v4-summary">
          <span><b>{articles.filter(item => item.status === 'published').length}</b> 条可用答复</span>
          {canManage ? <span><b>{openQuestions.length}</b> 个待补充问题</span> : null}
        </div>
      </div>

      <div className="knowledge-v4-workspace">
        <aside className="knowledge-v4-categories" aria-label="知识分类">
          <div className="knowledge-v4-panel-title">
            <span>销售场景</span>
            <small>按流程筛选</small>
          </div>
          <nav>
            {['全部', ...allCategories].map(item => (
              <button key={item} type="button" className={category === item ? 'is-active' : ''} onClick={() => setCategory(item)}>
                <span>{item}</span>
                {category === item ? <span aria-hidden="true">›</span> : null}
              </button>
            ))}
          </nav>
          <div className="knowledge-v4-rule">
            <ShieldAlert className="h-4 w-4" />
            <div>
              <b>先确认再承诺</b>
              <p>折扣、退款、定制、效果保证和到账状态必须升级确认。</p>
            </div>
          </div>
        </aside>

        <section className="knowledge-v4-list" aria-label="知识卡列表">
          <div className="knowledge-v4-panel-title">
            <span>{category === '全部' ? '匹配结果' : category}</span>
            <small>{loading ? '读取中' : `${articles.length} 条`}</small>
          </div>
          <div className="knowledge-v4-list-scroll">
            {loading ? <p className="knowledge-v4-empty">正在加载销售知识卡…</p> : articles.length === 0 ? (
              <div className="knowledge-v4-empty">
                <MessageSquareText className="mx-auto mb-2 h-5 w-5" />
                <p>没有匹配的知识卡</p>
                <Button className="mt-3" size="sm" variant="outline" onClick={() => setQuestionOpen(true)}>提交这个问题</Button>
              </div>
            ) : articles.map(article => (
              <button
                key={article.id}
                type="button"
                className={`knowledge-v4-list-item ${activeArticle?.id === article.id ? 'is-active' : ''}`}
                onClick={() => setSelectedArticle(article)}
              >
                <span className="knowledge-v4-list-meta">
                  <span>{article.category}</span>
                  {article.is_sensitive ? <span className="is-sensitive">内部信息</span> : null}
                  {article.status === 'draft' ? <span className="is-draft">草稿</span> : null}
                </span>
                <strong>{article.title}</strong>
                <p>{article.customer_question || '适用于相关销售场景'}</p>
                <small>{getShortKnowledgeAnswer(article.standard_answer, 88)}</small>
              </button>
            ))}
          </div>
        </section>

        <article className="knowledge-v4-detail" aria-live="polite">
          {activeArticle ? (
            <>
              <div className="knowledge-v4-detail-head">
                <div>
                  <div className="flex flex-wrap gap-2">
                    <Badge className="bg-blue-50 text-blue-700">{activeArticle.category}</Badge>
                    {activeArticle.is_sensitive ? <Badge className="bg-amber-100 text-amber-800">仅内部销售使用</Badge> : null}
                    {activeArticle.status === 'draft' ? <Badge className="bg-violet-100 text-violet-700">草稿</Badge> : null}
                  </div>
                  <h3>{activeArticle.title}</h3>
                  <p>客户问：{activeArticle.customer_question || '适用于此类问题'}</p>
                </div>
                {canManage ? <Button size="icon" variant="ghost" title="编辑知识卡" onClick={() => openEditor(activeArticle)}><Pencil className="h-4 w-4" /></Button> : null}
              </div>

              <section className="knowledge-v4-short-answer">
                <div>
                  <span>电话短版</span>
                  <small>约 15–30 秒</small>
                </div>
                <p>{getShortKnowledgeAnswer(activeArticle.standard_answer)}</p>
                <Button size="sm" onClick={() => void copyShortAnswer(activeArticle)}><Copy className="mr-1.5 h-4 w-4" />复制短版话术</Button>
              </section>

              <section className="knowledge-v4-full-answer">
                <div className="flex items-center justify-between gap-3">
                  <h4>完整标准答复</h4>
                  <Button size="sm" variant="outline" onClick={() => void copyAnswer(activeArticle)}><Copy className="mr-1.5 h-4 w-4" />复制完整答复</Button>
                </div>
                <p>{activeArticle.standard_answer}</p>
              </section>

              {activeArticle.action_steps.length > 0 ? (
                <section className="knowledge-v4-steps">
                  <h4>执行步骤</h4>
                  <ol>
                    {activeArticle.action_steps.map((step, index) => (
                      <li key={`${step}-${index}`}><span>{index + 1}</span><p>{step}</p></li>
                    ))}
                  </ol>
                </section>
              ) : null}

              {activeArticle.escalation_rule ? (
                <section className="knowledge-v4-escalation">
                  <ShieldAlert className="h-5 w-5" />
                  <div><h4>需要升级确认</h4><p>{activeArticle.escalation_rule}</p></div>
                </section>
              ) : null}

              {activeArticle.tags.length > 0 ? (
                <div className="knowledge-v4-tags">{activeArticle.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
              ) : null}
            </>
          ) : <p className="knowledge-v4-empty">选择一个问题查看可用话术。</p>}
        </article>
      </div>

      {canManage && openQuestions.length > 0 ? (
        <Card className="border-amber-200 bg-amber-50/60 shadow-sm">
          <CardContent className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <CircleHelp className="h-5 w-5 text-amber-700" />
              <div><p className="font-semibold text-amber-950">销售待解答问题</p><p className="text-xs text-amber-800">补充知识卡后再标记完成。</p></div>
            </div>
            <div className="space-y-2">
              {openQuestions.slice(0, 6).map(item => (
                <div key={item.id} className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-white/80 p-3 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1"><p className="text-sm font-medium text-slate-900">{item.question}</p><p className="mt-1 text-xs text-slate-500">{item.context || '未补充场景'} · {item.submitted_by_name || '销售'} · {formatDate(item.created_at)}</p></div>
                  <Button size="sm" variant="outline" onClick={() => void resolveQuestion(item)}>标记已处理</Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
          <DialogHeader><DialogTitle>{editorArticle ? '编辑知识卡' : '新建知识卡'}</DialogTitle></DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div><Label>销售过程分类</Label><NativeSelect value={articleForm.category} onChange={value => { setArticleForm(current => ({ ...current, category: value })); setCustomCategory(''); }} options={allCategories.map(item => ({ value: item, label: item }))} /></div>
            <div><Label>新分类名称（选填）</Label><Input value={customCategory} onChange={event => setCustomCategory(event.target.value)} placeholder="没有合适分类时直接输入" /></div>
            <div><Label>排序数字</Label><Input type="number" value={articleForm.sort_order} onChange={event => setArticleForm(current => ({ ...current, sort_order: event.target.value }))} /></div>
            <div className="flex items-end"><p className="pb-2 text-xs text-slate-500">排序越小越靠前；新分类保存后会自动出现在分类栏。</p></div>
            <div className="sm:col-span-2"><Label>标题</Label><Input value={articleForm.title} onChange={event => setArticleForm(current => ({ ...current, title: event.target.value }))} placeholder="例如：客户怎么付款？" /></div>
            <div className="sm:col-span-2"><Label>客户问题</Label><Input value={articleForm.customer_question} onChange={event => setArticleForm(current => ({ ...current, customer_question: event.target.value }))} placeholder="销售常遇到的原始问法" /></div>
            <div className="sm:col-span-2"><Label>标准答复</Label><Textarea rows={6} value={articleForm.standard_answer} onChange={event => setArticleForm(current => ({ ...current, standard_answer: event.target.value }))} placeholder="销售可直接参考并按实际情况表达的答复" /></div>
            <div className="sm:col-span-2"><Label>执行步骤（每行一条）</Label><Textarea rows={4} value={articleForm.action_steps} onChange={event => setArticleForm(current => ({ ...current, action_steps: event.target.value }))} placeholder={'先确认客户购买的服务\n再发送正确的付款说明\n提交财务确认'} /></div>
            <div className="sm:col-span-2"><Label>何时需要升级确认</Label><Textarea rows={3} value={articleForm.escalation_rule} onChange={event => setArticleForm(current => ({ ...current, escalation_rule: event.target.value }))} placeholder="如涉及折扣、退款、特殊价格或效果承诺..." /></div>
            <div><Label>标签（用逗号分隔）</Label><Input value={articleForm.tags} onChange={event => setArticleForm(current => ({ ...current, tags: event.target.value }))} placeholder="付款，Stripe，收款" /></div>
            <label className="mt-6 flex min-h-11 items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={articleForm.is_sensitive} onChange={event => setArticleForm(current => ({ ...current, is_sensitive: event.target.checked }))} />内部敏感信息</label>
            <label className="flex min-h-11 items-center gap-2 text-sm text-slate-700 sm:col-span-2"><input type="checkbox" checked={publishNow} onChange={event => setPublishNow(event.target.checked)} />保存后立即发布给销售查看</label>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button><Button disabled={saving} onClick={() => void saveArticle()}>{saving ? '保存中...' : '保存知识卡'}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={questionOpen} onOpenChange={setQuestionOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>提交销售新问题</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-500">把客户的原话和具体场景留下来，销售主管会整理为统一的标准答复。</p>
            <div><Label>客户问了什么？</Label><Textarea rows={4} value={questionForm.question} onChange={event => setQuestionForm(current => ({ ...current, question: event.target.value }))} placeholder="例如：客户问广告费是否包含在代运营套餐中？" /></div>
            <div><Label>补充场景（可选）</Label><Textarea rows={3} value={questionForm.context} onChange={event => setQuestionForm(current => ({ ...current, context: event.target.value }))} placeholder="客户行业、正在讨论的套餐、已承诺内容等" /></div>
            <DialogFooter><Button variant="outline" onClick={() => setQuestionOpen(false)}>取消</Button><Button disabled={saving} onClick={() => void submitQuestion()}><Send className="mr-1.5 h-4 w-4" />提交问题</Button></DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
