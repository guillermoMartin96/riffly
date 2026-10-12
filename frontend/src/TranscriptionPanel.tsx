import type { AppConfig, Transcription } from './api';

interface Props {
  config: AppConfig | null;
  transcription: Transcription | null;
  busy: boolean;
  error: string | null;
  disabled: boolean;
  onTranscribe: () => void;
}

export function TranscriptionPanel({
  config,
  transcription: t,
  busy,
  error,
  disabled,
  onTranscribe,
}: Props) {
  const engine = config?.transcription ?? null;
  return (
    <section className="panel transcription" aria-label="Transcription">
      <div className="row">
        <h3>Notes &amp; tab</h3>
        {engine && (
          <button onClick={onTranscribe} disabled={busy || disabled}>
            {busy ? 'Transcribing…' : t ? 'Transcribe again' : 'Transcribe'}
          </button>
        )}
      </div>
      {!engine && (
        <p className="notice" data-testid="no-engine">
          No transcription engine is configured, so no notes or tab are shown. Recording, playback
          and riffs work without one.
        </p>
      )}
      {engine && !engine.test_only && !engine.validated && (
        <p className="notice" data-testid="provisional-engine">
          Provisional engine: accuracy on real guitar recordings made with JamRecall has not been
          validated yet. Expect missed or wrong notes.
        </p>
      )}
      {t?.test_only && (
        <p className="fixture-banner" role="status" data-testid="fixture-banner">
          TEST FIXTURE — these notes come from the test-only adapter “{t.engine}” and are NOT
          derived from this recording.
        </p>
      )}
      {t && (
        <p className="provenance" data-testid="provenance">
          Engine <code>{t.engine}</code> <code title={t.engine_version}>{t.engine_version.split('/')[0]}</code> · status{' '}
          <strong data-testid="transcription-status">{t.status}</strong>
          {t.status === 'succeeded' && (
            <>
              {' '}
              · {t.notes.length} notes · processed in {t.processing_seconds?.toFixed(2)} s
              {t.inference_seconds != null && (
                <> (decode {t.decode_seconds?.toFixed(2)} s, inference {t.inference_seconds.toFixed(2)} s)</>
              )}
            </>
          )}
        </p>
      )}
      {t?.status === 'failed' && (
        <p role="alert" className="error" data-testid="transcription-error">
          Transcription failed: {t.error}
        </p>
      )}
      {t?.status === 'succeeded' && t.notes.length === 0 && (
        <p className="notice">No notes were detected in this recording.</p>
      )}
      {t?.status === 'succeeded' && t.notes.length > 0 && (
        <p className="hint">
          Pitches (♪ row) are what the engine detected. String/fret numbers are an{' '}
          <strong>inferred</strong> fingering ({t.fingering_method}); underlined frets have other
          playable positions. Output may contain errors; bends, slides, harmonics and chords are
          not modelled.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}
