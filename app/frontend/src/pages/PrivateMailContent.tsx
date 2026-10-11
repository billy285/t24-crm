import { useState } from 'react';
import { ChevronRight, Languages, LoaderCircle } from 'lucide-react';
import { privateMailChinese, type PrivateItem } from '@/lib/private-workspace-api';
import './private-mail-ads-clarity.css';

export default function PrivateMailContent({ item, busy, previewBusy, unavailable, notice, onTranslateBody }: { item: PrivateItem; busy: boolean; previewBusy: boolean; unavailable: boolean; notice: string; onTranslateBody: () => void }) {
  const [language, setLanguage] = useState<'zh' | 'original'>('zh');
  const translation = item.mail_translation;
  const hasChinese = translation?.state === 'ready' && [translation.title_zh, translation.summary_zh, translation.body_zh].some(value => typeof value === 'string' && value.trim());
  const bodyOriginal = typeof translation?.body_original === 'string' ? translation.body_original : '';
  const bodyChinese = translation?.state === 'ready' && typeof translation.body_zh === 'string' ? translation.body_zh : '';
  const hasBody = translation?.body_available === true && Boolean(bodyOriginal);
  const title = language === 'zh' ? privateMailChinese(item, 'title') : item.title;
  const summary = language === 'zh' ? privateMailChinese(item, 'summary') : item.summary;
  return <section className="pw-mail-content pw-mail-clarity" aria-label="邮件内容">
    <div className="pw-mail-brief-toolbar"><span>邮件重点</span><div className="pw-mail-language" aria-label="邮件语言"><button type="button" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button><button type="button" aria-pressed={language === 'original'} aria-expanded={language === 'original'} onClick={() => setLanguage(language === 'original' ? 'zh' : 'original')}>原文</button></div></div>
    <div className="pw-mail-summary pw-mail-brief-headline"><h4>发生了什么 · 邮件摘要{(!hasChinese || language === 'original') && ' · 原始摘要'}</h4><p>{summary || '此邮件没有摘要，可在 Gmail 查看。'}</p></div>
    <div className="pw-mail-next-action"><span>我该做什么</span><p>查看完整邮件，确认是否需要处理。</p></div>
    {language === 'original' && <div className="pw-clarity-original"><h3 className="pw-mail-content-title">{title}</h3><span>{hasBody ? '邮件原文' : '原始摘要'}</span><p>{item.summary || '此邮件没有摘要，可在 Gmail 查看。'}</p>{hasBody && <div className="pw-mail-full-body"><h4>邮件正文{translation?.truncated && <span>仅展示已读取的部分</span>}</h4><p>{bodyOriginal}</p></div>}</div>}
    {hasBody && language === 'zh' && bodyChinese && <details className="pw-clarity-disclosure pw-mail-full-body"><summary>中文正文{translation?.truncated && ' · 部分正文'}<ChevronRight aria-hidden="true" /></summary><p>{bodyChinese}</p></details>}
    {language === 'zh' && !hasChinese && !busy && !previewBusy && !notice && <p className="pw-mail-translation-status">中文翻译尚未完成，当前显示原文。</p>}
    {previewBusy && !hasChinese && !busy && <p className="pw-mail-translation-status" role="status"><LoaderCircle aria-hidden="true" />正在准备中文摘要，原文仍可查看…</p>}
    {busy && <p className="pw-mail-translation-status" role="status"><LoaderCircle aria-hidden="true" />正在读取并翻译正文，原文仍可查看…</p>}
    {(notice || unavailable) && <p className="pw-mail-translation-status" role="status">{notice || '中文翻译尚未开通，当前可查看原文。'}</p>}
    {!bodyChinese && <button type="button" className="pw-button" disabled={busy || unavailable} onClick={onTranslateBody}><Languages aria-hidden="true" />{busy ? '正在翻译…' : '翻译正文'}</button>}
    <details className="pw-clarity-disclosure"><summary>阅读依据<ChevronRight aria-hidden="true" /></summary>{!hasBody && <p className="pw-mail-translation-hint">当前显示邮件摘要，正文需单独读取与翻译。</p>}{hasBody && !bodyChinese && <p className="pw-mail-translation-hint">正文中文翻译尚未完成，可展开原文查看。</p>}{(bodyChinese || hasChinese) && <p className="pw-mail-translation-hint">译文供阅读，金额、日期和操作要求请结合原文核实。</p>}<p>未有来源依据的日期不作为截止时间展示。</p></details>
  </section>;
}
