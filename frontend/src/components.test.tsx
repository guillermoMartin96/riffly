import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Transcription } from './api';
import { Recorder } from './Recorder';
import { RiffList } from './RiffList';
import { TranscriptionPanel } from './TranscriptionPanel';

function installMedia(getUserMedia: () => Promise<MediaStream>) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(getUserMedia) },
  });
  vi.stubGlobal('MediaRecorder', Object.assign(function () {}, { isTypeSupported: () => true }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Recorder', () => {
  it('explains microphone permission denial', async () => {
    installMedia(() => Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' })));
    render(<Recorder onSaved={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /record/i }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveAttribute('data-error-code', 'permission_denied');
    expect(alert).toHaveTextContent(/denied/i);
    expect(screen.getByRole('button', { name: /record/i })).toBeEnabled();
  });

  it('explains a missing input device', async () => {
    installMedia(() => Promise.reject(Object.assign(new Error('none'), { name: 'NotFoundError' })));
    render(<Recorder onSaved={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /record/i }));
    expect(await screen.findByRole('alert')).toHaveAttribute('data-error-code', 'no_device');
  });

  it('reports unsupported browsers without calling getUserMedia', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined });
    render(<Recorder onSaved={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /record/i }));
    expect(await screen.findByRole('alert')).toHaveAttribute('data-error-code', 'unsupported');
  });
});

const base: Transcription = {
  id: 't', session_id: 's', engine: 'test-fixture', engine_version: '1', test_only: true,
  status: 'succeeded', error: null, created_at: '', completed_at: '', processing_seconds: 0.01,
  fingering_method: 'dp-hand-window-v1',
  decode_seconds: null, inference_seconds: null,
  notes: [{ start_seconds: 0.25, end_seconds: 0.65, duration_seconds: 0.4, midi_pitch: 57, confidence: null,
            fingering: { string: 3, fret: 2, inferred: true, alternatives: 2 } }],
};

describe('TranscriptionPanel', () => {
  const props = { busy: false, error: null, disabled: false, onTranscribe: () => {} };
  it('labels fixture output as not derived from audio', () => {
    render(
      <TranscriptionPanel
        {...props}
        config={{ transcription: { engine: 'test-fixture', version: '1', test_only: true, validated: false, model_load_seconds: 0 },
                  accepted_mime_types: [], max_upload_bytes: 1, max_duration_seconds: 1 }}
        transcription={base}
      />,
    );
    expect(screen.getByTestId('fixture-banner')).toHaveTextContent(/NOT derived from this recording/);
  });
  it('says when no engine is configured and offers no transcribe button', () => {
    render(
      <TranscriptionPanel
        {...props}
        config={{ transcription: null, accepted_mime_types: [], max_upload_bytes: 1, max_duration_seconds: 1 }}
        transcription={null}
      />,
    );
    expect(screen.getByTestId('no-engine')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /transcribe/i })).toBeNull();
  });
  it('shows engine failure reason', () => {
    render(
      <TranscriptionPanel
        {...props}
        config={null}
        transcription={{ ...base, test_only: false, status: 'failed', error: 'boom', notes: [] }}
      />,
    );
    expect(screen.getByTestId('transcription-error')).toHaveTextContent('boom');
    expect(screen.queryByTestId('fixture-banner')).toBeNull();
  });
});

describe('provisional engine', () => {
  it('warns that a real but unvalidated engine is provisional', () => {
    render(
      <TranscriptionPanel
        busy={false} error={null} disabled={false} onTranscribe={() => {}}
        config={{ transcription: { engine: 'basic-pitch', version: '0.4.0+x', test_only: false, validated: false, model_load_seconds: 2 },
                  accepted_mime_types: [], max_upload_bytes: 1, max_duration_seconds: 1 }}
        transcription={{ ...base, engine: 'basic-pitch', test_only: false, inference_seconds: 0.1, decode_seconds: 0.01 }}
      />,
    );
    expect(screen.getByTestId('provisional-engine')).toBeInTheDocument();
    expect(screen.queryByTestId('fixture-banner')).toBeNull();
    expect(screen.getByTestId('provenance')).toHaveTextContent('inference 0.10 s');
  });
});

describe('RiffList', () => {
  it('requires confirmation before deleting', async () => {
    const onDelete = vi.fn();
    const riff = { id: 'r', session_id: 's', title: 'Lick', start_seconds: 1, end_seconds: 2, created_at: '' };
    render(<RiffList riffs={[riff]} activeRiffId={null} looping={false} onPlay={() => {}} onStop={() => {}} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole('button', { name: 'Delete riff Lick' }));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(onDelete).toHaveBeenCalledWith(riff);
  });
});
