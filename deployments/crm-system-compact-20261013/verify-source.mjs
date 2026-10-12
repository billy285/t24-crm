#!/usr/bin/env node
/** Independent, fail-closed source audit for the CRM desktop presentation release.
 * Run without arguments to audit the working tree. --save writes a release proof
 * only after every application source file matches the immutable committed HEAD.
 * This proves source preservation; browser acceptance remains a separate check.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(ROOT, 'app/frontend/package.json'));
const ts = require('typescript');
const postcss = require('postcss');
const BASELINE = 'e1d17ade3497b6bea2a98c30559039bf1a96851f';
const PREFIX = 'app/frontend/src/';
const TSX = [
  'components/Layout.tsx', 'pages/Callbacks.tsx', 'pages/Commissions.tsx',
  'pages/CompanyRoadmap.tsx', 'pages/CustomerLifecycle.tsx', 'pages/Customers.tsx',
  'pages/Dashboard.tsx', 'pages/Deals.tsx', 'pages/Employees.tsx',
  'pages/ManagementDecisions.tsx', 'pages/MerchantPool.tsx', 'pages/MonthlyDeduction.tsx',
  'pages/OperationsWorkbench.tsx', 'pages/PartnerPortal.tsx', 'pages/Payroll.tsx',
  'pages/Permissions.tsx', 'pages/RmbProfitEstimate.tsx', 'pages/Sales.tsx',
  'pages/SalesKnowledge.tsx', 'pages/SalesLeads.tsx', 'pages/SalesWorkbench.tsx',
  'pages/ServiceBoard.tsx', 'pages/Settings.tsx', 'pages/Tasks.tsx',
].map(p => PREFIX + p);
const CSS = [
  'components/crm-desktop-compact.css', 'pages/crm-command-compact.css',
  'pages/crm-customer-delivery-compact.css', 'pages/crm-org-compact.css',
  'pages/crm-sales-compact.css',
].map(p => PREFIX + p);
const CONFIG = PREFIX + 'components/crm-command-tables.ts';
const ALLOWED = new Set([...TSX, ...CSS, CONFIG]);
const STATIC_DECLARATIONS = {
  'Commissions.tsx': ['commissionLedger', 'commissionSettlements', 'commissionAttributions'],
  'PartnerPortal.tsx': ['partnerCustomers', 'partnerEntries'],
  'Payroll.tsx': ['payrollItems', 'payrollDepartments', 'payrollMonths', 'payrollEmployees'],
  'RmbProfitEstimate.tsx': ['rmbProfitPeriods'],
};
const SALES_PRESENTATION = `
const [compactDesktop, setCompactDesktop] = useState(() => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches);
useEffect(() => {
  const query = window.matchMedia('(min-width: 1024px)');
  const update = () => setCompactDesktop(query.matches);
  update();
  query.addEventListener('change', update);
  return () => query.removeEventListener('change', update);
}, []);
const showSourceDetails = compactDesktop || showAllColumns;
const ledgerHeaders = ['商家名称', '联系人', ...(showSourceDetails ? ['州/国家', '成交套餐'] : []), '当前服务', ...(showSourceDetails ? ['最近成交'] : []), '服务状态', ...(canViewFinance && showSourceDetails ? ['最近收款'] : []), ...(canViewFinance ? ['尾款'] : []), '负责销售', '操作'];
const ledgerColumns: CompactFinanceColumn[] = [
  { label: '商家', indexes: [ledgerHeaders.indexOf('商家名称')], width: 28, summaryMode: 'first' },
  { label: '当前服务', indexes: [ledgerHeaders.indexOf('当前服务')], width: 22, summaryMode: 'first' },
  { label: '服务状态', indexes: [ledgerHeaders.indexOf('服务状态')], width: 14, summaryMode: 'first' },
  ...(canViewFinance ? [{ label: '尾款', indexes: [ledgerHeaders.indexOf('尾款')], width: 12, align: 'right' as const }] : []),
  { label: '负责人', indexes: [ledgerHeaders.indexOf('负责销售')], width: 12 },
];`;
const SALES_DETAIL_GROUPS = `[
  { label: '客户与负责人', indexes: ['商家名称', '联系人', '州/国家', '负责销售'].map(label => ledgerHeaders.indexOf(label)) },
  { label: '服务与到期', indexes: ['成交套餐', '当前服务', '服务状态'].map(label => ledgerHeaders.indexOf(label)) },
  { label: '成交与收款', indexes: ['最近成交', '最近收款', '尾款'].map(label => ledgerHeaders.indexOf(label)) },
]`;
const LEAD_DISCLOSURE = '<details className="slr-merchant-context hidden min-[1024px]:block"><summary aria-label={`查看${lead.business_name}负责人和地区`}>{lead.assigned_sales_name || \'待分配\'}<ChevronDown size={11} /></summary><div className="sl-identity-meta"><span>{lead.assigned_sales_name || \'待分配\'}</span><span>{lead.industry || \'未分类\'}{lead.city || lead.state ? ` · ${[lead.city, lead.state].filter(Boolean).join(\', \')}` : \'\'}</span></div></details>';

function need(value, code, detail = '') {
  if (!value) throw new Error(`${code}${detail ? ': ' + detail : ''}`);
}
const hash = data => createHash('sha256').update(data).digest('hex');
const digest = value => hash(JSON.stringify(value));
const git = (...args) => execFileSync('git', args, { cwd: ROOT, maxBuffer: 256 * 1024 * 1024 });
const textGit = (...args) => git(...args).toString('utf8').trim();
const read = name => fs.readFileSync(path.join(ROOT, name));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function inventory(ref) {
  const names = git('ls-tree', '-r', '-z', ref, '--', 'app/').toString('utf8').split('\0').filter(Boolean).map(row => {
    const [metadata, name] = row.split('\t');
    const [mode, type] = metadata.split(' ');
    need(type === 'blob' && ['100644', '100755'].includes(mode), 'REGULAR_APPLICATION_SOURCE_REQUIRED', name);
    return name;
  });
  const batch = execFileSync('git', ['cat-file', '--batch'], {
    cwd: ROOT, input: names.map(n => `${ref}:${n}\n`).join(''), maxBuffer: 256 * 1024 * 1024,
  });
  const result = new Map();
  let offset = 0;
  for (const name of names) {
    const end = batch.indexOf(10, offset);
    const header = batch.subarray(offset, end).toString('utf8').split(' ');
    need(header[1] === 'blob', 'BASELINE_BLOB_MISSING', name);
    const size = Number(header[2]);
    result.set(name, batch.subarray(end + 1, end + 1 + size));
    offset = end + 1 + size + 1;
  }
  need(offset === batch.length, 'GIT_BATCH_LENGTH_MISMATCH');
  return result;
}

function parse(name, source) {
  const sf = ts.createSourceFile(name, source.toString('utf8'), ts.ScriptTarget.Latest, true,
    name.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  need(sf.parseDiagnostics.length === 0, 'TYPESCRIPT_PARSE_FAILED', name);
  return sf;
}
function collect(root, predicate) {
  const out = [];
  const walk = node => {
    if (predicate(node)) out.push(node);
    ts.forEachChild(node, walk);
  };
  walk(root);
  return out;
}
function plain(node) {
  const children = [];
  ts.forEachChild(node, child => { children.push(plain(child)); });
  const props = {};
  for (const key of ['isTypeOnly', 'isExportEquals', 'isBlockScoped']) {
    if (typeof node[key] === 'boolean') props[key] = node[key];
  }
  if (ts.isVariableDeclarationList(node)) props.declarationFlags = node.flags & (ts.NodeFlags.Const | ts.NodeFlags.Let | ts.NodeFlags.Using | ts.NodeFlags.AwaitUsing);
  const val = ts.isSourceFile(node) ? null : typeof node.text === 'string' ? node.text : children.length ? null : node.getText();
  return [ts.SyntaxKind[node.kind], props, val, children];
}
const expectedSales = parse('SalesExpected.tsx', SALES_PRESENTATION).statements.map(plain);
const expectedGroups = plain(parse('groups.ts', `const groups = ${SALES_DETAIL_GROUPS};`).statements[0].declarationList.declarations[0].initializer);
const expectedLeadDisclosure = plain(parse('lead.tsx', `const x = ${LEAD_DISCLOSURE};`).statements[0].declarationList.declarations[0].initializer);

function literal(node) {
  if (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node)) return literal(node.expression);
  if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind)) return true;
  if (ts.isArrayLiteralExpression(node)) return node.elements.every(literal);
  if (ts.isObjectLiteralExpression(node)) return node.properties.every(p => ts.isPropertyAssignment(p) && !ts.isComputedPropertyName(p.name) && literal(p.initializer));
  return false;
}
function classValue(element) {
  const opening = element.openingElement || element;
  const attr = opening.attributes?.properties.find(a => ts.isJsxAttribute(a) && a.name.text === 'className');
  return attr?.initializer && ts.isStringLiteral(attr.initializer) ? attr.initializer.text : '';
}
function jsxTag(node) {
  return (node.openingElement || node).tagName?.getText();
}
function normalizeJsxText(text) {
  return text.replace(/\s+/g, ' ').trim();
}
function firstDifference(a, b, at = '$') {
  if (equal(a, b)) return null;
  if (!Array.isArray(a) || !Array.isArray(b)) return { path: at, before: JSON.stringify(a)?.slice(0, 200), after: JSON.stringify(b)?.slice(0, 200) };
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const found = firstDifference(a[i], b[i], `${at}[${i}]`);
    if (found) return found;
  }
}

function presentationAudit(name, sf, side) {
  const baseName = path.basename(name);
  const omitted = new Set();
  const approvedImports = new Set([
    '@/components/CompactFinanceTable', '@/components/crm-command-tables',
    './crm-desktop-compact.css', './crm-command-compact.css', './crm-customer-delivery-compact.css',
    './crm-org-compact.css', './crm-sales-compact.css',
  ]);
  const statics = STATIC_DECLARATIONS[baseName] || [];
  const foundStatics = [];
  for (const statement of sf.statements) {
    if (ts.isImportDeclaration(statement) && approvedImports.has(statement.moduleSpecifier.text)) omitted.add(statement);
    if (ts.isVariableStatement(statement) && statement.declarationList.declarations.length === 1) {
      const declaration = statement.declarationList.declarations[0];
      if (statics.includes(declaration.name.getText(sf))) {
        need(literal(declaration.initializer), 'PRESENTATION_CONFIG_MUST_BE_LITERAL', `${name}:${declaration.name.getText(sf)}`);
        omitted.add(statement);
        foundStatics.push(declaration.name.getText(sf));
      }
    }
  }
  if (side === 'after') need(equal(foundStatics.sort(), [...statics].sort()), 'EXACT_PRESENTATION_DECLARATIONS_REQUIRED', name);
  if (side === 'before') need(!foundStatics.length, 'PRESENTATION_DECLARATION_ALREADY_IN_BASELINE', name);
  if (baseName === 'Sales.tsx' && side === 'after') {
    for (const expected of expectedSales) {
      const found = collect(sf, n => ts.isStatement(n) && equal(plain(n), expected));
      need(found.length === 1, 'EXACT_APPROVED_SALES_PRESENTATION_BLOCK_REQUIRED', name);
      omitted.add(found[0]);
    }
  }
  let dashboardWrappers = 0;
  let leadDisclosures = 0;
  let leadWrappers = 0;
  let adapters = 0;
  let salesGating = 0;
  const adapterProps = new Set(['columns', 'expectedHeaders', 'label', 'detailGroups', 'actionIndexes', 'className', 'legacyClassName']);
  function adapterAttribute(attr) {
    if (ts.isJsxSpreadAttribute(attr)) {
      const raw = attr.expression.getText(sf);
      need(statics.includes(raw) || /^CRM_COMMAND_TABLES\.[a-zA-Z]+$/.test(raw), 'UNREVIEWED_ADAPTER_SPREAD', `${name}:${raw}`);
      return;
    }
    need(ts.isJsxAttribute(attr) && adapterProps.has(attr.name.text), 'UNREVIEWED_ADAPTER_PROP', name);
    const key = attr.name.text;
    if (['className', 'legacyClassName'].includes(key)) return;
    const value = attr.initializer;
    need(value, 'ADAPTER_PROP_VALUE_REQUIRED', `${name}:${key}`);
    if (ts.isStringLiteral(value)) return;
    need(ts.isJsxExpression(value) && value.expression, 'ADAPTER_PROP_EXPRESSION_REQUIRED', `${name}:${key}`);
    const expression = value.expression;
    if (baseName === 'Sales.tsx') {
      if (key === 'columns' && expression.getText(sf) === 'ledgerColumns') return;
      if (key === 'expectedHeaders' && expression.getText(sf) === 'ledgerHeaders') return;
      if (key === 'detailGroups' && equal(plain(expression), expectedGroups)) return;
    }
    need(literal(expression), 'ADAPTER_METADATA_MUST_BE_PURE_LITERAL', `${name}:${key}`);
  }
  function attrs(opening, isAdapter) {
    if (isAdapter) {
      opening.attributes.properties.forEach(adapterAttribute);
      return [];
    }
    const result = [];
    for (const attr of opening.attributes.properties) {
      if (ts.isJsxAttribute(attr)) {
        const key = attr.name.text;
        if (key === 'className') continue;
        if (baseName === 'Layout.tsx' && key === 'data-crm-page') {
          need(attr.initializer?.getText(sf) === '{currentPath}' && opening.tagName.getText(sf) === 'main', 'LAYOUT_ROUTE_ATTRIBUTE_MISMATCH');
          continue;
        }
        if (baseName === 'Customers.tsx' && key === 'data-customer-column') {
          need(['th', 'td'].includes(opening.tagName.getText(sf)) && ts.isStringLiteral(attr.initializer), 'CUSTOMER_COLUMN_ATTRIBUTE_MISMATCH');
          continue;
        }
        if (key === 'title' && ((baseName === 'Customers.tsx' && attr.initializer?.getText(sf) === '{c.business_name}' && opening.tagName.getText(sf) === 'td') ||
          (baseName === 'SalesLeads.tsx' && attr.initializer?.getText(sf) === '{lead.business_name}' && opening.tagName.getText(sf) === 'button') ||
          (baseName === 'MerchantPool.tsx' && attr.initializer?.getText(sf) === '{merchant.business_name}' && opening.tagName.getText(sf) === 'button'))) continue;
      }
      result.push(canonical(attr));
    }
    return result;
  }
  function children(nodes) {
    const out = [];
    for (const child of nodes) {
      const value = canonical(child);
      if (value === null) continue;
      if (value[0] === 'FLATTEN') out.push(...value[1]);
      else out.push(value);
    }
    return out;
  }
  function canonical(node) {
    if (omitted.has(node)) return null;
    if (ts.isJsxText(node)) {
      const value = normalizeJsxText(node.text);
      return value ? ['JsxText', value] : null;
    }
    if (ts.isJsxExpression(node) && !node.expression) return null;
    if (ts.isJsxElement(node)) {
      const tag = jsxTag(node);
      const cls = classValue(node);
      if (baseName === 'Dashboard.tsx' && tag === 'span' && node.openingElement.attributes.properties.length === 0 && node.getText(sf) === '<span>#{item.rank} {item.salesperson}</span>') {
        dashboardWrappers++;
        return ['FLATTEN', children(node.children)];
      }
      if (baseName === 'SalesLeads.tsx' && tag === 'div' && ['slr-compact-identity', 'slr-legacy-identity-meta min-[1024px]:hidden'].includes(cls)) {
        need(node.openingElement.attributes.properties.length === 1, 'LEAD_WRAPPER_ATTRIBUTES_CHANGED');
        leadWrappers++;
        return ['FLATTEN', children(node.children)];
      }
      if (baseName === 'SalesLeads.tsx' && tag === 'details' && cls === 'slr-merchant-context hidden min-[1024px]:block') {
        need(equal(plain(node), expectedLeadDisclosure), 'LEAD_DISCLOSURE_NOT_EXACT_APPROVED_PRESENTATION');
        leadDisclosures++;
        return null;
      }
      const adapter = tag === 'CompactFinanceTable';
      if (adapter) adapters++;
      return ['JsxElement', adapter ? 'table' : tag, attrs(node.openingElement, adapter), children(node.children)];
    }
    if (ts.isJsxSelfClosingElement(node)) return ['JsxSelfClosingElement', jsxTag(node), attrs(node, false)];
    if (baseName === 'Sales.tsx' && ts.isIdentifier(node) && node.text === 'showSourceDetails') {
      let parent = node.parent;
      while (parent && !ts.isJsxExpression(parent)) parent = parent.parent;
      need(parent, 'SALES_GATE_CHANGE_OUTSIDE_JSX');
      salesGating++;
      return ['Identifier', {}, 'showAllColumns', []];
    }
    const nested = [];
    ts.forEachChild(node, child => { const value = canonical(child); if (value !== null) nested.push(value); });
    const props = {};
    for (const key of ['isTypeOnly', 'isExportEquals', 'isBlockScoped']) if (typeof node[key] === 'boolean') props[key] = node[key];
    if (ts.isVariableDeclarationList(node)) props.declarationFlags = node.flags & (ts.NodeFlags.Const | ts.NodeFlags.Let | ts.NodeFlags.Using | ts.NodeFlags.AwaitUsing);
    const val = ts.isSourceFile(node) ? null : typeof node.text === 'string' ? node.text : nested.length ? null : node.getText(sf);
    return [ts.SyntaxKind[node.kind], props, val, nested];
  }
  const tree = canonical(sf);
  const evidence = { removed_presentation_statement_count: omitted.size, static_declarations: foundStatics, compact_table_count: adapters, dashboard_identity_wrappers: dashboardWrappers, lead_identity_wrappers: leadWrappers, lead_identity_disclosures: leadDisclosures, sales_jsx_gate_references: salesGating };
  return { canonical, tree, evidence };
}

function cssAudit(name) {
  const ast = postcss.parse(read(name).toString('utf8'), { from: name });
  let rules = 0;
  ast.walkAtRules(at => need(['media', 'container'].includes(at.name), 'UNREVIEWED_CSS_AT_RULE', `${name}:${at.name}`));
  ast.walkRules(rule => {
    let parent = rule.parent;
    let desktopOnly = false;
    while (parent) {
      if (parent.type === 'atrule' && parent.name === 'media' && /^\(min-width:\s*1024px\)(?:\s+and\s+\(max-width:\s*\d+px\))?$/.test(parent.params)) desktopOnly = true;
      parent = parent.parent;
    }
    need(desktopOnly, 'ALL_NEW_STYLE_RULES_MUST_REQUIRE_DESKTOP_1024', name);
    // Split only selector-list commas, not commas inside :is() or :where().
    let depth = 0, quoted = '', start = 0;
    const selectors = [];
    for (let i = 0; i < rule.selector.length; i++) {
      const char = rule.selector[i];
      if (quoted) { if (char === quoted && rule.selector[i - 1] !== '\\') quoted = ''; continue; }
      if (char === '"' || char === "'") quoted = char;
      else if (char === '(' || char === '[') depth++;
      else if (char === ')' || char === ']') depth--;
      else if (char === ',' && depth === 0) { selectors.push(rule.selector.slice(start, i).trim()); start = i + 1; }
    }
    selectors.push(rule.selector.slice(start).trim());
    need(selectors.every(selector => /^\.t24-system(?:\.app-shell)? \.crm-desktop-main(?=[ :.[#])/.test(selector)), 'ALL_NEW_SELECTORS_MUST_BE_CRM_SCOPED', name);
    rules++;
  });
  need(rules > 0, 'EMPTY_COMPACT_STYLESHEET', name);
  return { sha256: hash(read(name)), rule_count: rules, all_rules_desktop_1024_and_crm_scoped: true };
}

try {
  const save = process.argv.includes('--save');
  need(process.argv.slice(2).every(a => a === '--save'), 'ONLY_SUPPORTED_OPTION_IS_SAVE');
  const head = textGit('rev-parse', 'HEAD');
  need(/^[a-f0-9]{40}$/.test(head), 'FULL_HEAD_SHA_REQUIRED');
  git('merge-base', '--is-ancestor', BASELINE, head);
  const before = inventory(BASELINE);
  const protectedFiles = {};
  const changed = new Set();
  for (const [name, original] of before) {
    const file = path.join(ROOT, name);
    need(fs.existsSync(file) && fs.lstatSync(file).isFile(), 'TRACKED_APPLICATION_SOURCE_MISSING_OR_SYMLINK', name);
    const current = read(name);
    if (hash(original) !== hash(current)) changed.add(name);
    if (!ALLOWED.has(name)) {
      need(hash(original) === hash(current), 'PROTECTED_APPLICATION_SOURCE_CHANGED', name);
      protectedFiles[name] = hash(current);
    }
  }
  const sourceFiles = [];
  function walkSource(folder) {
    for (const entry of fs.readdirSync(path.join(ROOT, folder), { withFileTypes: true })) {
      const name = `${folder}/${entry.name}`;
      need(!entry.isSymbolicLink(), 'SOURCE_SYMLINK_REJECTED', name);
      if (entry.isDirectory()) walkSource(name);
      else { need(entry.isFile(), 'SOURCE_TYPE_REJECTED', name); sourceFiles.push(name); }
    }
  }
  walkSource('app/frontend/src');
  for (const name of sourceFiles) if (!before.has(name)) { need(ALLOWED.has(name), 'UNREVIEWED_NEW_FRONTEND_SOURCE', name); changed.add(name); }
  need(equal([...changed].sort(), [...ALLOWED].sort()), 'EXACT_APPROVED_PRODUCT_FILE_CHANGE_SET_REQUIRED');

  const config = parse(CONFIG, read(CONFIG));
  need(config.statements.length === 2 && ts.isImportDeclaration(config.statements[0]) && config.statements[0].importClause?.isTypeOnly && config.statements[0].moduleSpecifier.text === './CompactFinanceTable', 'PURE_TABLE_CONFIG_IMPORT_REQUIRED');
  const configDeclaration = config.statements[1].declarationList?.declarations?.[0];
  need(configDeclaration?.name?.getText(config) === 'CRM_COMMAND_TABLES' && literal(configDeclaration.initializer), 'PURE_TABLE_CONFIG_LITERAL_REQUIRED');
  const cssProofs = Object.fromEntries(CSS.map(name => [name, cssAudit(name)]));
  const fileProofs = {};
  let eventTotal = 0, cellTotal = 0, dialogTotal = 0, adapterTotal = 0;
  for (const name of TSX) {
    const original = before.get(name), current = read(name);
    need(original, 'ORIGINAL_TSX_REQUIRED', name);
    const a = parse(name, original), b = parse(name, current);
    const handlers = sf => collect(sf, n => ts.isJsxAttribute(n) && /^on[A-Z]/.test(n.name.getText(sf))).map(n => n.getText(sf));
    const originalEvents = handlers(a), updatedEvents = handlers(b);
    need(equal(originalEvents, updatedEvents), 'EVENT_HANDLERS_CHANGED', name);
    const normalizedA = presentationAudit(name, a, 'before'), normalizedB = presentationAudit(name, b, 'after');
    need(equal(normalizedA.tree, normalizedB.tree), 'NON_PRESENTATION_SOURCE_CHANGED', `${name} ${JSON.stringify(firstDifference(normalizedA.tree, normalizedB.tree))}`);
    const cells = (sf, audit) => collect(sf, n => ts.isJsxElement(n) && ['td', 'th'].includes(jsxTag(n))).map(audit.canonical);
    const originalCells = cells(a, normalizedA), updatedCells = cells(b, normalizedB);
    need(equal(originalCells, updatedCells), 'TABLE_CELLS_CHANGED', name);
    const dialogs = (sf, audit) => collect(sf, n => ts.isJsxElement(n) && /^(?:Dialog|AlertDialog|Sheet)(?:Content)?$/.test(jsxTag(n))).map(audit.canonical);
    const originalDialogs = dialogs(a, normalizedA), updatedDialogs = dialogs(b, normalizedB);
    need(equal(originalDialogs, updatedDialogs), 'DIALOG_SOURCE_CHANGED', name);
    const tablesA = collect(a, n => ts.isJsxElement(n) && jsxTag(n) === 'table');
    const tablesB = collect(b, n => ts.isJsxElement(n) && ['table', 'CompactFinanceTable'].includes(jsxTag(n)));
    need(tablesA.length === tablesB.length, 'TABLE_COUNT_CHANGED', name);
    tablesB.forEach((table, i) => {
      if (jsxTag(table) !== 'CompactFinanceTable') return;
      const oldAttrs = tablesA[i].openingElement.attributes.properties;
      need(oldAttrs.every(attr => ts.isJsxAttribute(attr) && attr.name.text === 'className'), 'ORIGINAL_TABLE_BEHAVIOR_WOULD_BE_DROPPED', name);
      const oldClass = oldAttrs.find(attr => attr.name.text === 'className')?.initializer;
      const legacyClass = table.openingElement.attributes.properties.find(attr => ts.isJsxAttribute(attr) && attr.name.text === 'legacyClassName')?.initializer;
      need((!oldClass && !legacyClass) || (oldClass && legacyClass && equal(plain(oldClass), plain(legacyClass))), 'MOBILE_LEGACY_TABLE_CLASS_CHANGED', name);
      const lostParentHandlers = collect(table, n => (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) && ['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'].includes(jsxTag(n)) && n.attributes.properties.some(attr => ts.isJsxAttribute(attr) && /^on[A-Z]/.test(attr.name.text)));
      need(lostParentHandlers.length === 0, 'ADAPTER_CANNOT_DROP_PARENT_CELL_OR_ROW_EVENT', name);
      for (const header of collect(table, n => ts.isJsxElement(n) && jsxTag(n) === 'thead')) {
        need(collect(header, n => (ts.isJsxAttribute(n) && /^on[A-Z]/.test(n.name.text)) ||
          ((ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) && ['button', 'input', 'select', 'textarea', 'a'].includes(jsxTag(n)))).length === 0,
        'ADAPTER_CANNOT_DROP_HEADER_INTERACTION', name);
      }
      need(collect(table, n => ts.isJsxAttribute(n) && n.name.text === 'onSelect').length === 0, 'ADAPTER_ONSELECT_HANDOFF_NOT_SUPPORTED', name);
    });
    eventTotal += originalEvents.length; cellTotal += originalCells.length; dialogTotal += originalDialogs.length;
    adapterTotal += normalizedB.evidence.compact_table_count;
    fileProofs[name] = {
      before_sha256: hash(original), after_sha256: hash(current),
      event_handler_count: originalEvents.length, event_handlers_unchanged: true,
      event_handlers_sha256: digest(originalEvents), render_expressions_unchanged: true,
      normalized_complete_source_sha256: digest(normalizedA.tree),
      table_cell_count: originalCells.length, table_cells_sha256: digest(originalCells), table_cells_unchanged: true,
      dialog_count: originalDialogs.length, dialogs_sha256: digest(originalDialogs), dialogs_unchanged: true,
      presentation_normalizations: normalizedB.evidence,
    };
  }
  const sharedAdapter = PREFIX + 'components/CompactFinanceTable.tsx';
  need(before.get(sharedAdapter).equals(read(sharedAdapter)), 'SHARED_FINANCE_TABLE_CHANGED');
  need(read(sharedAdapter).toString('utf8').includes("'(min-width: 1024px)'") && read(sharedAdapter).toString('utf8').includes('<table className={legacyClassName}>{children}</table>'), 'UNCHANGED_ADAPTER_MOBILE_FALLBACK_REQUIRED');
  const finance = PREFIX + 'pages/Finance.tsx';
  const privateEntries = Object.entries(protectedFiles).filter(([name]) => /private|personal.finance/i.test(name));
  need(privateEntries.length > 0, 'PRIVATE_SOURCE_INVENTORY_REQUIRED');
  let committed = false;
  if (save) {
    need(head !== BASELINE, 'SAVE_REQUIRES_NEW_COMMITTED_SOURCE');
    const committedFiles = inventory(head);
    const committedChanges = new Set(git('diff', '--name-only', '-z', BASELINE, head, '--', 'app/').toString('utf8').split('\0').filter(Boolean));
    need(equal([...committedChanges].sort(), [...ALLOWED].sort()), 'COMMIT_MUST_CONTAIN_EXACT_APPROVED_PRODUCT_CHANGES');
    for (const [name, bytes] of committedFiles) need(bytes.equals(read(name)), 'WORKING_SOURCE_DOES_NOT_MATCH_HEAD', name);
    need(sourceFiles.every(name => committedFiles.has(name)), 'ALL_FRONTEND_SOURCE_MUST_BE_COMMITTED');
    committed = true;
  }
  const proof = {
    format_version: 1, stage: 'CRM_SYSTEM_COMPACT_PRESENTATION_SOURCE_PROOF',
    baseline_source_sha: BASELINE, source_sha: head, source_mode: committed ? 'committed' : 'working_tree_preview',
    generated_at: new Date().toISOString(),
    finance_file_before_sha256: hash(before.get(finance)), finance_file_after_sha256: hash(read(finance)),
    financial_calculations_unchanged: true, event_handlers_unchanged: true,
    table_cells_unchanged: true, dialogs_unchanged: true, mobile_render_unchanged: true,
    private_workspace_source_unchanged: true,
    file_proofs: fileProofs,
    evidence: {
      method: 'Exact JSX event attributes; complete TypeScript AST equality after the explicitly constrained presentation normalizations; original table-cell and dialog AST equality; complete protected application source byte equality.',
      scope: 'Source preservation only. This does not replace runtime, browser, accessibility or accounting acceptance.',
      tsx_files: TSX.length, original_event_handlers: eventTotal, original_table_cells: cellTotal, original_dialog_nodes: dialogTotal, adapted_tables: adapterTotal,
      approved_product_files: [...ALLOWED].sort(),
      protected_application_file_count: Object.keys(protectedFiles).length,
      protected_application_inventory_sha256: digest(protectedFiles),
      private_file_count: privateEntries.length, private_inventory_sha256: digest(privateEntries),
      shared_finance_adapter_sha256: hash(read(sharedAdapter)),
      css_proofs: cssProofs, table_config_sha256: hash(read(CONFIG)),
      approved_exceptions: [
        'CSS imports/class names and literal compact-table column/header/action metadata only. Original native table cells and permission expressions are kept in the adapter.',
        'Sales.tsx: exact 1024px matchMedia effect extends desktop source fields into the detail drawer. Below 1024px showSourceDetails equals the unchanged showAllColumns; canViewFinance gates are preserved.',
        'Dashboard.tsx: a single attr-free span groups original rank and salesperson for summary identity; original text/expressions are unchanged.',
        'SalesLeads.tsx: exact desktop-only native details duplicates original owner/industry/location metadata, with original mobile metadata retained. Two class-only div wrappers and a business-name title are presentation-only.',
        'Customers.tsx: data-column attributes and the business-name title only. Selection/inline-edit/native table cell events remain intact. MerchantPool.tsx also adds the existing merchant name as its button title.',
      ],
      verifier_sha256: hash(fs.readFileSync(fileURLToPath(import.meta.url))),
    },
  };
  if (save) {
    const target = path.join(ROOT, 'outputs/crm-system-compact-20261013/source-proof.json');
    fs.writeFileSync(target, JSON.stringify(proof, null, 2) + '\n');
    console.log(JSON.stringify({ success: true, source_sha: head, file: path.relative(ROOT, target), sha256: hash(fs.readFileSync(target)), tsx_files: TSX.length, event_handlers: eventTotal, table_cells: cellTotal, dialogs: dialogTotal, adapted_tables: adapterTotal }, null, 2));
  } else console.log(JSON.stringify(proof, null, 2));
} catch (error) {
  console.error(JSON.stringify({ success: false, error: error.message }, null, 2));
  process.exitCode = 1;
}
