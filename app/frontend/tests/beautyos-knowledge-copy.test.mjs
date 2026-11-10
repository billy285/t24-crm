import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../src/lib/sales-knowledge.ts', import.meta.url), 'utf8');
const mod = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: mod, exports: mod.exports });
const api = mod.exports;
const article = overrides => ({ id: 1, category: '异议处理', title: '内部编排标题', customer_question: '客户问如何试用？', standard_answer: '我先核对您门店当前适用的规则，再准确回复您。', phone_answer: '我先替您核对当前规则。', product_scope: 'beautyos', store_types: ['通用'], availability: 'ready', revision: 1, high_frequency: true, action_steps: ['INTERNAL_ACTION_CANARY'], internal_notes: 'INTERNAL_NOTES_CANARY', escalation_rule: 'INTERNAL_ESCALATION_CANARY', demo_steps: ['INTERNAL_DEMO_CANARY'], next_action: 'INTERNAL_NEXT_CANARY', followup_question: 'INTERNAL_FOLLOWUP_CANARY', related_links: [], tags: ['内部标签'], status: 'published', is_sensitive: false, sort_order: 1, ...overrides });

test('authored phone script stays independent from the long answer', () => {
  const card = article({ standard_answer: '完整答复。'.repeat(60), phone_answer: '独立写好的电话短版。' });
  assert.equal(api.getPhoneKnowledgeAnswer(card), '独立写好的电话短版。');
  assert.equal(api.getFullKnowledgeAnswer(card), card.standard_answer);
});

test('customer clipboard excludes internal notes, actions, escalation, demos and labels', () => {
  const card = article();
  for (const copied of [api.getPhoneKnowledgeAnswer(card), api.getFullKnowledgeAnswer(card)]) {
    assert.doesNotMatch(copied, /INTERNAL_|内部编排|内部标签|标准答复：|建议步骤/);
  }
  assert.equal(api.getFullKnowledgeAnswer(card), card.standard_answer);
});

test('legacy sensitive guidance cannot be copied even if public-looking fields exist', () => {
  const card = article({ revision: 0, legacy_profile: true, is_sensitive: true, standard_answer: 'PRIVATE_BILLING_CANARY', phone_answer: 'PRIVATE_SHORT_CANARY' });
  assert.match(api.getKnowledgeCopyBlockReason(card), /内部信息待核对/);
  assert.equal(api.getPhoneKnowledgeAnswer(card), '');
  assert.equal(api.getFullKnowledgeAnswer(card), '');
});

test('draft and archived revisions cannot become customer clipboard output', () => {
  for (const status of ['draft', 'archived']) {
    const card = article({ status });
    assert.match(api.getKnowledgeCopyBlockReason(card), /尚未发布/);
    assert.equal(api.getPhoneKnowledgeAnswer(card), '');
    assert.equal(api.getFullKnowledgeAnswer(card), '');
  }
});

test('missing legacy phone script is not synthesized by truncating the full text', () => {
  const card = article({ revision: 0, phone_answer: undefined, standard_answer: '历史已发布完整答复。'.repeat(40) });
  assert.match(api.getKnowledgeCopyBlockReason(card, 'phone'), /电话短版尚未整理/);
  assert.equal(api.getPhoneKnowledgeAnswer(card), '');
  assert.equal(api.getFullKnowledgeAnswer(card), card.standard_answer);
});

test('published safe policy clarification remains usable while disputed numbers stay internal', () => {
  const card = article({ availability: 'pending_confirmation', internal_notes: '历史资料包含30天和60天，需负责人核对；不得向客户复制此争议。' });
  assert.equal(api.getKnowledgeCopyBlockReason(card, 'phone'), '');
  assert.equal(api.getKnowledgeCopyBlockReason(card, 'full'), '');
  assert.doesNotMatch(api.getPhoneKnowledgeAnswer(card) + api.getFullKnowledgeAnswer(card), /30|60|争议/);
});

test('whitespace-only customer fields do not enable copy actions', () => {
  const card = article({ phone_answer: ' \n ', standard_answer: ' \n ' });
  assert.ok(api.getKnowledgeCopyBlockReason(card, 'phone'));
  assert.ok(api.getKnowledgeCopyBlockReason(card, 'full'));
  assert.equal(api.getPhoneKnowledgeAnswer(card), '');
  assert.equal(api.getFullKnowledgeAnswer(card), '');
});

test('BeautyOS scope excludes general, restaurant and managed-service guidance', () => {
  assert.equal(api.matchesKnowledgeProduct(article(), 'beautyos'), true);
  for (const product_scope of ['general', 'restaurant', 'managed_service', undefined]) assert.equal(api.matchesKnowledgeProduct(article({ product_scope }), 'beautyos'), false);
  assert.equal(api.matchesKnowledgeProduct(article({ product_scope: 'managed_service' }), ''), true);
  assert.equal(api.matchesKnowledgeProduct(article({ product_scope: undefined }), 'general'), true);
});

test('canonical store filters retain independent studio and medical business values', () => {
  const values = Array.from(api.knowledgeStoreOptions, option => option.value);
  for (const expected of ['美甲', '美发', '美容护肤', '美睫', '个人工作室', 'SPA', '医美经营']) assert.ok(values.includes(expected));
  assert.equal(api.knowledgeAvailabilityLabel('ready'), '标准话术');
});

test('copy reads preserve the original card and its internal guidance', () => {
  const card = article();
  const before = JSON.stringify(card);
  api.getPhoneKnowledgeAnswer(card); api.getFullKnowledgeAnswer(card);
  assert.equal(JSON.stringify(card), before);
});
