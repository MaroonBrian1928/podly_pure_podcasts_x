// Enables the second episode of the first feed by hand, confirms processing, waits
// for it to finish and opens its stats. Run after walkthrough.mjs, which adds the
// feed. Screenshots, a video and a log land in <out-dir>.
import { chromium } from 'playwright';
import { createRun, enableEpisode, parseArgs, signIn, waitForStatsButtons } from './lib.mjs';

const args = parseArgs('enable-and-process.mjs');
const { base, outDir } = args;
const run = createRun(outDir, 'manual-');

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  colorScheme: 'light',
  recordVideo: { dir: `${outDir}/video-manual`, size: { width: 1280, height: 800 } },
});
const page = await ctx.newPage();
run.watch(page, 'desktop', base);
try {
  await signIn(page, args);
  await page.locator('button').filter({ hasText: /episodes/ }).first().click();
  await page.waitForTimeout(3500);

  // Turn on profanity bleeping for the feed, so this episode is transcribed with
  // word timestamps and the mock transcript's swear word is bleeped.
  await page.getByRole('button', { name: 'Feed settings' }).first().click();
  const confirmWhisperx = page.getByRole('checkbox', { name: /WhisperX-compatible/ });
  await confirmWhisperx.waitFor({ timeout: 10000 });
  await confirmWhisperx.check();
  await page.locator('label:has-text("WhisperX-compatible") + div select').selectOption('on');
  await page.waitForTimeout(600);
  await run.shot(page, 'bleeping-on');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await confirmWhisperx.waitFor({ state: 'detached', timeout: 15000 });
  run.note('turned on profanity bleeping for the feed');
  await page.waitForTimeout(1500);

  // Some feeds start with every episode enabled; switch it off first so the run
  // always goes through the confirm-and-process path.
  const toggle = page.getByRole('switch').nth(1);
  await toggle.waitFor({ timeout: 20000 });
  await toggle.scrollIntoViewIfNeeded();
  if ((await toggle.getAttribute('aria-checked')) === 'true') {
    await toggle.click();
    await page.waitForFunction(
      () => document.querySelectorAll('[role="switch"]')[1]?.getAttribute('aria-checked') === 'false',
      null,
      { timeout: 20000 }
    );
    run.note('disabled the second episode before re-enabling it');
  }
  await run.shot(page, 'episode-disabled');
  const dialog = await enableEpisode(page, 1);
  await run.shot(page, 'enable-confirm');
  await dialog.confirm();
  await dialog.enabled();
  run.note('enabled and queued the second episode');
  await page.waitForTimeout(2500);
  await run.shot(page, 'processing');

  const { buttons, seconds } = await waitForStatsButtons(page, 2);
  run.note(`second episode finished after ${seconds}s`);
  await run.shot(page, 'processed');
  await buttons.nth(1).click();
  await page.getByRole('tab', { name: /Model calls/ }).waitFor({ timeout: 20000 });
  await page.waitForTimeout(2500);
  await run.shot(page, 'stats');

  // The mock transcript has one swear word, bleeped because of the feed setting.
  const bleepsHeading = page.getByRole('heading', { name: 'Bleeps added' });
  await bleepsHeading.waitFor({ timeout: 10000 });
  const bleepsCardEl = bleepsHeading.locator('xpath=..');
  await bleepsCardEl.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(1200);
  const bleepsCard = await bleepsCardEl.innerText();
  const bleeped = Number(bleepsCard.match(/(\d+)\s*Bleeped sections/)?.[1]);
  await run.shot(page, 'stats-bleeps');
  if (bleeped !== 1) throw new Error(`expected 1 bleeped section, the stats show ${bleeped}`);
  run.note('stats show 1 bleeped section');

  // The mock INA service returns 9 segments: speech with a music sting at each
  // end of both ad breaks.
  await page.getByRole('tab', { name: /Audio segments/ }).click();
  const audioRows = page.locator('h3:has-text("Audio segments") + div tbody tr');
  await audioRows.first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(1000);
  await run.shot(page, 'stats-audio-segments');
  const total = await audioRows.count();
  const music = await audioRows.filter({ hasText: 'music' }).count();
  if (total !== 9 || music !== 4) {
    throw new Error(`expected 9 INA audio segments with 4 music, the stats show ${total} with ${music} music`);
  }
  run.note('stats show 9 INA audio segments, 4 music');
} catch (err) {
  run.fail(err.message);
  await run.shot(page, 'failure').catch(() => {});
}
await ctx.close();
await browser.close();
run.finish('enable-and-process.log');
