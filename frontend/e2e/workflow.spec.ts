import { expect, test } from '@playwright/test';
import { audioState, installMic, MIC_MODE, recordPhrase, sha256 } from './helpers';

// Uses Chromium's fake capture device fed from a WAV file, through the real getUserMedia +
// MediaRecorder + upload path. The transcription engine in this project is the TEST-ONLY fixture
// (unless JAMRECALL_E2E_ENGINE selects an approved real engine).

test('record → save → transcribe → select → save riff → reload → replay/loop → delete', async ({
  page,
  request,
}) => {
  const fixtureEngine = (process.env.JAMRECALL_E2E_ENGINE ?? 'fixture') === 'fixture';
  test.info().annotations.push({ type: 'mic-mode', description: MIC_MODE });
  await installMic(page);
  await page.goto('/');
  await expect(page.getByTestId('engine-chip')).toContainText(
    fixtureEngine ? 'TEST-ONLY engine: test-fixture' : 'Engine:',
  );

  // 1. Record ~4 s and verify the stored original.
  const sessionId = await recordPhrase(page, 4);
  const session = await (await request.get(`/api/sessions/${sessionId}`)).json();
  expect(session.audio_mime).toBe('audio/webm');
  expect(session.duration_seconds).toBeGreaterThan(3.0);
  expect(session.duration_seconds).toBeLessThan(6.0);
  const audio = await request.get(`/api/sessions/${sessionId}/audio`);
  expect(audio.status()).toBe(200);
  expect(sha256(await audio.body())).toBe(session.audio_sha256);
  await page.screenshot({ path: 'test-results/evidence/01-recorded.png', fullPage: true });

  // 2. Transcribe.
  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 30_000 });
  if (fixtureEngine) {
    await expect(page.getByTestId('fixture-banner')).toContainText('NOT derived from this recording');
  } else {
    await expect(page.getByTestId('fixture-banner')).toHaveCount(0);
  }
  await expect(page.getByTestId('tab-note').first()).toBeVisible();
  await page.screenshot({ path: 'test-results/evidence/02-transcribed.png', fullPage: true });

  // 3. Invalid selections are rejected in the UI.
  const start = page.locator('input[name=start]');
  const end = page.locator('input[name=end]');
  const title = page.locator('input[name=title]');
  await start.fill('2');
  await end.fill('1');
  await title.fill('Backwards');
  await page.getByRole('button', { name: 'Save riff' }).click();
  await expect(page.getByTestId('riff-form-error')).toContainText('End must be after start');
  await start.fill('1');
  await end.fill('99');
  await page.getByRole('button', { name: 'Save riff' }).click();
  await expect(page.getByTestId('riff-form-error')).toContainText('at or before');
  await expect(page.getByTestId('riff-item')).toHaveCount(0);

  // 4. Drag-select on the timeline produces a selection, then type exact bounds and save.
  const box = (await page.getByTestId('timeline').boundingBox())!;
  await page.mouse.move(box.x + 22 + 60, box.y + 60);
  await page.mouse.down();
  await page.mouse.move(box.x + 22 + 180, box.y + 60, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId('selection')).toBeVisible();
  expect(Number(await start.inputValue())).toBeCloseTo(0.5, 1);
  expect(Number(await end.inputValue())).toBeCloseTo(1.5, 1);
  await start.fill('0.5');
  await end.fill('1.75');
  await title.fill('E2E lick');
  await page.getByRole('button', { name: 'Save riff' }).click();
  await expect(page.getByTestId('riff-item')).toHaveCount(1);
  await expect(page.getByTestId('riff-range')).toHaveText('0:00.50 – 0:01.75');

  // 5. Reload: same session view, same riff, identical persisted timestamps.
  await page.reload();
  await expect(page.getByTestId('session-view')).toHaveAttribute('data-session-id', sessionId);
  await expect(page.getByTestId('riff-range')).toHaveText('0:00.50 – 0:01.75');
  const riffs = await (await request.get(`/api/sessions/${sessionId}/riffs`)).json();
  expect(riffs).toHaveLength(1);
  expect([riffs[0].start_seconds, riffs[0].end_seconds]).toEqual([0.5, 1.75]);
  expect(riffs[0].session_id).toBe(sessionId);
  await page.screenshot({ path: 'test-results/evidence/03-reloaded-riff.png', fullPage: true });

  // 6. Play once: playback starts at the riff start and stops at its end.
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(true);
  const afterPlay = await audioState(page);
  expect(afterPlay.currentTime).toBeGreaterThanOrEqual(1.7);
  expect(afterPlay.currentTime).toBeLessThan(1.85);

  // 7. Loop: after > 2 loop lengths it is still playing and stays inside [start, end].
  await page.getByRole('button', { name: 'Loop' }).click();
  const samples: number[] = [];
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(200);
    const s = await audioState(page);
    expect(s.paused).toBe(false);
    samples.push(s.currentTime);
  }
  expect(Math.min(...samples)).toBeGreaterThanOrEqual(0.5 - 0.01);
  expect(Math.max(...samples)).toBeLessThanOrEqual(1.75 + 0.1);
  // It wrapped at least once (time went backwards).
  expect(samples.some((t, i) => i > 0 && t < samples[i - 1])).toBe(true);
  await page.getByRole('button', { name: /Stop loop/ }).click();
  await expect.poll(async () => (await audioState(page)).paused).toBe(true);

  // 8. Delete the riff: the riff goes, the source recording stays playable.
  await page.getByRole('button', { name: 'Delete riff E2E lick' }).click();
  await page.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByTestId('riff-item')).toHaveCount(0);
  const after = await request.get(`/api/sessions/${sessionId}/audio`);
  expect(after.status()).toBe(200);
  expect(sha256(await after.body())).toBe(session.audio_sha256);
});
