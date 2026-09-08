// Local browser verification only. Reads one persisted successful job and its original bytes.
// All browser API calls are intercepted: NO generation, share, download counter, or DB writes.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.cwd();
const require = createRequire(resolve(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
const target = resolve(root, 'output/ip-creation-comparison');
await mkdir(target, { recursive: true });
const sql = `SELECT json_build_object('job',to_jsonb(j),'output',to_jsonb(a),
 'references',(SELECT json_agg(to_jsonb(r) ORDER BY g.ordinal)
 FROM ip_asset_generation_references g JOIN ip_assets r ON r.id=g.asset_id
 WHERE g.job_id=j.id)) FROM ip_asset_generation_jobs j
 JOIN ip_assets a ON a.id=j.output_asset_id
 WHERE j.status='succeeded' ORDER BY j.created_at DESC LIMIT 1`;
const record = JSON.parse(execFileSync('docker', [
  'exec','edu-ai-lead-agent-postgres-1','sh','-c',
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"','sh',sql,
], { encoding: 'utf8' }));
assert(record.references.length > 0 && record.references.length <= 3);

function card(row) {
  const result = {};
  for (const key of ['asset_ref','canonical_name','character','asset_type','source_kind',
    'department','contributor','emotion','action','scene','intended_use','style','media_type',
    'byte_size','width','height','has_alpha','orientation','status','semantic_status','created_at',
    'safe_original_filename','name_version']) result[key] = row[key];
  return { ...result, tags: [], shared: row.shared_at !== null, favorite: false,
    checksum_ref: row.blob_sha256.slice(0,12),
    thumbnail_url: `/api/v1/ip-assets/${row.asset_ref}/thumbnail?v=1`,
    preview_url: `/api/v1/ip-assets/${row.asset_ref}/preview`,
    download_url: `/api/v1/ip-assets/${row.asset_ref}/download` };
}
const references = record.references.map(card);
const output = card(record.output);
const images = new Map();
for (const row of [...record.references, record.output]) {
  // Use the local MinIO namespace: the currently running Docker bridge cannot resolve minio.
  // Credentials stay in the container environment; output contains only object bytes.
  const body = execFileSync('docker', ['exec','edu-ai-lead-agent-minio-1','sh','-c',
    'MC_HOST_replay="http://$MINIO_ROOT_USER:$MINIO_ROOT_PASSWORD@127.0.0.1:9000" mc cat "replay/$1/$2"',
    'sh',row.bucket,row.object_key], { maxBuffer: 30 * 1024 * 1024 });
  assert.equal(body.length, row.byte_size);
  assert.equal(createHash('sha256').update(body).digest('hex'), row.blob_sha256);
  images.set(row.asset_ref, { body, contentType: row.media_type });
}
const job = {
  job_ref: record.job.job_ref, status: 'succeeded', created: false,
  generation_available: true, output_asset_ref: output.asset_ref,
  reference_asset_refs: references.map(item => item.asset_ref),
  reference_asset_ref: references[0].asset_ref, error_code: null,
  status_url: `/api/v1/ip-assets/generations/${record.job.job_ref}`,
  created_at: record.job.created_at, completed_at: record.job.completed_at,
};
// Deliberately synthetic browser profile, never sent to a real API.
const profile = { token: 'A'.repeat(43), profileRef: `ipp_${'a'.repeat(20)}`,
  displayName: '历史任务回放', department: '本地效果验证' };
process.env.VITE_IP_ASSET_HUB_ENABLED = 'true';
process.env.VITE_API_BASE_URL = 'http://127.0.0.1:5173';
const server = await createServer({ root: resolve(root,'frontend'),
  configFile: resolve(root,'frontend/vite.config.ts'),
  define: { 'import.meta.env.VITE_IP_ASSET_HUB_ENABLED': JSON.stringify('true'),
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify('http://127.0.0.1:5173') },
  server: { host: '127.0.0.1', port: 5173, strictPort: true }, logLevel: 'error' });
let browser;
const failures = [];
const pageErrors = [];
let submitted = 0;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 },
    deviceScaleFactor: 1, reducedMotion: 'reduce' });
  await context.addInitScript(value => {
    localStorage.setItem('edu-ai.ip-assets.profile.v1', JSON.stringify(value));
    sessionStorage.setItem('sai.ip-assets.demo-access.v1', 'granted');
  }, profile);
  await context.route('**/api/v1/**', async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const respond = data => route.fulfill({ status: 200, json: data });
    if (path.endsWith('/capabilities')) return respond({ enabled: true, authentication: 'none',
      deployment_boundary:'company_intranet', semantic_search_available: true,
      generation_available: true, recognition_available: true, max_upload_bytes:26214400,
      accepted_media_types:['image/png','image/jpeg','image/webp'] });
    if (path.endsWith('/profiles/me')) return respond({ profile_ref:profile.profileRef,
      display_name:profile.displayName, department:profile.department,
      identity_boundary:'browser_local_unverified', created_at:job.created_at });
    if (path.endsWith('/profiles/me/assets')) return respond({ items:[], next_cursor:null });
    if (path.endsWith('/generations') && req.method() === 'POST') {
      const body = req.postDataJSON();
      assert.equal(body.prompt, record.job.prompt);
      assert.deepEqual(body.reference_asset_refs, job.reference_asset_refs);
      submitted += 1;
      return respond(job); // Replay only: never forward this request.
    }
    if (path === job.status_url && req.method() === 'GET') return respond(job);
    if (path === '/api/v1/ip-assets' && req.method() === 'GET')
      return respond({items:references,next_cursor:null});
    const media = path.match(/\/ip-assets\/(ipa_[a-f0-9]+)\/(preview|thumbnail)$/);
    if (media && req.method() === 'GET' && images.has(media[1])) {
      if (media[1] === output.asset_ref && !output.shared)
        assert.equal(req.headers()['x-ip-profile-token'], profile.token);
      return route.fulfill({status:200,...images.get(media[1])});
    }
    const item = [...references,output].find(asset => path === `/api/v1/ip-assets/${asset.asset_ref}`);
    if (item && req.method() === 'GET') return respond(item);
    failures.push(`${req.method()} ${path}`);
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:5173/ip-assets/create?reference=${references[0].asset_ref}`);
  await page.getByLabel('画面描述').fill(record.job.prompt);
  await page.getByRole('combobox', { name: /IP 角色/ }).selectOption(record.job.character);
  await page.getByRole('button', { name: '生成 1:1 图片', exact: true }).click();
  const comparison = page.getByRole('region', { name: '从参考，到新画面' });
  await comparison.waitFor({ timeout: 15000 });
  await comparison.locator('img').evaluateAll(async items => {
    await Promise.all(items.map(image => image.decode()));
  });
  await comparison.screenshot({ path: resolve(target,'comparison-desktop.png') });
  // Confirm that edits to the next brief cannot rewrite completed provenance.
  await page.getByLabel('画面描述').fill('这个新输入还没有提交');
  assert((await comparison.innerText()).includes(record.job.prompt));
  assert(!(await comparison.innerText()).includes('这个新输入还没有提交'));
  const zoomTrigger = comparison.getByRole('button', { name: /放大/ }).last();
  await zoomTrigger.click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('dialog').locator('img').evaluateAll(async items =>
    Promise.all(items.map(image => image.decode())));
  await page.screenshot({path:resolve(target,'comparison-zoom.png')});
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(),0);
  assert(await zoomTrigger.evaluate(el => el === document.activeElement));
  await page.setViewportSize({width:390,height:844});
  await comparison.getByRole('heading', { name: '从参考，到新画面' }).click();
  await comparison.evaluate(element => element.scrollIntoView({ block:'start' }));
  await comparison.screenshot({path:resolve(target,'comparison-mobile.png')});
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth, document:document.documentElement.scrollWidth }));
  assert(dimensions.document <= dimensions.viewport);
  assert.equal(submitted,1);
  assert.deepEqual(failures,[]);
  assert.deepEqual(pageErrors,[]);
  const report = { mode:'Read-only replay of a real historical local job; no new generation',
    jobRef:job.job_ref, createdAt:job.created_at, referenceCount:references.length,
    verifiedOriginalHashes:true, submittedRequestsIntercepted:submitted,
    realMutationRequests:0, snapshotIsolation:true, zoomEscapeAndFocusRestore:true,
    mobileDimensions:dimensions, unexpectedRequests:failures, pageErrors };
  await writeFile(resolve(target,'verification.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {
  await browser?.close();
  await server.close();
}
