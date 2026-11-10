import { useEffect, useMemo, useState } from 'react';
import '@/pages/sales-knowledge-refined.css';
import { BookOpen, ChevronLeft, ChevronRight, Copy, Search, ShieldAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { Input } from '@/components/ui/input';
import {
  getFullKnowledgeAnswer, getPhoneKnowledgeAnswer, getKnowledgeCopyBlockReason,
  knowledgeProductLabel, knowledgeAvailabilityLabel, matchesKnowledgeProduct,
  type SalesKnowledgeArticle, type KnowledgeProduct,
} from '@/lib/sales-knowledge';
import { invokeWithAuth } from '@/lib/tokenStore';

type SalesKnowledgeAssistantProps = { collapsed?: boolean; contextLabel?: string; contextCategory?: string; productScope?: KnowledgeProduct; onToggle?: () => void };
const quickScenarios = ['开场', '已有系统', '试用', '演示'];

export default function SalesKnowledgeAssistant({ collapsed = false, contextLabel, contextCategory, productScope = 'beautyos', onToggle }: SalesKnowledgeAssistantProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [articles, setArticles] = useState<SalesKnowledgeArticle[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [loadedKey, setLoadedKey] = useState('');
  const key = JSON.stringify([productScope, query, contextCategory, retry]);
  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true); setLoadError(false);
      try {
        const params = new URLSearchParams({ product_scope: productScope, include_general: 'false' });
        if (query.trim()) params.set('query', query.trim());
        else if (contextCategory) params.set('category', contextCategory);
        const response = await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?${params}`, method: 'GET' });
        if (cancelled) return;
        if (!Array.isArray(response.data?.items)) throw new Error('Incomplete knowledge response');
        const items = (response.data.items as SalesKnowledgeArticle[]).filter(article => article.status === 'published' && matchesKnowledgeProduct(article, productScope));
        setArticles(items); setLoadedKey(key);
        setSelectedId(current => items.some(item => item.id === current) ? current : items[0]?.id ?? null);
      } catch {
        if (!cancelled) { setArticles([]); setLoadedKey(key); setLoadError(true); }
      } finally { if (!cancelled) setLoading(false); }
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [collapsed, key, productScope, query, contextCategory]);
  const currentArticles = loadedKey === key ? articles : [];
  const pending = loading || loadedKey !== key;
  const selectedArticle = useMemo(() => currentArticles.find(article => article.id === selectedId) || currentArticles[0] || null, [currentArticles, selectedId]);
  const copyAnswer = async (version: 'phone' | 'full') => {
    if (!selectedArticle) return;
    const blocked = getKnowledgeCopyBlockReason(selectedArticle, version);
    if (blocked) { toast.error(blocked); return; }
    try { await navigator.clipboard.writeText(version === 'phone' ? getPhoneKnowledgeAnswer(selectedArticle) : getFullKnowledgeAnswer(selectedArticle)); toast.success(version === 'phone' ? '电话短版话术已复制' : '对外完整答复已复制'); }
    catch { toast.error('复制失败，请手动选择对外答复复制'); }
  };
  if (collapsed) return <aside className="sales-v3-assistant is-collapsed" aria-label="销售知识助手"><Button type="button" variant="ghost" size="icon" title="展开知识助手" onClick={onToggle}><ChevronLeft className="h-4 w-4" /></Button><BookOpen className="h-4 w-4 text-blue-600" /><span>话术</span></aside>;
  return <aside className="sales-v3-assistant sk-beautyos-assistant" aria-label="销售知识助手">
    <div className="sales-v3-assistant-head"><div><p><BookOpen className="h-4 w-4" /> 通话知识助手</p><span>{knowledgeProductLabel(productScope)} · {query.trim() ? '按客户原话查找' : contextCategory || '全部场景'}{contextLabel ? ` · ${contextLabel}` : ''}</span></div>{onToggle && <Button type="button" variant="ghost" size="icon" title="收起知识助手" onClick={onToggle}><ChevronRight className="h-4 w-4" /></Button>}</div>
    <div className="sales-v3-assistant-search"><Search className="h-4 w-4" /><Input value={query} onChange={event => setQuery(event.target.value)} placeholder="输入：已有系统、试用、预约…" aria-label="搜索销售话术" /></div>
    <div className="sales-v3-assistant-scenarios" aria-label="高频销售场景">{quickScenarios.map(item => <button key={item} type="button" className={query === item ? 'is-active' : ''} aria-pressed={query === item} onClick={() => setQuery(item)}>{item}</button>)}</div>
    <div className="sales-v3-assistant-body">{pending ? <p className="sales-v3-assistant-empty">正在查找当前产品话术…</p> : loadError ? <div className="sales-v3-assistant-empty" role="alert">话术加载失败<Button variant="ghost" size="sm" onClick={() => setRetry(value => value + 1)}>重新加载</Button></div> : currentArticles.length === 0 ? <p className="sales-v3-assistant-empty">当前产品和场景暂无已发布话术，可前往知识库调整筛选或提交问题。</p> : <><label className="sc-answer-picker"><span>匹配话术 · {currentArticles.length} 条</span><NativeSelect aria-label="选择当前产品话术" value={String(selectedArticle?.id || '')} onChange={value => setSelectedId(Number(value))} options={currentArticles.map(article => ({ value: String(article.id), label: article.title }))} /></label>{selectedArticle && <div className="sales-v3-assistant-answer">
      <div className="flex flex-wrap gap-1.5"><Badge className="bg-blue-50 text-blue-700">{knowledgeProductLabel(selectedArticle.product_scope)}</Badge><Badge className="bg-slate-100 text-slate-700">{selectedArticle.category}</Badge>{selectedArticle.is_sensitive && <Badge className="bg-amber-100 text-amber-800">内部信息待核对</Badge>}</div>
      <h4>{selectedArticle.title}</h4><p className="sales-v3-assistant-question">客户问：{selectedArticle.customer_question || '适用于当前销售场景'}</p>
      <div className="sales-v3-assistant-script"><span>电话短版</span><p>{selectedArticle.is_sensitive ? '这张卡属于内部信息，尚未整理可直接给客户的答复。' : selectedArticle.phone_answer?.trim() || '电话短版尚未整理，请在知识库查看完整答复。'}</p></div>
      <p className="sk-assistant-availability">{knowledgeAvailabilityLabel(selectedArticle.availability)}</p>
      {selectedArticle.followup_question && <div className="sk-assistant-next"><strong>接着问一句</strong><p>{selectedArticle.followup_question}</p></div>}
      {selectedArticle.next_action && <div className="sk-assistant-next"><strong>下一步</strong><p>{selectedArticle.next_action}</p></div>}
      {(selectedArticle.internal_notes || selectedArticle.escalation_rule || selectedArticle.is_sensitive) && <details className="sk-assistant-internal"><summary><ShieldAlert className="h-4 w-4" />内部提醒 · 不随答复复制</summary>{selectedArticle.is_sensitive && <p>{selectedArticle.standard_answer}</p>}{selectedArticle.internal_notes && <p>{selectedArticle.internal_notes}</p>}{selectedArticle.escalation_rule && <p>{selectedArticle.escalation_rule}</p>}</details>}
      <div className="grid grid-cols-2 gap-2"><Button size="sm" disabled={Boolean(getKnowledgeCopyBlockReason(selectedArticle, 'phone'))} onClick={() => void copyAnswer('phone')}><Copy className="mr-1 h-3.5 w-3.5" />复制短版</Button><Button size="sm" variant="outline" disabled={Boolean(getKnowledgeCopyBlockReason(selectedArticle, 'full'))} onClick={() => void copyAnswer('full')}>复制完整答复</Button></div>
    </div>}</>}</div>
    <Button type="button" variant="ghost" className="sales-v3-assistant-library" onClick={() => navigate('/sales-knowledge')}>打开完整销售知识库</Button>
  </aside>;
}
