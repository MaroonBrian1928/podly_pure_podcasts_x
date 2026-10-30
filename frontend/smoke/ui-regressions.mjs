// Browser checks for the feed page that need no backend: the API is answered by
// route mocks. Usage: node smoke/ui-regressions.mjs <base-url>
//   npm run build && npx vite preview --port 4173   (then base-url http://127.0.0.1:4173)
import { chromium } from 'playwright';

const base = (process.argv[2] || '').replace(/\/$/, '');
if (!base) {
  console.error('Usage: node smoke/ui-regressions.mjs <base-url>');
  process.exit(2);
}

const feed = {
  id: 1,
  rss_url: 'http://mock.invalid/rss',
  title: 'Mock Feed',
  description: 'A feed with enough episodes to scroll.',
  author: 'Mock Author',
  image_url: null,
  posts_count: 30,
  is_member: true,
  is_active_subscription: true,
  ad_detection_strategy: 'llm',
};
const episodes = Array.from({ length: 30 }, (_, i) => ({
  id: i + 1,
  guid: `guid-${i + 1}`,
  title: `Episode ${i + 1}`,
  description: 'An episode description. '.repeat(20),
  release_date: '2026-10-01T00:00:00',
  duration: 1800,
  whitelisted: true,
  has_processed_audio: false,
  has_unprocessed_audio: false,
  download_url: 'http://mock.invalid/a.mp3',
  image_url: null,
  download_count: 0,
}));

const failures = [];
const check = (ok, msg) => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`);
  if (!ok) failures.push(msg);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(e.message));

// Playwright tries the most recently registered route first.
await page.route('**/api/**', (r) => r.fulfill({ json: {} }));
await page.route('**/api/auth/status', (r) =>
  r.fulfill({ json: { require_auth: false, landing_page_enabled: false } })
);
await page.route('**/feeds', (r) => r.fulfill({ json: [feed] }));
await page.route('**/api/feeds/1/posts*', (r) =>
  r.fulfill({
    json: { items: episodes, total: 30, page: 1, page_size: 30, total_pages: 1, whitelisted_total: 30 },
  })
);

try {
  await page.goto(`${base}/`);
  await page.getByText('Mock Feed').first().click();
  await page.getByText('Episode 5', { exact: true }).waitFor({ timeout: 15000 });
  // Let the page transition and feed reveal settle.
  await page.waitForTimeout(2500);

  // The mouse wheel over the episode list scrolls the feed pane (it did nothing in Chrome).
  const pane = page.locator('.overscroll-contain').first();
  const box = await pane.boundingBox();
  const metrics = await pane.evaluate((el) => ({ scrollHeight: el.scrollHeight, clientHeight: el.clientHeight }));
  check(
    box !== null && box.height <= 800 && metrics.scrollHeight > metrics.clientHeight,
    `feed pane is bounded and scrollable (client ${metrics.clientHeight}, content ${metrics.scrollHeight})`
  );
  await page.mouse.move(box.x + box.width / 2, 600);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(800);
  const scrolled = await pane.evaluate((el) => el.scrollTop);
  check(scrolled > 0, `wheel over the episode list scrolls the feed pane (scrollTop ${scrolled})`);

  // A ResizeObserver loop notice is not an error worth a Troubleshooting popup.
  await page.evaluate(() => {
    window.dispatchEvent(
      new ErrorEvent('error', { message: 'ResizeObserver loop completed with undelivered notifications.' })
    );
    window.dispatchEvent(new ErrorEvent('error', { message: 'ResizeObserver loop limit exceeded' }));
  });
  await page.waitForTimeout(500);
  check(
    (await page.getByRole('heading', { name: 'Troubleshooting' }).count()) === 0,
    'ResizeObserver loop notices do not open the Troubleshooting popup'
  );

  // A genuine error still does.
  await page.evaluate(() => {
    window.dispatchEvent(new ErrorEvent('error', { message: 'Something actually broke' }));
  });
  await page.getByRole('heading', { name: 'Troubleshooting' }).waitFor({ timeout: 5000 }).then(
    () => check(true, 'a genuine error still opens the Troubleshooting popup'),
    () => check(false, 'a genuine error still opens the Troubleshooting popup')
  );

  check(pageErrors.length === 0, `no uncaught page errors${pageErrors.length ? `: ${pageErrors.join('; ')}` : ''}`);
} catch (err) {
  failures.push(String(err));
  console.error(err);
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
