import { useEffect, useMemo, useState } from 'react';
import { BookOpen, ChevronLeft, ChevronRight, Copy, Search, ShieldAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getFullKnowledgeAnswer, getShortKnowledgeAnswer, type SalesKnowledgeArticle } from '@/lib/sales-knowledge';
import { invokeWithAuth } from '@/lib/tokenStore';

type SalesKnowledgeAssistantProps = {
  collapsed?: boolean;
  contextLabel?: string;
  onToggle?: () => void;
};

const quickScenarios = ['开场白', '太贵', '已有系统', '付款'];

async function copyText(content: string, successMessage: string) {
  try {
    await navigator.clipboard.writeText(content);
    toast.success(successMessage);
  } catch {
    toast.error('复制失败，请手动选择内容复制');
  }
}

export default function SalesKnowledgeAssistant({ collapsed = false, contextLabel, onToggle }: SalesKnowledgeAssistantProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [articles, setArticles] = useState<SalesKnowledgeArticle[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (query.trim()) params.set('query', query.trim());
        const response = await invokeWithAuth({ url: `/api/v1/sales-knowledge/articles?${params}`, method: 'GET' });
        if (cancelled) return;
        const items = (response.data?.items || []) as SalesKnowledgeArticle[];
        setArticles(items);
        setSelectedId(current => items.some(item => item.id === current) ? current : items[0]?.id ?? null);
      } catch {
        if (!cancelled) setArticles([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [collapsed, query]);

  const selectedArticle = useMemo(
    () => articles.find(article => article.id === selectedId) || articles[0] || null,
    [articles, selectedId],
  );

  if (collapsed) {
    return (
      <aside className="sales-v3-assistant is-collapsed" aria-label="销售知识助手">
        <Button type="button" variant="ghost" size="icon" title="展开知识助手" onClick={onToggle}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <BookOpen className="h-4 w-4 text-blue-600" />
        <span>话术</span>
      </aside>
    );
  }

  return (
    <aside className="sales-v3-assistant" aria-label="销售知识助手">
      <div className="sales-v3-assistant-head">
        <div>
          <p><BookOpen className="h-4 w-4" /> 通话知识助手</p>
          <span>{contextLabel ? `当前：${contextLabel}` : '搜索客户原话，直接复制使用'}</span>
        </div>
        {onToggle ? (
          <Button type="button" variant="ghost" size="icon" title="收起知识助手" onClick={onToggle}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        ) : null}
      </div>

      <div className="sales-v3-assistant-search">
        <Search className="h-4 w-4" />
        <Input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="输入：太贵、退款、怎么付款…"
          aria-label="搜索销售话术"
        />
      </div>

      <div className="sales-v3-assistant-scenarios" aria-label="高频销售场景">
        {quickScenarios.map(item => (
          <button key={item} type="button" className={query === item ? 'is-active' : ''} onClick={() => setQuery(item)}>{item}</button>
        ))}
      </div>

      <div className="sales-v3-assistant-body">
        {loading ? <p className="sales-v3-assistant-empty">正在查找可用话术…</p> : articles.length === 0 ? (
          <p className="sales-v3-assistant-empty">没有匹配话术，可前往知识库提交新问题。</p>
        ) : (
          <>
            <div className="sales-v3-assistant-results" role="listbox" aria-label="话术搜索结果">
              {articles.slice(0, 6).map(article => (
                <button
                  key={article.id}
                  type="button"
                  role="option"
                  aria-selected={selectedArticle?.id === article.id}
                  className={selectedArticle?.id === article.id ? 'is-active' : ''}
                  onClick={() => setSelectedId(article.id)}
                >
                  <span>{article.title}</span>
                  <small>{article.category}</small>
                </button>
              ))}
            </div>

            {selectedArticle ? (
              <div className="sales-v3-assistant-answer">
                <div className="flex flex-wrap gap-1.5">
                  <Badge className="bg-blue-50 text-blue-700">{selectedArticle.category}</Badge>
                  {selectedArticle.is_sensitive ? <Badge className="bg-amber-100 text-amber-800">仅内部使用</Badge> : null}
                </div>
                <h4>{selectedArticle.title}</h4>
                <p className="sales-v3-assistant-question">客户问：{selectedArticle.customer_question || '适用于当前销售场景'}</p>
                <div className="sales-v3-assistant-script">
                  <span>电话短版</span>
                  <p>{getShortKnowledgeAnswer(selectedArticle.standard_answer)}</p>
                </div>
                {selectedArticle.escalation_rule ? (
                  <div className="sales-v3-assistant-warning">
                    <ShieldAlert className="h-4 w-4" />
                    <span>此场景需要主管或相关部门确认</span>
                  </div>
                ) : null}
                <div className="grid grid-cols-2 gap-2">
                  <Button size="sm" onClick={() => void copyText(getShortKnowledgeAnswer(selectedArticle.standard_answer), '电话短版话术已复制')}>
                    <Copy className="mr-1 h-3.5 w-3.5" />复制短版
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void copyText(getFullKnowledgeAnswer(selectedArticle), '完整答复已复制')}>
                    复制完整答复
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      <Button type="button" variant="ghost" className="sales-v3-assistant-library" onClick={() => navigate('/sales-knowledge')}>
        打开完整销售知识库
      </Button>
    </aside>
  );
}
