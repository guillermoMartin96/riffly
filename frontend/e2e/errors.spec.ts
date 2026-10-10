import { expect, test } from '@playwright/test';
import { readdirSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { E2E_DATA_ROOT } from '../playwright.config';
import { installMic, recordPhrase } from './helpers';

// This project's backend is configured with the TEST-ONLY "failing" engine.

test('microphone permission denied shows guidance', async ({ page }) => {
  // No fake-ui flag in this project and no permission granted: Chromium denies the request.
  await page.goto('/');
  await page.getByRole('button', { name: /● Record/ }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toHaveAttribute('data-error-code', 'permission_denied');
  await expect(page.getByRole('button', { name: /● Record/ })).toBeEnabled();
  await page.screenshot({ path: 'test-results/evidence/10-permission-denied.png' });
});

test('missing input device shows guidance', async ({ page }) => {
  // Simulated: Chromium has no flag to remove all capture devices, so getUserMedia is stubbed
  // to reject the way browsers do when no microphone exists.
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () =>
      Promise.reject(new DOMException('Requested device not found', 'NotFoundError'));
  });
  await page.goto('/');
  await page.getByRole('button', { name: /● Record/ }).click();
  await expect(page.getByRole('alert')).toHaveAttribute('data-error-code', 'no_device');
  await page.screenshot({ path: 'test-results/evidence/11-no-device.png' });
});

test('processing failure is shown and persisted; missing audio is reported', async ({
  page,
  context,
  request,
}) => {
  await context.grantPermissions(['microphone']);
  await installMic(page);
  await page.goto('/');
  const sessionId = await recordPhrase(page, 2);

  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('failed', { timeout: 30_000 });
  await expect(page.getByTestId('transcription-error')).toContainText('always fails');
  await expect(page.getByTestId('tab-note')).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('transcription-error')).toContainText('always fails');
  await page.screenshot({ path: 'test-results/evidence/12-processing-failed.png', fullPage: true });

  // Save a riff, then remove the source file behind the server's back.
  await page.locator('input[name=start]').fill('0.2');
  await page.locator('input[name=end]').fill('1.0');
  await page.locator('input[name=title]').fill('Survivor');
  await page.getByRole('button', { name: 'Save riff' }).click();
  await expect(page.getByTestId('riff-item')).toHaveCount(1);
  const dir = join(E2E_DATA_ROOT, 'errors', 'media', 'sessions', sessionId);
  for (const f of readdirSync(dir)) unlinkSync(join(dir, f));

  await page.reload();
  await expect(page.getByTestId('audio-missing')).toBeVisible();
  await expect(page.getByTestId('riff-range')).toHaveText('0:00.20 – 0:01.00');
  expect((await request.get(`/api/sessions/${sessionId}/audio`)).status()).toBe(404);
  await page.screenshot({ path: 'test-results/evidence/13-audio-missing.png', fullPage: true });
});
