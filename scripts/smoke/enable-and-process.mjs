// Follow-up: enable a second episode by hand, press Process, and open its stats.
// Usage: node walk2.mjs <base-url> <env-file> <out-dir>
import fs from 'fs';
import { chromium } from 'playwright';

const [BASE, envFile, OUT] = process.argv.slice(2);
const env = Object.fromEntries(
  fs.readFileSync(envFile, 'utf8').split('\n').filter((l) => l.includes('=')).map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)])
);
const note = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);
let n = 30;
const shot = async (page, label) => {
  n += 1;
  await page.screenshot({ path: `${OUT}/${n}-${label}.jpg`, type: 'jpeg', quality: 70, scale: 'css' });
  note(`shot ${n}-${label}.jpg`);
};

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  colorScheme: 'light',
  recordVideo: { dir: `${OUT}/video-manual`, size: { width: 1280, height: 800 } },
});
const page = await ctx.newPage();
page.on('pageerror', (e) => note(`PAGEERROR ${e.message}`));
page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/api/auth/me')) note(`HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
try {
  await page.goto(`${BASE}/`);
  await page.locator('#username').waitFor();
  await page.fill('#username', env.PODLY_ADMIN_USERNAME);
  await page.fill('#password', env.PODLY_ADMIN_PASSWORD);
  await page.keyboard.press('Enter');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'));
  await page.locator('button').filter({ hasText: /episodes/ }).first().click();
  await page.waitForTimeout(3500);

  const toggle = page.getByRole('switch').nth(1);
  note(`second episode switch aria-checked=${await toggle.getAttribute('aria-checked')}`);
  await toggle.scrollIntoViewIfNeeded();
  await shot(page, 'second-episode-disabled');
  await toggle.click();
  const confirm = page.getByRole('button', { name: 'Confirm & process' });
  await confirm.waitFor({ timeout: 10000 });
  await page.waitForTimeout(600);
  await shot(page, 'second-episode-confirm');
  await confirm.click();
  note('confirmed enable & process');
  await page.waitForFunction(() => document.querySelectorAll('[role="switch"]')[1]?.getAttribute('aria-checked') === 'true', null, { timeout: 20000 });
  await page.waitForTimeout(2500);
  await shot(page, 'second-episode-processing');

  const statsButtons = page.getByRole('button', { name: /^Stats$/ });
  const started = Date.now();
  while ((await statsButtons.count()) < 2) {
    if (Date.now() - started > 15 * 60 * 1000) throw new Error('second episode did not finish within 15 minutes');
    await page.waitForTimeout(5000);
  }
  note(`second episode finished after ${Math.round((Date.now() - started) / 1000)}s`);
  await shot(page, 'second-episode-processed');
  await statsButtons.nth(1).click();
  await page.waitForTimeout(3500);
  await shot(page, 'second-episode-stats');
} catch (err) {
  note(`FAILED: ${err.message}`);
  await shot(page, 'failure').catch(() => {});
}
await ctx.close();
await browser.close();
