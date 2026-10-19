// 보고서 스크린샷 (Playwright + 설치된 Chromium, 네트워크 차단).
// 사용: node screenshot_report.js <report.html> <out_prefix> [light|dark]
const path = require('path');
let pw;
try { pw = require('playwright'); } catch (e) { console.error('NO_PLAYWRIGHT'); process.exit(3); }
(async () => {
  const [html, prefix, theme] = process.argv.slice(2);
  const browser = await pw.chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: theme || 'light' });
  const page = await ctx.newPage();
  const ext = [];
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith('file:')) return route.continue();
    ext.push(u); return route.abort();
  });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  await page.goto('file://' + path.resolve(html));
  await page.screenshot({ path: prefix + '_top.png' });
  const el = await page.$('#sec-env') || await page.$('h2:nth-of-type(3)');
  if (el) await el.scrollIntoViewIfNeeded();
  await page.evaluate(() => { const h = [...document.querySelectorAll('h2')][2]; if (h) h.scrollIntoView(); });
  await page.screenshot({ path: prefix + '_envelope.png' });
  console.log(JSON.stringify({ external_requests: ext, page_errors: errs }));
  await browser.close();
})().catch((e) => { console.error(String(e)); process.exit(1); });
