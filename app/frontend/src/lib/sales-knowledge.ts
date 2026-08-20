export type SalesKnowledgeArticle = {
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

const sentenceBoundary = /(?<=[。！？!?])\s*/;

export function getShortKnowledgeAnswer(answer: string, maxLength = 140) {
  const normalized = answer.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;

  const sentences = normalized.split(sentenceBoundary).filter(Boolean);
  let shortAnswer = '';
  for (const sentence of sentences) {
    if (`${shortAnswer}${sentence}`.length > maxLength) break;
    shortAnswer += sentence;
    if (shortAnswer.length >= 72) break;
  }

  if (shortAnswer) return shortAnswer.trim();
  return `${normalized.slice(0, maxLength).trim()}…`;
}

export function getFullKnowledgeAnswer(article: SalesKnowledgeArticle) {
  return `${article.title}\n\n标准答复：\n${article.standard_answer}${article.action_steps.length ? `\n\n建议步骤：\n${article.action_steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}` : ''}`;
}
