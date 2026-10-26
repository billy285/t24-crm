const fs=require('fs'),cp=require('child_process'),path=require('path');
const guard=require('./verify_ui_scope.cjs');
const base='69666997496e57189e6e2f32f33467a584fe37c5';
const files=[...cp.execFileSync('git',['diff','--name-only','--','app/'],{encoding:'utf8'}).trim().split('\n').filter(Boolean),...cp.execFileSync('git',['ls-files','--others','--exclude-standard','app/frontend/src'],{encoding:'utf8'}).trim().split('\n').filter(Boolean)].sort();
const reasons={
 'SalesWorkbench.tsx':'Exact requested merchant selection; existing result payload and protection unchanged; synchronous submit lock, response identity checks and independent auxiliary refresh with scope protection',
 'sales-workbench-flow.ts':'Pure selection of tasks from an already authorized queue; no transport or writes',
 'Customers.tsx':'Consume invite UI deep link only after freshly verified customer detail and original can_manage_access; no invitation saved by navigation',
 'ServiceFollowThrough.tsx':'Separate owner receipt and invitation work from team reception, preserving server counts and original action gates',
 'SalesDealHandoffQueue.tsx':'Owner/team grouping; exact selected handoff and filter return path; existing guarded forms only',
 'SalesDealHandoffDialog.tsx':'Registered receipt exposes existing guarded queue actions with source return path; no submission or financial change',
 'sales-handoff-navigation.ts':'Pure safe internal navigation to existing authorized forms; no permissions or writes',
 'owner-handoff-entry.css':'Scoped owner queue visual hierarchy and responsive layout',
 'SalesLeadDossier.tsx':'Current authorized context and quality hints; original data, event handlers, protection and writes unchanged',
 'sales-lead-dossier.css':'Dossier-scoped responsive context and quality styles',
 'sales-dossier-quality.ts':'Pure missing-data hints from current enrichment and summary; no historical substitution or data updates'
};
const registry={baseline_source_sha:base,scope:'Sales workflow navigation, read scheduling and presentation; no backend, financial, permission or private changes',files:{},hard_deltas:{}};const payload={files:{}};
for(const file of files){
 if(!guard.allowedPath(file))throw Error('Unreviewable file '+file);
 const reason=reasons[path.basename(file)];if(!reason)throw Error('No explicit review reason '+file);
 let before='';try{before=cp.execFileSync('git',['show',base+':'+file],{encoding:'utf8',stdio:['ignore','pipe','ignore']});}catch{}
 const after=fs.readFileSync(file,'utf8');payload.files[file]={before,after};const a=guard.inventory(file,before),b=guard.inventory(file,after);registry.files[file]={};
 for(const category of guard.categories){const d=guard.delta(a.buckets[category],b.buckets[category]);for(const direction of ['removed','added'])d[direction]=d[direction].map(e=>({...e,review_id:'CRM-MANAGEMENT-FLOW-'+path.basename(file)+'-'+category,reason}));registry.files[file][category]=d;}
 if(['Customers.tsx','SalesWorkbench.tsx'].includes(path.basename(file)))for(const category of Object.keys(a.hard)){
  const d=guard.delta(a.hard[category],b.hard[category]);if(!d.removed.length&&!d.added.length)continue;
  registry.hard_deltas[file]??={};registry.hard_deltas[file][category]={...d,review_id:'CRM-FLOW-SCOPED-'+path.basename(file)+'-'+category,reason};
 }
}
const out=__dirname,body=JSON.stringify(registry,null,2)+'\n';fs.writeFileSync(path.join(out,'approved-deltas.json'),body);fs.writeFileSync(path.join(out,'source-allowlist.json'),JSON.stringify(files,null,2)+'\n');
const report=guard.verify(payload,registry,guard.hash(body));fs.writeFileSync(path.join(out,'scope-current.json'),JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify({files:files.length,registered:report.registered_delta_count,hard:report.hard_protected_counts}));
