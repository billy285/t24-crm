import { expect, test } from '@playwright/test';
import {
  appNavigationItems, getDesktopNavigationSections,
  getDesktopNavigationHref, isDesktopNavigationItemActive,
} from '../src/lib/app-navigation';
import { financeNavigationItems } from '../src/lib/finance-navigation';

test('desktop groups retain every existing page exactly once', () => {
  const items = getDesktopNavigationSections(() => true).flatMap(section => section.items);
  expect([...new Set(items.map(item => item.path))].sort()).toEqual(appNavigationItems.map(item => item.path).sort());
  const hrefs = items.map(item => getDesktopNavigationHref(item));
  expect(new Set(hrefs).size).toBe(items.length);
  expect(items.filter(item => item.path === '/finance').map(item => item.tab).sort()).toEqual([
    'overview', 'customer_profit', 'receivables', 'income', 'refunds', 'ad_funds',
    'customer_expense', 'company_expense', 'subscriptions', 'charts', 'monthly_detail',
  ].sort());
});

test('restricted accounts only receive allowed pages, even when a group entry is hidden', () => {
  for (const allowed of [[], ['/partner-portal'], ['/settings/deduction'], ['/tasks', '/customers'], ['/finance']]) {
    const sections = getDesktopNavigationSections(path => allowed.includes(path));
    expect([...new Set(sections.flatMap(section => section.items.map(item => item.path)))].sort()).toEqual([...allowed].sort());
    for (const section of sections) expect(section.items.length).toBeGreaterThan(0);
  }
  const partner = getDesktopNavigationSections(path => path === '/partner-portal')[0];
  expect(getDesktopNavigationHref(partner.items[0])).toBe('/partner-portal');
});

test('finance links preserve query context and select exactly one page, including invalid tabs', () => {
  const items = getDesktopNavigationSections(path => path === '/finance')[0].items;
  for (const tab of [...financeNavigationItems.map(item => item.tab), '', 'unknown']) {
    const search = `?tab=${tab}&customer_id=42&from=dashboard`;
    const active = items.filter(item => isDesktopNavigationItemActive(item, '/finance', search));
    expect(active).toHaveLength(1);
    expect(active[0].tab).toBe(tab && tab !== 'unknown' ? tab : 'overview');
    expect(items.some(item => isDesktopNavigationItemActive(item, '/settings', search))).toBe(false);
    for (const item of items) {
      const url = new URL(getDesktopNavigationHref(item, '/finance', search), 'https://example.test');
      expect(url.searchParams.get('customer_id')).toBe('42');
      expect(url.searchParams.get('from')).toBe('dashboard');
      expect(url.searchParams.get('tab')).toBe(item.tab === 'overview' ? null : item.tab);
    }
  }
  expect(getDesktopNavigationHref(items[1], '/customers', '?detail=42')).toBe('/finance?tab=income');
});
