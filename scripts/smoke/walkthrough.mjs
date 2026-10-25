// End-to-end walkthrough of a fresh upstream Podly instance running the ported UI.
// Usage: node walk.mjs <base-url> <env-file> <out-dir>
import fs from 'fs';
import { chromium, devices } from 'playwright';

const [BASE, envFile, OUT] = process.argv.slice(2);
const env = Object.fromEntries(
  fs.readFileSync(envFile, 'utf8').split('\n').filter((l) => l.includes('=')).map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)])
);
const FEED_URL = 'https://feeds.npr.org/500005/podcast.xml';
fs.mkdirSync(OUT, { recursive: true });

const log = [];
const note = (msg) => { const line = `[${new Date().toISOString().slice(11, 19)}] ${msg}`; log.push(line); console.log(line); };
let n = 0;
const shot = async (page, label) => {
  n += 1;
  const file = `${String(n).padStart(2, '0')}-${label}.jpg`;
  await page.screenshot({ path: `${OUT}/${file}`, type: 'jpeg', quality: 70, scale: 'css' });
  note(`shot ${file}`);
};
// Settings show API keys, key previews and server addresses. This runs before any
// page script and blurs every Settings field from the first painted frame, so
// screenshots and recordings never capture them.
const MASK_SETTINGS = () => {
  const apply = () => document.documentElement.toggleAttribute('data-smoke-mask', location.pathname.startsWith('/config'));
  for (const fn of ['pushState', 'replaceState']) {
    const original = history[fn];
    history[fn] = function (...args) { const result = original.apply(this, args); apply(); return result; };
  }
  window.addEventListener('popstate', apply);
  const install = () => {
    const style = document.createElement('style');
    style.textContent = 'html[data-smoke-mask] main input, html[data-smoke-mask] main textarea, html[data-smoke-mask] main select { filter: blur(7px) !important; }';
    document.documentElement.appendChild(style);
    apply();
  };
  if (document.documentElement) install(); else document.addEventListener('DOMContentLoaded', install);
};
const watch = (page, tag) => {
  page.on('pageerror', (e) => note(`${tag} PAGEERROR ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') note(`${tag} console.error ${m.text().slice(0, 200)}`); });
  page.on('response', (r) => { if (r.status() >= 400) note(`${tag} HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
};

const browser = await chromium.launch();
const desktop = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  colorScheme: 'dark',
  recordVideo: { dir: `${OUT}/video`, size: { width: 1280, height: 800 } },
});
await desktop.addInitScript(MASK_SETTINGS);
const page = await desktop.newPage();
watch(page, 'desktop');

try {
  // Sign in: a wrong password first, then the real one.
  await page.goto(`${BASE}/`);
  await page.locator('#username').waitFor({ timeout: 30000 });
  await page.waitForTimeout(800);
  await shot(page, 'login');
  await page.fill('#username', env.PODLY_ADMIN_USERNAME);
  await page.fill('#password', 'wrong-password');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1200);
  await shot(page, 'login-wrong-password');
  await page.fill('#password', env.PODLY_ADMIN_PASSWORD);
  await page.keyboard.press('Enter');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 });
  await page.waitForTimeout(2000);
  await shot(page, 'home-empty');
  note('signed in');

  // Settings tour.
  await page.getByRole('link', { name: 'Settings' }).first().click();
  await page.waitForTimeout(2000);
  await shot(page, 'settings-basics');
  for (const [q, label] of [['tab=advanced&section=llm', 'settings-llm'], ['tab=advanced&section=whisper', 'settings-transcription'], ['tab=users', 'settings-users'], ['tab=costs', 'settings-costs']]) {
    await page.goto(`${BASE}/config?${q}`);
      await page.waitForTimeout(1800);
    await shot(page, label);
  }

  // Add a feed by RSS URL.
  await page.getByRole('link', { name: 'Home' }).first().click();
  await page.waitForTimeout(1500);
  await page.getByRole('button', { name: /^Add feed$/ }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: 'Enter RSS URL' }).click();
  await page.fill('#feed-url', FEED_URL);
  await page.mouse.move(5, 5);
  await page.waitForTimeout(600);
  await shot(page, 'add-feed-form');
  await page.locator('form button[type="submit"]').first().click();
  await page.locator('button').filter({ hasText: /episodes/ }).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(2000);
  await shot(page, 'feed-added');
  note('feed added');

  // Open the feed and enable the newest episode.
  await page.locator('button').filter({ hasText: /episodes/ }).first().click();
  await page.waitForTimeout(3500);
  await shot(page, 'feed-detail');
  const toggle = page.getByRole('switch').first();
  await toggle.waitFor({ timeout: 20000 });
  if ((await toggle.getAttribute('aria-checked')) !== 'true') {
    await toggle.click();
    await page.waitForFunction(() => document.querySelector('[role="switch"]')?.getAttribute('aria-checked') === 'true', null, { timeout: 20000 });
    note('enabled newest episode');
  } else {
    note('newest episode already enabled');
  }
  await page.waitForTimeout(1500);
  await shot(page, 'episode-enabled');

  // Process it and wait for the Stats button.
  const processBtn = page.getByRole('button', { name: /^Process$/ }).first();
  if (await processBtn.count()) {
    await processBtn.click();
    note('clicked Process');
  } else {
    note('no Process button (processing may have started automatically)');
  }
  await page.waitForTimeout(4000);
  await shot(page, 'processing');
  const started = Date.now();
  let midShot = false;
  const statsBtn = page.getByRole('button', { name: /^Stats$/ }).first();
  while (!(await statsBtn.count())) {
    if (Date.now() - started > 15 * 60 * 1000) throw new Error('processing did not finish within 15 minutes');
    if (!midShot && Date.now() - started > 45000) { await shot(page, 'processing-progress'); midShot = true; }
    await page.waitForTimeout(5000);
  }
  note(`processing finished after ${Math.round((Date.now() - started) / 1000)}s`);
  await page.waitForTimeout(1500);
  await shot(page, 'episode-processed');

  // Inspect the stats.
  await statsBtn.click();
  await page.waitForTimeout(3500);
  await shot(page, 'stats-overview');
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(1500);
  await shot(page, 'stats-overview-lower');
  for (const tab of ['Model calls', 'Transcript segments', 'Identifications']) {
    await page.getByRole('tab', { name: new RegExp(tab) }).click();
    await page.waitForTimeout(1200);
    await shot(page, `stats-${tab.split(' ')[0].toLowerCase()}`);
  }
  const detailsBtn = page.getByRole('button', { name: 'Details' }).first();
  await page.getByRole('tab', { name: /Model calls/ }).click();
  await page.waitForTimeout(800);
  if (await detailsBtn.count()) { await detailsBtn.click(); await page.waitForTimeout(800); await shot(page, 'stats-model-call-details'); }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(800);

  // Jobs page after the run.
  await page.getByRole('link', { name: 'Jobs' }).first().click();
  await page.waitForTimeout(2000);
  await page.getByRole('button', { name: 'Load all jobs' }).click().catch(() => {});
  await page.waitForTimeout(2000);
  await shot(page, 'jobs');
} catch (err) {
  note(`FAILED: ${err.message}`);
  await shot(page, 'failure').catch(() => {});
}

const cookies = await desktop.cookies();
await desktop.close();

// Phone layout with the same session.
const phone = await browser.newContext({ ...devices['iPhone 13'], colorScheme: 'light' });
await phone.addInitScript(MASK_SETTINGS);
await phone.addCookies(cookies);
const p2 = await phone.newPage();
watch(p2, 'phone');
await p2.goto(`${BASE}/`);
await p2.waitForTimeout(2500);
await shot(p2, 'phone-home');
const card = p2.locator('button').filter({ hasText: /episodes/ }).first();
if (await card.count()) {
  await card.click();
  await p2.waitForTimeout(2500);
  await shot(p2, 'phone-feed');
  const close = p2.getByRole('button', { name: /close|back/i }).first();
  if (await close.count()) { await close.click(); await p2.waitForTimeout(1500); await shot(p2, 'phone-closed'); }
}
await phone.close();
await browser.close();
fs.writeFileSync(`${OUT}/walkthrough.log`, log.join('\n') + '\n');
