import { useState } from 'react';
import type { Riff } from './api';
import { formatTime } from './timing';

interface Props {
  riffs: Riff[];
  activeRiffId: string | null;
  looping: boolean;
  onPlay: (r: Riff, loop: boolean) => void;
  onStop: () => void;
  onDelete: (r: Riff) => void;
}

export function RiffList({ riffs, activeRiffId, looping, onPlay, onStop, onDelete }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (riffs.length === 0) {
    return <p className="hint">No riffs saved for this recording yet.</p>;
  }
  return (
    <ul className="riff-list" aria-label="Saved riffs">
      {riffs.map((r) => {
        const active = r.id === activeRiffId;
        return (
          <li key={r.id} data-testid="riff-item" className={active ? 'active' : ''}>
            <span className="riff-title">{r.title}</span>
            <span className="riff-range" data-testid="riff-range">
              {formatTime(r.start_seconds)} – {formatTime(r.end_seconds)}
            </span>
            {active ? (
              <button onClick={onStop}>Stop{looping ? ' loop' : ''}</button>
            ) : (
              <>
                <button onClick={() => onPlay(r, false)}>Play</button>
                <button onClick={() => onPlay(r, true)}>Loop</button>
              </>
            )}
            {confirming === r.id ? (
              <>
                <button
                  className="danger"
                  onClick={() => {
                    setConfirming(null);
                    onDelete(r);
                  }}
                >
                  Confirm delete
                </button>
                <button onClick={() => setConfirming(null)}>Cancel</button>
              </>
            ) : (
              <button onClick={() => setConfirming(r.id)} aria-label={`Delete riff ${r.title}`}>
                Delete
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
