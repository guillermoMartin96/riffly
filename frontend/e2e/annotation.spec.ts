import { expect, test } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { E2E_DATA_ROOT } from '../playwright.config';
import { installMic, MIC_MODE, recordPhrase, sha256 } from './helpers';

// Manual-testing workflow (tech lead, 2026-10-09): record → transcribe → correct notes into a
// reference annotation kept separate from model output → finalize → export → delete.
// Mic input is the SYNTHETIC phrase from fake-mic.ts; engine is real Basic Pitch.

test('correct model output into a reference annotation, export it, then delete the recording', async ({
  page,
  request,
}) => {
  await installMic(page);
  await page.goto('/');
  const sessionId = await recordPhrase(page, 5);
  const session = await (await request.get(`/api/sessions/${sessionId}`)).json();
  expect(session.capture_info.mime_type).toContain('audio/webm');
  expect(session.capture_info.requested_constraints.echoCancellation).toBe(false);
  // Only a real capture track reports applied settings (the webaudio injection has none).
  if (MIC_MODE === 'device') expect(session.capture_info.track_settings.echoCancellation).toBe(false);

  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 60_000 });
  const model = await (await request.get(`/api/sessions/${sessionId}/transcriptions/latest`)).json();
  expect(model.notes.length).toBeGreaterThanOrEqual(3);

  // Start from model output: one editable row per detected note.
  const panel = page.getByTestId('annotation-panel');
  await panel.getByRole('button', { name: 'Start from model output' }).click();
  const rows = panel.getByTestId('annotation-row');
  await expect(rows).toHaveCount(model.notes.length);

  // Delete a "false positive" (row 1), fix a pitch (row 1 after delete), nudge its start.
  await panel.getByRole('button', { name: 'Delete note 1' }).click();
  await expect(rows).toHaveCount(model.notes.length - 1);
  const pitch = rows.first().getByLabel('pitch', { exact: true });
  await pitch.fill('F#4');
  await pitch.press('Enter');
  await expect(pitch).toHaveValue('F#4');
  const startCell = rows.first().getByLabel('start', { exact: true });
  const before = Number(await startCell.inputValue());
  await rows.first().getByRole('button', { name: 'start +10 ms' }).click();
  await expect(startCell).toHaveValue((before + 0.01).toFixed(3));

  // Add a "missed" note at the playhead: seek by clicking the timeline near the end.
  await page.getByTestId('timeline').scrollIntoViewIfNeeded();
  const box = (await page.getByTestId('timeline').boundingBox())!;
  await page.mouse.click(box.x + 22 + 4.6 * 120, box.y + 40);
  await expect(page.getByTestId('clock')).toContainText('0:04.60');
  await panel.getByRole('button', { name: /Add note at playhead \(4\.600 s\)/ }).click();
  await expect(rows).toHaveCount(model.notes.length);

  // Listen to a note (plays only that range).
  await rows.first().getByRole('button', { name: 'Listen to note 1' }).click();

  // Metadata and save.
  await panel.locator('select').nth(0).selectOption('dev');
  await panel.locator('select').nth(1).selectOption('A');
  await panel.locator('input[name=annotator]').fill('e2e');
  await panel.getByRole('button', { name: 'Save draft' }).click();
  await expect(panel.getByTestId('annotation-message')).toContainText('Saved draft');

  // Reload: annotation persisted; model output unchanged; reference lane drawn.
  await page.reload();
  await expect(page.getByTestId('annotation-row')).toHaveCount(model.notes.length);
  await expect(page.getByTestId('ref-note').first()).toBeVisible();
  const ann = await (await request.get(`/api/sessions/${sessionId}/annotation`)).json();
  expect(ann.seed).toMatch(/^transcription:.*:basic-pitch@0\.4\.0/);
  expect(ann.notes[0].midi_pitch).toBe(66);
  expect(ann.notes[0].start_seconds).toBeCloseTo(model.notes[1].start_seconds + 0.01, 3);
  const added = ann.notes[ann.notes.length - 1];
  expect(added.start_seconds).toBeCloseTo(4.6, 3);
  const modelAfter = await (await request.get(`/api/sessions/${sessionId}/transcriptions/latest`)).json();
  expect(modelAfter.notes).toEqual(model.notes);
  await page.screenshot({ path: 'test-results/evidence/20-annotation.png', fullPage: true });

  // Overlapping notes are rejected before saving.
  const p2 = page.getByTestId('annotation-panel');
  const firstEnd = p2.getByTestId('annotation-row').first().getByLabel('end', { exact: true });
  await firstEnd.fill('4.9');
  await firstEnd.press('Enter');
  await expect(p2.getByTestId('annotation-problem')).toContainText('monophonic');
  await firstEnd.fill(String(ann.notes[0].end_seconds));
  await firstEnd.press('Enter');
  await expect(p2.getByTestId('annotation-problem')).toHaveCount(0);

  // Finalize locks the split; export downloads a zip with the original audio + reference.
  await p2.getByRole('button', { name: 'Finalize' }).click();
  await expect(p2.getByTestId('annotation-message')).toContainText('Finalized as dev');
  await expect(p2.locator('select').nth(0)).toBeDisabled();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    p2.getByTestId('export-link').click(),
  ]);
  expect(download.suggestedFilename()).toBe(`jamrecall-${sessionId.slice(0, 8)}.zip`);
  const zipPath = await download.path();
  const zip = readFileSync(zipPath!);
  expect(zip.subarray(0, 2).toString()).toBe('PK');
  for (const name of ['audio/original.webm', 'reference.json', 'transcriptions.json', 'metadata.json'])
    expect(zip.includes(Buffer.from(name))).toBe(true);
  const audio = await request.get(`/api/sessions/${sessionId}/audio`);
  expect(sha256(await audio.body())).toBe(session.audio_sha256);

  // Delete the recording from the UI: everything goes, including files on disk.
  await page.getByRole('button', { name: 'Delete recording…' }).click();
  await page.getByRole('button', { name: /Permanently delete/ }).click();
  await expect(page.getByTestId('session-view')).toHaveCount(0);
  expect((await request.get(`/api/sessions/${sessionId}`)).status()).toBe(404);
  expect(existsSync(join(E2E_DATA_ROOT, 'workflow', 'media', 'sessions', sessionId))).toBe(false);
});

test('a holdout reference seeded from model output is flagged', async ({ page }) => {
  await installMic(page);
  await page.goto('/');
  await recordPhrase(page, 2);
  await page.getByRole('button', { name: 'Transcribe' }).click();
  await expect(page.getByTestId('transcription-status')).toHaveText('succeeded', { timeout: 60_000 });
  const panel = page.getByTestId('annotation-panel');
  await panel.getByRole('button', { name: 'Start from model output' }).click();
  await panel.locator('select').nth(0).selectOption('holdout');
  await expect(panel.getByTestId('seed-warning')).toContainText('cannot count as an independent holdout');
});
