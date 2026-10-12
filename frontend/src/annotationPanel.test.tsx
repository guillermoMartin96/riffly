import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Annotation, Session } from './api';

const pending: { resolve?: (a: Annotation) => void } = {};
const saveAnnotation = vi.fn();
const finalizeAnnotation = vi.fn();

vi.mock('./api', async (orig) => {
  const real = await orig<typeof import('./api')>();
  return {
    ...real,
    api: {
      ...real.api,
      getAnnotation: () => Promise.reject(new real.ApiError(404, 'no_annotation', 'none')),
      saveAnnotation: (...args: unknown[]) => saveAnnotation(...args),
      finalizeAnnotation: (...args: unknown[]) => finalizeAnnotation(...args),
    },
  };
});

const { AnnotationPanel } = await import('./AnnotationPanel');

const session = {
  id: 's1', audio_mime: 'audio/webm', audio_bytes: 1, audio_sha256: 'h', duration_seconds: 5,
  sample_rate: 22050, created_at: '', status: 'ready', capture_info: null,
  provenance: { version: 1, tracked_since: 't', model_exposed_at: null, contaminated_at: null,
                contamination_reason: null, holdout_eligible: true,
                ineligible_reason: null },
} as unknown as Session;

const annotation = (split: 'dev' | 'holdout'): Annotation => ({
  id: 'a', session_id: 's1', status: 'draft', seed: 'blank', split_locked: false, revision: 1,
  created_at: '', updated_at: '', finalized_at: null, notes: [], split, condition: null,
  method: 'manual', annotator: null, instrument: null, notes_text: null,
});

beforeEach(() => {
  saveAnnotation.mockReset();
  finalizeAnnotation.mockReset();
});

describe('AnnotationPanel save race', () => {
  it('keeps edits made while a save is in flight and saves them before finalizing', async () => {
    saveAnnotation.mockImplementationOnce(
      () => new Promise<Annotation>((resolve) => (pending.resolve = resolve)),
    );
    render(
      <AnnotationPanel session={session} transcription={null} playhead={0}
        onAudition={() => {}} onNotesChange={() => {}} onProvenanceChange={() => {}} />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Start blank' }));
    const split = screen.getAllByRole('combobox')[0];
    await userEvent.selectOptions(split, 'dev');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await userEvent.selectOptions(split, 'holdout'); // edit while the save is pending
    pending.resolve!(annotation('dev'));
    expect(await screen.findByText(/newer edits are not saved yet/)).toBeInTheDocument();
    expect(screen.getByText(/unsaved changes/)).toBeInTheDocument();

    saveAnnotation.mockResolvedValueOnce(annotation('holdout'));
    finalizeAnnotation.mockResolvedValueOnce({ ...annotation('holdout'), status: 'final' });
    await userEvent.click(screen.getByRole('button', { name: 'Finalize' }));
    expect(saveAnnotation).toHaveBeenCalledTimes(2);
    expect(saveAnnotation.mock.calls[1][1].split).toBe('holdout');
    expect(finalizeAnnotation).toHaveBeenCalledTimes(1);
  });
});
