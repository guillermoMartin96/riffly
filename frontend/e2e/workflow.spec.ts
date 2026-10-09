import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { PHRASE_MIDI } from './fake-mic';
import { audioState, installMic, MIC_MODE, sha256 } from './helpers';

// Full browser workflow through the real getUserMedia + MediaRecorder (Opus/WebM, 48 kHz) + upload
// path, transcribed by the configured engine (default: real Basic Pitch, DR-0001). The microphone
// input is a SYNTHETIC plucked-string phrase (fake-mic.ts), not a guitar recording.

const realEngine = (process.env.JAMRECALL_E2E_ENGINE ?? 'basic-pitch') !== 'fixture';

function lcs(a: number[], b: number[]): number {
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
  return dp[a.length][b.length];
}

test('record → save → transcribe → select → save riff → reload → replay/loop → delete', async ({
  page,
  request,
}) => {
  test.info().annotations.push({ type: 'mic-mode', description: MIC_MODE });
  await installMic(page);
  const latency: Record<string, number> = {};
  await page.goto('/');
  const config = await (await request.get('/api/config')).json();
  if (realEngine) {
    expect(config.transcription.engine).toBe('basic-pitch');
    expect(config.transcription.test_only).toBe(false);
    await expect(page.getByTestId('engine-chip')).toContainText('Engine: basic-pitch (provisional)');
    latency.model_load_s = config.transcription.model_load_seconds;
  }

  // 1. Record ~5 s (one pass of the looped phrase) and verify the stored original.
  await page.getByRole('button', { name: /● Record/ }).click();
  await expect(page.getByRole('button', { name: /Stop/ })).toBeVisible();
  await page.waitForTimeout(5000);
  let t0 = Date.now();
  await page.getByRole('button', { name: /Stop/ }).click();
  await expect(page.getByTestId('session-view')).toBeVisible({ timeout: 15_000 });
  latency.stop_to_session_view_s = (Date.now() - t0) / 1000;
  const sessionId = (await page.getByTestId('session-view').getAttribute('data-session-id'))!;
  const session = await (await request.get(`/api/sessions/${sessionId}`)).json();
  expect(session.audio_mime).toBe('audio/webm');
  expect(session.duration_seconds).toBeGreaterThan(4.0);
  expect(session.duration_seconds).toBeLessThan(7.0);
  const audio = await request.get(`/api/sessions/${sessionId}/audio`);
  expect(sha256(await audio.body())).toBe(session.audio_sha256);
  await page.screenshot({ path: 'test-results/evidence/01-recorded.png', fullPage: true });

  // 2. Transcribe with the real engine and check it heard the phrase that was played.
  t0 = Date.now();
  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 60_000 });
  latency.click_to_succeeded_s = (Date.now() - t0) / 1000;
  await expect(page.getByTestId('tab-note').first()).toBeVisible();
  latency.click_to_tab_rendered_s = (Date.now() - t0) / 1000;
  const t = await (await request.get(`/api/sessions/${sessionId}/transcriptions/latest`)).json();
  latency.server_decode_s = t.decode_seconds;
  latency.server_inference_s = t.inference_seconds;
  latency.server_processing_s = t.processing_seconds;
  latency.recording_duration_s = session.duration_seconds;
  if (realEngine) {
    await expect(page.getByTestId('fixture-banner')).toHaveCount(0);
    await expect(page.getByTestId('provisional-engine')).toBeVisible();
    const midi = t.notes.map((n: { midi_pitch: number }) => n.midi_pitch);
    test.info().annotations.push({ type: 'detected-midi', description: JSON.stringify(midi) });
    // The recording may cut the looped phrase at either end; require 6 of its 7 notes, in order.
    expect(lcs(midi, [...PHRASE_MIDI, ...PHRASE_MIDI])).toBeGreaterThanOrEqual(6);
    expect(midi.length).toBeLessThanOrEqual(PHRASE_MIDI.length + 3);
  } else {
    await expect(page.getByTestId('fixture-banner')).toContainText('NOT derived from this recording');
  }
  mkdirSync('test-results/evidence', { recursive: true });
  writeFileSync('test-results/evidence/latency.json', JSON.stringify({ mic_mode: MIC_MODE, ...latency }, null, 1));
  test.info().annotations.push({ type: 'latency', description: JSON.stringify(latency) });
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

  // 4. Drag-select on the timeline, then type exact bounds and save.
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

  // 5. Reload: same session, same riff, identical persisted timestamps; transcription persists.
  await page.reload();
  await expect(page.getByTestId('session-view')).toHaveAttribute('data-session-id', sessionId);
  await expect(page.getByTestId('riff-range')).toHaveText('0:00.50 – 0:01.75');
  await expect(page.getByTestId('tab-note').first()).toBeVisible();
  const riffs = await (await request.get(`/api/sessions/${sessionId}/riffs`)).json();
  expect([riffs[0].start_seconds, riffs[0].end_seconds]).toEqual([0.5, 1.75]);
  expect(riffs[0].session_id).toBe(sessionId);
  await page.screenshot({ path: 'test-results/evidence/03-reloaded-riff.png', fullPage: true });

  // 6. Play once: starts at the riff start and stops at its end.
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(true);
  const afterPlay = await audioState(page);
  expect(afterPlay.currentTime).toBeGreaterThanOrEqual(1.7);
  expect(afterPlay.currentTime).toBeLessThan(1.85);

  // 7. Loop: still playing after > 2 loop lengths, staying inside [start, end], wrapping at least once.
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
  expect(samples.some((v, i) => i > 0 && v < samples[i - 1])).toBe(true);
  await page.getByRole('button', { name: /Stop loop/ }).click();
  await expect.poll(async () => (await audioState(page)).paused).toBe(true);

  // 8. Delete the riff: the riff goes; the source recording and its transcription stay.
  await page.getByRole('button', { name: 'Delete riff E2E lick' }).click();
  await page.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByTestId('riff-item')).toHaveCount(0);
  const after = await request.get(`/api/sessions/${sessionId}/audio`);
  expect(sha256(await after.body())).toBe(session.audio_sha256);
  expect((await request.get(`/api/sessions/${sessionId}/transcriptions`)).status()).toBe(200);
});
