import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import * as react from 'react';
import * as jsx from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { adsFixture } from './fixtures/private-ads.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const modules = new Map();
const api = {
  privateMailChinese: (item, part) => item.mail_translation?.state === 'ready' && item.mail_translation[`${part}_zh`] || item[part],
  privateSourceActionAvailability: () => ({ canSync: false }),
  verifiedPrivateSourceUrl: (_, url) => url === 'https://ads.google.com/aw/overview' ? url : null,
};
function load(relative) {
  if (modules.has(relative)) return modules.get(relative);
  const compiled = ts.transpileModule(readFileSync(resolve(root, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
    if (name.endsWith('.css')) return {};
    if (name === '@/lib/private-workspace-api') return api;
    if (name === '@/lib/private-ads') return load('lib/private-ads.ts');
    throw new Error(`Unexpected dependency: ${name}`);
  };
  vm.runInNewContext(`(function(module,exports,require){${compiled}\n})`, { Intl, Date })(module, module.exports, require);
  modules.set(relative, module.exports); return module.exports;
}
const Brief = load('pages/PrivateMailBrief.tsx').default;
const Content = load('pages/PrivateMailContent.tsx').default;
const Ads = load('pages/PrivateAdsDashboard.tsx');
const render = (Component, props) => renderToStaticMarkup(jsx.jsx(Component, props));
const mail = overrides => ({ id: 'synthetic-mail', source_id: 'gmail', title: 'Original subject', summary: 'Original summary', evidence: {}, ...overrides });
const readyBrief = overrides => ({ state: 'ready', summary_zh: '客户希望确认广告方案', next_action: '核对方案后回复客户', needs_action: true, source_scope: 'body', original_body: 'PRIVATE ORIGINAL BODY', source_evidence: ['Original source quotation'], key_points: ['方案重点'], deadline: null, ...overrides });
const briefProps = item => ({ item, busy: false, configured: true, loading: false, notice: '', onOrganize: () => assert.fail('Rendering must not start AI work') });
const adsProps = (items, source, extra = {}) => ({ items, source, now: Date.now(), accountLabel: '合成账户', total: items.length, loading: false, error: '', busy: false, syncing: false, onSelect: () => {}, onManage: () => {}, onSync: () => assert.fail('Rendering must not sync Ads'), onRetry: () => {}, ...extra });

test('mail highlights keep original body collapsed and show a deadline only with quoted source evidence', () => {
  for (const deadline of [null, { text: 'Friday', confirmed: true }, { text: 'Friday', evidence: ' ', confirmed: false }]) {
    const markup = render(Brief, briefProps(mail({ mail_brief: readyBrief({ deadline }) })));
    assert.ok(markup.includes('发生了什么')); assert.ok(markup.includes('我该做什么'));
    assert.ok(!markup.includes('pw-mail-brief-deadline')); assert.ok(!markup.includes('PRIVATE ORIGINAL BODY'));
    assert.ok(markup.includes('<details')); assert.ok(!markup.includes('<details open'));
  }
  const markup = render(Brief, briefProps(mail({ mail_brief: readyBrief({ deadline: { text: 'Friday', evidence: 'Please reply Friday.', confirmed: false } }) })));
  assert.ok(markup.includes('pw-mail-brief-deadline')); assert.ok(markup.includes('Friday')); assert.ok(markup.includes('待确认'));
});
test('unavailable mail organization describes only original evidence and keeps the paid action disabled', () => {
  const markup = render(Brief, { ...briefProps(mail({ mail_brief: { state: 'unavailable' } })), configured: false, notice: '智能整理尚待接入，当前可查看邮件原文' });
  assert.ok(markup.includes('Original summary')); assert.ok(markup.includes('原始摘要')); assert.ok(markup.includes('disabled=""'));
  assert.ok(!markup.includes('AI 阅读整理')); assert.ok(!markup.includes('中文工作简报'));
});
test('preview and incomplete brief evidence retain visible uncertainty without inventing a deadline', () => {
  for (const limited of [{ source_scope: 'preview' }, { evidence_limited: true }, { truncated: true }]) {
    const markup = render(Brief, briefProps(mail({ mail_brief: readyBrief(limited) })));
    assert.ok(markup.includes('内容待确认')); assert.ok(!markup.includes('pw-mail-brief-deadline'));
  }
});
test('legacy mail translation keeps original body collapsed and stale translations are never presented as Chinese', () => {
  for (const state of ['ready', 'failed']) {
    const item = mail({ mail_translation: { state, summary_zh: '中文摘要', body_original: 'PRIVATE ORIGINAL BODY', body_zh: 'PRIVATE CHINESE BODY', body_available: true } });
    const markup = render(Content, { item, busy: false, previewBusy: false, unavailable: state === 'failed', notice: '', onTranslateBody: () => assert.fail('Rendering must not translate mail') });
    assert.ok(!markup.includes('PRIVATE ORIGINAL BODY'));
    assert.equal(markup.includes('PRIVATE CHINESE BODY'), state === 'ready');
    if (state === 'ready') { assert.ok(markup.includes('<details class="pw-clarity-disclosure pw-mail-full-body"')); assert.ok(!markup.includes('<details open')); }
  }
});
test('Ads priority is explicitly a preview, counts use loaded records, and aliases preserve original evidence in details', () => {
  const fixtures = Array.from({ length: 4 }, (_, index) => adsFixture('problem', index));
  fixtures[0].item.title = 'SystemGenerated-12345'; const source = fixtures[0].source; source.metadata.partial = true;
  const original = structuredClone(fixtures[0].item);
  const markup = render(Ads.default, adsProps(fixtures.map(value => value.item), source, { total: 100 }));
  assert.ok(markup.includes('先看 3 项 · 共 4 项')); assert.equal((markup.match(/<article/g) || []).length, 3);
  assert.ok(markup.includes('已同步 4 个广告系列 · 部分记录')); assert.ok(markup.includes('本地服务广告'));
  assert.ok(!markup.includes('SystemGenerated-12345'));
  const detail = render(Ads.PrivateAdsDetail, { item: fixtures[0].item, source, now: Date.now() });
  assert.ok(detail.includes('原始名称与检查依据')); assert.ok(detail.includes('SystemGenerated-12345')); assert.ok(detail.includes('获客效果'));
  assert.deepEqual(fixtures[0].item, original);
});
test('old Ads inspections cannot present a current delivery or performance achievement', () => {
  const { item, source } = adsFixture('healthy', 1, { observed_at: new Date(Date.now() - 25 * 3600000).toISOString(), target: { cpa_micros: 10000000, assessment: 'SYNTHETIC TARGET ACHIEVED' } });
  const markup = render(Ads.default, adsProps([item], source));
  assert.ok(markup.includes('数据待确认')); assert.ok(markup.includes('待完成检查'));
  const detail = render(Ads.PrivateAdsDetail, { item, source, now: Date.now() });
  assert.ok(detail.includes('检查数据待确认，暂不评价当前效果')); assert.ok(!detail.includes('SYNTHETIC TARGET ACHIEVED'));
});
