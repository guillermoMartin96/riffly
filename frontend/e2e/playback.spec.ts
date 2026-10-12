import { expect, test, type Page } from '@playwright/test';
import { audioState, installMic, recordPhrase } from './helpers';

// Riff playback boundaries (Codex interim review findings 5 and 6).

async function saveRiff(page: Page, start: string, end: string, title: string) {
  await page.locator('input[name=start]').fill(start);
  await page.locator('input[name=end]').fill(end);
  await page.locator('input[name=title]').fill(title);
  await page.getByRole('button', { name: 'Save riff' }).click();
  await expect(page.getByTestId('riff-item').filter({ hasText: title })).toBeVisible();
}

test('a looping riff that ends at the recording end keeps looping', async ({ page, request }) => {
  await installMic(page);
  await page.goto('/');
  const sessionId = await recordPhrase(page, 3);
  const session = await (await request.get(`/api/sessions/${sessionId}`)).json();
  // Server-measured end: may be up to one Opus frame past the browser's duration.
  const end = session.duration_seconds;
  const start = Math.max(0, end - 1.0);
  await saveRiff(page, start.toFixed(3), end.toFixed(3), 'Tail');
  await page.getByTestId('riff-item').filter({ hasText: 'Tail' }).getByRole('button', { name: 'Loop' }).click();
  const samples: number[] = [];
  for (let i = 0; i < 16; i++) {
    await page.waitForTimeout(200);
    const s = await audioState(page);
    expect(s.paused).toBe(false); // still looping after ~3 loop lengths
    samples.push(s.currentTime);
  }
  expect(Math.min(...samples)).toBeGreaterThanOrEqual(start - 0.01);
  expect(samples.some((t, i) => i > 0 && t < samples[i - 1])).toBe(true);
  await page.getByRole('button', { name: /Stop loop/ }).click();
});

test('range end is enforced even when animation frames are suspended (background tab)', async ({
  page,
}) => {
  // Simulate a hidden tab: requestAnimationFrame callbacks never run.
  await page.addInitScript(() => {
    window.requestAnimationFrame = () => 0;
  });
  await installMic(page);
  await page.goto('/');
  await recordPhrase(page, 4);
  await saveRiff(page, '0.5', '1.75', 'Hidden');
  await page.getByTestId('riff-item').getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(true);
  const s = await audioState(page);
  expect(s.currentTime).toBeGreaterThanOrEqual(1.7);
  expect(s.currentTime).toBeLessThan(2.05); // timer/timeupdate fallback, not the rest of the take
});
