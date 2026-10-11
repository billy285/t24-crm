import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
import { adsFixture } from './fixtures/private-ads.mjs';
const path = resolve(dirname(fileURLToPath(import.meta.url)), '../src/lib/private-ads.ts');
const compiled = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = { exports: {} }; vm.runInNewContext(`(function(module,exports){${compiled}\n})`, { Intl, Date })(module, module.exports);
const api = module.exports;
test('Ads delivery classification ignores local work status and preserves a verified problem in partial inventory', () => {
  const { item, source } = adsFixture('problem'); item.action_status = 'done'; source.metadata.partial = true; source.metadata.ads_snapshot.inventory_complete = false; item.evidence.ads_health.coverage.inventory_complete = false;
  assert.equal(api.privateAdsObservation(item, source).bucket, 'problem'); assert.equal(api.privateAdsNeedsAttention(item, source), true);
});
test('old, mixed-snapshot, incomplete, future, and failed source checks never declare current delivery healthy', () => {
  for (const change of [
    (item) => item.evidence.ads_health.observed_at = new Date(Date.now() - 25 * 3600000).toISOString(),
    (item) => item.evidence.ads_health.snapshot_id = 'old-snapshot',
    (item) => item.evidence.ads_health.coverage.metrics_complete = false,
    (item) => item.evidence.ads_health.observed_at = new Date(Date.now() + 10 * 60000).toISOString(),
    (_, source) => source.error = 'synthetic sync failure',
    (_, source) => source.status = 'disconnected',
    (_, source) => delete source.metadata.ads_snapshot,
    (item) => delete item.evidence.ads_health,
    (item) => item.evidence.ads_health.metrics.last_7_days.cost_micros = NaN,
  ]) { const { item, source } = adsFixture(); change(item, source); assert.equal(api.privateAdsObservation(item, source).bucket, 'unknown'); assert.equal(api.privateAdsNeedsAttention(item, source), false); }
});
test('delivery can be healthy without tracking while effect metrics remain unconfigured', () => {
  const { item, source, health } = adsFixture(); health.tracking.state = 'unconfigured'; health.metrics.last_7_days.conversions = 0;
  const observation = api.privateAdsObservation(item, source);
  assert.equal(observation.bucket, 'healthy'); assert.equal(api.privateAdsConversions(observation.health, observation.health.metrics.last_7_days), '未配置');
});
test('Ads money converts original micros once and keeps two decimals and account currency', () => {
  assert.equal(api.privateAdsMoney(263940000, 'USD'), 'USD 263.94'); assert.equal(api.privateAdsMoney(0, 'CNY'), 'CNY 0.00');
  for (const invalid of [NaN, Infinity, -100, Number.MAX_SAFE_INTEGER + 1, '100', null]) assert.equal(api.privateAdsMoney(invalid, 'USD'), '待确认');
  assert.equal(api.privateAdsMoney(1000000, 'bad'), '待确认'); assert.equal(api.privateAdsNumber(1.5), '1.5');
});
test('malformed health never leaks raw object fields into display values', () => {
  const { item, source } = adsFixture(); item.evidence.ads_health.currency = { secret: 'synthetic' }; item.evidence.ads_health.target.assessment = { raw: true };
  const observation = api.privateAdsObservation(item, source); assert.equal(observation.bucket, 'unknown'); assert.equal(observation.health.target.assessment, ''); assert.equal(observation.health.currency, '');
  item.evidence.ads_health.bucket = 'invented'; assert.equal(api.privateAdsObservation(item, source).health, null);
});
test('actual CPA is a read-only ratio, never an invented target or missing conversion score', () => {
  const { health } = adsFixture(); assert.equal(api.privateAdsActualCpa(health), 'USD 3.33');
  health.tracking.state = 'unknown'; assert.equal(api.privateAdsActualCpa(health), '待确认');
  health.tracking.state = 'configured'; health.metrics.last_7_days.conversions = 0; assert.equal(api.privateAdsActualCpa(health), '待确认');
});
test('platform reasons are translated without exposing raw metadata on the primary decision', () => {
  const { health } = adsFixture('problem'); assert.equal(api.privateAdsReasons(health).join(''), '预算配置错误');
  health.current.primary_status_reasons = ['NEW_UNKNOWN_REASON']; assert.equal(api.privateAdsReasons(health).join(''), 'Google 状态原因待确认');
});
test('system-generated campaign names use a display alias without changing source evidence', () => {
  for (const title of ['LocalServicesCampaign:SystemGenerated:000657ec92f7095e', 'SystemGenerated-2026-10-10-09-00', 'SystemGenerated_local_service', 'systemgenerated: 12345', 'SystemGenerated']) {
    const item = { title }; assert.equal(api.privateAdsDisplayTitle(item), '本地服务广告'); assert.equal(item.title, title);
  }
  assert.equal(api.privateAdsDisplayTitle({ title: '秋季获客广告' }), '秋季获客广告');
  assert.equal(api.privateAdsDisplayTitle({ title: 'SystemGeneratedCustomName' }), 'SystemGeneratedCustomName');
  assert.equal(api.ADS_BUCKET_NAMES.unknown, '数据待确认');
});
