import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/stripe-history-reminders.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const { reminderCount, pendingStripeReminders, stripeDailyScanState, stripeReminderHref } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const complete = { enabled: true, last_run_status: 'completed', last_completed_at: '2026-10-19T01:01:00Z', active_bindings: 18, covered_bindings: 18, catchup_bindings: 0, retry_bindings: 0, running_bindings: 0, last_error_code: null };

test('待核数只合并待核对与待刷新，不把异常或发现数当收入', () => {
  assert.equal(pendingStripeReminders({ pending_review: 2, needs_refresh: 1, exception: 9, total: 12 }), 3);
  assert.equal(pendingStripeReminders({ pending_review: 0, needs_refresh: 0, exception: 9, total: 9 }), 0);
});
test('缺失、负数、非整数均待确认，不能默认零', () => {
  for (const value of [undefined, null, -1, 1.5, NaN, Infinity, '0']) assert.equal(reminderCount(value), null);
  assert.equal(reminderCount(0), 0);
  assert.equal(pendingStripeReminders(undefined), null);
  assert.equal(pendingStripeReminders({ pending_review: 1 }), null);
});
test('完整已覆盖且完成才显示完成', () => {
  assert.deepEqual(stripeDailyScanState(complete), { label: '最近补查已完成', tone: 'complete' });
  for (const patch of [{ last_completed_at: null }, { covered_bindings: undefined }, { active_bindings: undefined }, { enabled: undefined }, { covered_bindings: 17 }]) assert.notEqual(stripeDailyScanState({ ...complete, ...patch }).tone, 'complete');
});
test('失败、未完成、运行中不显示补查完成', () => {
  assert.equal(stripeDailyScanState({ ...complete, retry_bindings: 1 }).label, '补查待重试');
  assert.equal(stripeDailyScanState({ ...complete, last_error_code: 'PROVIDER_UNAVAILABLE' }).label, '补查待重试');
  assert.equal(stripeDailyScanState({ ...complete, last_run_status: 'partial', covered_bindings: 16, catchup_bindings: 2 }).label, '补查尚未完成');
  assert.equal(stripeDailyScanState({ ...complete, last_run_status: 'running', running_bindings: 1 }).label, '正在补查');
});
test('未启用、无关联和首次等待分别展示', () => {
  assert.equal(stripeDailyScanState({ ...complete, enabled: false, last_run_status: 'disabled' }).label, '每日补查未启用');
  assert.equal(stripeDailyScanState({ ...complete, last_run_status: 'no_bindings', active_bindings: 0 }).label, '暂无已关联服务可补查');
  assert.equal(stripeDailyScanState({ ...complete, last_run_status: 'never', covered_bindings: 0, last_completed_at: null }).label, '等待首次补查');
  assert.equal(stripeDailyScanState().label, '补查结果待确认');
});
test('单笔链接只允许本站对账详情，并去掉附带参数', () => {
  assert.equal(stripeReminderHref('/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71&returnTo=https://example.com'), '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71');
  for (const href of [null, 'https://example.com/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71', '//example.com/finance', '/private-workspace?stripe_review=71', '/finance?tab=income&stripe_view=reviews&stripe_review=71', '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=-1', '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=0', '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71\\']) assert.equal(stripeReminderHref(href), null);
});
