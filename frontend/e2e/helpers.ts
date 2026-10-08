import { expect, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fakeMicPath } from './fake-mic';

/**
 * How test audio reaches getUserMedia:
 * - 'device': Chromium's fake capture device plays the WAV (launch flags in playwright.config).
 * - 'webaudio': getUserMedia is replaced by a MediaStream built from the same WAV with Web Audio.
 *   Used on macOS, where Chromium's audio capture blocks on the OS microphone permission of the
 *   host terminal app. MediaRecorder encoding, upload, decoding and playback are real in both modes.
 */
export const MIC_MODE =
  process.env.JAMRECALL_E2E_MIC ?? (process.platform === 'darwin' ? 'webaudio' : 'device');

export async function installMic(page: Page) {
  if (MIC_MODE !== 'webaudio') return;
  const wav = readFileSync(fakeMicPath());
  await page.route('**/__e2e__/mic.wav', (r) =>
    r.fulfill({ body: wav, contentType: 'audio/wav' }),
  );
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      const ctx = new AudioContext({ sampleRate: 48000 });
      const data = await (await fetch('/__e2e__/mic.wav')).arrayBuffer();
      const src = ctx.createBufferSource();
      src.buffer = await ctx.decodeAudioData(data);
      src.loop = true;
      const dest = ctx.createMediaStreamDestination();
      src.connect(dest);
      await ctx.resume();
      src.start();
      return dest.stream;
    };
  });
}

export async function recordPhrase(page: Page, seconds: number) {
  await page.getByRole('button', { name: /● Record/ }).click();
  await expect(page.getByRole('button', { name: /Stop/ })).toBeVisible();
  await page.waitForTimeout(seconds * 1000);
  await page.getByRole('button', { name: /Stop/ }).click();
  await expect(page.getByTestId('session-view')).toBeVisible({ timeout: 15_000 });
  return (await page.getByTestId('session-view').getAttribute('data-session-id'))!;
}

export async function audioState(page: Page) {
  return page.getByTestId('audio').evaluate((a: HTMLAudioElement) => ({
    paused: a.paused,
    currentTime: a.currentTime,
  }));
}

export const sha256 = (b: Buffer) => createHash('sha256').update(b).digest('hex');
