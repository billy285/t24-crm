/* Exact, reviewed semantic deltas for CRM read scheduling and presentation only. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const ts=require(path.resolve('app/frontend/node_modules/typescript'));
const BASE='a03af2220ecd6cb063f97ae279bfa288f07ca97e';
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const print=ts.createPrinter({removeComments:true});
const categories=['imports','declarations','view_expressions','props','event_contexts','styles'];
function allowedPath(file) {
 if(['app/frontend/src/App.tsx','app/frontend/vite.config.ts'].includes(file))return true;
 return /^app\/frontend\/src\/(?:components|pages)\/[A-Za-z0-9_./-]+\.(?:tsx|ts|css)$/.test(file)&&!file.split('/').some(p=>p.startsWith('.'))&&!/private|auth|token|session|payment-utils|subscription-utils/i.test(file);
}
function containsJsx(node){if(ts.isJsxElement(node)||ts.isJsxSelfClosingElement(node)||ts.isJsxFragment(node))return true;let yes=false;ts.forEachChild(node,c=>{if(containsJsx(c))yes=true});return yes;}
function inventory(file,text) {
 const buckets=Object.fromEntries(categories.map(c=>[c,[]]));
 const hard={mutations:[],requests:[],gates:[],routes:[],private_branches:[],ordinary_dialog:[],deduction_block:[],mutation_handlers:[]};
 if(file.endsWith('.css')){if(text)buckets.styles.push({key:'stylesheet',hash:hash(text),code:text});return{buckets,hard};}
 const source=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 if(source.parseDiagnostics.length)throw Error('UI_SOURCE_SYNTAX_REJECTED:'+file);
 const pp=n=>print.printNode(ts.EmitHint.Unspecified,n,source);
 function shape(n){const transformed=ts.transform(n,[context=>root=>{const visit=x=>ts.isJsxElement(x)||ts.isJsxSelfClosingElement(x)||ts.isJsxFragment(x)?ts.factory.createIdentifier('__VIEW__'):ts.visitEachChild(x,visit,context);return ts.visitNode(root,visit);}]);const result=pp(transformed.transformed[0]);transformed.dispose();return result;}
 function record(category,key,code){buckets[category].push({key,hash:hash(code),code});}
 function hardRecord(category,key,code){hard[category].push({key,hash:hash(code)});}
 const mutationMethods=new Set(['POST','PUT','PATCH','DELETE']);
 function methodArgument(a){return ts.isObjectLiteralExpression(a)&&a.properties.some(p=>ts.isPropertyAssignment(p)&&p.name.getText(source).replace(/['"]/g,'')==='method'&&ts.isStringLiteralLike(p.initializer)&&mutationMethods.has(p.initializer.text.toUpperCase()));}
 function walkHard(n,scopes=[]) {
  const name=ts.isFunctionDeclaration(n)?n.name?.text:ts.isFunctionLike(n)&&ts.isVariableDeclaration(n.parent)&&ts.isIdentifier(n.parent.name)?n.parent.name.text:undefined;
  const scope=scopes.join('/');
  if(ts.isVariableDeclaration(n)&&ts.isIdentifier(n.name)&&n.initializer) {
   const v=n.name.text;
   if(/^can[A-Z]/.test(v)||['isOwner','isAdmin','canAdmin','permissions','accessMemberPayload','attributionReady','attributionIsDirect','attributionRequiresHistory'].includes(v))hardRecord('gates',scope+'/'+v,pp(n.initializer));
   if(file==='app/frontend/src/App.tsx'&&['PrivateWorkspace','AuthCallback','AuthError','LoginPage','NotFound'].includes(v))hardRecord('private_branches',v,pp(n.initializer));
   if(file==='app/frontend/src/components/ui/dialog.tsx'&&['DialogContent','DialogOverlay','DialogHeader','DialogFooter','DialogTitle','DialogDescription','Dialog','DialogClose','DialogPortal','DialogTrigger'].includes(v))hardRecord('ordinary_dialog',v,pp(n.initializer));
  }
  if(ts.isIfStatement(n)&&file==='app/frontend/src/components/Layout.tsx'&&n.expression.getText(source).includes("'/private-workspace'"))hardRecord('private_branches','private-shell-return',pp(n));
  if((ts.isJsxElement(n)||ts.isJsxSelfClosingElement(n))&&(ts.isJsxElement(n)?n.openingElement.tagName:n.tagName).getText(source)==='Route')hardRecord('routes','Route',pp(n));
  if(ts.isCallExpression(n)) {
   const callee=n.expression.getText(source),method=ts.isPropertyAccessExpression(n.expression)?n.expression.name.text.toLowerCase():'';
   const moduleCacheDelete=file==='app/frontend/src/components/crm-route-modules.ts'&&callee==='moduleRequests.delete'&&n.arguments.length===1&&n.arguments[0].getText(source)==='route';
   if((['create','update','remove','delete','post','put','patch','destroy'].includes(method)&&!moduleCacheDelete)||n.arguments.some(a=>ts.isStringLiteralLike(a)&&mutationMethods.has(a.text.toUpperCase()))||n.arguments.some(methodArgument)) {
    hardRecord('mutations',callee,pp(n));
    for(let owner=n.parent;owner&&owner!==source;owner=owner.parent)if(ts.isFunctionLike(owner)&&!containsJsx(owner)) {
     const ownerName=ts.isFunctionDeclaration(owner)?owner.name?.text:ts.isVariableDeclaration(owner.parent)&&ts.isIdentifier(owner.parent.name)?owner.parent.name.text:'<anonymous>';
     if(!(file==='app/frontend/src/pages/Finance.tsx'&&ownerName==='loadData'))hardRecord('mutation_handlers',ownerName||'<anonymous>',pp(owner));
    }
   }
   if(/^(?:invokeWithAuth|api|fetch|client\.apiCall\.invoke)$/.test(callee)||/^client\.entities\.[^.]+\.(?:query|queryAll|create|update|delete|remove)$/.test(callee))hardRecord('requests',callee,pp(n));
  }
  ts.forEachChild(n,c=>walkHard(c,name?[...scopes,name]:scopes));
 }
 walkHard(source);
 if(file==='app/frontend/src/pages/Finance.tsx') {
  const start='      try {\n        const months = new Set<string>();',end="      } catch (e) { console.warn('load rates failed', e); }";
  if(text.includes(start)){const a=text.indexOf(start),b=text.indexOf(end,a);if(b<0)throw Error('DEDUCTION_BLOCK_INCOMPLETE');hardRecord('deduction_block','existing-ensure-list',text.slice(a,b+end.length));}
 }
 function walk(n,scopes=[],contexts=[]) {
  if(ts.isImportDeclaration(n)){record('imports','import',pp(n));return;}
  if(ts.isJsxText(n))return;
  if(ts.isJsxAttribute(n)&&['className','style'].includes(n.name.getText(source)))return;
  const fn=ts.isFunctionDeclaration(n)||ts.isFunctionExpression(n)||ts.isArrowFunction(n);
  const name=ts.isFunctionDeclaration(n)?n.name?.text:fn&&ts.isVariableDeclaration(n.parent)&&ts.isIdentifier(n.parent.name)?n.parent.name.text:undefined;
  const scope=scopes.join('/');
  if(fn&&!containsJsx(n))record('declarations','function:'+scope+'/'+(name||'<anonymous>'),pp(n));
  if(ts.isVariableDeclaration(n)&&n.initializer)record('declarations','variable:'+scope+'/'+pp(n.name),containsJsx(n.initializer)?shape(n.initializer):pp(n.initializer));
  if(ts.isJsxAttribute(n)) {
   const key=n.name.getText(source),value=n.initializer?pp(n.initializer):'true';
   record('props',key,value);
   if(/^on[A-Z]/.test(key))record('event_contexts',key,JSON.stringify({value,contexts}));
  }
  if(ts.isJsxExpression(n)&&n.expression&&!ts.isJsxAttribute(n.parent))record('view_expressions',scope,containsJsx(n.expression)?shape(n.expression):pp(n.expression));
  let nextContexts=contexts;
  if(ts.isJsxExpression(n)&&n.expression&&containsJsx(n.expression))nextContexts=[...contexts,'condition:'+shape(n.expression)];
  if(ts.isJsxElement(n)&&n.openingElement.tagName.getText(source)==='fieldset') {
   const disabled=n.openingElement.attributes.properties.find(a=>ts.isJsxAttribute(a)&&a.name.getText(source)==='disabled');
   if(disabled)nextContexts=[...contexts,'fieldset:'+pp(disabled)];
  }
  ts.forEachChild(n,c=>walk(c,name?[...scopes,name]:scopes,nextContexts));
 }
 walk(source);
 return{buckets,hard};
}
function delta(original,current) {
 const old=[...original],added=[];
 for(const item of current){const at=old.findIndex(v=>v.key===item.key&&v.hash===item.hash);if(at<0)added.push(item);else old.splice(at,1);}
 const sort=xs=>xs.sort((a,b)=>(a.key+'\0'+a.hash).localeCompare(b.key+'\0'+b.hash));
 return{removed:sort(old),added:sort(added)};
}
function fingerprints(items){return items.map(x=>({key:x.key,hash:x.hash})).sort((a,b)=>(a.key+'\0'+a.hash).localeCompare(b.key+'\0'+b.hash));}
function verify(payload,registry,registryHash) {
 if(registry.baseline_source_sha!==BASE)throw Error('EXACT_APPROVED_BASELINE_REQUIRED');
 const reviewed=[],hardCounts={},used=[];
 for(const[file,pair]of Object.entries(payload.files||{})) {
  if(!allowedPath(file))throw Error('SOURCE_SCOPE_REJECTED:'+file);
  const before=inventory(file,pair.before),after=inventory(file,pair.after);
  for(const category of Object.keys(before.hard)) {
   const a=JSON.stringify(fingerprints(before.hard[category])),b=JSON.stringify(fingerprints(after.hard[category]));
   if(a!==b)throw Error('PROTECTED_'+category.toUpperCase()+'_DRIFT:'+file);
   hardCounts[category]=(hardCounts[category]||0)+before.hard[category].length;
  }
  const approved=registry.files[file]||{};
  for(const category of categories) {
   const actual=delta(before.buckets[category],after.buckets[category]),expected=approved[category]||{removed:[],added:[]};
   for(const direction of ['removed','added']) {
    if(JSON.stringify(fingerprints(actual[direction]))!==JSON.stringify(fingerprints(expected[direction])))throw Error('UNREGISTERED_'+category.toUpperCase()+'_'+direction.toUpperCase()+':'+file);
    for(const entry of expected[direction]){if(!entry.reason||!entry.review_id)throw Error('EXPLICIT_DELTA_REVIEW_REQUIRED');used.push({file,category,direction,key:entry.key,sha256:entry.hash,review_id:entry.review_id,reason:entry.reason});}
   }
  }
  if(pair.before!==pair.after)reviewed.push(file);
 }
 return{unchanged:true,mutation_calls_unchanged:true,original_api_requests_unchanged:true,authorization_gates_unchanged:true,private_and_ordinary_dialog_unchanged:true,registered_read_and_ui_changes_only:true,unknown_semantic_drift:false,baseline_source_sha:BASE,approved_deltas_sha256:registryHash,hard_protected_counts:hardCounts,registered_delta_count:used.length,registered_deltas:used,ui_read_filters_require_review:reviewed};
}
module.exports={inventory,delta,verify,categories,allowedPath,BASE,hash};
if(require.main===module) {
 const body=fs.readFileSync(path.join(__dirname,'approved-deltas.json'));
 const result=verify(JSON.parse(fs.readFileSync(0,'utf8')),JSON.parse(body),hash(body));
 process.stdout.write(JSON.stringify(result));
}
