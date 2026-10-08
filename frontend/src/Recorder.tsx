import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Session } from './api';
import {
  describeMediaError,
  GUITAR_AUDIO_CONSTRAINTS,
  pickMimeType,
  recordingSupport,
  type RecorderError,
} from './recording';
import { formatTime } from './timing';

type Phase = 'idle' | 'requesting' | 'recording' | 'uploading';

export function Recorder({ onSaved }: { onSaved: (s: Session) => void }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<RecorderError | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => stopEverything(), []);

  function stopEverything() {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  async function start() {
    setError(null);
    const unsupported = recordingSupport();
    if (unsupported) {
      setError(unsupported);
      return;
    }
    const mimeType = pickMimeType((t) => MediaRecorder.isTypeSupported(t))!;
    setPhase('requesting');
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: GUITAR_AUDIO_CONSTRAINTS });
    } catch (err) {
      setError(describeMediaError(err));
      setPhase('idle');
      return;
    }
    streamRef.current = stream;
    const chunks: Blob[] = [];
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType });
    } catch (err) {
      stopEverything();
      setError(describeMediaError(err));
      setPhase('idle');
      return;
    }
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onerror = (e) => {
      stopEverything();
      setError(describeMediaError((e as unknown as { error?: unknown }).error ?? e));
      setPhase('idle');
    };
    recorder.onstop = async () => {
      stopEverything();
      const blob = new Blob(chunks, { type: recorder.mimeType || mimeType });
      if (blob.size === 0) {
        setError({ code: 'empty_recording', message: 'Nothing was recorded. Please try again.' });
        setPhase('idle');
        return;
      }
      setPhase('uploading');
      try {
        const session = await api.createSession(blob, recorder.mimeType || mimeType);
        setPhase('idle');
        onSaved(session);
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : String(err);
        setError({ code: 'unknown', message: `Could not save the recording: ${msg}` });
        setPhase('idle');
      }
    };
    const startedAt = performance.now();
    setElapsed(0);
    timerRef.current = window.setInterval(
      () => setElapsed((performance.now() - startedAt) / 1000),
      100,
    );
    recorder.start(250);
    setPhase('recording');
  }

  function stop() {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
  }

  return (
    <section className="panel recorder" aria-label="Recorder">
      <h2>Record</h2>
      <p className="hint">Play a single-note (monophonic) phrase. Audio stays on this machine.</p>
      {phase === 'recording' ? (
        <button className="record-btn recording" onClick={stop}>
          ■ Stop ({formatTime(elapsed)})
        </button>
      ) : (
        <button
          className="record-btn"
          onClick={start}
          disabled={phase === 'requesting' || phase === 'uploading'}
        >
          {phase === 'requesting'
            ? 'Waiting for microphone…'
            : phase === 'uploading'
              ? 'Saving…'
              : '● Record'}
        </button>
      )}
      {error && (
        <p role="alert" className="error" data-error-code={error.code}>
          {error.message}
        </p>
      )}
    </section>
  );
}
