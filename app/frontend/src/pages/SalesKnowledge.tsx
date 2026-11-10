import '@/pages/crm-sales-visual-polish.css';
import { CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, ChevronRight, CircleHelp, Copy, MoreHorizontal, MessageSquareText, Pencil, Plus, Search, Send, ShieldAlert, X } from 'lucide-react';
import { toast } from 'sonner';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import '@/components/sales-center.css';
import './sales-workspace.css';
import './sales-knowledge-refined.css';
import './crm-sales-compact.css';
import './sales-ui-clarity.css';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useIsMobile } from '@/hooks/use-mobile';
import { useRole } from '@/lib/role-context';
import {
  getFullKnowledgeAnswer, getPhoneKnowledgeAnswer, getKnowledgeCopyBlockReason,
  knowledgeProductOptions, knowledgeStoreOptions, knowledgeAvailabilityOptions,
  knowledgeProductLabel, knowledgeAvailabilityLabel, matchesKnowledgeProduct,
  type SalesKnowledgeArticle, type BeautyKnowledgePackPreview,
} from '@/lib/sales-knowledge';
import { invokeWithAuth } from '@/lib/tokenStore';

type Article = SalesKnowledgeArticle;
type KnowledgeQuestion = { id: number; question: string; context?: string; status: 'open' | 'resolved'; submitted_by_name?: string; created_at?: string };
type ArticleForm = {
  category: string; title: string; customer_question: string; standard_answer: string; phone_answer: string;
  followup_question: string; demo_steps: string; next_action: string; internal_notes: string;
  product_scope: string; store_types: string[]; availability: string; high_frequency: boolean;
  action_steps: string; escalation_rule: string; tags: string; is_sensitive: boolean; sort_order: string;
};
const beautyCategoryOptions = ['首拨核验', '需求诊断', '功能与场景', '异议处理', '演示邀约', '试用与回访', '成交与交接', '边界与售后'];
const categoryOptions = ['销售准备与开场', '需求诊断', '产品与服务', '套餐与报价', '异议与合规', '收款与付款', '成交与交接', '售后与升级', '销售红线', '其他'];
const emptyArticleForm = (): ArticleForm => ({
  category: '其他', title: '', customer_question: '', standard_answer: '', phone_answer: '', followup_question: '', demo_steps: '',
  next_action: '', internal_notes: '', product_scope: 'beautyos', store_types: [], availability: 'pending_confirmation', high_frequency: false,
  action_steps: '', escalation_rule: '', tags: '', is_sensitive: false, sort_order: '200',
});
const formatDate = (value?: string) => value ? value.slice(0, 16).replace('T', ' ') : '待记录';
const splitLines = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean);
const splitTags = (value: string) => value.split(/[，,]/).map(item => item.trim()).filter(Boolean);
const errorMessage = (error: any, fallback: string) => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : typeof error?.data?.detail === 'string' ? error.data.detail : error?.message || fallback;
const statusCode = (error: any) => error?.response?.status || error?.data?.status || error?.status;

function KnowledgeArticleDetail({ article, canManage, onEdit, onCopyShort, onCopyFull, preview = false }: {
  article: Article; canManage: boolean; onEdit: (article: Article) => void; onCopyShort: (article: Article) => void; onCopyFull: (article: Article) => void; preview?: boolean;
}) {
  const shortBlocked = getKnowledgeCopyBlockReason(article, 'phone');
  const fullBlocked = getKnowledgeCopyBlockReason(article, 'full');
  const hasInternal = article.is_sensitive || article.internal_notes || article.escalation_rule || article.action_steps?.length;
  return <div className="knowledge-v4-detail-content">
    <div className="knowledge-v4-detail-head">
      <div>
        <div className="sk-detail-badges">
          <Badge className="bg-blue-50 text-blue-700">{knowledgeProductLabel(article.product_scope)}</Badge>
          <Badge className="bg-slate-100 text-slate-700">{article.category}</Badge>
          {article.high_frequency && <Badge className="bg-emerald-50 text-emerald-800">新销售必读</Badge>}
          {article.is_sensitive && <Badge className="bg-amber-100 text-amber-800">内部信息待核对</Badge>}
          {article.status === 'draft' && <Badge className="bg-violet-100 text-violet-700">{preview ? '待添加预览' : '本次修改为草稿'}</Badge>}
          {(article.legacy_profile ?? !article.revision) && <Badge className="bg-slate-100 text-slate-600">历史口径待复核</Badge>}
        </div>
        <h3>{article.title}</h3>
        <p>客户问：{article.customer_question || '适用于此类问题'}</p>
      </div>
      {canManage && <Button size="icon" variant="ghost" aria-label="编辑知识卡" title="编辑知识卡" onClick={() => onEdit(article)}><Pencil className="h-4 w-4" /></Button>}
    </div>
    <div className={`sk-capability-note ${article.availability === 'ready' ? 'is-ready' : ''}`}>
      <span>{knowledgeAvailabilityLabel(article.availability)}</span>
      {article.store_types?.length ? <p>适用门店：{article.store_types.join('、')}</p> : null}
      {article.availability === 'requires_setup' && <p>演示或承诺前，先确认该门店已开通并完成对应配置。</p>}
      {article.availability === 'pending_confirmation' && <p>具体条件请先核实；对客户使用下方已整理的答复，内部待确认事项不随话术复制。</p>}
    </div>
    {article.is_sensitive ? <section className="sk-internal-warning" role="note"><ShieldAlert className="h-5 w-5" /><div><p>这张卡属于内部信息，尚未整理为可直接给客户的答复。请先核对口径，复制功能已停用。</p><div className="mt-3 flex flex-wrap gap-2"><Button disabled>复制短版话术</Button><Button disabled variant="outline">复制完整答复</Button></div></div></section> : <Tabs defaultValue="short" className="sk-answer-tabs">
      <TabsList aria-label="答复版本"><TabsTrigger value="short">电话话术</TabsTrigger><TabsTrigger value="full">完整答复</TabsTrigger></TabsList>
      <TabsContent value="short" className="knowledge-v4-short-answer">
        <div><span>电话短版</span><small>约 15–30 秒</small></div>
        <p>{article.phone_answer?.trim() || '电话短版尚未整理，请查看完整答复。'}</p>
        {shortBlocked && <p className="sk-copy-note">{shortBlocked}</p>}
        <Button disabled={Boolean(shortBlocked)} onClick={() => onCopyShort(article)}><Copy className="mr-1.5 h-4 w-4" />复制短版话术</Button>
      </TabsContent>
      <TabsContent value="full" className="knowledge-v4-full-answer">
        <p>{article.standard_answer}</p>
        {fullBlocked && <p className="sk-copy-note">{fullBlocked}</p>}
        <Button disabled={Boolean(fullBlocked)} variant="outline" onClick={() => onCopyFull(article)}><Copy className="mr-1.5 h-4 w-4" />复制完整答复</Button>
      </TabsContent>
    </Tabs>}
    {article.followup_question && <section className="sk-followup"><h4>接着问一句</h4><p>{article.followup_question}</p></section>}
    {!!article.demo_steps?.length && <section className="knowledge-v4-steps"><h4>对应演示</h4><ol>{article.demo_steps.map((step, index) => <li key={`${index}-${step}`}><span>{index + 1}</span><p>{step}</p></li>)}</ol></section>}
    {article.next_action && <section className="sk-next-action"><h4>下一步</h4><p>{article.next_action}</p></section>}
    {hasInternal && <details className="sk-internal-guidance" open={article.is_sensitive}>
      <summary><ShieldAlert className="h-4 w-4" />内部提醒 · 不随答复复制</summary>
      {article.is_sensitive && <p>{article.standard_answer}</p>}
      {article.internal_notes && <p>{article.internal_notes}</p>}
      {!!article.action_steps?.length && <section><h4>销售执行步骤</h4><ol>{article.action_steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol></section>}
      {article.escalation_rule && <section className="knowledge-v4-escalation"><h4>需要升级确认</h4><p>{article.escalation_rule}</p></section>}
    </details>}
    {!!article.tags?.length && <div className="knowledge-v4-tags">{article.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}
    <div className="sk-review-meta">{preview ? <p>话术包预览，添加并发布后供销售使用。</p> : <><p>{article.revision ? `${article.status === 'draft' ? '草稿' : '已发布'}修订 ${article.revision} · ` : ''}{article.status === 'published' ? `发布人：${article.published_by_name || '待记录'} · ${formatDate(article.published_at)}` : `最近修改：${formatDate(article.updated_at)}`}</p>{article.reviewed_by_name && <p>核对人：{article.reviewed_by_name} · {formatDate(article.reviewed_at)}</p>}{article.status === 'draft' && Boolean(article.published_revision) && <p>销售继续使用已发布修订 {article.published_revision}，本次草稿尚未替换对外口径。</p>}</>}</div>
  </div>;
}

export default function SalesKnowledge() {
  const { role, isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const canManage = isAdmin || role === 'sales_manager';
  const [articles, setArticles] = useState<Article[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [questions, setQuestions] = useState<KnowledgeQuestion[]>([]);
  const [questionsError, setQuestionsError] = useState(false);
  const recentKey = `t24:knowledge-recent:${employee?.id}:${role}`;
  const [recentIds, setRecentIds] = useState<number[]>([]);
  useEffect(() => { try { const value = JSON.parse(sessionStorage.getItem(recentKey) || '[]'); setRecentIds(Array.isArray(value) ? value.filter(id => Number.isSafeInteger(id) && id > 0).slice(0, 5) : []); } catch { setRecentIds([]); } }, [recentKey]);
  const [loadState, setLoadState] = useState({ key: '', loading: true, error: '' });
  const [loadedKey, setLoadedKey] = useState('');
  const knowledgeRequestRef = useRef(0);
  const [query, setQuery] = useState('');
  const [visibleCount, setVisibleCount] = useState(20);
  const searchRef = useRef<HTMLInputElement>(null);
  const returnToFilters = () => { searchRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); searchRef.current?.focus({ preventScroll: true }); };
  const [category, setCategory] = useState('全部');
  const [productScope, setProductScope] = useState('beautyos');
  const [storeType, setStoreType] = useState('');
  const [highFrequency, setHighFrequency] = useState(false);
  const requestKey = JSON.stringify([employee?.id, role, canManage, query, category, productScope, storeType, highFrequency]);
  useEffect(() => setVisibleCount(20), [requestKey]);
  const currentView = useRef({ key: requestKey, query, category, productScope, storeType, highFrequency, canManage });
  if (currentView.current.key !== requestKey) knowledgeRequestRef.current++;
  currentView.current = { key: requestKey, query, category, productScope, storeType, highFrequency, canManage };
  const loadError = loadState.key === requestKey ? loadState.error : '';
  const loading = loadState.key !== requestKey || loadState.loading;
  const currentArticles = loadedKey === requestKey && !loadError ? articles.filter(article => matchesKnowledgeProduct(article, productScope)) : [];
  const [selectedArticleId, setSelectedArticleId] = useState<number | null>(null);
  const [editorArticle, setEditorArticle] = useState<Article | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [articleForm, setArticleForm] = useState<ArticleForm>(emptyArticleForm);
  const [customCategory, setCustomCategory] = useState('');
  const [publishNow, setPublishNow] = useState(false);
  const [editorError, setEditorError] = useState('');
  const [conflictArticle, setConflictArticle] = useState<Article | null>(null);
  const [conflictLoading, setConflictLoading] = useState(false);
  const [questionOpen, setQuestionOpen] = useState(false);
  const [questionForm, setQuestionForm] = useState({ question: '', context: '' });
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const editorBaseline = useRef('');
  const questionBaseline = useRef('');
  const editorGuard = useUnsavedChanges(editorOpen && JSON.stringify({ articleForm, customCategory, publishNow }) !== editorBaseline.current);
  const questionGuard = useUnsavedChanges(questionOpen && JSON.stringify(questionForm) !== questionBaseline.current);
  const [packOpen, setPackOpen] = useState(false);
  const [packLoading, setPackLoading] = useState(false);
  const [packInstalling, setPackInstalling] = useState(false);
  const [packPreview, setPackPreview] = useState<BeautyKnowledgePackPreview | null>(null);
  const [packError, setPackError] = useState('');
  const [packResult, setPackResult] = useState('');
  const [packSelected, setPackSelected] = useState(0);
  const rememberArticle = (id: number) => { const next = [id, ...recentIds.filter(value => value !== id)].slice(0, 5); setRecentIds(next); try { sessionStorage.setItem(recentKey, JSON.stringify(next)); } catch { /* Optional recent list. */ } };
  const openQuestion = () => {
    setQuestionError(null);
    const scope = productScope ? `适用产品：${knowledgeProductLabel(productScope)}` : '适用产品：全部产品';
    const initial = { question: questionForm.question || query.trim(), context: questionForm.context || [scope, category !== '全部' ? `知识分类：${category}` : '', storeType ? `门店类型：${storeType}` : ''].filter(Boolean).join('；') };
    questionBaseline.current = JSON.stringify(initial); setQuestionForm(initial); setQuestionOpen(true);
  };
  const loadKnowledge = async () => {
    const view = currentView.current, requestId = ++knowledgeRequestRef.current;
    setLoadState({ key: view.key, loading: true, error: '' });
    try {
      const params = new URLSearchParams({ include_general: 'false' });
      if (view.query.trim()) params.set('query', view.query.trim());
      if (view.category !== '全部') params.set('category', view.category);
      if (view.productScope) params.set('product_scope', view.productScope);
      if (view.storeType) params.set('store_type', view.storeType);
      if (view.highFrequency) params.set('high_frequency', 'true');
      if (view.canManage) params.set('include_all', 'true');
      const response = await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?${params}`, method: 'GET' });
      if (requestId !== knowledgeRequestRef.current || view.key !== currentView.current.key) return;
      if (!Array.isArray(response.data?.items)) throw new Error('销售知识卡未完整返回，请重新加载。');
      setArticles(response.data.items); setCategories(response.data.categories || []); setLoadedKey(view.key);
      setLoadState({ key: view.key, loading: false, error: '' });
    } catch (error: any) {
      if (requestId === knowledgeRequestRef.current && view.key === currentView.current.key) { setArticles([]); setLoadedKey(''); setLoadState({ key: view.key, loading: false, error: errorMessage(error, '销售知识库加载失败') }); }
    }
  };
  const loadQuestions = async () => {
    if (!canManage) { setQuestions([]); return; }
    try { const response = await invokeWithAuth({ url: '/api/v1/sales-knowledge/questions', method: 'GET' }); setQuestions(response.data?.items || []); setQuestionsError(false); }
    catch { setQuestionsError(true); }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => { void loadKnowledge(); }, 160);
    return () => { window.clearTimeout(timer); knowledgeRequestRef.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);
  useEffect(() => { void loadQuestions(); }, [canManage]);

  const openEditor = (article?: Article) => {
    const form = article ? {
      category: article.category, title: article.title, customer_question: article.customer_question || '', standard_answer: article.standard_answer,
      phone_answer: article.phone_answer || '', followup_question: article.followup_question || '', demo_steps: (article.demo_steps || []).join('\n'),
      next_action: article.next_action || '', internal_notes: article.internal_notes || '', product_scope: article.product_scope || 'general',
      store_types: article.store_types || [], availability: article.availability || 'pending_confirmation', high_frequency: Boolean(article.high_frequency),
      action_steps: (article.action_steps || []).join('\n'), escalation_rule: article.escalation_rule || '', tags: (article.tags || []).join('，'),
      is_sensitive: article.is_sensitive, sort_order: String(article.sort_order ?? 200),
    } : emptyArticleForm();
    setEditorArticle(article || null); setArticleForm(form); setPublishNow(false); setCustomCategory(''); setEditorError(''); setConflictArticle(null);
    editorBaseline.current = JSON.stringify({ articleForm: form, customCategory: '', publishNow: false }); setEditorOpen(true);
  };
  const copyAnswer = async (article: Article, version: 'phone' | 'full') => {
    const blocked = getKnowledgeCopyBlockReason(article, version);
    if (blocked) { toast.error(blocked); return; }
    try { await navigator.clipboard.writeText(version === 'phone' ? getPhoneKnowledgeAnswer(article) : getFullKnowledgeAnswer(article)); toast.success(version === 'phone' ? '电话短版话术已复制' : '对外完整答复已复制'); rememberArticle(article.id); }
    catch { toast.error('复制失败，请手动选择对外答复复制'); }
  };
  const saveArticle = async () => {
    if (!articleForm.title.trim() || !articleForm.standard_answer.trim()) { setEditorError('请填写标题和完整对外答复。'); return; }
    if (publishNow && !articleForm.is_sensitive && !articleForm.phone_answer.trim()) { setEditorError('发布前请单独整理电话短版，不能直接截取完整答复。'); return; }
    setSaving(true); setEditorError('');
    const payload = {
      category: customCategory.trim() || articleForm.category, title: articleForm.title.trim(), customer_question: articleForm.customer_question.trim() || null,
      standard_answer: articleForm.standard_answer.trim(), phone_answer: articleForm.phone_answer.trim(),
      followup_question: articleForm.followup_question.trim(), demo_steps: splitLines(articleForm.demo_steps), next_action: articleForm.next_action.trim(),
      internal_notes: articleForm.internal_notes.trim(), product_scope: articleForm.product_scope,
      store_types: articleForm.store_types, availability: articleForm.availability, high_frequency: articleForm.high_frequency,
      action_steps: splitLines(articleForm.action_steps), related_links: editorArticle?.related_links || [], escalation_rule: articleForm.escalation_rule.trim() || null,
      tags: splitTags(articleForm.tags), is_sensitive: articleForm.is_sensitive, sort_order: Number.isSafeInteger(Number(articleForm.sort_order)) ? Number(articleForm.sort_order) : 200,
      ...(editorArticle ? { expected_revision: editorArticle.revision || 0 } : {}),
    };
    let savedDraft = false;
    try {
      if (editorArticle) {
        const response = await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles/${editorArticle.id}`, method: 'PUT', data: payload });
        if (!Number.isSafeInteger(response.data?.revision)) throw new Error('保存回执未完整返回，请查看最新版本核对结果。');
        savedDraft = true;
        setEditorArticle({ ...editorArticle, ...response.data });
        if (publishNow) await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles/${editorArticle.id}/publish`, method: 'POST', data: { expected_revision: response.data.revision } });
      } else await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?publish_now=${publishNow}`, method: 'POST', data: payload });
      toast.success(publishNow ? '知识卡已发布给销售' : '草稿已保存，已发布口径继续保留'); editorGuard.markSaved(); setEditorOpen(false); await Promise.all([loadKnowledge(), loadQuestions()]);
    } catch (error: any) {
      setEditorError(statusCode(error) === 409 ? '内容已被其他人更新，当前输入已保留。请查看最新版本后再合并修改。' : savedDraft ? '草稿已保存，发布结果尚未确认。请查看最新版本核对发布状态，当前输入已保留。' : errorMessage(error, '保存结果尚未确认，当前输入已保留。请先核对最新知识卡再重试。'));
    } finally { setSaving(false); }
  };
  const readLatestArticle = async () => {
    if (!editorArticle) return; setConflictLoading(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-knowledge/articles?include_all=true&include_general=false', method: 'GET' });
      const latest = (response.data?.items || []).find((item: Article) => item.id === editorArticle.id);
      if (!latest) throw new Error('该知识卡已不可编辑，请保留当前输入并联系主管。');
      setConflictArticle(latest);
    } catch (error: any) { setEditorError(errorMessage(error, '最新版本读取失败，当前输入已保留。')); }
    finally { setConflictLoading(false); }
  };
  const submitQuestion = async () => {
    if (questionForm.question.trim().length < 3) { setQuestionError('请写清楚客户提出的问题'); return; }
    setQuestionError(null); setSaving(true);
    try {
      await invokeWithAuth({ url: '/api/v1/sales-knowledge/questions', method: 'POST', data: { question: questionForm.question.trim(), context: questionForm.context.trim() || null } });
      toast.success('问题已提交给销售主管'); setQuestionForm({ question: '', context: '' }); questionGuard.markSaved(); setQuestionOpen(false); await loadQuestions();
    } catch (error: any) { setQuestionError(errorMessage(error, '问题提交失败')); }
    finally { setSaving(false); }
  };
  const resolveQuestion = async (question: KnowledgeQuestion) => {
    if (!window.confirm(`确认将“${question.question}”标记为已处理？请先确保已有对应知识卡。`)) return;
    try { await invokeWithAuth({ url: `/api/v1/sales-knowledge/questions/${question.id}/resolve`, method: 'POST', data: {} }); toast.success('问题已标记为已处理'); await loadQuestions(); }
    catch (error: any) { toast.error(errorMessage(error, '处理失败')); }
  };
  const previewPack = async () => {
    setPackOpen(true); setPackLoading(true); setPackError(''); setPackResult(''); setPackPreview(null); setPackSelected(0);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-knowledge/beautyos-pack/preview', method: 'POST', data: {} });
      const preview = response.data;
      if (!Array.isArray(preview?.items) || !/^[a-f0-9]{64}$/.test(preview.manifest_hash || '') || !['total', 'new_count', 'existing_count', 'high_frequency_count'].every(key => Number.isSafeInteger(preview[key]) && preview[key] >= 0) || preview.items.length !== preview.total || preview.new_count + preview.existing_count !== preview.total || preview.high_frequency_count > preview.total) throw new Error('话术清单未完整返回，请重新预览。');
      setPackPreview(preview);
    } catch (error: any) { setPackError(errorMessage(error, '美业话术包暂时无法读取，请重新预览。')); }
    finally { setPackLoading(false); }
  };
  const installPack = async () => {
    if (!packPreview || packInstalling || packPreview.new_count === 0) return;
    setPackInstalling(true); setPackError('');
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-knowledge/beautyos-pack/install', method: 'POST', data: { manifest_hash: packPreview.manifest_hash, publish_now: true } });
      const installed = response.data?.installed_count, skipped = response.data?.skipped_count;
      if (!Number.isSafeInteger(installed) || !Number.isSafeInteger(skipped) || installed < 0 || skipped < 0 || installed + skipped !== packPreview.total) throw new Error('添加结果待确认，请重新预览核对已存在数量。');
      setPackResult(`已添加并发布 ${installed} 条，已存在的 ${skipped} 条未重复添加。`);
      setPackPreview(current => current ? { ...current, existing_count: current.total, new_count: 0 } : current);
      await loadKnowledge();
    } catch (error: any) {
      setPackError(statusCode(error) === 409 ? '话术清单已更新，请重新预览后再添加。' : errorMessage(error, '添加结果待确认，请重新预览核对已存在数量后再操作。'));
      setPackPreview(null);
    } finally { setPackInstalling(false); }
  };
  const openQuestions = useMemo(() => questions.filter(item => item.status === 'open'), [questions]);
  const allCategories = useMemo(() => Array.from(new Set([...(loadedKey === requestKey ? categories : []), ...(productScope === 'beautyos' ? beautyCategoryOptions : productScope ? categoryOptions : [...beautyCategoryOptions, ...categoryOptions])])), [categories, productScope, loadedKey, requestKey]);
  const editorCategories = Array.from(new Set([...beautyCategoryOptions, ...categoryOptions, ...categories, articleForm.category]));
  const activeArticle = loading || loadError ? null : currentArticles.find(item => item.id === selectedArticleId) || currentArticles[0] || null;
  const packArticle = packPreview?.items[packSelected] ? { ...packPreview.items[packSelected], id: -(packSelected + 1), status: 'draft' as const, legacy_profile: false } : null;
  const details = activeArticle && <KnowledgeArticleDetail key={activeArticle.id} article={activeArticle} canManage={canManage} onEdit={openEditor} onCopyShort={article => void copyAnswer(article, 'phone')} onCopyFull={article => void copyAnswer(article, 'full')} />;

  return <div className="knowledge-v4-page knowledge-refined-page sales-center-ui calm-sales-page calm-sales-knowledge app-page crm-sales-compact">
    <header className="knowledge-v4-header sc-section-heading app-page-title"><div><h2 className="app-page-heading">销售知识库</h2><p className="sk-page-intro">先选产品和客户场景，再使用对应话术。</p></div><div className="sk-heading-actions">{isMobile ? <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="更多知识库操作"><MoreHorizontal size={19}/></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={openQuestion}>提交新问题</DropdownMenuItem>{canManage && <><DropdownMenuItem onSelect={() => void previewPack()}>美业 OS 话术包</DropdownMenuItem><DropdownMenuItem onSelect={() => openEditor()}>新建知识卡</DropdownMenuItem></>}</DropdownMenuContent></DropdownMenu> : <><Button variant="outline" onClick={openQuestion}><CircleHelp className="mr-1.5 h-4 w-4" />提交新问题</Button>{canManage && <><Button variant="outline" onClick={() => void previewPack()}>美业 OS 话术包</Button><Button onClick={() => openEditor()}><Plus className="mr-1.5 h-4 w-4" />新建知识卡</Button></>}</>}</div></header>
    <div className="knowledge-v4-toolbar"><div className="knowledge-v4-search"><Search className="h-4 w-4" /><Input ref={searchRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="直接输入客户原话：已有系统、没时间、预约怎么做…" aria-label="搜索销售知识库" />{query && <Button className="sk-clear-search" type="button" size="icon" variant="ghost" aria-label="清空知识库搜索" onClick={() => setQuery('')}><X className="h-4 w-4" /></Button>}</div></div>
    <div className="sk-product-filters" role="group" aria-label="知识库适用范围"><label><span>适用产品</span><NativeSelect value={productScope} onChange={value => { setProductScope(value); setCategory('全部'); setStoreType(''); setHighFrequency(false); }} options={knowledgeProductOptions} aria-label="筛选适用产品" /></label><label><span>门店类型</span><NativeSelect value={storeType} onChange={setStoreType} options={knowledgeStoreOptions} aria-label="筛选门店类型" /></label><Button variant={highFrequency ? 'default' : 'outline'} aria-pressed={highFrequency} onClick={() => setHighFrequency(value => !value)}>{productScope === 'beautyos' ? '新销售必读 20 条' : '高频话术'}</Button></div>
    {query === '' && category === '全部' && recentIds.some(id => currentArticles.some(article => article.id === id)) && <div className="sk-recent" aria-label="最近使用话术"><span>最近使用</span>{recentIds.map(id => currentArticles.find(article => article.id === id)).filter(Boolean).map(article => <Button key={article!.id} variant="ghost" size="sm" onClick={() => { setSelectedArticleId(article!.id); if (isMobile) setMobileDetailOpen(true); }}>{article!.title}</Button>)}</div>}
    <aside className="knowledge-v4-categories" aria-label="知识分类"><nav aria-label="按销售场景筛选">{['全部', ...allCategories].map(item => <button key={item} type="button" className={category === item ? 'is-active' : ''} aria-pressed={category === item} onClick={() => setCategory(item)}><span>{item}</span></button>)}</nav></aside>
    <div className="knowledge-v4-workspace"><section className="knowledge-v4-list" aria-label="知识卡列表"><div className="knowledge-v4-panel-title"><span>{category === '全部' ? `${productScope ? knowledgeProductLabel(productScope) : '全部产品'} · 匹配结果` : category}</span><small>{loading ? '读取中' : loadError ? '暂不可用' : `${currentArticles.length} 条`}</small></div><div className="knowledge-v4-list-scroll">
      {loading ? <p className="knowledge-v4-empty">正在加载销售知识卡…</p> : loadError ? <div className="knowledge-v4-empty" role="alert"><p>销售知识库暂时无法读取</p><p>{loadError}</p><Button className="mt-3" size="sm" variant="outline" onClick={() => void loadKnowledge()}>重新加载</Button></div> : currentArticles.length === 0 ? <div className="knowledge-v4-empty"><MessageSquareText className="mx-auto mb-2 h-5 w-5" /><p>没有匹配的知识卡</p><p>{query.trim() ? `“${query.trim()}”` : '可调整产品、门店或高频筛选。'}</p><Button className="mt-3" variant="outline" onClick={openQuestion}>提交这个问题</Button></div> : currentArticles.slice(0, visibleCount).map(article => <button key={article.id} type="button" aria-pressed={activeArticle?.id === article.id} className={`knowledge-v4-list-item ${activeArticle?.id === article.id ? 'is-active' : ''}`} onClick={() => { setSelectedArticleId(article.id); if (isMobile) setMobileDetailOpen(true); }}><strong>{article.title}</strong><span className="knowledge-v4-list-meta"><span>{knowledgeProductLabel(article.product_scope)} · {article.category}</span>{article.high_frequency && <span className="is-featured">必读</span>}{article.is_sensitive && <span className="is-sensitive">内部信息</span>}{article.status === 'draft' && <span className="is-draft">草稿</span>}</span><ChevronRight className="sk-result-arrow h-4 w-4" aria-hidden="true" /></button>)}
    </div>{!loading && !loadError && currentArticles.length > 0 && <div className="sk-list-navigation">{visibleCount < currentArticles.length && <Button variant="outline" onClick={() => setVisibleCount(count => count + 20)}>显示更多话术（剩余 {currentArticles.length - visibleCount} 条）</Button>}<Button variant="ghost" onClick={returnToFilters}><ArrowUp size={14}/>返回搜索与筛选</Button></div>}<div className="sk-list-footer"><span>没找到答案？</span><Button variant="ghost" onClick={openQuestion}>提交问题</Button></div></section><article className="knowledge-v4-detail" aria-live="polite">{details || <p className="knowledge-v4-empty">{loading ? '正在读取当前筛选…' : '选择一个问题查看可用话术。'}</p>}</article></div>
    {isMobile && <Sheet open={mobileDetailOpen} onOpenChange={setMobileDetailOpen}><SheetContent side="bottom" className="knowledge-v4-mobile-sheet knowledge-refined-portal sales-center-ui"><SheetHeader className="sr-only"><SheetTitle>{activeArticle?.title || '销售话术详情'}</SheetTitle><SheetDescription>查看对外答复、演示步骤及单独的内部提醒。</SheetDescription></SheetHeader><div className="knowledge-v4-mobile-sheet-scroll">{details}</div>{activeArticle && <div className="sk-mobile-copy-actions" aria-label="复制当前话术"><Button disabled={Boolean(getKnowledgeCopyBlockReason(activeArticle, 'phone'))} onClick={() => void copyAnswer(activeArticle, 'phone')}><Copy size={15}/>复制短版话术</Button><Button variant="outline" disabled={Boolean(getKnowledgeCopyBlockReason(activeArticle, 'full'))} onClick={() => void copyAnswer(activeArticle, 'full')}>复制完整答复</Button></div>}</SheetContent></Sheet>}
    {canManage && questionsError && <div className="knowledge-v4-empty" role="alert">待解答问题暂时无法读取<Button variant="ghost" onClick={() => void loadQuestions()}>重试</Button></div>}
    {canManage && openQuestions.length > 0 && <details className="sk-open-questions"><summary><MessageSquareText className="h-4 w-4" /><span>销售待解答问题</span><Badge>{openQuestions.length}</Badge></summary><p>补充知识卡后再标记完成。</p><div className="sk-question-list">{openQuestions.map(item => <div key={item.id} className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-white/80 p-3 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><p className="text-sm font-medium text-slate-900">{item.question}</p><p className="mt-1 text-xs text-slate-500">{item.context || '未补充场景'} · {item.submitted_by_name || '销售'} · {formatDate(item.created_at)}</p></div><Button size="sm" variant="outline" onClick={() => void resolveQuestion(item)}>标记已处理</Button></div>)}</div></details>}
    <Dialog open={editorOpen} onOpenChange={open => { if (!open && !saving && editorGuard.confirmDiscard()) setEditorOpen(false); }}><CrmFormDialogContent className="knowledge-refined-portal sk-editor-dialog sales-center-ui max-w-3xl crm-sales-dialog-polish"><CrmFormDialogHeader><DialogTitle>{editorArticle ? '编辑知识卡' : '新建知识卡'}</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody className="crm-sales-dialog-body"><fieldset disabled={saving} className="sk-editor-fields grid gap-4 sm:grid-cols-2">
      <div><Label htmlFor="knowledge-product">适用产品</Label><select id="knowledge-product" className="t24-native-select" value={articleForm.product_scope} onChange={event => setArticleForm(current => ({ ...current, product_scope: event.target.value }))}>{knowledgeProductOptions.filter(option => option.value).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
      <div><Label htmlFor="knowledge-availability">能力与规则状态</Label><select id="knowledge-availability" className="t24-native-select" value={articleForm.availability} onChange={event => setArticleForm(current => ({ ...current, availability: event.target.value }))}>{knowledgeAvailabilityOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
      <div><Label htmlFor="knowledge-category">销售过程分类</Label><select id="knowledge-category" className="t24-native-select" value={articleForm.category} onChange={event => { setArticleForm(current => ({ ...current, category: event.target.value })); setCustomCategory(''); }}>{editorCategories.map(item => <option key={item} value={item}>{item}</option>)}</select></div>
      <div><Label htmlFor="knowledge-new-category">新分类名称（选填）</Label><Input id="knowledge-new-category" value={customCategory} onChange={event => setCustomCategory(event.target.value)} /></div>
      <fieldset className="sk-store-types sm:col-span-2"><legend>适用门店（不选表示该产品全部门店）</legend>{[{ value: '通用', label: '全部门店通用' }, ...knowledgeStoreOptions.filter(option => option.value)].map(option => <label key={option.value}><input type="checkbox" checked={articleForm.store_types.includes(option.value)} onChange={event => setArticleForm(current => ({ ...current, store_types: event.target.checked ? option.value === '通用' ? ['通用'] : [...current.store_types.filter(item => item !== '通用'), option.value] : current.store_types.filter(item => item !== option.value) }))} />{option.label}</label>)}</fieldset>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-title">标题</Label><Input id="knowledge-title" value={articleForm.title} onChange={event => setArticleForm(current => ({ ...current, title: event.target.value }))} /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-customer-question">客户问题</Label><Input id="knowledge-customer-question" value={articleForm.customer_question} onChange={event => setArticleForm(current => ({ ...current, customer_question: event.target.value }))} placeholder="销售常遇到的原始问法" /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-phone-answer">电话短版（单独编写）</Label><Textarea id="knowledge-phone-answer" rows={3} value={articleForm.phone_answer} onChange={event => setArticleForm(current => ({ ...current, phone_answer: event.target.value }))} placeholder="用 15–30 秒可以自然说完的客户答复" /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-standard-answer">完整对外答复</Label><Textarea id="knowledge-standard-answer" rows={5} value={articleForm.standard_answer} onChange={event => setArticleForm(current => ({ ...current, standard_answer: event.target.value }))} placeholder="只填写可以直接发给客户的内容；内部规则请放到内部提醒" /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-followup">接着问一句</Label><Input id="knowledge-followup" value={articleForm.followup_question} onChange={event => setArticleForm(current => ({ ...current, followup_question: event.target.value }))} /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-demo">对应演示步骤（每行一条）</Label><Textarea id="knowledge-demo" rows={3} value={articleForm.demo_steps} onChange={event => setArticleForm(current => ({ ...current, demo_steps: event.target.value }))} /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-next-action">下一步</Label><Input id="knowledge-next-action" value={articleForm.next_action} onChange={event => setArticleForm(current => ({ ...current, next_action: event.target.value }))} /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-internal">内部提醒（不随答复复制）</Label><Textarea id="knowledge-internal" rows={4} value={articleForm.internal_notes} onChange={event => setArticleForm(current => ({ ...current, internal_notes: event.target.value }))} placeholder="条件限制、待核实规则、不能承诺的事项" /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-action-steps">销售执行步骤（每行一条，仅内部）</Label><Textarea id="knowledge-action-steps" rows={3} value={articleForm.action_steps} onChange={event => setArticleForm(current => ({ ...current, action_steps: event.target.value }))} /></div>
      <div className="sm:col-span-2"><Label htmlFor="knowledge-escalation">何时需要升级确认</Label><Textarea id="knowledge-escalation" rows={3} value={articleForm.escalation_rule} onChange={event => setArticleForm(current => ({ ...current, escalation_rule: event.target.value }))} /></div>
      <div><Label htmlFor="knowledge-tags">搜索标签（用逗号分隔）</Label><Input id="knowledge-tags" value={articleForm.tags} onChange={event => setArticleForm(current => ({ ...current, tags: event.target.value }))} /></div>
      <div><Label htmlFor="knowledge-sort-order">排序数字</Label><Input id="knowledge-sort-order" type="number" value={articleForm.sort_order} onChange={event => setArticleForm(current => ({ ...current, sort_order: event.target.value }))} /></div>
      <label className="sk-form-check"><input type="checkbox" checked={articleForm.high_frequency} onChange={event => setArticleForm(current => ({ ...current, high_frequency: event.target.checked }))} />加入新销售必读</label>
      <label className="sk-form-check"><input type="checkbox" checked={articleForm.is_sensitive} onChange={event => setArticleForm(current => ({ ...current, is_sensitive: event.target.checked }))} />内部敏感信息（禁止对客复制）</label>
      <label className="sk-form-check sm:col-span-2"><input type="checkbox" checked={publishNow} onChange={event => setPublishNow(event.target.checked)} />已核对本次内容，保存后发布给销售查看</label>
      <p className="sk-editor-help sm:col-span-2">不勾选发布会保存为草稿。原已发布答复继续供销售使用，待本次内容核对后再发布。</p>
      {editorError && <div role="alert" className="sk-editor-error sm:col-span-2"><p>{editorError}</p>{editorArticle && <Button variant="outline" disabled={conflictLoading} onClick={() => void readLatestArticle()}>{conflictLoading ? '读取中…' : '查看最新版本'}</Button>}{conflictArticle && <div><p>最新修订 {conflictArticle.revision || 0}：{conflictArticle.title}</p><p>{conflictArticle.standard_answer}</p><Button variant="outline" onClick={() => openEditor(conflictArticle)}>放弃当前修改，载入最新内容</Button></div>}</div>}
    </fieldset></CrmFormDialogBody><CrmFormDialogFooter className="sk-editor-actions"><Button variant="outline" disabled={saving} onClick={() => { if (editorGuard.confirmDiscard()) setEditorOpen(false); }}>取消</Button><Button disabled={saving} onClick={() => void saveArticle()}>{saving ? '保存中…' : '保存知识卡'}</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={questionOpen} onOpenChange={open => { if (!open && !saving && questionGuard.confirmDiscard()) setQuestionOpen(false); }}><CrmFormDialogContent className="knowledge-refined-portal sk-question-dialog sales-center-ui crm-sales-dialog-polish"><CrmFormDialogHeader><DialogTitle>提交销售新问题</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody className="crm-sales-dialog-body"><fieldset disabled={saving} className="sk-editor-fields space-y-4"><p className="text-sm text-slate-500">留下客户原话和门店场景，主管会整理为统一话术。</p><div><Label htmlFor="knowledge-question">客户问了什么？</Label><Textarea id="knowledge-question" rows={4} value={questionForm.question} onChange={event => setQuestionForm(current => ({ ...current, question: event.target.value }))} /></div><div><Label htmlFor="knowledge-question-context">补充场景（可选）</Label><Textarea id="knowledge-question-context" rows={3} value={questionForm.context} onChange={event => setQuestionForm(current => ({ ...current, context: event.target.value }))} /></div>{questionError && <p role="alert" className="sk-editor-error">{questionError}</p>}</fieldset></CrmFormDialogBody><CrmFormDialogFooter className="sk-editor-actions"><Button variant="outline" disabled={saving} onClick={() => { if (questionGuard.confirmDiscard()) setQuestionOpen(false); }}>取消</Button><Button disabled={saving} onClick={() => void submitQuestion()}><Send className="mr-1.5 h-4 w-4" />提交问题</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={packOpen} onOpenChange={open => { if (!packInstalling && !packLoading) setPackOpen(open); }}><CrmFormDialogContent className="knowledge-refined-portal sk-pack-dialog sales-center-ui max-w-5xl crm-sales-dialog-polish"><CrmFormDialogHeader><DialogTitle>美业 OS 销售话术包</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody className="crm-sales-dialog-body">
      {packLoading ? <p className="knowledge-v4-empty">正在读取话术清单…</p> : <>{packError && <div role="alert" className="sk-editor-error">{packError}</div>}{packResult && <div role="status" className="sk-pack-success"><p>{packResult}</p><Button variant="ghost" onClick={() => { setProductScope('beautyos'); setCategory('全部'); setStoreType(''); setHighFrequency(false); setQuery(''); setPackOpen(false); }}>查看美业 OS 话术</Button></div>}{packPreview && <><div className="sk-pack-summary"><strong>{packPreview.total} 条美业话术</strong><span>新销售必读 {packPreview.high_frequency_count} 条</span><span>本次新增 {packPreview.new_count} 条</span><span>已存在 {packPreview.existing_count} 条</span></div><p className="sk-editor-help">先浏览话术内容；添加时保留现有知识卡，已经添加过的条目会自动跳过。具体费用和第三方功能条件以卡内核实要求为准。</p><div className="sk-pack-workspace"><nav aria-label="话术包内容">{packPreview.items.map((article, index) => <button key={index} type="button" aria-pressed={packSelected === index} onClick={() => setPackSelected(index)}>{article.high_frequency && <span>必读 · </span>}{article.title}</button>)}</nav><div className="sk-pack-detail">{packArticle && <KnowledgeArticleDetail article={packArticle} preview canManage={false} onEdit={() => {}} onCopyShort={() => {}} onCopyFull={() => {}} />}</div></div></>}</>}
    </CrmFormDialogBody><CrmFormDialogFooter className="sk-editor-actions"><Button variant="outline" disabled={packInstalling || packLoading} onClick={() => setPackOpen(false)}>关闭</Button><Button variant="outline" disabled={packInstalling || packLoading} onClick={() => void previewPack()}>重新预览</Button><Button disabled={packInstalling || packLoading || !packPreview || packPreview.new_count === 0} onClick={() => void installPack()}>{packInstalling ? '添加中…' : packPreview?.new_count === 0 ? '话术已全部添加' : `添加并发布 ${packPreview?.new_count ?? ''} 条话术`}</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </div>;
}
