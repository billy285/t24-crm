#!/usr/bin/env node
/** Auditable presentation preservation proof. Does not execute application or network calls. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
const DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(DIR, '../..');
const require = createRequire(path.join(ROOT, 'app/frontend/package.json'));
const ts = require('typescript');
const postcss = require('postcss');
const BASELINE = 'a4ef1fbcf7d68b5a71e6afc01d4d89c16b68a61b';
const PAGE = 'app/frontend/src/pages/ManagementDecisions.tsx';
const COMPONENT = 'app/frontend/src/components/ManagementActionDesk.tsx';
const CSS = 'app/frontend/src/pages/management-action-desk.css';
const ALLOWED = [PAGE, COMPONENT, CSS].sort();
const need = (ok, label, data='') => { if (!ok) throw new Error(`${label}${data ? ': '+data : ''}`); };
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const digest = data => sha(JSON.stringify(data));
const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
const read = name => fs.readFileSync(path.join(ROOT,name));
const git = (...args) => execFileSync('git',args,{cwd:ROOT,maxBuffer:256*1024*1024});
const textGit = (...args) => git(...args).toString().trim();
const visit = (node, fn) => { fn(node); ts.forEachChild(node, child => visit(child,fn)); };
const collect = (node, pred) => { const out=[];visit(node,n=>{if(pred(n))out.push(n)});return out; };
const parse = (name,bytes) => { const sf=ts.createSourceFile(name,bytes.toString(),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);need(!sf.parseDiagnostics.length,'SOURCE_PARSE_FAILED',name);return sf; };
const timestampSetter = n => ts.isExpressionStatement(n) && ts.isCallExpression(n.expression) && ['setViewLoadedAt','setGrowthLoadedAt'].includes(n.expression.expression.getText());
const timestampStatement = n => timestampSetter(n) || (ts.isIfStatement(n) && n.expression.getText()==='growthResponse.data' && !n.elseStatement && timestampSetter(n.thenStatement) && n.thenStatement.expression.expression.getText()==='setGrowthLoadedAt');
function shape(node, skipTime=false) {
  const children=[];ts.forEachChild(node,child=>{if(!(skipTime&&timestampStatement(child)))children.push(shape(child,skipTime));});
  const properties={};
  for(const k of ['isTypeOnly','isExportEquals'])if(typeof node[k]==='boolean')properties[k]=node[k];
  if(ts.isVariableDeclarationList(node))properties.declarationFlags=node.flags&(ts.NodeFlags.Const|ts.NodeFlags.Let);
  return [ts.SyntaxKind[node.kind],properties,ts.isSourceFile(node)?null:typeof node.text==='string'?node.text:children.length?null:node.getText(),children];
}
function declaration(sf,name) {
  const found=collect(sf,n=>(ts.isFunctionDeclaration(n)||ts.isVariableDeclaration(n))&&n.name?.getText(sf)===name);
  need(found.length===1,'ONE_NAMED_DECLARATION_REQUIRED',name);return found[0];
}
function inventory(ref) {
  const rows=git('ls-tree','-r','-z',ref,'--','app/').toString().split('\0').filter(Boolean);
  const names=rows.map(row=>{const [meta,name]=row.split('\t');need(/^100(?:644|755) blob /.test(meta),'REGULAR_BLOB_REQUIRED',name);return name;});
  const data=execFileSync('git',['cat-file','--batch'],{cwd:ROOT,input:names.map(n=>`${ref}:${n}\n`).join(''),maxBuffer:256*1024*1024});
  const out=new Map();let pos=0;
  for(const name of names){const e=data.indexOf(10,pos);const h=data.subarray(pos,e).toString().split(' ');need(h[1]==='blob','BASE_BLOB_REQUIRED',name);const size=Number(h[2]);out.set(name,data.subarray(e+1,e+1+size));pos=e+size+2;}
  need(pos===data.length,'BATCH_LENGTH_MISMATCH');return out;
}
const functionNames=[
 'authOptions','errorMessage','dateValue','money','localDateString','profitRangeForPreset','suggestionToForm','projectToForm',
 'loadData','loadGrowth','saveExchangeRate','changeProfitPreset','updateProfitClose',
 'runAutomationScan','createQualityTask','createVisibleQualityTasks','openReview','updateProjectForm','saveReview','openStatus','saveStatus',
 'visibleItems','industries','visibleProjects','projectPageCount','safeProjectPage','paginatedProjects','visibleQualityIssues','activeQualityCount','visibleIssuesWithoutTask',
 'summary','pendingCount','followUpCount','warningTotal','economicsTotals','riskyHealth','salesCapacitySummary','profitCenter','profitSummary','currentMonth',
 'lineLabels','lineProducts','projectStatusLabels','projectStatusClasses','reviewLabels','collectionLabels','qualityCategoryLabels','healthLabels','healthClasses',
];
const mutableHandlers=['saveExchangeRate','updateProfitClose','runAutomationScan','createQualityTask','createVisibleQualityTasks','saveReview','saveStatus'];
const calcNames=['money','localDateString','profitRangeForPreset','changeProfitPreset','projectPageCount','safeProjectPage','paginatedProjects','warningTotal','economicsTotals','riskyHealth','profitCenter','profitSummary','currentMonth'];
const tag=n=>(n.openingElement||n).tagName?.getText();
function apiShapes(sf){return collect(sf,n=>ts.isCallExpression(n)&&n.expression.getText(sf)==='client.apiCall.invoke').map(n=>shape(n));}
function financialRegion(sf){
 const candidates=collect(sf,n=>ts.isJsxElement(n)&&tag(n)==='details'&&n.getText(sf).includes('高级财务月结与历史口径'));
 need(candidates.length===1,'ONE_ADVANCED_FINANCE_REGION_REQUIRED');
 return candidates[0];
}
function gatingConditions(node) {
 const out=[];
 const add=part=>{if(ts.isBinaryExpression(part)&&part.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken){add(part.left);add(part.right);}else out.push(part.getText());};
 for(let p=node.parent;p&&!ts.isSourceFile(p);p=p.parent){
  if(ts.isBinaryExpression(p)&&p.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken)add(p.left);
  if(ts.isConditionalExpression(p))add(p.condition);
 }
 return out;
}
try {
 const save=process.argv.includes('--save');need(process.argv.slice(2).every(x=>x==='--save'),'ONLY_SAVE_FLAG_SUPPORTED');
 const currentRef=textGit('rev-parse','HEAD');git('merge-base','--is-ancestor',BASELINE,currentRef);
 const baseline=inventory(BASELINE),current=inventory(currentRef),protectedFiles={},changed=[];
 for(const [name,bytes] of baseline){need(fs.existsSync(path.join(ROOT,name))&&fs.lstatSync(path.join(ROOT,name)).isFile(),'REGULAR_EXISTING_SOURCE_REQUIRED',name);const now=read(name);if(!bytes.equals(now))changed.push(name);if(!ALLOWED.includes(name)){need(bytes.equals(now),'UNAPPROVED_APP_CHANGE',name);protectedFiles[name]=sha(now);}}
 for(const name of current.keys())if(!baseline.has(name))need(ALLOWED.includes(name),'UNAPPROVED_TRACKED_ADDITION',name);
 const sourceFiles=[];function walk(folder){for(const ent of fs.readdirSync(path.join(ROOT,folder),{withFileTypes:true})){const name=`${folder}/${ent.name}`;need(!ent.isSymbolicLink(),'NO_SOURCE_SYMLINK',name);if(ent.isDirectory())walk(name);else{need(ent.isFile(),'REGULAR_SOURCE_REQUIRED',name);sourceFiles.push(name);}}}walk('app/frontend/src');
 for(const name of sourceFiles)if(!baseline.has(name)){need(ALLOWED.includes(name),'UNAPPROVED_FRONTEND_ADDITION',name);changed.push(name);}
 need(same(changed.sort(),ALLOWED),'EXACT_APPROVED_SOURCE_SET_REQUIRED',JSON.stringify(changed));
 const before=parse(PAGE,baseline.get(PAGE)),after=parse(PAGE,read(PAGE)),functions={};
 for(const name of functionNames){const normalize=['loadData','loadGrowth'].includes(name);const a=shape(declaration(before,name),normalize),b=shape(declaration(after,name),normalize);need(same(a,b),'PROTECTED_DECLARATION_CHANGED',name);functions[name]={before_ast_sha256:digest(a),after_ast_sha256:digest(b),normalization:normalize?'Ignore only display timestamp setters; setGrowthLoadedAt may be guarded by growthResponse.data':'None'};}
 for(const name of ['loadData','loadGrowth'])for(const node of collect(declaration(after,name),timestampSetter)){need(node.expression.arguments.length===1,'TIMESTAMP_SETTER_SINGLE_VALUE');need(/^(?:new Date\(\)(?:\.toISOString\(\))?|Date\.now\(\))$/.test(node.expression.arguments[0].getText()),'TIMESTAMP_SETTER_ONLY_CURRENT_TIME',node.getText());}
 const apiBefore=apiShapes(before),apiAfter=apiShapes(after);need(same(apiBefore,apiAfter),'ALL_API_CALLS_URL_METHOD_PAYLOAD_AUTH_MUST_MATCH');
 const originalFinancial=financialRegion(before),newFinancial=financialRegion(after);need(same(shape(originalFinancial),shape(newFinancial)),'ADVANCED_FINANCIAL_UI_AND_CLOSE_GATES_CHANGED');
 const financialTables={};
 for(const key of ['formalProfit','unitEconomics']){
  const table=sf=>collect(sf,n=>ts.isJsxElement(n)&&tag(n)==='CompactFinanceTable'&&n.openingElement.getText(sf).includes(`CRM_COMMAND_TABLES.${key}`));
  const a=table(before),b=table(after);need(a.length===1&&b.length===1&&same(shape(a[0]),shape(b[0])),'FINANCIAL_TABLE_EXPRESSIONS_CHANGED',key);financialTables[key]=digest(shape(a[0]));
 }
 const oldGates=gatingConditions(originalFinancial),newGates=gatingConditions(newFinancial);
 need(same(oldGates,['!isMobile','growth',"section === 'insights'"]),'BASELINE_FINANCE_GATES_DIFFER_FROM_REVIEWED');
 need(['!isMobile','growth','isAdmin'].every(x=>newGates.includes(x)),'FINANCE_PERMISSION_MUST_RETAIN_DESKTOP_DATA_AND_ADMIN',JSON.stringify({oldGates,newGates}));
 // Closing dialog is unchanged, including reason length and busy gates.
 const getReopen=sf=>collect(sf,n=>ts.isJsxElement(n)&&tag(n)==='Dialog'&&n.openingElement.getText(sf).includes('reopenProfitMonth'));
 const oldReopen=getReopen(before),newReopen=getReopen(after);need(oldReopen.length===1&&newReopen.length===1&&same(shape(oldReopen[0]),shape(newReopen[0])),'REOPEN_DIALOG_AND_GATES_CHANGED');
 const pageRole=collect(after,n=>ts.isVariableDeclaration(n)&&n.name.getText()==='{ isAdmin }');need(pageRole.length===1&&pageRole[0].initializer?.getText()==='useRole()','ROLE_AUTHORITY_MUST_REMAIN_USE_ROLE');
 const comp=parse(COMPONENT,read(COMPONENT));
 need(!collect(comp,n=>ts.isImportDeclaration(n)&&/api|tokenStore|private-workspace|role-context/.test(n.moduleSpecifier.text)).length,'PRESENTATION_COMPONENT_MUST_NOT_IMPORT_AUTH_OR_TRANSPORT');
 need(!collect(comp,n=>ts.isCallExpression(n)&&/^(?:fetch|eval|WebSocket|XMLHttpRequest)$|\.invoke$|localStorage\.|sessionStorage\./.test(n.expression.getText())).length,'PRESENTATION_COMPONENT_NO_TRANSPORT_OR_STORAGE');
 const sheet=postcss.parse(read(CSS).toString(),{from:CSS});let ruleCount=0;sheet.walkRules(rule=>{for(const selector of rule.selector.split(','))need(/^\s*\.(?:management-action-page|mgt-action-detail|mgt-review-dialog)(?:\s|\.|:|>|\[|$)/.test(selector),'MANAGEMENT_ONLY_CSS_REQUIRED',selector);ruleCount++;});sheet.walkAtRules(at=>need(at.name==='media','ONLY_MEDIA_AT_RULES_ALLOWED',at.name));need(ruleCount>0&&!/url\s*\(/i.test(sheet.toString()),'LOCAL_SCOPED_STYLES_ONLY');
 if(save){need(currentRef!==BASELINE,'NEW_SOURCE_COMMIT_REQUIRED');need(same(git('diff','--name-only','-z',BASELINE,currentRef,'--','app/').toString().split('\0').filter(Boolean).sort(),ALLOWED),'COMMITTED_SCOPE_MUST_MATCH');for(const [name,bytes]of current)need(bytes.equals(read(name)),'APP_WORKTREE_MUST_MATCH_COMMIT',name);need(sourceFiles.every(n=>current.has(n)),'COMMIT_ALL_APPROVED_SOURCE');}
 const privateFiles=Object.entries(protectedFiles).filter(([n])=>/private|personal.finance/i.test(n));need(privateFiles.length>0,'PRIVATE_SOURCE_EVIDENCE_REQUIRED');
 const proof={format_version:1,stage:'MANAGEMENT_ACTION_DESK_PRESENTATION_SOURCE_PROOF',source_mode:save?'committed':'working_tree_preview',baseline_source_sha:BASELINE,baseline_carrier_sha:'3d61155f11dea2d1466d75c06b09a621a9be947d',source_sha:currentRef,generated_at:new Date().toISOString(),management_file_before_sha256:sha(baseline.get(PAGE)),management_file_after_sha256:sha(read(PAGE)),component_file_sha256:sha(read(COMPONENT)),styles_file_sha256:sha(read(CSS)),financial_calculations_unchanged:true,close_conditions_unchanged:true,private_workspace_source_unchanged:true,data_reads_unchanged:true,mutation_handlers_unchanged:true,management_presentation_only:true,evidence:{method:'AST equality for named financial calculations, original API invocation trees and write handlers; complete advanced financial UI and closing dialog subtrees unchanged; byte equality of every other tracked app file. UI additions require separate review and browser QA.',scope:'Source preservation proof only; no claim of live deployment or browser completion.',changed_application_files:changed,preserved_functions:functions,preserved_api_call_count:apiBefore.length,preserved_api_calls_sha256:digest(apiBefore),preserved_mutation_handlers_sha256:digest(mutableHandlers.map(n=>[n,functions[n].before_ast_sha256])),preserved_management_calculations_sha256:digest(calcNames.map(n=>[n,functions[n].before_ast_sha256])),preserved_finance_region_sha256:digest(shape(originalFinancial)),preserved_financial_tables:financialTables,preserved_reopen_dialog_sha256:digest(shape(oldReopen[0])),preserved_finance_ancestor_gates:oldGates,protected_application_file_count:Object.keys(protectedFiles).length,protected_application_inventory_sha256:digest(protectedFiles),private_file_count:privateFiles.length,private_source_inventory_sha256:digest(privateFiles),styles_scoped_rule_count:ruleCount,verifier_sha256:sha(fs.readFileSync(fileURLToPath(import.meta.url)))}};
 fs.writeFileSync(path.join(DIR,save?'source-proof.json':'working-tree-source-proof.json'),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify({ok:true,stage:proof.stage,functions:functionNames.length,api_calls:apiBefore.length,protected_app_files:Object.keys(protectedFiles).length,private_files:privateFiles.length,source_mode:proof.source_mode},null,2));
}catch(error){console.error(error.stack||String(error));process.exitCode=1;}
