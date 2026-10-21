import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/stripe-auto-posting.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const moduleUrl = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
const { autoPostingTime, validAutoPostingSelection, canEnableAutoPosting, safeAutoPostingTotals, autoPostingCount, autoPostingTotalsCount, isAutoPostedReview, isAwaitingAutoPosting } = await import(moduleUrl);
const policies = Array.from({ length: 7 }, (_, index) => ({ binding_id: index + 1, eligible: true, enabled: false, trial: { passed: true } }));

test('自动入账 UTC 时间在不同时区浏览器均显示同一北京时间，已有偏移不重复换算', () => {
  const values = [
    '2026-10-21T00:58:00',
    '2026-10-21 00:58:00.123456',
    '2026-10-21T00:58:00Z',
    '2026-10-21T00:58:00+00:00',
    '2026-10-21T08:58:00+08:00',
    '2026-10-20T17:58:00-07:00',
    '2026-10-21T20:58:00',
  ];
  for (const timezone of ['UTC', 'Asia/Shanghai', 'America/Los_Angeles']) {
    const script = `import { autoPostingTime } from ${JSON.stringify(moduleUrl)}; process.stdout.write(JSON.stringify(${JSON.stringify(values)}.map(autoPostingTime)));`;
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { env: { ...process.env, TZ: timezone }, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), Array(6).fill('10/21 08:58').concat('10/22 04:58'), timezone);
  }
});

test('自动入账缺失或不完整时间不会伪造为生效时间', () => {
  for (const value of [undefined, null, '']) assert.equal(autoPostingTime(value), '尚无记录');
  for (const value of ['待确认', '2026-10-21', '2026-13-21T00:58:00', '2026-10-21T25:58:00']) assert.equal(autoPostingTime(value), value);
});

test('模拟只允许三至五项有效且未启用的不同服务', () => {
  assert.equal(validAutoPostingSelection([1, 2, 3], policies), true);
  assert.equal(validAutoPostingSelection([1, 2, 3, 4, 5], policies), true);
  for (const selection of [[], [1, 2], [1, 2, 2], [1, 2, 9], [1, 2, 3, 4, 5, 6]]) assert.equal(validAutoPostingSelection(selection, policies), false);
  assert.equal(validAutoPostingSelection([1, 2, 3], [{ ...policies[0], enabled: true }, ...policies.slice(1)]), false);
  assert.equal(validAutoPostingSelection([1, 2, 3], [{ ...policies[0], eligible: false }, ...policies.slice(1)]), false);
  assert.equal(validAutoPostingSelection([1, 2, 3], [{ ...policies[0], eligible: 'true' }, ...policies.slice(1)]), false);
  for (const limit of [null, 0, 2, 3.5, NaN, Infinity]) assert.equal(validAutoPostingSelection([1, 2, 3], policies, limit), false);
});

test('启用必须模拟通过且当前试点小于五项，不能用未知计数开放', () => {
  assert.equal(canEnableAutoPosting(policies[0], 0), true);
  assert.equal(canEnableAutoPosting(policies[0], 4), true);
  for (const count of [undefined, null, -1, 1.5, 5, 6, Infinity]) assert.equal(canEnableAutoPosting(policies[0], count), false);
  assert.equal(canEnableAutoPosting({ ...policies[0], trial: null }, 0), false);
  assert.equal(canEnableAutoPosting({ ...policies[0], trial: { passed: false } }, 0), false);
  assert.equal(canEnableAutoPosting({ ...policies[0], enabled: true }, 0), false);
  assert.equal(canEnableAutoPosting({ ...policies[0], eligible: false }, 0), false);
  assert.equal(canEnableAutoPosting(policies[0], 0, NaN), false);
});

test('金额按主币单位分币种保留，不将未知金额误记为零', () => {
  assert.deepEqual(safeAutoPostingTotals([{ currency: 'usd', amount: 198.25, count: 1 }, { currency: 'CNY', amount: 500, count: 2 }]), [{ currency: 'USD', amount: 198.25, count: 1 }, { currency: 'CNY', amount: 500, count: 2 }]);
  assert.deepEqual(safeAutoPostingTotals([]), []);
  assert.equal(safeAutoPostingTotals([{ currency: ['USD'], amount: 99, count: 1 }]), null);
  for (const value of [undefined, null, {}, [{ currency: 'USD', amount: null, count: 1 }], [{ currency: 'USD', amount: 0, count: -1 }], [{ currency: 'USD', amount: NaN, count: 1 }], [{ currency: 'US', amount: 1, count: 1 }], [{ currency: 'USD', amount: 1, count: 1 }, { currency: 'usd', amount: 2, count: 2 }]]) assert.equal(safeAutoPostingTotals(value), null);
});

test('计数必须是安全非负整数，缺失数据不显示零笔', () => {
  assert.equal(autoPostingCount(0), 0);
  assert.equal(autoPostingTotalsCount([]), 0);
  assert.equal(autoPostingTotalsCount([{ currency: 'USD', amount: 198, count: 1 }, { currency: 'CNY', amount: 300, count: 2 }]), 3);
  for (const value of [null, undefined, -1, 1.5, '0', NaN, Infinity]) assert.equal(autoPostingCount(value), null);
  assert.equal(autoPostingTotalsCount(undefined), null);
  assert.equal(autoPostingTotalsCount([{ currency: 'USD', amount: 1, count: Number.MAX_SAFE_INTEGER }, { currency: 'CNY', amount: 1, count: 1 }]), null);
});

test('系统排队和重试不归为待人工，异常保留人工入口', () => {
  assert.equal(isAwaitingAutoPosting({ auto_posting: { status: 'queued' } }), true);
  assert.equal(isAwaitingAutoPosting({ auto_posting: { status: 'retry' } }), true);
  assert.equal(isAwaitingAutoPosting({ auto_posting: { status: 'manual_required' } }), false);
  assert.equal(isAwaitingAutoPosting({}), false);
});

test('只有明确系统已入账状态才标为已自动入账', () => {
  assert.equal(isAutoPostedReview({ auto_posting: { status: 'auto_posted' } }), true);
  for (const status of ['queued', 'retry', 'manual_required', 'manual_completed', 'unknown', null]) assert.equal(isAutoPostedReview({ auto_posting: { status } }), false);
  assert.equal(isAutoPostedReview({}), false);
});
