import { useCallback, useEffect, useState } from 'react';
import { api, type AppConfig, type Riff, type Session } from './api';
import { Recorder } from './Recorder';
import { SessionView } from './SessionView';
import { formatTime } from './timing';

function sessionFromHash(): string | null {
  const m = window.location.hash.match(/^#\/sessions\/([0-9a-f]+)/);
  return m ? m[1] : null;
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [riffs, setRiffs] = useState<Riff[]>([]);
  const [selected, setSelected] = useState<string | null>(sessionFromHash());
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.listSessions(), api.listRiffs()]);
      setSessions(s);
      setRiffs(r);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch((e) => setError((e as Error).message));
    refresh();
    const onHash = () => setSelected(sessionFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [refresh]);

  function open(id: string) {
    window.location.hash = `#/sessions/${id}`;
    setSelected(id);
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>JamRecall</h1>
        <span className="engine-chip" data-testid="engine-chip">
          {config === null
            ? '…'
            : config.transcription
              ? `${config.transcription.test_only ? 'TEST-ONLY engine' : 'Engine'}: ${config.transcription.engine} v${config.transcription.version}`
              : 'No transcription engine'}
        </span>
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="layout">
        <aside className="sidebar">
          <Recorder
            onSaved={async (s) => {
              await refresh();
              open(s.id);
            }}
          />
          <section className="panel" aria-label="Recordings">
            <h2>Recordings</h2>
            {sessions.length === 0 ? (
              <p className="hint">No recordings yet.</p>
            ) : (
              <ul className="session-list">
                {sessions.map((s) => (
                  <li key={s.id}>
                    <button
                      className={s.id === selected ? 'link selected' : 'link'}
                      onClick={() => open(s.id)}
                      data-testid="session-item"
                    >
                      {new Date(s.created_at).toLocaleTimeString()} ·{' '}
                      {formatTime(s.duration_seconds)}
                      {s.riff_count ? ` · ${s.riff_count} riff${s.riff_count > 1 ? 's' : ''}` : ''}
                      {s.status === 'audio_missing' ? ' · audio missing' : ''}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel" aria-label="All riffs">
            <h2>All riffs</h2>
            {riffs.length === 0 ? (
              <p className="hint">Saved riffs appear here.</p>
            ) : (
              <ul className="session-list">
                {riffs.map((r) => (
                  <li key={r.id}>
                    <button className="link" onClick={() => open(r.session_id)}>
                      {r.title} · {formatTime(r.start_seconds)}–{formatTime(r.end_seconds)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
        <main className="main">
          {selected ? (
            <SessionView key={selected} sessionId={selected} config={config} onRiffsChanged={refresh} />
          ) : (
            <p className="hint empty-state">Record a phrase or open a recording to begin.</p>
          )}
        </main>
      </div>
    </div>
  );
}
