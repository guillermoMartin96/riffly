import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, type AppConfig, type Riff, type Session, type Transcription } from './api';
import { RiffList } from './RiffList';
import { Timeline, type Selection } from './Timeline';
import { TranscriptionPanel } from './TranscriptionPanel';
import { formatTime, roundMs, validateRange } from './timing';
import { usePlayer } from './usePlayer';

interface Props {
  sessionId: string;
  config: AppConfig | null;
  onRiffsChanged: () => void;
}

const message = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function SessionView({ sessionId, config, onRiffsChanged }: Props) {
  const [session, setSession] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [transcribeError, setTranscribeError] = useState<string | null>(null);
  const [riffs, setRiffs] = useState<Riff[]>([]);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [startText, setStartText] = useState('');
  const [endText, setEndText] = useState('');
  const [title, setTitle] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [activeRiff, setActiveRiff] = useState<{ id: string; loop: boolean } | null>(null);
  const [pxPerSecond, setPxPerSecond] = useState(120);

  const missing = session?.status === 'audio_missing';
  const player = usePlayer(session && !missing ? api.audioUrl(session.id) : null);

  const loadRiffs = useCallback(async () => {
    setRiffs(await api.sessionRiffs(sessionId));
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    setSession(null);
    setLoadError(null);
    setPeaks([]);
    setTranscription(null);
    setTranscribeError(null);
    setSelection(null);
    setStartText('');
    setEndText('');
    setActiveRiff(null);
    (async () => {
      try {
        const s = await api.getSession(sessionId);
        if (cancelled) return;
        setSession(s);
        loadRiffs().catch((e) => setLoadError(message(e)));
        if (s.status === 'ready') {
          api
            .peaks(sessionId, Math.min(4000, Math.ceil(s.duration_seconds * 40)))
            .then((p) => !cancelled && setPeaks(p.peaks))
            .catch(() => undefined);
        }
        api
          .latestTranscription(sessionId)
          .then((t) => !cancelled && setTranscription(t))
          .catch(() => undefined);
      } catch (err) {
        if (!cancelled) setLoadError(message(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, loadRiffs]);

  // Poll while a transcription is in progress.
  const inProgress = transcription?.status === 'pending' || transcription?.status === 'running';
  useEffect(() => {
    if (!inProgress) return;
    const id = window.setInterval(async () => {
      try {
        setTranscription(await api.latestTranscription(sessionId));
      } catch (err) {
        setTranscribeError(message(err));
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [inProgress, sessionId]);

  // Clear the active-riff marker when range playback stops.
  useEffect(() => {
    if (!player.range) setActiveRiff(null);
  }, [player.range]);

  function applySelection(s: Selection) {
    setSelection(s);
    setStartText(s.start.toFixed(3));
    setEndText(s.end.toFixed(3));
    setFormError(null);
  }

  function onRangeText(which: 'start' | 'end', text: string) {
    if (which === 'start') setStartText(text);
    else setEndText(text);
    const start = Number(which === 'start' ? text : startText);
    const end = Number(which === 'end' ? text : endText);
    if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
      setSelection({ start, end });
    }
  }

  async function transcribe() {
    setTranscribeError(null);
    try {
      setTranscription(await api.startTranscription(sessionId));
    } catch (err) {
      setTranscribeError(message(err));
    }
  }

  async function saveRiff(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    const start = roundMs(Number(startText));
    const end = roundMs(Number(endText));
    const invalid =
      startText.trim() === '' || endText.trim() === ''
        ? 'Select a range on the timeline or enter start and end times.'
        : validateRange(start, end, session.duration_seconds);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    if (!title.trim()) {
      setFormError('Give the riff a name.');
      return;
    }
    try {
      await api.createRiff(session.id, title.trim(), start, end);
      setTitle('');
      setFormError(null);
      await loadRiffs();
      onRiffsChanged();
    } catch (err) {
      setFormError(message(err));
    }
  }

  async function deleteRiff(r: Riff) {
    try {
      if (activeRiff?.id === r.id) player.pause();
      await api.deleteRiff(r.id);
      await loadRiffs();
      onRiffsChanged();
    } catch (err) {
      setFormError(message(err));
    }
  }

  function playRiff(r: Riff, loop: boolean) {
    setActiveRiff({ id: r.id, loop });
    applySelection({ start: r.start_seconds, end: r.end_seconds });
    player.play({ start: r.start_seconds, end: r.end_seconds, loop });
  }

  if (loadError) {
    return (
      <p role="alert" className="error">
        Could not load this recording: {loadError}
      </p>
    );
  }
  if (!session) return <p className="hint">Loading recording…</p>;

  const notes = transcription?.status === 'succeeded' ? transcription.notes : [];

  return (
    <div className="session-view" data-testid="session-view" data-session-id={session.id}>
      <header className="session-header">
        <h2>Recording {new Date(session.created_at).toLocaleString()}</h2>
        <p className="meta">
          Duration <strong data-testid="session-duration">{formatTime(session.duration_seconds)}</strong>{' '}
          · {session.audio_mime} · {(session.audio_bytes / 1024).toFixed(1)} KB · sha256{' '}
          <code title={session.audio_sha256}>{session.audio_sha256.slice(0, 12)}…</code>
        </p>
      </header>

      {missing ? (
        <p role="alert" className="error" data-testid="audio-missing">
          The original audio file for this recording is missing, so it cannot be played or
          transcribed. Saved riff timestamps are kept.
        </p>
      ) : (
        <>
          <audio {...player.bind} data-testid="audio" />
          <div className="transport">
            {player.playing ? (
              <button onClick={player.pause}>❚❚ Pause</button>
            ) : (
              <button onClick={() => player.play(null)}>▶ Play</button>
            )}
            <span className="clock" data-testid="clock">
              {formatTime(player.time)} / {formatTime(session.duration_seconds)}
            </span>
            {selection && (
              <button onClick={() => player.play({ ...selection, loop: false })}>
                ▶ Play selection
              </button>
            )}
            <label className="zoom">
              Zoom
              <input
                type="range"
                min={20}
                max={400}
                value={pxPerSecond}
                onChange={(e) => setPxPerSecond(Number(e.target.value))}
              />
            </label>
          </div>
          {player.error && (
            <p role="alert" className="error">
              {player.error}
            </p>
          )}
        </>
      )}

      <Timeline
        duration={session.duration_seconds}
        pxPerSecond={pxPerSecond}
        peaks={peaks}
        notes={notes}
        riffs={riffs}
        time={player.time}
        selection={selection}
        onSelect={applySelection}
        onSeek={player.seek}
      />

      <TranscriptionPanel
        config={config}
        transcription={transcription}
        busy={inProgress}
        error={transcribeError}
        disabled={missing}
        onTranscribe={transcribe}
      />

      <section className="panel" aria-label="Save riff">
        <h3>Save a riff</h3>
        <p className="hint">Drag across the timeline, or type times in seconds.</p>
        <form className="riff-form" onSubmit={saveRiff} noValidate>
          <label>
            Start (s)
            <input
              name="start"
              inputMode="decimal"
              value={startText}
              onChange={(e) => onRangeText('start', e.target.value)}
            />
          </label>
          <label>
            End (s)
            <input
              name="end"
              inputMode="decimal"
              value={endText}
              onChange={(e) => onRangeText('end', e.target.value)}
            />
          </label>
          <label className="grow">
            Name
            <input
              name="title"
              maxLength={120}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Opening lick"
            />
          </label>
          <button type="submit">Save riff</button>
        </form>
        {formError && (
          <p role="alert" className="error" data-testid="riff-form-error">
            {formError}
          </p>
        )}
        <RiffList
          riffs={riffs}
          activeRiffId={activeRiff?.id ?? null}
          looping={activeRiff?.loop ?? false}
          onPlay={playRiff}
          onStop={player.pause}
          onDelete={deleteRiff}
        />
      </section>
    </div>
  );
}
