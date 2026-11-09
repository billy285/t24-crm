import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/contact-timezone.ts', import.meta.url), 'utf8');
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { formatContactClock, resolveContactTimezone, validContactTimezone } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`);

test('daylight saving transitions follow the selected IANA zone, including Arizona exception', () => {
  const before = new Date('2026-03-08T09:30:00Z');
  const after = new Date('2026-03-08T10:30:00Z');
  assert.equal(formatContactClock('America/Los_Angeles', before), '01:30');
  assert.equal(formatContactClock('America/Los_Angeles', after), '03:30');
  assert.equal(formatContactClock('America/Phoenix', before), '02:30');
  assert.equal(formatContactClock('America/Phoenix', after), '03:30');
  const summer = new Date('2026-07-01T17:30:00Z');
  assert.equal(formatContactClock('America/Denver', summer), '11:30');
  assert.equal(formatContactClock('America/Phoenix', summer), '10:30');
  assert.equal(formatContactClock('America/Anchorage', summer), '09:30');
  assert.equal(formatContactClock('Pacific/Honolulu', summer), '07:30');
});

test('authoritative computed contact zone wins over legacy profile and old APIs retain manual fallback', () => {
  const derived = { timezone: 'America/Los_Angeles', timezone_group: 'pacific', timezone_basis: 'address_city', timezone_needs_confirmation: true };
  assert.deepEqual(resolveContactTimezone(' America/New_York ', derived), derived);
  assert.deepEqual(resolveContactTimezone(' America/New_York '), { timezone: 'America/New_York', timezone_basis: 'confirmed_profile', timezone_needs_confirmation: false });
  assert.deepEqual(resolveContactTimezone('Invalid/Zone', derived), derived);
  assert.deepEqual(resolveContactTimezone('', derived), derived);
  for (const invalid of [123, false, null, [], {}]) {
    assert.equal(validContactTimezone(invalid), undefined);
    assert.deepEqual(resolveContactTimezone(invalid, derived), derived);
    assert.equal(resolveContactTimezone(invalid).timezone, null);
  }
});

test('unknown or invalid timezone stays unknown and never uses the computer zone', () => {
  assert.equal(validContactTimezone('Not/A_Timezone'), undefined);
  assert.equal(formatContactClock('Not/A_Timezone'), undefined);
  assert.equal(formatContactClock(null), undefined);
  assert.deepEqual(resolveContactTimezone('', { timezone: null, timezone_group: 'unknown' }), { timezone: null, timezone_group: 'unknown', timezone_basis: 'unknown', timezone_needs_confirmation: true });
  assert.equal(resolveContactTimezone('america/new_york', { timezone: null, timezone_group: 'unknown' }).timezone, null);
  assert.equal(resolveContactTimezone('America/New_York', { timezone: 'Invalid/Zone' }).timezone, null);
});
