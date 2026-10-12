import { expect, test, type Page } from '@playwright/test';
import { installMic, recordPhrase, transcribeDisqualifying } from './helpers';

// Holdout contamination guard (DR-0004 guard, 2026-10-12), through the real UI and API.

const eligibility = (page: Page) => page.getByTestId('holdout-eligibility');

async function blankHoldoutReference(page: Page) {
  const panel = page.getByTestId('annotation-panel');
  await panel.getByRole('button', { name: 'Start blank' }).click();
  await panel.locator('select').nth(0).selectOption('holdout');
  await panel.locator('select').nth(1).selectOption('A');
  await panel.locator('input[name=annotator]').fill('e2e');
  await page.getByTestId('timeline').scrollIntoViewIfNeeded();
  const box = (await page.getByTestId('timeline').boundingBox())!;
  await page.mouse.click(box.x + 22 + 0.4 * 120, box.y + 40);
  await panel.getByRole('button', { name: /Add note at playhead/ }).click();
  await panel.getByRole('button', { name: 'Save draft' }).click();
  await expect(panel.getByTestId('annotation-message')).toContainText('Saved draft');
  return panel;
}

test('a holdout take annotated blank and finalized before transcription stays eligible', async ({
  page,
  request,
}) => {
  await installMic(page);
  await page.goto('/');
  const sid = await recordPhrase(page, 3);
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'true');

  const panel = await blankHoldoutReference(page);
  await panel.getByRole('button', { name: 'Finalize' }).click();
  await expect(panel.getByTestId('annotation-message')).toContainText('Finalized as holdout');

  // Transcription after finalization: no warning, still eligible.
  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 60_000 });
  await expect(page.getByTestId('disqualify-warning')).toHaveCount(0);
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'true');

  // Reopening now would disqualify it: warned, and Cancel keeps it eligible.
  await panel.getByRole('button', { name: 'Reopen for edits' }).click();
  await expect(panel.getByTestId('reopen-warning')).toBeVisible();
  await panel.getByRole('button', { name: 'Cancel' }).click();
  await page.reload();
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'true');
  const s = await (await request.get(`/api/sessions/${sid}`)).json();
  expect(s.provenance.holdout_eligible).toBe(true);
  expect(s.provenance.model_exposed_at).not.toBeNull();
  await page.screenshot({ path: 'test-results/evidence/30-holdout-eligible.png', fullPage: true });
});

test('transcribing before finalization warns, can be cancelled, and disqualifies permanently', async ({
  page,
  request,
}) => {
  await installMic(page);
  await page.goto('/');
  const sid = await recordPhrase(page, 3);
  await blankHoldoutReference(page); // draft holdout reference: not yet finalized

  // Warned; Cancel leaves no model output and keeps the recording eligible.
  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('disqualify-warning')).toContainText('permanently disqualify');
  await page.getByRole('button', { name: 'Cancel' }).click();
  expect(await (await request.get(`/api/sessions/${sid}/transcriptions`)).json()).toEqual([]);
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'true');

  // Continue intentionally: transcribed, permanently ineligible, explained in the UI.
  await transcribeDisqualifying(page);
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 60_000 });
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'false');
  await expect(eligibility(page)).toContainText('before the reference annotation was finalized');
  await expect(page.getByTestId('holdout-ineligible-warning')).toBeVisible();

  // Survives reload and a split change; finalizing does not restore eligibility.
  await page.reload();
  const panel = page.getByTestId('annotation-panel');
  await panel.locator('select').nth(0).selectOption('dev');
  await panel.getByRole('button', { name: 'Save draft' }).click();
  // No wait on purpose: editing while a save is in flight must not be lost (regression).
  await panel.locator('select').nth(0).selectOption('holdout');
  await panel.getByRole('button', { name: 'Finalize' }).click();
  await expect(panel.getByTestId('annotation-message')).toContainText('Finalized as holdout');
  await page.reload();
  await expect(eligibility(page)).toHaveAttribute('data-eligible', 'false');
  const s = await (await request.get(`/api/sessions/${sid}`)).json();
  expect(s.provenance.holdout_eligible).toBe(false);
  await page.screenshot({ path: 'test-results/evidence/31-holdout-disqualified.png', fullPage: true });
});
