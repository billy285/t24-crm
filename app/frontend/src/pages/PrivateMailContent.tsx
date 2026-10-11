import { useState } from 'react';
import { Languages, LoaderCircle } from 'lucide-react';
import { privateMailChinese, type PrivateItem } from '@/lib/private-workspace-api';

export default function PrivateMailContent({ item, busy, previewBusy, unavailable, notice, onTranslateBody }: { item: PrivateItem; busy: boolean; previewBusy: boolean; unavailable: boolean; notice: string; onTranslateBody: () => void }) {
  const [language, setLanguage] = useState<'zh' | 'original'>('zh');
  const translation = item.mail_translation;
  const hasChinese = translation?.state === 'ready' && [translation.title_zh, translation.summary_zh, translation.body_zh].some(value => typeof value === 'string' && value.trim());
  const bodyOriginal = typeof translation?.body_original === 'string' ? translation.body_original : '';
  const bodyChinese = typeof translation?.body_zh === 'string' ? translation.body_zh : '';
  const hasBody = translation?.body_available === true && Boolean(bodyOriginal);
  const title = language === 'zh' ? privateMailChinese(item, 'title') : item.title;
  const summary = language === 'zh' ? privateMailChinese(item, 'summary') : item.summary;
  return <section className="pw-mail-content" aria-label="邮件内容">
    <div className="pw-mail-language" aria-label="邮件语言"><button type="button" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button><button type="button" aria-pressed={language === 'original'} onClick={() => setLanguage('original')}>原文</button></div>
    {language === 'original' && title !== privateMailChinese(item, 'title') && <h3 className="pw-mail-content-title">{title}</h3>}
    <div className="pw-mail-summary"><h4>邮件摘要</h4><p>{summary || '此邮件没有摘要，可在 Gmail 查看。'}</p></div>
    {hasBody && <div className="pw-mail-full-body"><h4>邮件正文{translation?.truncated && <span>仅展示已读取的部分</span>}</h4><p>{language === 'zh' && bodyChinese ? bodyChinese : bodyOriginal}</p>{language === 'zh' && !bodyChinese && <p className="pw-mail-translation-status">正文中文翻译尚未完成，当前显示原文。</p>}</div>}
    {!hasBody && <p className="pw-mail-translation-hint">当前显示邮件摘要，正文需单独读取与翻译。</p>}
    {language === 'zh' && !hasChinese && !busy && !previewBusy && !notice && <p className="pw-mail-translation-status">中文翻译尚未完成，当前显示原文。</p>}
    {previewBusy && !hasChinese && !busy && <p className="pw-mail-translation-status" role="status"><LoaderCircle aria-hidden="true" />正在准备中文摘要，原文仍可查看…</p>}
    {busy && <p className="pw-mail-translation-status" role="status"><LoaderCircle aria-hidden="true" />正在读取并翻译正文，原文仍可查看…</p>}
    {notice && <p className="pw-mail-translation-status" role="status">{notice}</p>}
    {!bodyChinese && <button type="button" className="pw-button" disabled={busy || unavailable} onClick={onTranslateBody}><Languages aria-hidden="true" />{busy ? '正在翻译…' : '翻译正文'}</button>}
    {(bodyChinese || hasChinese) && <p className="pw-mail-translation-hint">译文供阅读，金额、日期和操作要求请结合原文核实。</p>}
  </section>;
}
