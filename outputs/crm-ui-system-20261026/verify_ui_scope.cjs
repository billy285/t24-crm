/* Local packaging guard: allow view changes while freezing existing financial mutations and access gates. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require(path.resolve('app/frontend/node_modules/typescript'));
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const handlerNames = new Set(['handleSavePayment', 'handlePayCustomerChange', 'allowFinanceClose', 'handleSave', 'confirm', 'confirmBinding', 'requestPreview', 'sync', 'refresh', 'save']);
const mutationMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
function objectMutationArgument(argument) {
  if (!ts.isObjectLiteralExpression(argument)) return false;
  return argument.properties.some(property => {
    if (!ts.isPropertyAssignment(property) || !(ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) || property.name.text !== 'method') return false;
    const value = property.initializer;
    return ts.isStringLiteralLike(value) && mutationMethods.has(value.text.toUpperCase());
  });
}
function inventory(file, text) {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const errors = source.parseDiagnostics || [];
  if (errors.length) throw Error('UI_SOURCE_SYNTAX_REJECTED');
  const nodes = {}, mutations = [], logic = [], events = [];
  const semanticAttributes = /^(on[A-Z]|disabled$|readOnly$|required$|value$|checked$|defaultValue$|defaultChecked$|open$|forceMount$)/;
  const append = (key, value) => (nodes[key] ||= []).push(hash(value));
  function visit(node, scopes) {
    const isFunction = ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node);
    const name = ts.isFunctionDeclaration(node) && node.name ? node.name.text : isFunction && ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name) ? node.parent.name.text : '';
    const qualified = scopes.join('/');
    if (isFunction && !containsJsx(node)) logic.push(hash(node.getText(source)));
    if (ts.isVariableDeclaration(node) && node.initializer && !containsJsx(node.initializer) && !ts.isFunctionLike(node.initializer)) logic.push(hash(node.getText(source)));
    if (ts.isJsxAttribute(node) && semanticAttributes.test(node.name.getText(source)) && node.initializer) events.push(hash(node.initializer.getText(source)));
    if (ts.isJsxExpression(node) && node.expression && containsJsx(node.expression)) {
      function shape(n) { if (ts.isJsxElement(n)||ts.isJsxSelfClosingElement(n)||ts.isJsxFragment(n)) return '#VIEW'; return ts.forEachChild(n,()=>undefined) === undefined && n.getChildCount(source)===0 ? n.getText(source) : n.getChildren(source).map(shape).join(' '); }
      const value=shape(node.expression); if (value!=='#VIEW') logic.push(hash(value));
    }
    if (isFunction && name && handlerNames.has(name)) append('handler:' + qualified + '/' + name, node.getText(source));
    if (ts.isFunctionDeclaration(node) && node.name && scopes.length === 0 && !containsJsx(node)) append('helper:' + node.name.text, node.getText(source));
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && (/^can[A-Z]/.test(node.name.text) || ['isOwner', 'isAdmin'].includes(node.name.text))) append('gate:' + qualified + '/' + node.name.text, node.initializer?.getText(source) || '');
    if (ts.isCallExpression(node)) {
      const method = ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text.toLowerCase() : '';
      if (['post', 'put', 'patch', 'delete'].includes(method) || node.arguments.some(arg => ts.isStringLiteral(arg) && mutationMethods.has(arg.text.toUpperCase())) || node.arguments.some(objectMutationArgument)) mutations.push(hash(node.getText(source)));
    }
    ts.forEachChild(node, child => visit(child, isFunction && name ? [...scopes, name] : scopes));
  }
  visit(source, []);
  return { nodes, mutations: mutations.sort(), logic: logic.sort(), events: events.sort() };
}
function containsJsx(node) {
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) return true;
  let found = false; ts.forEachChild(node, child => { if (!found && containsJsx(child)) found = true; }); return found;
}
const protectedNodes = {}, reviewedViewChanges = [];
for (const [file, pair] of Object.entries(payload.files)) {
  const before = inventory(file, pair.before), after = inventory(file, pair.after);
  for (const [name, values] of Object.entries(before.nodes)) {
    if (JSON.stringify(after.nodes[name]) !== JSON.stringify(values)) throw Error('PROTECTED_UI_BEHAVIOR_DRIFT: ' + file + ':' + name);
    protectedNodes[file + ':' + name] = values;
  }
  if (JSON.stringify(before.mutations) !== JSON.stringify(after.mutations)) throw Error('MUTATION_CALL_DRIFT: ' + file);
  function preserves(original, current) {const remaining = [...current]; return original.every(item => {const at=remaining.indexOf(item); if(at<0)return false; remaining.splice(at,1); return true;});}
  if (!preserves(before.logic, after.logic)) throw Error('NON_PRESENTATION_LOGIC_DRIFT: ' + file);
  if (JSON.stringify(before.events) !== JSON.stringify(after.events)) throw Error('EXISTING_CONTROL_BEHAVIOR_DRIFT: ' + file);
  // New controls may change GET view selection; they cannot add or alter a mutation.
  if (pair.before !== pair.after) reviewedViewChanges.push(file);
}
process.stdout.write(JSON.stringify({ unchanged: true, node_count: Object.keys(protectedNodes).length, protected_nodes: protectedNodes, mutation_calls_unchanged: true, existing_logic_and_control_expressions_preserved: true, ui_read_filters_require_review: reviewedViewChanges }));
