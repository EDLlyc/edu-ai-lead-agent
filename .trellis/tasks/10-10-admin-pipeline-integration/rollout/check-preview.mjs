import { chromium, expect } from '/root/projects/edu-ai-lead-agent/frontend/node_modules/@playwright/test/index.mjs';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const origin='http://127.0.0.1:5180';
const report={at:new Date().toISOString(),production:{url:origin+'/admin/',documents:[],http:{},assets:{},errors:[],blockedWrites:[]},demo:{url:'http://127.0.0.1:5181/admin/'}};
const browser=await chromium.launch({headless:true});
try {
 const context=await browser.newContext({viewport:{width:390,height:844},locale:'zh-CN'});
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!==origin||req.method()!=='GET') {report.production.blockedWrites.push({path:url.pathname,method:req.method()});await route.abort();return;}
  await route.continue();
 });
 const page=await context.newPage();page.on('pageerror',e=>report.production.errors.push(e.message));
 for(const path of ['/admin/','/admin/sources','/admin/wechat-publish','/admin/audit','/admin/layout-templates']) {
  const response=await page.goto(origin+path,{waitUntil:'networkidle'});expect(response.status()).toBe(200);
  await expect(page.getByLabel('数据环境')).toContainText('生产环境 · 真实数据');
  await expect(page.getByRole('button',{name:'登录',exact:true})).toBeVisible();
  const refreshed=await page.reload({waitUntil:'networkidle'});expect(refreshed.status()).toBe(200);
  await expect(page.getByRole('button',{name:'登录',exact:true})).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  report.production.documents.push({path,status:200,reload:200,unauthenticatedLogin:true,mobileOverflow:false});
 }
 await page.screenshot({path:'/tmp/edu-admin-pipeline-integration/production-login-mobile.png',fullPage:true});
 for(const [path,status] of [['/api/v1/admin/auth/me',401],['/api/v1/admin/wechat/publish-jobs?limit=20',401],['/assets/missing-pipeline-check.js',404],['/api/v1/unproxied-pipeline-check',404],['/outside-pipeline-check',404]]) {
  const response=await context.request.get(origin+path);expect(response.status()).toBe(status);report.production.http[path]=status;
 }
 const candidate=JSON.parse(await readFile('/tmp/edu-admin-pipeline-integration/candidate.json','utf8'));
 for(const [name,hash] of Object.entries(candidate.frontend)) {
  const response=await context.request.get(origin+'/'+name);expect(response.status()).toBe(200);
  const actual=createHash('sha256').update(await response.body()).digest('hex');expect(actual).toBe(hash);report.production.assets[name]=actual;
 }
 expect(report.production.errors).toEqual([]);expect(report.production.blockedWrites).toEqual([]);
 await context.close();
 const demoContext=await browser.newContext({viewport:{width:390,height:844},locale:'zh-CN'});
 const demo=await demoContext.newPage();
 await demo.goto(report.demo.url+'wechat-publish',{waitUntil:'networkidle'});
 await expect(demo.getByLabel('数据环境')).toContainText('演示环境 · 模拟数据 · 只读');
 await demo.getByRole('tab',{name:'发布记录',exact:true}).click();
 await expect(demo.getByRole('navigation',{name:'发布记录分页'})).toContainText('共 65 条记录');
 report.demo={...report.demo,label:'演示环境 · 模拟数据 · 只读',fixtureJobs:65};
 await demo.screenshot({path:'/tmp/edu-admin-pipeline-integration/demo-jobs-mobile.png',fullPage:true});
 await demo.goto('http://127.0.0.1:5181/admin/layout-templates',{waitUntil:'networkidle'});
 await expect(demo.getByText('本页显示已保存的配置，未检测草稿服务的实时运行状态；生成后请在草稿箱核对效果。')).toBeVisible();
 await expect(demo.getByText(/9 月 28|现在还不会生效/)).toHaveCount(0);
 report.demo.templateNoticeUpdated=true;
 await demoContext.close();
} finally {await browser.close();}
await writeFile('/tmp/edu-admin-pipeline-integration/preview-result.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
